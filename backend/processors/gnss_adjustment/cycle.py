"""Round-Robin cycle responsibilities."""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Optional
import numpy as np
from .geometry import (
    _aggregate_parallel_baselines,
    _build_fundamental_loops,
    _canonical_baseline,
    _ecef_to_llh,
    _graph_components,
    _is_usable_llh,
    _llh_horizontal_distance_m,
    _neu_to_ecef_delta,
    _vector_length,
)
from .session import (
    _COMMAND_RESPONSE_RE,
    _CollectedObservation,
    _CommandAckWaiter,
    _SafeRoverRotationSkip,
    _normalized_receiver_command,
    _receiver_response_result,
    requires_common_base_handover,
    RoundRobinSessionLifecycleMixin,
)
from .statistics import (
    _BASELINE_STD_REJECTION_THRESHOLD_M,
    _InformationAccumulator,
    _edge_effective_sample_size,
    _initial_positive_sequence_ess,
    _pooled_lag_one_autocorrelations,
    _rolling_drift_exceeds_abort_limits,
    _rolling_mean_stability,
    _spd_solve,
    _split_effective_sample_sessions,
)

logger = logging.getLogger(__name__)

class RoundRobinCycleMixin:
    async def prepare_common_fixed_base_seed(self, project_id: int) -> list[dict]:
        """Atomically synchronize failover state and establish the seed topology."""

        async with self._cors_topology_lock:
            session = self._sessions.get(project_id)
            if session is None:
                raise KeyError(f"no active adjustment session for project {project_id}")
            failover_clusters = [
                cluster
                for cluster in session.get("clusters", [])
                if isinstance(cluster, dict) and cluster.get("backup_base_station")
            ]
            if failover_clusters:
                failover_outcomes = await self._reconcile_cors_failover_pairs_unlocked(
                    failover_clusters
                )
                for cluster, outcome in zip(
                    failover_clusters,
                    failover_outcomes,
                ):
                    role = {
                        "PRIMARY_ACTIVE": "primary",
                        "BACKUP_ACTIVE": "backup",
                    }.get(str(outcome.get("state") or ""))
                    if role is None:
                        continue
                    selected = next(
                        (
                            candidate
                            for candidate in self._fixed_base_candidates(cluster)
                            if str(candidate.get("role") or "").casefold() == role
                        ),
                        None,
                    )
                    if selected is not None:
                        self._lock_fixed_base_candidate(
                            cluster,
                            selected,
                            (
                                f"CORS topology API confirmed {role} route active: "
                                f"{selected.get('base_station')}/S"
                                f"{selected.get('base_server_id')} -> "
                                f"{selected.get('base_stream_mp')}"
                            ),
                        )
            return await self._prepare_common_fixed_base_seed_unlocked(project_id)


    async def _prepare_common_fixed_base_seed_unlocked(
        self,
        project_id: int,
    ) -> list[dict]:
        """Force both CORS outputs to originate at the selected physical base.

        A total-cluster seed is only geometrically valid when every rover sees
        one control coordinate.  In the normal failover topology, S1 and S2 may
        legitimately be fed by two different physical receivers, so the
        adjustment must establish a temporary break-before-make topology before
        accepting any fixed-base observations.
        """

        session = self._sessions.get(project_id)
        if session is None:
            raise KeyError(f"no active adjustment session for project {project_id}")

        def has_dual_selected_stream(cluster: dict) -> bool:
            # Ordinary clusters must keep their own configured/failover base so
            # independent dam adjustments can run concurrently.  Only a total
            # cluster intentionally moves every rover onto one common base.
            if not requires_common_base_handover(cluster):
                return False
            candidates = self._fixed_base_candidates(cluster)
            selected_config = candidates[0].get("base_service_config") or {}
            return len(candidates) >= 2 or all(
                bool(str(selected_config.get(f"mountpoint{server_id}") or "").strip())
                for server_id in (1, 2)
            )

        if not any(has_dual_selected_stream(cluster) for cluster in session["clusters"]):
            for cluster in session["clusters"]:
                candidates = self._fixed_base_candidates(cluster)
                if len(candidates) == 1:
                    self._lock_fixed_base_candidate(
                        cluster,
                        candidates[0],
                        "configured fixed base selected before seed collection",
                    )
                elif not cluster.get("selected_fixed_base_candidate"):
                    cluster["selected_fixed_base_candidate"] = None
                    cluster["fixed_base_selection_diagnostic"] = (
                        "awaiting AGRICA confirmation of the active primary/backup base"
                    )
            return []
        raw_stations = await asyncio.to_thread(
            self._cors_api_request_sync,
            "GET",
            "/api/public/map-stations",
        )
        if isinstance(raw_stations, dict):
            raw_stations = raw_stations.get("value") or raw_stations.get("items") or []
        stations = [item for item in (raw_stations or []) if isinstance(item, dict)]
        snapshots: dict[str, dict] = session.setdefault("seed_topology_snapshots", {})
        outcomes: list[dict] = []

        try:
            for cluster_index, cluster in enumerate(session["clusters"]):
                candidates = self._fixed_base_candidates(cluster)
                # A mixed request may still contain a legacy single-stream
                # base alongside a dual-stream total cluster.
                if not has_dual_selected_stream(cluster):
                    if len(candidates) == 1:
                        self._lock_fixed_base_candidate(
                            cluster,
                            candidates[0],
                            "configured fixed base selected before seed collection",
                        )
                    elif not cluster.get("selected_fixed_base_candidate"):
                        cluster["selected_fixed_base_candidate"] = None
                        cluster["fixed_base_selection_diagnostic"] = (
                            "awaiting AGRICA confirmation of the active primary/backup base"
                        )
                    continue

                resolved_candidates: list[tuple[dict, tuple[dict, int]]] = []
                for candidate in candidates:
                    candidate_match = self._cors_failover_stream(
                        stations,
                        station_name=candidate.get("base_station"),
                        serial=candidate.get("base_serial"),
                        server_id=candidate.get("base_server_id"),
                        host=candidate.get("base_stream_host"),
                        mountpoint=candidate.get("base_stream_mp"),
                    )
                    if candidate_match is not None:
                        resolved_candidates.append((candidate, candidate_match))

                if not resolved_candidates:
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: could not resolve "
                        "any configured CORS failover stream uniquely"
                    )

                # Candidate order is primary then backup, but the primary may be
                # offline while the backup receiver's S2 is already serving its
                # mountpoint.  Select the first *online physical receiver* that
                # can publish both reciprocal mountpoints for the common seed.
                usable_candidates = []
                online_candidates = []
                for candidate, candidate_match in resolved_candidates:
                    candidate_station, _ = candidate_match
                    if not self._cors_station_is_online(candidate_station):
                        continue
                    online_candidates.append((candidate, candidate_match))
                    service_config = self._cors_effective_service_config(
                        candidate_station,
                        candidate.get("base_service_config"),
                    )
                    if all(
                        bool(str(service_config.get(f"mountpoint{server_id}") or "").strip())
                        for server_id in (1, 2)
                    ):
                        usable_candidates.append((candidate, candidate_match))

                if not online_candidates:
                    names = ", ".join(
                        str(candidate.get("base_station") or "unknown")
                        for candidate, _ in resolved_candidates
                    )
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: no configured "
                        f"physical base is online ({names})"
                    )
                if not usable_candidates:
                    names = ", ".join(
                        str(candidate.get("base_station") or "unknown")
                        for candidate, _ in online_candidates
                    )
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: online physical base(s) "
                        f"{names} must have explicit mountpoints configured for both "
                        "S1 and S2 before a common-base seed can start"
                    )

                selected, selected_match = usable_candidates[0]
                selected_station, _ = selected_match
                selected_serial = str(selected_station.get("serial") or "").strip()
                selected_service_config = self._cors_effective_service_config(
                    selected_station,
                    selected.get("base_service_config"),
                )

                try:
                    selected_server_id = int(selected.get("base_server_id") or 1)
                except (TypeError, ValueError):
                    selected_server_id = 1
                paired_mountpoints = {
                    str(selected_service_config.get(f"mountpoint{server_id}") or "")
                    .strip()
                    .casefold()
                    for server_id in (1, 2)
                    if server_id != selected_server_id
                    and str(selected_service_config.get(f"mountpoint{server_id}") or "").strip()
                }
                physical_matches = []
                for station in stations:
                    serial = str(station.get("serial") or "").strip()
                    if not serial or serial.casefold() == selected_serial.casefold():
                        continue
                    service_config = self._cors_effective_service_config(station)
                    identity_tokens = {
                        str(station.get("name") or "").strip().casefold(),
                        str(station.get("code") or "").strip().casefold(),
                        str(station.get("mountpoint") or "").strip().casefold(),
                        str(service_config.get("mountpoint1") or "").strip().casefold(),
                    }
                    if paired_mountpoints.intersection(identity_tokens):
                        physical_matches.append(station)

                # Compatibility fallback for older project records where the
                # selected station did not expose its reciprocal S2 metadata.
                other = next(
                    (candidate for candidate in candidates if candidate is not selected),
                    {},
                )
                if len(physical_matches) != 1 and other:
                    target_serial = str(other.get("base_serial") or "").strip().casefold()
                    target_name = str(other.get("base_station") or "").strip().casefold()
                    physical_matches = [
                        station
                        for station in stations
                        if (
                            target_serial
                            and str(station.get("serial") or "").strip().casefold()
                            == target_serial
                        )
                        or (
                            not target_serial
                            and target_name
                            and str(station.get("name") or station.get("code") or "")
                            .strip()
                            .casefold()
                            == target_name
                        )
                    ]
                if len(physical_matches) != 1:
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: selected base "
                        f"{selected.get('base_station')} has reciprocal mountpoint(s) "
                        f"{sorted(paired_mountpoints)}, but matched "
                        f"{len(physical_matches)} opposite physical stations"
                    )
                other_station = physical_matches[0]
                other_serial = str(other_station.get("serial") or "").strip()
                other_name = str(
                    other_station.get("name") or other_station.get("code") or ""
                ).strip()

                for station in (selected_station, other_station):
                    serial = str(station.get("serial") or "").strip()
                    snapshots.setdefault(
                        serial.casefold(),
                        {
                            "serial": serial,
                            "service_config": self._cors_effective_service_config(station),
                        },
                    )
                session.setdefault("seed_topology_managed_serials", set()).update({
                    selected_serial.casefold(),
                    other_serial.casefold(),
                })

                other_online = self._cors_station_is_online(other_station)
                if other_online:
                    other_disabled = self._cors_service_config_with_server_enabled(
                        self._cors_effective_service_config(other_station),
                        None,
                        enabled=False,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        other_serial,
                        other_disabled,
                    )
                    other_station["service_config"] = other_disabled

                # Whether the opposite receiver is online or offline, assert
                # both enabled outputs on the chosen receiver. If it is offline,
                # failover normally already made S2 active and this is a no-op.
                selected_original = selected_service_config
                selected_enabled = self._cors_service_config_with_server_enabled(
                    selected_original,
                    None,
                    enabled=True,
                )
                if selected_enabled != selected_original:
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        selected_serial,
                        selected_enabled,
                    )
                    selected_station["service_config"] = selected_enabled

                self._lock_fixed_base_candidate(
                    cluster,
                    selected,
                    (
                        f"selected {selected.get('base_station')} had both S1/S2 hard-enabled; "
                        f"opposite station {other_name} was "
                        f"{'online and stopped' if other_online else 'offline'} before seed"
                    ),
                )
                cluster["require_fixed_base_length_check"] = True
                outcomes.append({
                    "cluster": str(cluster.get("name") or cluster_index + 1),
                    "selected_base": str(selected.get("base_station") or ""),
                    "opposite_base": other_name,
                    "opposite_online": other_online,
                    "state": "COMMON_SELECTED_BASE_PENDING_RTCM_VERIFICATION",
                })

            if outcomes:
                await self._emit_progress(
                    project_id,
                    "Đã ngắt base đối nghịch và bật cả S1/S2 của base được chọn; "
                    "đang chờ RTCM chuyển nguồn ổn định trước khi thu baseline chung.",
                )
                await asyncio.sleep(self.FIXED_BASE_HANDOVER_SETTLE_SECONDS)
                # No pre-handover fragment or observation may prove the new
                # source. Require fresh AGRICA evidence from every selected
                # rover before exposing COLLECTING_BASELINE to the caller.
                for cluster in session["clusters"]:
                    cluster["observations"].clear()
                    self._clear_cluster_fragment_buffers(project_id, cluster)
                session["seed_station_reports"].clear()

                verify_seconds = max(0.0, self.FIXED_BASE_HANDOVER_VERIFY_SECONDS)
                if verify_seconds:
                    expected_station_ids = {
                        int(station_id)
                        for cluster in session["clusters"]
                        for station_id in cluster["stations"]
                    }
                    verification_deadline = time.monotonic() + verify_seconds
                    while time.monotonic() < verification_deadline:
                        reports = session.get("seed_station_reports", {})
                        verified_station_ids = {
                            int(station_id)
                            for station_id, report in list(reports.items())
                            if report.get("base_identity_verified") is True
                        }
                        if expected_station_ids <= verified_station_ids:
                            break
                        await asyncio.sleep(0.25)
                    else:
                        reports = session.get("seed_station_reports", {})
                        pending = []
                        for cluster in session["clusters"]:
                            for station_id, rover_code in zip(
                                cluster["stations"], cluster["rovers"], strict=True
                            ):
                                report = reports.get(int(station_id), {})
                                if report.get("base_identity_verified") is not True:
                                    pending.append(
                                        f"{rover_code}: {report.get('reason') or 'no fresh AGRICA'}"
                                    )
                        raise RuntimeError(
                            "common-base handover was not confirmed by every rover within "
                            f"{verify_seconds:.0f}s; " + "; ".join(pending)
                        )

                # Verification epochs are transition evidence, not seed data.
                for cluster in session["clusters"]:
                    cluster["observations"].clear()
                    self._clear_cluster_fragment_buffers(project_id, cluster)
                session["seed_station_reports"].clear()
                session["seed_started_monotonic"] = time.monotonic()
                for outcome in outcomes:
                    outcome["state"] = "COMMON_SELECTED_BASE_VERIFIED"
            return outcomes
        except Exception:
            await self._restore_common_fixed_base_topology_unlocked(project_id)
            raise


    async def restore_common_fixed_base_topology(self, project_id: int) -> None:
        async with self._cors_topology_lock:
            await self._restore_common_fixed_base_topology_unlocked(project_id)


    async def _restore_common_fixed_base_topology_unlocked(self, project_id: int) -> None:
        """Restore CORS service modes saved before common-base seed collection."""

        session = self._sessions.get(project_id)
        if session is None:
            return
        snapshots = session.get("seed_topology_snapshots") or {}
        errors: list[str] = []
        remaining: dict[str, dict] = {}
        for snapshot_key, snapshot in reversed(list(snapshots.items())):
            try:
                await asyncio.to_thread(
                    self._cors_configure_service_sync,
                    snapshot["serial"],
                    copy.deepcopy(snapshot["service_config"]),
                )
            except Exception as exc:
                errors.append(f"{snapshot.get('serial')}: {exc}")
                remaining[snapshot_key] = snapshot
        session["seed_topology_snapshots"] = remaining
        session["seed_topology_managed_serials"] = set(remaining)
        if errors:
            raise RuntimeError("could not restore common-base topology: " + "; ".join(errors))


    async def _reacquire_fixed_base_between_rotations(
        self,
        project_id: int,
        cluster: dict,
        *,
        next_rover: str,
        mountpoint: str,
        selected_host: str,
        selected_serial: str = "",
        selected_server_id: Optional[int] = None,
    ) -> bool:
        """Reconnect every rover to the fixed BASE before the next rotation.

        Once a temporary pusher stops, rover NTRIP sessions disappear if the
        configured fixed stream remains disabled. A later rover therefore cannot
        receive its SET BASE command.  Restore the original stream, require new
        solver-eligible BASE observations from every rover, confirm the next
        AICaster session, and only then hard-disable the fixed server again.
        """

        start_index = len(cluster["observations"])
        cluster.pop("_last_reacquire_skip_mode", None)
        identity_kwargs = {}
        if selected_serial:
            identity_kwargs["selected_serial"] = selected_serial
        if selected_server_id is not None:
            identity_kwargs["selected_server_id"] = selected_server_id
        await self._emit_progress(
            project_id,
            (
                f"Inter-rotation handover: restoring fixed BASE {mountpoint} "
                f"so every rover reconnects before {next_rover} becomes the "
                "next temporary base."
            ),
        )
        await self._set_cors_fixed_base_enabled(
            mountpoint,
            enabled=True,
            selected_host=selected_host,
            **identity_kwargs,
        )

        all_rovers = {str(name) for name in cluster.get("rovers", ())}
        # Only the receiver that will become the next temporary BASE must have
        # an active fixed-source solution and SET control session here. Other
        # rovers can legitimately take longer to reconnect; their observations
        # are still rejected by source identity and estimated-length checks
        # until the next temporary source is genuinely acquired.
        required_rovers = {str(next_rover)}
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        nominal_deadline = (
            started_at + self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS
        )
        hard_deadline = started_at + max(
            self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS,
            self.INTER_ROTATION_REACQUIRE_MAX_SECONDS,
        )
        epochs_by_rover: Dict[str, set[int]] = {}
        next_client_confirmed = False
        client_check_state = "not-checked"
        client_check_error = ""
        client_check_failure_logged = False
        next_client_check_at = started_at
        last_next_rover_activity_at: Optional[float] = None
        next_rover_record_count = 0
        extension_announced = False
        while loop.time() < hard_deadline:
            now = loop.time()
            epochs_by_rover = {}
            current_next_rover_record_count = 0
            for record in cluster["observations"][start_index:]:
                observation = getattr(record, "observation", None)
                if (
                    observation is not None
                    and str(getattr(observation, "rover_name", "")) == str(next_rover)
                ):
                    current_next_rover_record_count += 1
                if (
                    observation is None
                    or getattr(record, "base_name", None) != "BASE"
                    or not getattr(record, "solver_eligible", True)
                    or max(float(value) for value in observation.std_neu)
                    > _BASELINE_STD_REJECTION_THRESHOLD_M
                    or _vector_length(observation.baseline_neu) < 1.0
                ):
                    continue
                rover_name = str(observation.rover_name)
                epochs_by_rover.setdefault(rover_name, set()).add(
                    int(observation.epoch_ts)
                )

            if current_next_rover_record_count > next_rover_record_count:
                next_rover_record_count = current_next_rover_record_count
                last_next_rover_activity_at = now

            fixed_ready = all(
                len(epochs_by_rover.get(rover_name, ()))
                >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
                for rover_name in required_rovers
            )
            if fixed_ready or now >= next_client_check_at:
                try:
                    client_info = await self._find_client_info(
                        next_rover,
                        project_id=project_id,
                        log_missing=False,
                    )
                    next_client_confirmed = client_info is not None
                    client_check_state = (
                        "confirmed" if next_client_confirmed else "checked-missing"
                    )
                    client_check_error = ""
                except Exception as exc:
                    next_client_confirmed = False
                    client_check_state = "check-failed"
                    client_check_error = str(exc) or type(exc).__name__
                    if not client_check_failure_logged:
                        client_check_failure_logged = True
                        logger.warning(
                            "AICaster session check failed during fixed BASE "
                            "reacquisition for %s; polling will continue: %s",
                            next_rover,
                            client_check_error,
                        )
                next_client_check_at = (
                    now + self.INTER_ROTATION_CLIENT_POLL_SECONDS
                )
            if fixed_ready and next_client_confirmed:
                break

            fixed_service_proven_elsewhere = any(
                rover_name != str(next_rover)
                and len(epochs) >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
                for rover_name, epochs in epochs_by_rover.items()
            )
            if (
                next_client_confirmed
                and next_rover_record_count == 0
                and fixed_service_proven_elsewhere
                and now - started_at
                >= self.INTER_ROTATION_STALE_ROVER_GRACE_SECONDS
            ):
                break

            activity_deadline = (
                last_next_rover_activity_at
                + self.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS
                if last_next_rover_activity_at is not None
                else nominal_deadline
            )
            effective_deadline = min(
                hard_deadline,
                max(nominal_deadline, activity_deadline),
            )
            if now >= nominal_deadline and effective_deadline > now:
                if not extension_announced:
                    extension_announced = True
                    await self._emit_progress(
                        project_id,
                        (
                            f"{next_rover}: nominal fixed-BASE reacquisition wait "
                            f"reached {self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS}s, "
                            "but fresh AGRICA transition data is still arriving; "
                            f"extending adaptively up to "
                            f"{self.INTER_ROTATION_REACQUIRE_MAX_SECONDS}s."
                        ),
                    )
            elif now >= effective_deadline:
                break
            await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

        if not (fixed_ready and next_client_confirmed):
            counts = {
                rover_name: len(epochs_by_rover.get(rover_name, ()))
                for rover_name in sorted(all_rovers)
            }
            elapsed_seconds = max(0, int(round(loop.time() - started_at)))
            client_detail = client_check_state
            if client_check_error:
                client_detail += f" ({client_check_error})"
            detail = (
                f"Fixed BASE reacquisition before {next_rover} timed out after "
                f"{elapsed_seconds}s "
                f"(nominal {self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS}s, "
                f"hard limit {self.INTER_ROTATION_REACQUIRE_MAX_SECONDS}s); "
                f"BASE epochs={counts}, next AICaster session="
                f"{client_detail}"
            )
            # This receiver has not entered its temporary-BASE rotation yet.
            # Either an authoritative client-table miss *or* an active control
            # session with no fresh fixed-BASE observations proves that this
            # rover cannot safely become the next temporary BASE.  Skip that
            # rover and continue the cluster.  Query failures remain fatal:
            # they describe loss of controller visibility, not the state of
            # this individual rover.
            confirmed_offline = client_check_state == "checked-missing"
            fixed_service_proven_elsewhere = any(
                rover_name != str(next_rover)
                and len(epochs) >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
                for rover_name, epochs in epochs_by_rover.items()
            )
            fixed_data_missing = bool(
                next_client_confirmed
                and not fixed_ready
                and (
                    next_rover_record_count > 0
                    or fixed_service_proven_elsewhere
                )
            )
            live_but_uncontrolled = bool(
                confirmed_offline
                and next_rover_record_count > 0
            )
            if not confirmed_offline and not fixed_data_missing:
                raise RuntimeError(detail)
            if fixed_data_missing:
                availability = (
                    "AICaster control session is active but no fresh, solver-eligible "
                    "fixed-BASE epochs arrived"
                )
                skip_detail = (
                    "skipping this data-plane-stale rover from the remaining "
                    "temporary-BASE rotation and cross-baseline expectations. "
                )
                skip_mode = "offline"
            elif live_but_uncontrolled:
                availability = (
                    "AGRICA is live but the AICaster control identity is unavailable"
                )
                skip_detail = (
                    "skipping only its temporary-BASE rotation. The station remains "
                    "eligible as a rover in other rotations. "
                )
                skip_mode = "uncontrolled"
            else:
                availability = "AICaster session disappeared"
                skip_detail = "skipping its temporary-BASE rotation. "
                skip_mode = "offline"
            warning = (
                f"{next_rover}: "
                f"{availability} during inter-rotation handover; "
                + skip_detail
                + detail
            )
            cluster["_last_reacquire_skip_mode"] = skip_mode
            session = self._sessions.get(project_id) or {}
            session.setdefault("rotation_warnings", []).append({
                "cluster_index": int(cluster.get("current_rotation_index") or 0),
                "rover": str(next_rover),
                "message": warning,
            })
            await self._emit_progress(project_id, warning)
            self._exclude_fixed_base_records(
                cluster,
                start_index,
                flag="EXCLUDE_INTER_ROTATION_REACQUISITION",
                diagnostic=(
                    "Fresh fixed-BASE epoch used only to verify inter-rotation NTRIP "
                    "reacquisition; excluded from the common fixed-BASE solver seed."
                ),
            )
            return False

        await self._emit_progress(
            project_id,
            (
                f"Inter-rotation handover verified: {next_rover} supplied at least "
                f"{self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS} fresh fixed-BASE "
                "epochs and has an active AICaster session. Other slow clients "
                "remain quarantined by source/length validation. Keeping "
                f"{mountpoint} active through the next rover preflight; it will "
                "Sleep immediately before temporary SOURCE fanout."
            ),
        )

        self._exclude_fixed_base_records(
            cluster,
            start_index,
            flag="EXCLUDE_INTER_ROTATION_REACQUISITION",
            diagnostic=(
                "Fresh fixed-BASE epoch used only to verify inter-rotation NTRIP "
                "reacquisition; excluded from the common fixed-BASE "
                "solver seed."
            ),
        )
        return True


    @staticmethod
    def _exclude_fixed_base_records(
        cluster: dict,
        start_index: int,
        *,
        flag: str,
        diagnostic: str,
    ) -> None:
        for record_index in range(start_index, len(cluster["observations"])):
            record = cluster["observations"][record_index]
            if str(getattr(record, "base_name", "")).casefold() != "base":
                continue
            flags = tuple(dict.fromkeys((
                *tuple(getattr(record, "quality_flags", ()) or ()),
                flag,
            )))
            record.solver_eligible = False
            record.quality_flags = flags
            record.source_diagnostic = diagnostic


    def _freeze_temporary_base_coordinates(self, cluster: dict) -> Dict[str, dict]:
        """Freeze temporary BASE coordinates and an immutable solver seed.

        The common fixed-BASE window is the only authoritative source for both
        the temporary-BASE coordinates and the fixed edges used by the final
        adjustment.  Later handover code deliberately quarantines fixed-BASE
        observations for audit.  Keep a deep snapshot here so those live-record
        state changes cannot make a seed that was already accepted disappear at
        solve time.
        """

        try:
            from backend.processors.gnss_adjustment.transforms import (
                neu_standard_deviation_to_ecef_covariance,
            )
            from backend.processors.gnss_adjustment.runtime import _llh_to_ecef
        except ModuleNotFoundError:
            from processors.gnss_adjustment.transforms import (
                neu_standard_deviation_to_ecef_covariance,
            )
            from processors.gnss_adjustment.runtime import _llh_to_ecef

        fixed_llh = self._cluster_base_llh(cluster)
        fixed_ecef = np.asarray(_llh_to_ecef(*fixed_llh), dtype=float)
        frozen: Dict[str, dict] = {}
        retained_record_indices: set[int] = set()
        for configured_rover in cluster.get("rovers", ()):
            rover_key = str(configured_rover).casefold()
            candidates: list[tuple[np.ndarray, np.ndarray, int, int]] = []
            for record_index, record in enumerate(cluster.get("observations", ())):
                observation = getattr(record, "observation", None)
                if (
                    observation is None
                    or str(getattr(record, "base_name", "")).casefold() != "base"
                    or str(getattr(observation, "rover_name", "")).casefold()
                    != rover_key
                    or not getattr(record, "solver_eligible", True)
                    or max(float(value) for value in observation.std_neu)
                    > _BASELINE_STD_REJECTION_THRESHOLD_M
                    or _vector_length(observation.baseline_neu) < 1.0
                ):
                    continue
                delta = np.asarray(self._baseline_ecef(observation, fixed_llh), dtype=float)
                covariance = np.asarray(
                    neu_standard_deviation_to_ecef_covariance(
                        observation.std_neu, fixed_llh[0], fixed_llh[1]
                    ),
                    dtype=float,
                )
                if (
                    delta.shape == (3,)
                    and covariance.shape == (3, 3)
                    and np.all(np.isfinite(delta))
                    and np.all(np.isfinite(covariance))
                ):
                    candidates.append((
                        delta,
                        covariance,
                        int(observation.epoch_ts),
                        record_index,
                    ))

            if not candidates:
                raise RuntimeError(
                    f"Cannot freeze temporary BASE coordinate for {configured_rover}: "
                    "the initial fixed-BASE solver window has no valid observation"
                )

            vectors = np.vstack([item[0] for item in candidates])
            center = np.median(vectors, axis=0)
            deviations = np.linalg.norm(vectors - center, axis=1)
            median_deviation = float(np.median(deviations))
            mad = float(np.median(np.abs(deviations - median_deviation)))
            rejection_limit = max(
                0.25,
                median_deviation + 8.0 * 1.4826 * mad,
            )
            retained = [
                item
                for item, deviation in zip(candidates, deviations, strict=True)
                if float(deviation) <= rejection_limit
            ]
            if not retained:
                raise RuntimeError(
                    f"Cannot freeze temporary BASE coordinate for {configured_rover}: "
                    "all fixed-BASE seed vectors were rejected"
                )

            retained_record_indices.update(item[3] for item in retained)

            precision_sum = np.zeros((3, 3), dtype=float)
            weighted_sum = np.zeros(3, dtype=float)
            for delta, covariance, _epoch, _record_index in retained:
                precision = _spd_solve(covariance, np.eye(3, dtype=float))
                precision_sum += precision
                weighted_sum += precision @ delta
            endpoint = fixed_ecef + np.linalg.solve(precision_sum, weighted_sum)
            lat, lon, alt = _ecef_to_llh(*endpoint)
            frozen[str(configured_rover)] = {
                "lat": float(lat),
                "lon": float(lon),
                "alt": float(alt),
                "ecef_xyz": tuple(float(value) for value in endpoint),
                "seed_observation_count": len(retained),
                "seed_rejected_count": len(candidates) - len(retained),
                "seed_first_epoch": min(item[2] for item in retained),
                "seed_last_epoch": max(item[2] for item in retained),
                "source": "FROZEN_COVARIANCE_WEIGHTED_FIXED_BASE_SEED",
            }

        seed_snapshot = copy.deepcopy(list(cluster.get("observations", ())))
        for record_index, record in enumerate(seed_snapshot):
            if str(getattr(record, "base_name", "")).casefold() != "base":
                continue
            if not getattr(record, "solver_eligible", True):
                continue
            if record_index in retained_record_indices:
                continue
            record.solver_eligible = False
            record.quality_flags = tuple(dict.fromkeys((
                *tuple(getattr(record, "quality_flags", ()) or ()),
                "EXCLUDE_FIXED_BASE_SEED_FREEZE_OUTLIER",
            )))
            record.source_diagnostic = (
                "Fixed-BASE seed was not retained by the same robust vector/STD "
                "selection that froze the temporary-BASE coordinates."
            )

        cluster["fixed_base_seed_records_snapshot"] = seed_snapshot
        cluster["temporary_base_llh_by_rover"] = frozen
        return frozen


    async def _run_cycle(self, project_id: int) -> None:
        suspended_bases: set[tuple[str, str, str, int]] = set()
        disabled_conflict_bases: dict[str, dict] = {}
        cycle_error: Optional[Exception] = None
        try:
            session = self._sessions[project_id]
            for cluster_index, cluster in enumerate(session["clusters"]):
                rovers = cluster["rovers"]
                post_seed_start_index = len(cluster["observations"])
                cluster["fixed_base_seed_cutoff_index"] = post_seed_start_index
                logger.info(
                    "Starting Round-Robin project=%s cluster=%s with %s rovers: %s",
                    project_id,
                    cluster.get("name", cluster_index + 1),
                    len(rovers),
                    rovers,
                )
                selected_fixed_base = cluster.get("selected_fixed_base_candidate")
                if not isinstance(selected_fixed_base, dict):
                    configured_candidates = self._fixed_base_candidates(cluster)
                    if len(configured_candidates) == 1:
                        selected_fixed_base = configured_candidates[0]
                        self._lock_fixed_base_candidate(
                            cluster,
                            selected_fixed_base,
                            "legacy single fixed-base configuration",
                        )
                    else:
                        raise RuntimeError(
                            f"{cluster.get('name', cluster_index + 1)}: fixed-base "
                            "primary/backup candidate was not confirmed by AGRICA before "
                            "the round-robin cycle"
                        )
                await self._emit_progress(
                    project_id,
                    (
                        f"{cluster.get('name', cluster_index + 1)}: locked "
                        f"{selected_fixed_base.get('role', 'fixed')} fixed base "
                        f"{selected_fixed_base.get('base_station')} at "
                        f"{selected_fixed_base.get('base_stream_host')}:"
                        f"{selected_fixed_base.get('base_stream_port')}/"
                        f"{selected_fixed_base.get('base_stream_mp')}. "
                        "This identity, ECEF control coordinate and CORS service are "
                        "immutable for the complete job."
                    ),
                )
                frozen_base_coordinates = self._freeze_temporary_base_coordinates(cluster)
                await self._emit_progress(
                    project_id,
                    (
                        f"{cluster.get('name', cluster_index + 1)}: froze temporary-BASE "
                        f"coordinates for {', '.join(str(rover) for rover in rovers)} "
                        "from the common fixed-BASE seed window; every rotation will "
                        "reuse these exact coordinates."
                    ),
                )
                route_host = (
                    cluster.get("round_robin_route_host")
                    or cluster.get("base_stream_host")
                    or self.source_host
                )
                route_port_value = (
                    cluster.get("round_robin_route_port")
                    or cluster.get("base_stream_port")
                    or self.source_port
                )
                try:
                    route_port = int(route_port_value)
                except (TypeError, ValueError):
                    route_port = self.source_port
                configured_mountpoint = (
                    cluster.get("round_robin_route_mountpoint")
                    or cluster.get("base_stream_mp")
                )
                # Only a total cluster owns both CORS outputs. Normal clusters
                # may run concurrently on S1/S2 of the same physical receiver;
                # publishing to the other mountpoint corrupts its corrections.
                uses_common_base = requires_common_base_handover(cluster)
                temporary_route_mountpoints: list[str] = []
                if configured_mountpoint:
                    temporary_route_mountpoints.append(str(configured_mountpoint).strip())
                selected_service_config = cluster.get("base_service_config") or {}
                normalized_route_host = str(route_host or "").strip().casefold()
                for server_id in ((1, 2) if uses_common_base else ()):
                    candidate_mountpoint = str(
                        selected_service_config.get(f"mountpoint{server_id}") or ""
                    ).strip()
                    candidate_host = str(
                        selected_service_config.get(f"serverhost{server_id}") or route_host or ""
                    ).strip()
                    if (
                        not selected_service_config.get(f"server{server_id}_enabled", False)
                        or not candidate_mountpoint
                        or (
                            normalized_route_host
                            and candidate_host.casefold() != normalized_route_host
                        )
                    ):
                        continue
                    if not any(
                        existing.casefold() == candidate_mountpoint.casefold()
                        for existing in temporary_route_mountpoints
                    ):
                        temporary_route_mountpoints.append(candidate_mountpoint)
                temporary_route_mountpoint = ",".join(temporary_route_mountpoints)
                # This is the exact S1/S2 host selected in Project Management.
                # Do not infer server 1 from the mountpoint alone: S1 and S2 may
                # expose the same mountpoint on different caster hosts.
                configured_base_host = str(
                    cluster.get("base_stream_host") or route_host or ""
                ).strip()
                configured_base_serial = str(
                    cluster.get("base_serial") or ""
                ).strip()
                try:
                    configured_base_server_id = int(
                        cluster.get("base_server_id") or 0
                    )
                except (TypeError, ValueError):
                    configured_base_server_id = 0
                fixed_base_identity_kwargs = {}
                if configured_base_serial:
                    fixed_base_identity_kwargs["selected_serial"] = (
                        configured_base_serial
                    )
                if configured_base_server_id:
                    fixed_base_identity_kwargs["selected_server_id"] = (
                        configured_base_server_id
                    )
                route_password = cluster.get("round_robin_route_password")
                if route_password is None:
                    route_password = self.source_password
                
                # Hard-disable the fixed Base immediately before each temporary
                # rover route. The exact original service config is restored later.
                base_stream_key = (
                    configured_base_host,
                    str(configured_mountpoint or ""),
                    configured_base_serial,
                    configured_base_server_id,
                )
                if configured_mountpoint and base_stream_key not in suspended_bases:
                    await self._emit_progress(
                        project_id,
                        f"Đã khóa topology Base cố định {configured_mountpoint}; giữ stream hoạt động "
                        "qua preflight và chỉ ngắt server ngay trước khi mở fanout BASE tạm.",
                    )
                    suspended_bases.add(base_stream_key)
                    # The actual break happens immediately before SOURCE fanout.
                    # Keeping the fixed stream alive through SET/preflight prevents
                    # rover clients from entering a long reconnect backoff.
                    
                    # Ngắt các trạm Base phụ thuộc (conflict bases)
                    conflict_bases = (
                        []
                        if session.get("seed_topology_snapshots")
                        else cluster.get("conflict_bases", [])
                    )
                    for cb in conflict_bases:
                        cb_serial = cb.get("serial", "").strip()
                        cb_name = cb.get("name", "").strip()
                        if not cb_serial:
                            continue
                        
                        cb_key = cb_serial.casefold()
                        if cb_key not in disabled_conflict_bases:
                            await self._emit_progress(
                                project_id,
                                f"Tắt trạm Base phụ thuộc {cb_name} (theo cấu hình Cụm Tổng) để tránh xung đột dữ liệu.",
                            )
                            try:
                                original_config = await asyncio.to_thread(
                                    self._disable_conflict_base_sync,
                                    cb_serial,
                                )
                                if original_config is not None:
                                    disabled_conflict_bases[cb_key] = {
                                        "serial": cb_serial,
                                        "service_config": original_config,
                                    }
                                await asyncio.sleep(2.0)
                            except Exception as e:
                                logger.exception(f"Failed to sleep conflict base {cb_name}: {e}")

                    self._exclude_fixed_base_records(
                        cluster,
                        post_seed_start_index,
                        flag="EXCLUDE_POST_SEED_TRANSITION",
                        diagnostic=(
                            "Fixed-BASE epoch arrived after the common seed window "
                            "was frozen and while the fixed stream was entering Sleep; "
                            "retained for audit only."
                        ),
                    )
                    
                def current_solver_eligible_cross_coverage() -> tuple[set[tuple[str, str]], set[str]]:
                    edges: set[tuple[str, str]] = set()
                    participants: set[str] = set()
                    for record in cluster["observations"]:
                        observation = getattr(record, "observation", None)
                        from_name = str(getattr(record, "base_name", "") or "")
                        to_name = str(getattr(observation, "rover_name", "") or "")
                        if (
                            observation is None
                            or not getattr(record, "solver_eligible", True)
                            or not from_name
                            or from_name == "BASE"
                            or not to_name
                            or from_name.casefold() == to_name.casefold()
                        ):
                            continue
                        if max(
                            float(value) for value in observation.std_neu
                        ) > _BASELINE_STD_REJECTION_THRESHOLD_M:
                            continue
                        if _vector_length(observation.baseline_neu) < 1.0:
                            continue
                        edge = tuple(sorted((from_name, to_name), key=str.casefold))
                        edges.add(edge)
                        participants.update(edge)
                    return edges, participants

                def productive_temporary_bases() -> list[str]:
                    """Bases that have already produced a solver-eligible cross sample."""

                    productive: list[str] = []
                    for candidate in rovers:
                        candidate_key = str(candidate).casefold()
                        for record in cluster["observations"]:
                            observation = getattr(record, "observation", None)
                            if (
                                observation is None
                                or not getattr(record, "solver_eligible", True)
                                or str(getattr(record, "base_name", "") or "").casefold()
                                != candidate_key
                                or max(float(value) for value in observation.std_neu)
                                > _BASELINE_STD_REJECTION_THRESHOLD_M
                                or _vector_length(observation.baseline_neu) < 1.0
                            ):
                                continue
                            productive.append(str(candidate))
                            break
                    return productive

                def recovery_targets(
                    rover_code: str,
                    cross_edges: set[tuple[str, str]],
                ) -> set[str]:
                    """Target rovers outside the temporary base's current component."""

                    components = _graph_components(rovers, cross_edges)
                    rover_key = str(rover_code).casefold()
                    current_component = next(
                        (
                            component
                            for component in components
                            if rover_key in {name.casefold() for name in component}
                        ),
                        {str(rover_code)},
                    )
                    current_keys = {name.casefold() for name in current_component}
                    return {
                        str(candidate)
                        for candidate in rovers
                        if str(candidate).casefold() not in current_keys
                    }

                rotation_queue = list(rovers)
                initial_rotation_count = len(rotation_queue)
                completed_mandatory_rotations: set[str] = set()
                skipped_offline_rotation_keys: set[str] = set()
                waived_uncontrolled_rotation_keys: set[str] = set()
                graph_recovery_scheduled = False
                for rotation_index, rover_code in enumerate(rotation_queue):
                    if str(rover_code).casefold() in (
                        skipped_offline_rotation_keys
                        | waived_uncontrolled_rotation_keys
                    ):
                        continue
                    cluster["current_rotation_index"] = rotation_index + 1
                    cluster["current_stable_window_index"] = None
                    next_stable_window_index = 0
                    is_graph_recovery = rotation_index >= initial_rotation_count
                    if is_graph_recovery:
                        existing_edges, _ = current_solver_eligible_cross_coverage()
                        expected_cross_rovers = recovery_targets(rover_code, existing_edges)
                        if not expected_cross_rovers:
                            continue
                        await self._emit_progress(
                            project_id,
                            (
                                f"{rover_code}: targeted graph recovery for missing "
                                f"cross-baseline participant(s) "
                                f"{', '.join(sorted(expected_cross_rovers))}."
                            ),
                        )
                    else:
                        expected_cross_rovers = {
                            str(candidate)
                            for candidate in rovers
                            if str(candidate).casefold() != str(rover_code).casefold()
                            and str(candidate).casefold()
                            not in skipped_offline_rotation_keys
                        }

                    def mark_collection_started(
                        *,
                        current_cluster_index: int = cluster_index,
                        current_cluster: dict = cluster,
                        current_rover: str = rover_code,
                    ) -> None:
                        self._clear_cluster_fragment_buffers(project_id, current_cluster)
                        self._reset_online_baseline_states(
                            session,
                            current_cluster_index,
                            current_rover,
                        )
                        session["active_bases"][current_cluster_index] = current_rover

                    def mark_collection_stopped(
                        *,
                        current_cluster_index: int = cluster_index,
                        current_cluster: dict = cluster,
                    ) -> None:
                        session["active_bases"].pop(current_cluster_index, None)
                        self._clear_cluster_fragment_buffers(project_id, current_cluster)

                    for collection_attempt in range(1, self.CROSS_BASE_COLLECTION_ATTEMPTS + 1):
                        attempt_start_index = len(cluster["observations"])
                        solver_start_index = attempt_start_index

                        def eligible_records_from(
                            start_index: int,
                            *,
                            require_solver_eligible: bool = True,
                            current_rover: str = rover_code,
                            current_cluster: dict = cluster,
                        ) -> list:
                            eligible = []
                            for record in current_cluster["observations"][start_index:]:
                                observation = getattr(record, "observation", None)
                                if (
                                    getattr(record, "base_name", None) != current_rover
                                    or observation is None
                                    or (
                                        require_solver_eligible
                                        and not getattr(record, "solver_eligible", True)
                                    )
                                    or (
                                        not require_solver_eligible
                                        and "EXCLUDE_UNCONFIRMED_SOURCE"
                                        in tuple(getattr(record, "quality_flags", ()) or ())
                                    )
                                ):
                                    continue
                                if max(
                                    float(value) for value in observation.std_neu
                                ) > _BASELINE_STD_REJECTION_THRESHOLD_M:
                                    continue
                                if _vector_length(observation.baseline_neu) < 1.0:
                                    continue
                                eligible.append(record)
                            return eligible

                        def monitoring_records() -> list:
                            return eligible_records_from(
                                attempt_start_index,
                                require_solver_eligible=False,
                            )

                        def eligible_attempt_records() -> list:
                            return eligible_records_from(solver_start_index)

                        def mark_stable_collection_started(
                            *,
                            current_rover: str = rover_code,
                            current_cluster: dict = cluster,
                        ) -> None:
                            """Audit, but never solve with, handover/settling epochs."""

                            nonlocal solver_start_index, next_stable_window_index
                            records = current_cluster["observations"]
                            for record_index in range(solver_start_index, len(records)):
                                record = records[record_index]
                                if (
                                    record.base_name != current_rover
                                    or not record.solver_eligible
                                ):
                                    continue
                                flags = tuple(dict.fromkeys(
                                    (*record.quality_flags, "EXCLUDE_PRE_STABLE_WINDOW")
                                ))
                                record.solver_eligible = False
                                record.quality_flags = flags
                                record.source_diagnostic = (
                                    "Temporary-base source was verified, but this epoch "
                                    "belongs to the handover/settling window."
                                )
                            solver_start_index = len(records)
                            current_cluster["current_stable_window_index"] = next_stable_window_index
                            next_stable_window_index += 1
                            self._clear_cluster_fragment_buffers(project_id, current_cluster)

                        def mark_stable_collection_invalid(
                            reason: str = "stability",
                            *,
                            current_rover: str = rover_code,
                            current_cluster: dict = cluster,
                        ) -> None:
                            """Quarantine a solver window that drifted or timed out."""

                            nonlocal solver_start_index
                            reason_key = str(reason).casefold()
                            flag = {
                                "drift": "EXCLUDE_STABILITY_LOST",
                                "duration": "EXCLUDE_INSUFFICIENT_DURATION",
                                "source": "EXCLUDE_SOURCE_NOT_CONFIRMED",
                            }.get(reason_key, "EXCLUDE_STABILITY_NOT_REACHED")
                            records = current_cluster["observations"]
                            for record_index in range(solver_start_index, len(records)):
                                record = records[record_index]
                                if (
                                    record.base_name != current_rover
                                    or not record.solver_eligible
                                ):
                                    continue
                                flags = tuple(dict.fromkeys((
                                    *record.quality_flags,
                                    flag,
                                )))
                                record.solver_eligible = False
                                record.quality_flags = flags
                                diagnostic_messages = {
                                    "drift": (
                                        "Stationarity was lost after the solver window opened; "
                                        "the complete window was reset."
                                    ),
                                    "source": (
                                        "Temporary-base source identity was not confirmed."
                                    ),
                                    "duration": (
                                        "Stationarity was confirmed but minimum solver duration "
                                        "was not reached before timeout."
                                    ),
                                }
                                record.source_diagnostic = diagnostic_messages.get(
                                    reason_key,
                                    "Collection duration was sufficient, but the non-overlapping "
                                    "windows never satisfied mean/scatter/slope stationarity.",
                                )
                            solver_start_index = len(records)
                            current_cluster["current_stable_window_index"] = None
                            self._clear_cluster_fragment_buffers(project_id, current_cluster)

                        def collection_status(
                            _monitoring_fn=monitoring_records,
                            _eligible_fn=eligible_attempt_records,
                        ) -> dict:
                            monitoring = _monitoring_fn()
                            solver_eligible = _eligible_fn()

                            def epoch_map(records: list) -> Dict[str, set[int]]:
                                result: Dict[str, set[int]] = {}
                                for record in records:
                                    rover_name = str(record.observation.rover_name)
                                    result.setdefault(rover_name, set()).add(
                                        int(record.observation.epoch_ts)
                                    )
                                return result

                            epochs_by_rover = epoch_map(monitoring)
                            solver_epochs_by_rover = epoch_map(solver_eligible)
                            samples_by_rover: Dict[
                                str, list[tuple[int, tuple[float, float, float]]]
                            ] = {}
                            for record in monitoring:
                                rover_name = str(record.observation.rover_name)
                                samples_by_rover.setdefault(rover_name, []).append((
                                    int(record.observation.epoch_ts),
                                    tuple(
                                        float(value)
                                        for value in record.observation.baseline_neu
                                    ),
                                ))
                            online_states = session.setdefault(
                                "online_baseline_states", {}
                            )
                            for rover_name in tuple(samples_by_rover):
                                online_state = online_states.get(
                                    self._online_baseline_key(
                                        cluster_index,
                                        rover_code,
                                        rover_name,
                                    )
                                )
                                if online_state is not None:
                                    samples_by_rover[rover_name] = (
                                        online_state.recent_samples()
                                    )
                            return {
                                "sample_count": len(monitoring),
                                "rover_names": set(epochs_by_rover),
                                "sample_counts_by_rover": {
                                    rover_name: len(epochs)
                                    for rover_name, epochs in epochs_by_rover.items()
                                },
                                "solver_sample_counts_by_rover": {
                                    rover_name: len(epochs)
                                    for rover_name, epochs in solver_epochs_by_rover.items()
                                },
                                "solver_durations_by_rover_seconds": {
                                    rover_name: max(epochs) - min(epochs)
                                    for rover_name, epochs in solver_epochs_by_rover.items()
                                    if epochs
                                },
                                "rolling_stability_by_rover": {
                                    rover_name: _rolling_mean_stability(
                                        samples,
                                        window_seconds=self.STABILITY_WINDOW_SECONDS,
                                        min_samples_per_window=(
                                            self.STABILITY_MIN_SAMPLES_PER_WINDOW
                                        ),
                                        max_sample_gap_seconds=(
                                            self.STABILITY_MAX_SAMPLE_GAP_SECONDS
                                        ),
                                        horizontal_component_limit_m=(
                                            self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M
                                        ),
                                        up_component_limit_m=(
                                            self.STABILITY_UP_COMPONENT_LIMIT_M
                                        ),
                                        horizontal_std_limit_m=(
                                            self.STABILITY_HORIZONTAL_STD_LIMIT_M
                                        ),
                                        up_std_limit_m=self.STABILITY_UP_STD_LIMIT_M,
                                        horizontal_slope_limit_mps=(
                                            self.STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS
                                        ),
                                        up_slope_limit_mps=(
                                            self.STABILITY_UP_SLOPE_LIMIT_MPS
                                        ),
                                        ewma_fast_tau_seconds=(
                                            self.STABILITY_EWMA_FAST_TAU_SECONDS
                                        ),
                                        ewma_slow_tau_seconds=(
                                            self.STABILITY_EWMA_SLOW_TAU_SECONDS
                                        ),
                                        ewma_horizontal_limit_m=(
                                            self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                                        ),
                                        ewma_up_limit_m=(
                                            self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M
                                        ),
                                    )
                                    for rover_name, samples in samples_by_rover.items()
                                },
                                "online_information_by_rover": {
                                    rover_name: online_states[
                                        self._online_baseline_key(
                                            cluster_index,
                                            rover_code,
                                            rover_name,
                                        )
                                    ].audit_snapshot()
                                    for rover_name in samples_by_rover
                                    if self._online_baseline_key(
                                        cluster_index,
                                        rover_code,
                                        rover_name,
                                    ) in online_states
                                },
                            }

                        try:
                            async def wake_fixed_base_for_rover_restore() -> dict:
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: temporary route stopped; restoring fixed "
                                        f"BASE {configured_mountpoint} and waiting for its "
                                        "AICaster control session before SET ROVER."
                                    ),
                                )
                                await self._set_cors_fixed_base_enabled(
                                    str(configured_mountpoint),
                                    enabled=True,
                                    selected_host=configured_base_host,
                                    **fixed_base_identity_kwargs,
                                )
                                loop = asyncio.get_running_loop()
                                deadline = (
                                    loop.time()
                                    + self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS
                                )
                                while loop.time() < deadline:
                                    refreshed_client = await self._find_client_info(
                                        rover_code,
                                        project_id=project_id,
                                        log_missing=False,
                                    )
                                    if refreshed_client:
                                        return refreshed_client
                                    await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)
                                raise RuntimeError(
                                    f"{rover_code}: fixed BASE returned but its AICaster "
                                    "control session did not reconnect before ROVER restore"
                                )

                            async def sleep_fixed_base_before_temporary_route() -> None:
                                await self._set_cors_fixed_base_enabled(
                                    str(configured_mountpoint),
                                    enabled=False,
                                    selected_host=configured_base_host,
                                    all_streams=uses_common_base,
                                    **fixed_base_identity_kwargs,
                                )

                            await self._set_rover_as_temporary_base(
                                rover_code,
                                project_id=project_id,
                                route_host=route_host,
                                route_port=route_port,
                                route_mountpoint=(
                                    temporary_route_mountpoint or configured_mountpoint
                                ),
                                route_password=str(route_password),
                                on_collection_started=mark_collection_started,
                                on_stable_collection_started=mark_stable_collection_started,
                                on_stable_collection_invalid=mark_stable_collection_invalid,
                                on_collection_stopped=mark_collection_stopped,
                                collection_status_callback=collection_status,
                                expected_cross_rovers=expected_cross_rovers,
                                base_llh_override=frozen_base_coordinates.get(
                                    str(rover_code)
                                ),
                                before_rover_restore=(
                                    wake_fixed_base_for_rover_restore
                                    if configured_mountpoint
                                    else None
                                ),
                                before_route_start=(
                                    sleep_fixed_base_before_temporary_route
                                    if configured_mountpoint
                                    else None
                                ),
                            )
                        except _SafeRoverRotationSkip as exc:
                            warning = str(exc) or f"{rover_code}: temporary-base rotation skipped"
                            if collection_attempt < self.CROSS_BASE_COLLECTION_ATTEMPTS:
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: rotation ended after safe ROVER "
                                        "recovery; retrying the full temporary-BASE rotation "
                                        f"({collection_attempt + 1}/"
                                        f"{self.CROSS_BASE_COLLECTION_ATTEMPTS}). {warning}"
                                    ),
                                )
                                continue
                            logger.warning(
                                "Round-Robin project=%s rover=%s skipped safely: %s",
                                project_id,
                                rover_code,
                                warning,
                            )
                            session.setdefault("rotation_warnings", []).append({
                                "cluster_index": cluster_index,
                                "rover": rover_code,
                                "message": warning,
                            })
                            await self._emit_progress(
                                project_id,
                                f"{rover_code}: rotation skipped after safe ROVER recovery. {warning}",
                            )
                            break
                        except Exception:
                            session["active_bases"].pop(cluster_index, None)
                            raise

                        eligible = eligible_attempt_records()
                        collected_count = len(eligible)
                        collected_rovers = {
                            str(record.observation.rover_name)
                            for record in eligible
                        }
                        missing_rovers = sorted(expected_cross_rovers - collected_rovers)
                        current_solver_eligible_cross_coverage()
                        if collected_count > 0:
                            if not is_graph_recovery:
                                completed_mandatory_rotations.add(
                                    str(rover_code).casefold()
                                )
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: mandatory temporary-BASE rotation "
                                    f"complete; collected {collected_count} solver-eligible "
                                    "rover-to-rover AGRICA baseline(s) from "
                                    f"{', '.join(sorted(collected_rovers))}. "
                                    + (
                                        "No usable edge from "
                                        f"{', '.join(missing_rovers)}; final graph connectivity "
                                        "will decide whether adjustment can proceed. "
                                        if missing_rovers else ""
                                    )
                                    + f"Full-rotation progress "
                                    f"{len(completed_mandatory_rotations)}/"
                                    f"{initial_rotation_count}; continuing with every "
                                    "configured rover before solving."
                                ),
                            )
                            break

                        if collection_attempt < self.CROSS_BASE_COLLECTION_ATTEMPTS:
                            partial_detail = (
                                f"; valid rovers={', '.join(sorted(collected_rovers)) or 'none'}, "
                                f"missing={', '.join(missing_rovers) or 'none'}"
                            )
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: temporary-base coverage is incomplete"
                                    f"{partial_detail}; "
                                    f"retrying temporary BASE rotation "
                                    f"({collection_attempt + 1}/{self.CROSS_BASE_COLLECTION_ATTEMPTS})."
                                ),
                            )
                            continue

                        warning = (
                            f"{rover_code}: incomplete solver-eligible cross-baseline "
                            f"coverage after {self.CROSS_BASE_COLLECTION_ATTEMPTS} "
                            f"collection attempts; valid rovers="
                            f"{', '.join(sorted(collected_rovers)) or 'none'}, missing="
                            f"{', '.join(missing_rovers) or 'none'}"
                        )
                        logger.warning(
                            "Round-Robin project=%s rover=%s: %s",
                            project_id,
                            rover_code,
                            warning,
                        )
                        session.setdefault("rotation_warnings", []).append({
                            "cluster_index": cluster_index,
                            "rover": rover_code,
                            "message": warning,
                        })
                        await self._emit_progress(project_id, warning)
                    session["active_bases"].pop(cluster_index, None)
                    if (
                        not is_graph_recovery
                        and rotation_index + 1 < initial_rotation_count
                        and configured_mountpoint
                    ):
                        fixed_base_identity_kwargs = {
                            "selected_serial": configured_base_serial,
                            "selected_server_id": (configured_base_server_id or None),
                        }
                        for next_index in range(
                            rotation_index + 1,
                            initial_rotation_count,
                        ):
                            next_candidate = str(rotation_queue[next_index])
                            if next_candidate.casefold() in (
                                skipped_offline_rotation_keys
                                | waived_uncontrolled_rotation_keys
                            ):
                                continue
                            reacquired = await self._reacquire_fixed_base_between_rotations(
                                project_id,
                                cluster,
                                next_rover=next_candidate,
                                mountpoint=str(configured_mountpoint),
                                selected_host=configured_base_host,
                                **fixed_base_identity_kwargs,
                            )
                            if reacquired:
                                break
                            skip_mode = cluster.pop(
                                "_last_reacquire_skip_mode",
                                "offline",
                            )
                            if skip_mode == "uncontrolled":
                                waived_uncontrolled_rotation_keys.add(
                                    next_candidate.casefold()
                                )
                            else:
                                skipped_offline_rotation_keys.add(
                                    next_candidate.casefold()
                                )
                    if (
                        not graph_recovery_scheduled
                        and rotation_index + 1 == initial_rotation_count
                    ):
                        existing_edges, _ = current_solver_eligible_cross_coverage()
                        productive_bases = productive_temporary_bases()
                        if productive_bases and len(_graph_components(rovers, existing_edges)) > 1:
                            graph_recovery_scheduled = True
                            rotation_queue.extend(productive_bases)
                            missing_components = [
                                ", ".join(sorted(component))
                                for component in _graph_components(rovers, existing_edges)
                            ]
                            await self._emit_progress(
                                project_id,
                                (
                                    "Cross-baseline graph is still disconnected "
                                    f"(components: {' | '.join(missing_components)}); "
                                    "retrying proven temporary bases "
                                    f"{', '.join(productive_bases)} against only the "
                                    "missing component(s)."
                                ),
                            )

                required_rotation_keys = {
                    str(candidate).casefold() for candidate in rovers
                }
                missing_rotation_keys = (
                    required_rotation_keys
                    - completed_mandatory_rotations
                    - skipped_offline_rotation_keys
                    - waived_uncontrolled_rotation_keys
                )
                final_cross_edges, _ = current_solver_eligible_cross_coverage()
                if missing_rotation_keys:
                    cross_graph_connected = (
                        len(final_cross_edges) >= max(len(rovers) - 1, 1)
                        and len(_graph_components(rovers, final_cross_edges)) == 1
                    )
                    if not cross_graph_connected:
                        components = _graph_components(rovers, final_cross_edges)
                        raise RuntimeError(
                            "Temporary-BASE coverage is insufficient: missing productive "
                            "base rotation(s) "
                            + ", ".join(sorted(missing_rotation_keys))
                            + "; cross-baseline graph remains disconnected (components: "
                            + " | ".join(", ".join(sorted(component)) for component in components)
                            + ")"
                        )
                    warning = (
                        "Proceeding with connected partial rotation coverage; skipped "
                        "base rotation(s): "
                        + ", ".join(sorted(missing_rotation_keys))
                        + f". Cross graph remains connected with {len(final_cross_edges)} edge(s)."
                    )
                    session.setdefault("rotation_warnings", []).append({
                        "cluster_index": cluster_index,
                        "rover": ",".join(sorted(missing_rotation_keys)),
                        "message": warning,
                    })
                    await self._emit_progress(project_id, warning)
                await self._emit_progress(
                    project_id,
                    (
                        f"{cluster.get('name', cluster_index + 1)}: "
                        f"{len(completed_mandatory_rotations)}/"
                        f"{initial_rotation_count} temporary-BASE rotations completed; collected "
                        f"{len(final_cross_edges)} distinct rover-to-rover edge(s). "
                        "Proceeding to fixed-base restoration and network adjustment."
                    ),
                )

        except asyncio.CancelledError:
            logger.info("RoundRobin cycle cancelled for project %s", project_id)
            raise
        except Exception as exc:
            cycle_error = exc
        finally:
            restore_errors: List[str] = []
            for selected_host, mp, selected_serial, selected_server_id in suspended_bases:
                try:
                    await self._emit_progress(
                        project_id,
                        f"Khôi phục đúng chế độ stream ban đầu của Base cố định {mp}.",
                    )
                    restore_identity_kwargs = {}
                    if selected_serial:
                        restore_identity_kwargs["selected_serial"] = selected_serial
                    if selected_server_id:
                        restore_identity_kwargs["selected_server_id"] = selected_server_id
                    await self._set_cors_fixed_base_enabled(
                        mp,
                        enabled=True,
                        selected_host=selected_host,
                        **restore_identity_kwargs,
                    )
                    await self._emit_progress(
                        project_id,
                        f"Khôi phục Base cố định {mp} thành công; chế độ stream ban đầu đã được áp dụng.",
                    )
                except Exception as e:
                    logger.exception("Failed to restore fixed base %s in finally block: %s", mp, e)
                    restore_errors.append(f"{mp}: {e}")
            for snapshot in reversed(list(disabled_conflict_bases.values())):
                try:
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        snapshot["serial"],
                        copy.deepcopy(snapshot["service_config"]),
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to restore conflict base %s in finally block: %s",
                        snapshot["serial"],
                        e,
                    )
                    restore_errors.append(f"{snapshot['serial']}: {e}")
            try:
                await self.restore_common_fixed_base_topology(project_id)
            except Exception as e:
                logger.exception(
                    "Failed to restore common fixed-base topology for project %s: %s",
                    project_id,
                    e,
                )
                restore_errors.append(str(e))
            self.running_tasks.pop(project_id, None)

            # A result must never be announced before every fixed-base stream is
            # restored. Otherwise the later restore progress event regresses the
            # public phase from COMPLETED back to FREE_NETWORK.
            if restore_errors and cycle_error is None:
                cycle_error = RuntimeError(
                    "could not restore fixed-base stream mode: " + "; ".join(restore_errors)
                )

        if cycle_error is not None:
            logger.error("RoundRobin cycle failed for project %s: %s", project_id, cycle_error)
            if self.error_callback:
                callback_result = self.error_callback(project_id, str(cycle_error))
                if inspect.isawaitable(callback_result):
                    await callback_result
            return

        try:
            completed_results: List[dict] = []
            for cluster_index, cluster in enumerate(session["clusters"]):
                self._exclude_fixed_base_records(
                    cluster,
                    int(cluster.get("fixed_base_seed_cutoff_index", len(cluster["observations"]))),
                    flag="EXCLUDE_POST_SEED_TRANSITION",
                    diagnostic=(
                        "Fixed-BASE epoch arrived after the common seed window was "
                        "frozen; retained for source/reconnection audit only."
                    ),
                )
                await self._emit_progress(
                    project_id,
                    (
                        f"{cluster.get('name', cluster_index + 1)}: aggregating repeated baselines "
                        "to one covariance-weighted value per geometric edge and solving the network."
                    ),
                )
                result = self._build_cluster_result(project_id, cluster_index, cluster)
                rotation_warnings = [
                    item
                    for item in session.get("rotation_warnings", [])
                    if item.get("cluster_index") == cluster_index
                ]
                if rotation_warnings:
                    result["rotation_warnings"] = rotation_warnings
                    result.setdefault("quality", {})["rotation_warning_count"] = len(rotation_warnings)
                logger.info(
                    "Network adjustment completed for project=%s cluster=%s: %s rover points",
                    project_id,
                    cluster.get("name", cluster_index + 1),
                    result["rover_count"],
                )
                completed_results.append(result)

            # Build every cluster first. Once the first result callback publishes
            # COMPLETED, no later FREE_NETWORK progress is allowed to regress it.
            for result in completed_results:
                if self.result_callback:
                    callback_result = self.result_callback(project_id, result)
                    if inspect.isawaitable(callback_result):
                        await callback_result
        except Exception as exc:
            logger.exception("Network adjustment failed for project %s: %s", project_id, exc)
            if self.error_callback:
                callback_result = self.error_callback(project_id, str(exc))
                if inspect.isawaitable(callback_result):
                    await callback_result


    async def _emit_progress(self, project_id: Optional[int], message: str) -> None:
        # Every phase boundary is a safe cooperative pause point. The current
        # receiver command is allowed to finish before execution is suspended.
        await self._wait_for_run_permission(project_id)
        logger.info("[Round-Robin PHASE] %s", message)
        if project_id is None or not self.progress_callback:
            return
        try:
            callback_result = self.progress_callback(project_id, message)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning("Could not broadcast Round-Robin PHASE: %s", exc)
