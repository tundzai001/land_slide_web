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


    def _has_dual_selected_stream(self, cluster: dict) -> bool:
        if not requires_common_base_handover(cluster):
            return False
        candidates = self._fixed_base_candidates(cluster)
        selected_config = candidates[0].get("base_service_config") or {}
        return len(candidates) >= 2 or all(
            bool(str(selected_config.get(f"mountpoint{server_id}") or "").strip())
            for server_id in (1, 2)
        )

    def _filter_online_and_usable_candidates(
        self, resolved_candidates: list, cluster: dict, cluster_index: int
    ) -> list[tuple[dict, tuple[dict, int]]]:
        usable_candidates = []
        online_candidates = []
        for candidate, candidate_match in resolved_candidates:
            candidate_station, _ = candidate_match
            if not self._cors_station_is_online(candidate_station):
                continue
            online_candidates.append((candidate, candidate_match))
            service_config = self._cors_effective_service_config(candidate_station, candidate.get("base_service_config"))
            if all(bool(str(service_config.get(f"mountpoint{s}") or "").strip()) for s in (1, 2)):
                usable_candidates.append((candidate, candidate_match))

        if not online_candidates:
            names = ", ".join(str(c.get("base_station") or "unknown") for c, _ in resolved_candidates)
            raise RuntimeError(f"{cluster.get('name', cluster_index + 1)}: no configured physical base is online ({names})")
        if not usable_candidates:
            names = ", ".join(str(c.get("base_station") or "unknown") for c, _ in online_candidates)
            raise RuntimeError(f"{cluster.get('name', cluster_index + 1)}: online physical base(s) {names} must have explicit mountpoints configured for both S1 and S2")
        return usable_candidates

    def _find_fallback_opposite_station(self, stations: list, other: dict) -> list[dict]:
        target_serial = str(other.get("base_serial") or "").strip().casefold()
        target_name = str(other.get("base_station") or "").strip().casefold()
        return [
            st for st in stations
            if (target_serial and str(st.get("serial") or "").strip().casefold() == target_serial)
            or (not target_serial and target_name and str(st.get("name") or st.get("code") or "").strip().casefold() == target_name)
        ]

    def _find_opposite_physical_station(
        self, stations: list, selected_serial: str, paired_mountpoints: set,
        candidates: list, selected: dict, cluster: dict, cluster_index: int
    ) -> dict:
        physical_matches = [
            st for st in stations
            if str(st.get("serial") or "").strip().casefold() != selected_serial.casefold()
            and paired_mountpoints.intersection({
                str(st.get("name") or "").strip().casefold(), str(st.get("code") or "").strip().casefold(),
                str(st.get("mountpoint") or "").strip().casefold(),
                str(self._cors_effective_service_config(st).get("mountpoint1") or "").strip().casefold(),
            })
        ]
        other = next((c for c in candidates if c is not selected), {})
        if len(physical_matches) != 1 and other:
            physical_matches = self._find_fallback_opposite_station(stations, other)
        if len(physical_matches) != 1:
            raise RuntimeError(f"{cluster.get('name', cluster_index + 1)}: selected base has reciprocal mountpoint(s) {sorted(paired_mountpoints)}, but matched {len(physical_matches)} opposite physical stations")
        return physical_matches[0]

    def _resolve_cluster_common_base(
        self, cluster: dict, cluster_index: int, stations: list
    ) -> tuple[dict, dict, dict, str, bool]:
        candidates = self._fixed_base_candidates(cluster)
        resolved_candidates = []
        for candidate in candidates:
            candidate_match = self._cors_failover_stream(
                stations, station_name=candidate.get("base_station"), serial=candidate.get("base_serial"),
                server_id=candidate.get("base_server_id"), host=candidate.get("base_stream_host"), mountpoint=candidate.get("base_stream_mp"),
            )
            if candidate_match is not None:
                resolved_candidates.append((candidate, candidate_match))

        if not resolved_candidates:
            raise RuntimeError(f"{cluster.get('name', cluster_index + 1)}: could not resolve any configured CORS failover stream uniquely")

        usable_candidates = self._filter_online_and_usable_candidates(resolved_candidates, cluster, cluster_index)
        selected, selected_match = usable_candidates[0]
        selected_station, _ = selected_match
        selected_serial = str(selected_station.get("serial") or "").strip()
        selected_service_config = self._cors_effective_service_config(selected_station, selected.get("base_service_config"))
        try:
            selected_server_id = int(selected.get("base_server_id") or 1)
        except (TypeError, ValueError):
            selected_server_id = 1

        paired_mountpoints = {
            str(selected_service_config.get(f"mountpoint{s}") or "").strip().casefold()
            for s in (1, 2) if s != selected_server_id and str(selected_service_config.get(f"mountpoint{s}") or "").strip()
        }
        other_station = self._find_opposite_physical_station(
            stations, selected_serial, paired_mountpoints, candidates, selected, cluster, cluster_index
        )
        other_name = str(other_station.get("name") or other_station.get("code") or "").strip()
        other_online = self._cors_station_is_online(other_station)
        return selected, selected_station, other_station, other_name, other_online

    def _lock_non_dual_clusters(self, clusters: list) -> None:
        for cluster in clusters:
            candidates = self._fixed_base_candidates(cluster)
            if len(candidates) == 1:
                self._lock_fixed_base_candidate(cluster, candidates[0], "configured fixed base selected before seed collection")
            elif not cluster.get("selected_fixed_base_candidate"):
                cluster["selected_fixed_base_candidate"] = None
                cluster["fixed_base_selection_diagnostic"] = "awaiting AGRICA confirmation of the active primary/backup base"

    async def _apply_cluster_common_base_topology(
        self, session: dict, cluster: dict, cluster_index: int,
        resolved_tuple: tuple
    ) -> dict:
        selected, selected_station, other_station, other_name, other_online = resolved_tuple
        snapshots: dict[str, dict] = session.setdefault("seed_topology_snapshots", {})
        selected_serial = str(selected_station.get("serial") or "").strip()
        other_serial = str(other_station.get("serial") or "").strip()

        for station in (selected_station, other_station):
            serial = str(station.get("serial") or "").strip()
            snapshots.setdefault(serial.casefold(), {"serial": serial, "service_config": self._cors_effective_service_config(station)})
        session.setdefault("seed_topology_managed_serials", set()).update({selected_serial.casefold(), other_serial.casefold()})

        if other_online:
            other_disabled = self._cors_service_config_with_server_enabled(
                self._cors_effective_service_config(other_station), None, enabled=False
            )
            await asyncio.to_thread(self._cors_configure_service_sync, other_serial, other_disabled)
            other_station["service_config"] = other_disabled

        selected_service_config = self._cors_effective_service_config(selected_station, selected.get("base_service_config"))
        selected_enabled = self._cors_service_config_with_server_enabled(selected_service_config, None, enabled=True)
        if selected_enabled != selected_service_config:
            await asyncio.to_thread(self._cors_configure_service_sync, selected_serial, selected_enabled)
            selected_station["service_config"] = selected_enabled

        self._lock_fixed_base_candidate(
            cluster, selected,
            f"selected {selected.get('base_station')} had both S1/S2 hard-enabled; opposite station {other_name} was {'online and stopped' if other_online else 'offline'} before seed"
        )
        cluster["require_fixed_base_length_check"] = True
        return {
            "cluster": str(cluster.get("name") or cluster_index + 1),
            "selected_base": str(selected.get("base_station") or ""),
            "opposite_base": other_name,
            "opposite_online": other_online,
            "state": "COMMON_SELECTED_BASE_PENDING_RTCM_VERIFICATION",
        }

    async def _verify_common_base_rtcm_handover(self, session: dict, project_id: int) -> None:
        await self._emit_progress(
            project_id,
            "Đã ngắt base đối nghịch và bật cả S1/S2 của base được chọn; đang chờ RTCM chuyển nguồn ổn định trước khi thu baseline chung.",
        )
        await asyncio.sleep(self.FIXED_BASE_HANDOVER_SETTLE_SECONDS)
        for cluster in session["clusters"]:
            cluster["observations"].clear()
            self._clear_cluster_fragment_buffers(project_id, cluster)
        session["seed_station_reports"].clear()

        verify_seconds = max(0.0, self.FIXED_BASE_HANDOVER_VERIFY_SECONDS)
        if not verify_seconds:
            return
        expected_station_ids = {int(s_id) for cl in session["clusters"] for s_id in cl["stations"]}
        deadline = time.monotonic() + verify_seconds
        while time.monotonic() < deadline:
            reports = session.get("seed_station_reports", {})
            verified_ids = {int(s_id) for s_id, rep in reports.items() if rep.get("base_identity_verified") is True}
            if expected_station_ids <= verified_ids:
                break
            await asyncio.sleep(0.25)
        else:
            reports = session.get("seed_station_reports", {})
            pending = [
                f"{r_code}: {reports.get(int(s_id), {}).get('reason') or 'no fresh AGRICA'}"
                for cl in session["clusters"]
                for s_id, r_code in zip(cl["stations"], cl["rovers"], strict=True)
                if reports.get(int(s_id), {}).get("base_identity_verified") is not True
            ]
            raise RuntimeError(f"common-base handover was not confirmed by every rover within {verify_seconds:.0f}s; {'; '.join(pending)}")

        for cluster in session["clusters"]:
            cluster["observations"].clear()
            self._clear_cluster_fragment_buffers(project_id, cluster)
        session["seed_station_reports"].clear()
        session["seed_started_monotonic"] = time.monotonic()

    async def _process_cluster_common_base_seed(
        self, session: dict, cluster: dict, cluster_index: int, stations: list
    ) -> Optional[dict]:
        candidates = self._fixed_base_candidates(cluster)
        if not self._has_dual_selected_stream(cluster):
            if len(candidates) == 1:
                self._lock_fixed_base_candidate(cluster, candidates[0], "configured fixed base selected before seed collection")
            elif not cluster.get("selected_fixed_base_candidate"):
                cluster["selected_fixed_base_candidate"] = None
                cluster["fixed_base_selection_diagnostic"] = "awaiting AGRICA confirmation of the active primary/backup base"
            return None

        resolved_tuple = self._resolve_cluster_common_base(cluster, cluster_index, stations)
        return await self._apply_cluster_common_base_topology(session, cluster, cluster_index, resolved_tuple)

    async def _prepare_common_fixed_base_seed_unlocked(
        self,
        project_id: int,
    ) -> list[dict]:
        session = self._sessions.get(project_id)
        if session is None:
            raise KeyError(f"no active adjustment session for project {project_id}")

        if not any(self._has_dual_selected_stream(cluster) for cluster in session["clusters"]):
            self._lock_non_dual_clusters(session["clusters"])
            return []

        raw_stations = await asyncio.to_thread(self._cors_api_request_sync, "GET", "/api/public/map-stations")
        if isinstance(raw_stations, dict):
            raw_stations = raw_stations.get("value") or raw_stations.get("items") or []
        stations = [item for item in (raw_stations or []) if isinstance(item, dict)]
        outcomes: list[dict] = []

        try:
            for cluster_index, cluster in enumerate(session["clusters"]):
                outcome = await self._process_cluster_common_base_seed(session, cluster, cluster_index, stations)
                if outcome:
                    outcomes.append(outcome)

            if outcomes:
                await self._verify_common_base_rtcm_handover(session, project_id)
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


    def _scan_reacquire_observations(
        self, cluster: dict, start_index: int, next_rover: str
    ) -> tuple[Dict[str, set[int]], int]:
        epochs_by_rover: Dict[str, set[int]] = {}
        next_rover_records = 0
        for record in cluster["observations"][start_index:]:
            observation = getattr(record, "observation", None)
            if observation is not None and str(getattr(observation, "rover_name", "")) == str(next_rover):
                next_rover_records += 1
            if (
                observation is None
                or getattr(record, "base_name", None) != "BASE"
                or not getattr(record, "solver_eligible", True)
                or max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M
                or _vector_length(observation.baseline_neu) < 1.0
            ):
                continue
            rover_name = str(observation.rover_name)
            epochs_by_rover.setdefault(rover_name, set()).add(int(observation.epoch_ts))
        return epochs_by_rover, next_rover_records

    async def _handle_reacquire_failure(
        self, cluster: dict, project_id: int, next_rover: str, all_rovers: set,
        epochs_by_rover: dict, elapsed_seconds: int, client_state: tuple,
        next_rover_record_count: int, fixed_ready: bool, start_index: int
    ) -> bool:
        client_check_state, client_check_error, next_client_confirmed = client_state
        counts = {rover_name: len(epochs_by_rover.get(rover_name, ())) for rover_name in sorted(all_rovers)}
        client_detail = f"{client_check_state} ({client_check_error})" if client_check_error else client_check_state
        detail = (
            f"Fixed BASE reacquisition before {next_rover} timed out after {elapsed_seconds}s "
            f"(nominal {self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS}s, hard limit {self.INTER_ROTATION_REACQUIRE_MAX_SECONDS}s); "
            f"BASE epochs={counts}, next AICaster session={client_detail}"
        )
        confirmed_offline = client_check_state == "checked-missing"
        fixed_service_proven_elsewhere = any(
            rover_name != str(next_rover) and len(epochs) >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
            for rover_name, epochs in epochs_by_rover.items()
        )
        fixed_data_missing = bool(
            next_client_confirmed and not fixed_ready and (next_rover_record_count > 0 or fixed_service_proven_elsewhere)
        )
        live_but_uncontrolled = bool(confirmed_offline and next_rover_record_count > 0)
        if not confirmed_offline and not fixed_data_missing:
            raise RuntimeError(detail)
        if fixed_data_missing:
            availability = "AICaster control session is active but no fresh, solver-eligible fixed-BASE epochs arrived"
            skip_detail = "skipping this data-plane-stale rover from the remaining temporary-BASE rotation and cross-baseline expectations. "
            skip_mode = "offline"
        elif live_but_uncontrolled:
            availability = "AGRICA is live but the AICaster control identity is unavailable"
            skip_detail = "skipping only its temporary-BASE rotation. The station remains eligible as a rover in other rotations. "
            skip_mode = "uncontrolled"
        else:
            availability = "AICaster session disappeared"
            skip_detail = "skipping its temporary-BASE rotation. "
            skip_mode = "offline"

        warning = f"{next_rover}: {availability} during inter-rotation handover; {skip_detail}{detail}"
        cluster["_last_reacquire_skip_mode"] = skip_mode
        session = self._sessions.get(project_id) or {}
        session.setdefault("rotation_warnings", []).append({
            "cluster_index": int(cluster.get("current_rotation_index") or 0),
            "rover": str(next_rover),
            "message": warning,
        })
        await self._emit_progress(project_id, warning)
        self._exclude_fixed_base_records(
            cluster, start_index, flag="EXCLUDE_INTER_ROTATION_REACQUISITION",
            diagnostic="Fresh fixed-BASE epoch used only to verify inter-rotation NTRIP reacquisition; excluded from the common fixed-BASE solver seed.",
        )
        return False

    async def _poll_reacquire_client_session(
        self, project_id: int, next_rover: str, client_check_failure_logged: bool
    ) -> tuple[bool, str, str, bool]:
        try:
            client_info = await self._find_client_info(next_rover, project_id=project_id, log_missing=False)
            return client_info is not None, "confirmed" if client_info is not None else "checked-missing", "", client_check_failure_logged
        except Exception as exc:
            err = str(exc) or type(exc).__name__
            if not client_check_failure_logged:
                logger.warning(
                    "AICaster session check failed during fixed BASE reacquisition for %s; polling will continue: %s",
                    next_rover, err,
                )
            return False, "check-failed", err, True

    def _check_reacquire_early_exit(
        self, fixed_ready: bool, next_client_confirmed: bool, next_rover: str,
        epochs_by_rover: dict, next_rover_record_count: int, started_at: float, now: float
    ) -> bool:
        if fixed_ready and next_client_confirmed:
            return True
        fixed_proven = any(
            rover != str(next_rover) and len(epochs) >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
            for rover, epochs in epochs_by_rover.items()
        )
        return bool(
            next_client_confirmed and next_rover_record_count == 0 and fixed_proven
            and now - started_at >= self.INTER_ROTATION_STALE_ROVER_GRACE_SECONDS
        )

    async def _evaluate_reacquire_deadline(
        self, project_id: int, next_rover: str, now: float, nominal_deadline: float,
        hard_deadline: float, last_activity: Optional[float], extension_announced: bool
    ) -> tuple[bool, bool]:
        activity_deadline = (
            last_activity + self.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS
            if last_activity is not None else nominal_deadline
        )
        effective_deadline = min(hard_deadline, max(nominal_deadline, activity_deadline))
        if now >= nominal_deadline and effective_deadline > now:
            if not extension_announced:
                await self._emit_progress(
                    project_id,
                    f"{next_rover}: nominal fixed-BASE reacquisition wait reached {self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS}s, but fresh AGRICA transition data is still arriving; extending adaptively up to {self.INTER_ROTATION_REACQUIRE_MAX_SECONDS}s.",
                )
                return False, True
            return False, True
        return (now >= effective_deadline), extension_announced

    async def _poll_reacquire_readiness(
        self, project_id: int, next_rover: str, required_rovers: set[str],
        epochs_by_rover: dict, now: float, next_client_check_at: float,
        next_client_confirmed: bool, client_check_state: str,
        client_check_error: str, client_check_failure_logged: bool
    ) -> tuple[bool, bool, str, str, bool, float]:
        fixed_ready = all(
            len(epochs_by_rover.get(rover_name, ())) >= self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS
            for rover_name in required_rovers
        )
        if fixed_ready or now >= next_client_check_at:
            next_client_confirmed, client_check_state, client_check_error, client_check_failure_logged = (
                await self._poll_reacquire_client_session(project_id, next_rover, client_check_failure_logged)
            )
            next_client_check_at = now + self.INTER_ROTATION_CLIENT_POLL_SECONDS
        return fixed_ready, next_client_confirmed, client_check_state, client_check_error, client_check_failure_logged, next_client_check_at

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
        start_index = len(cluster["observations"])
        cluster.pop("_last_reacquire_skip_mode", None)
        identity_kwargs = {}
        if selected_serial:
            identity_kwargs["selected_serial"] = selected_serial
        if selected_server_id is not None:
            identity_kwargs["selected_server_id"] = selected_server_id
        await self._emit_progress(
            project_id,
            f"Inter-rotation handover: restoring fixed BASE {mountpoint} so every rover reconnects before {next_rover} becomes the next temporary base.",
        )
        await self._set_cors_fixed_base_enabled(
            mountpoint, enabled=True, selected_host=selected_host, **identity_kwargs,
        )

        all_rovers = {str(name) for name in cluster.get("rovers", ())}
        required_rovers = {str(next_rover)}
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        nominal_deadline = started_at + self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS
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
        fixed_ready = False

        while loop.time() < hard_deadline:
            now = loop.time()
            epochs_by_rover, current_next_rover_records = self._scan_reacquire_observations(
                cluster, start_index, next_rover
            )
            if current_next_rover_records > next_rover_record_count:
                next_rover_record_count = current_next_rover_records
                last_next_rover_activity_at = now

            fixed_ready, next_client_confirmed, client_check_state, client_check_error, client_check_failure_logged, next_client_check_at = (
                await self._poll_reacquire_readiness(
                    project_id, next_rover, required_rovers, epochs_by_rover, now,
                    next_client_check_at, next_client_confirmed, client_check_state,
                    client_check_error, client_check_failure_logged
                )
            )

            if self._check_reacquire_early_exit(
                fixed_ready, next_client_confirmed, next_rover, epochs_by_rover,
                next_rover_record_count, started_at, now
            ):
                break

            should_break, extension_announced = await self._evaluate_reacquire_deadline(
                project_id, next_rover, now, nominal_deadline, hard_deadline,
                last_next_rover_activity_at, extension_announced
            )
            if should_break:
                break
            await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

        if not (fixed_ready and next_client_confirmed):
            elapsed_seconds = max(0, int(round(loop.time() - started_at)))
            client_state = (client_check_state, client_check_error, next_client_confirmed)
            return await self._handle_reacquire_failure(
                cluster, project_id, next_rover, all_rovers, epochs_by_rover,
                elapsed_seconds, client_state, next_rover_record_count, fixed_ready, start_index
            )

        await self._emit_progress(
            project_id,
            f"Inter-rotation handover verified: {next_rover} supplied at least {self.INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS} fresh fixed-BASE epochs and has an active AICaster session. Other slow clients remain quarantined by source/length validation. Keeping {mountpoint} active through the next rover preflight; it will Sleep immediately before temporary SOURCE fanout.",
        )
        self._exclude_fixed_base_records(
            cluster, start_index, flag="EXCLUDE_INTER_ROTATION_REACQUISITION",
            diagnostic="Fresh fixed-BASE epoch used only to verify inter-rotation NTRIP reacquisition; excluded from the common fixed-BASE solver seed.",
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


    def _collect_rover_seed_candidates(
        self, cluster: dict, rover_key: str, fixed_llh: tuple, transforms_mod: tuple
    ) -> list[tuple[np.ndarray, np.ndarray, int, int]]:
        neu_to_ecef_cov, _ = transforms_mod
        candidates: list[tuple[np.ndarray, np.ndarray, int, int]] = []
        for record_index, record in enumerate(cluster.get("observations", ())):
            observation = getattr(record, "observation", None)
            if (
                observation is None
                or str(getattr(record, "base_name", "")).casefold() != "base"
                or str(getattr(observation, "rover_name", "")).casefold() != rover_key
                or not getattr(record, "solver_eligible", True)
                or max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M
                or _vector_length(observation.baseline_neu) < 1.0
            ):
                continue
            delta = np.asarray(self._baseline_ecef(observation, fixed_llh), dtype=float)
            covariance = np.asarray(
                neu_to_ecef_cov(observation.std_neu, fixed_llh[0], fixed_llh[1]),
                dtype=float,
            )
            if (
                delta.shape == (3,)
                and covariance.shape == (3, 3)
                and np.all(np.isfinite(delta))
                and np.all(np.isfinite(covariance))
            ):
                candidates.append((delta, covariance, int(observation.epoch_ts), record_index))
        return candidates

    def _filter_and_weight_seed_candidates(
        self, candidates: list, configured_rover: str, fixed_ecef: np.ndarray
    ) -> tuple[dict, set[int]]:
        if not candidates:
            raise RuntimeError(
                f"Cannot freeze temporary BASE coordinate for {configured_rover}: the initial fixed-BASE solver window has no valid observation"
            )
        vectors = np.vstack([item[0] for item in candidates])
        center = np.median(vectors, axis=0)
        deviations = np.linalg.norm(vectors - center, axis=1)
        median_dev = float(np.median(deviations))
        mad = float(np.median(np.abs(deviations - median_dev)))
        rejection_limit = max(0.25, median_dev + 8.0 * 1.4826 * mad)
        retained = [
            item for item, deviation in zip(candidates, deviations, strict=True)
            if float(deviation) <= rejection_limit
        ]
        if not retained:
            raise RuntimeError(
                f"Cannot freeze temporary BASE coordinate for {configured_rover}: all fixed-BASE seed vectors were rejected"
            )

        precision_sum = np.zeros((3, 3), dtype=float)
        weighted_sum = np.zeros(3, dtype=float)
        for delta, covariance, _epoch, _record_index in retained:
            precision = _spd_solve(covariance, np.eye(3, dtype=float))
            precision_sum += precision
            weighted_sum += precision @ delta
        endpoint = fixed_ecef + np.linalg.solve(precision_sum, weighted_sum)
        lat, lon, alt = _ecef_to_llh(*endpoint)
        rover_frozen = {
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
        retained_indices = {item[3] for item in retained}
        return rover_frozen, retained_indices

    def _apply_seed_records_snapshot(self, cluster: dict, retained_record_indices: set[int]) -> None:
        seed_snapshot = copy.deepcopy(list(cluster.get("observations", ())))
        for record_index, record in enumerate(seed_snapshot):
            if (
                str(getattr(record, "base_name", "")).casefold() != "base"
                or not getattr(record, "solver_eligible", True)
                or record_index in retained_record_indices
            ):
                continue
            record.solver_eligible = False
            record.quality_flags = tuple(dict.fromkeys((
                *tuple(getattr(record, "quality_flags", ()) or ()),
                "EXCLUDE_FIXED_BASE_SEED_FREEZE_OUTLIER",
            )))
            record.source_diagnostic = (
                "Fixed-BASE seed was not retained by the same robust vector/STD selection that froze the temporary-BASE coordinates."
            )
        cluster["fixed_base_seed_records_snapshot"] = seed_snapshot

    def _freeze_temporary_base_coordinates(self, cluster: dict) -> Dict[str, dict]:
        try:
            from backend.processors.gnss_adjustment.transforms import neu_standard_deviation_to_ecef_covariance
            from backend.processors.gnss_adjustment.runtime import _llh_to_ecef
        except ModuleNotFoundError:
            from processors.gnss_adjustment.transforms import neu_standard_deviation_to_ecef_covariance
            from processors.gnss_adjustment.runtime import _llh_to_ecef

        transforms_mod = (neu_standard_deviation_to_ecef_covariance, _llh_to_ecef)
        fixed_llh = self._cluster_base_llh(cluster)
        fixed_ecef = np.asarray(_llh_to_ecef(*fixed_llh), dtype=float)
        frozen: Dict[str, dict] = {}
        retained_record_indices: set[int] = set()

        for configured_rover in cluster.get("rovers", ()):
            rover_key = str(configured_rover).casefold()
            candidates = self._collect_rover_seed_candidates(cluster, rover_key, fixed_llh, transforms_mod)
            rover_frozen, rover_retained = self._filter_and_weight_seed_candidates(candidates, configured_rover, fixed_ecef)
            frozen[str(configured_rover)] = rover_frozen
            retained_record_indices.update(rover_retained)

        self._apply_seed_records_snapshot(cluster, retained_record_indices)
        cluster["temporary_base_llh_by_rover"] = frozen
        return frozen


    def _resolve_cycle_fixed_base(self, cluster: dict, cluster_index: int) -> dict:
        selected_fixed_base = cluster.get("selected_fixed_base_candidate")
        if not isinstance(selected_fixed_base, dict):
            configured_candidates = self._fixed_base_candidates(cluster)
            if len(configured_candidates) == 1:
                selected_fixed_base = configured_candidates[0]
                self._lock_fixed_base_candidate(
                    cluster, selected_fixed_base, "legacy single fixed-base configuration"
                )
            else:
                raise RuntimeError(
                    f"{cluster.get('name', cluster_index + 1)}: fixed-base "
                    "primary/backup candidate was not confirmed by AGRICA before the round-robin cycle"
                )
        return selected_fixed_base

    def _resolve_cycle_route_config(self, cluster: dict, selected_fixed_base: dict) -> tuple[str, int, Optional[str], Optional[str]]:
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
            cluster.get("round_robin_route_mountpoint") or cluster.get("base_stream_mp")
        )
        route_password = cluster.get("round_robin_route_password")
        if route_password is None:
            route_password = self.source_password
        return route_host, route_port, configured_mountpoint, route_password

    async def _prepare_conflict_bases_sleep(
        self, project_id: int, cluster: dict, session: dict, disabled_conflict_bases: dict
    ) -> None:
        conflict_bases = (
            [] if session.get("seed_topology_snapshots") else cluster.get("conflict_bases", [])
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
                    original_config = await asyncio.to_thread(self._disable_conflict_base_sync, cb_serial)
                    if original_config is not None:
                        disabled_conflict_bases[cb_key] = {"serial": cb_serial, "service_config": original_config}
                    await asyncio.sleep(2.0)
                except Exception as e:
                    logger.exception(f"Failed to sleep conflict base {cb_name}: {e}")

    async def _init_cycle_cluster(
        self, project_id: int, cluster_index: int, cluster: dict, session: dict,
        suspended_bases: set, disabled_conflict_bases: dict
    ) -> dict:
        rovers = cluster["rovers"]
        post_seed_start_index = len(cluster["observations"])
        cluster["fixed_base_seed_cutoff_index"] = post_seed_start_index
        logger.info(
            "Starting Round-Robin project=%s cluster=%s with %s rovers: %s",
            project_id, cluster.get("name", cluster_index + 1), len(rovers), rovers,
        )
        selected_fixed_base = self._resolve_cycle_fixed_base(cluster, cluster_index)
        await self._emit_progress(
            project_id,
            f"{cluster.get('name', cluster_index + 1)}: locked {selected_fixed_base.get('role', 'fixed')} fixed base "
            f"{selected_fixed_base.get('base_station')} at {selected_fixed_base.get('base_stream_host')}:"
            f"{selected_fixed_base.get('base_stream_port')}/{selected_fixed_base.get('base_stream_mp')}.",
        )
        frozen_base_coordinates = self._freeze_temporary_base_coordinates(cluster)
        await self._emit_progress(
            project_id,
            f"{cluster.get('name', cluster_index + 1)}: froze temporary-BASE coordinates for {', '.join(str(rover) for rover in rovers)}.",
        )
        route_host, route_port, configured_mountpoint, route_password = self._resolve_cycle_route_config(cluster, selected_fixed_base)
        uses_common_base = requires_common_base_handover(cluster)
        temporary_route_mountpoint = self._resolve_temporary_route_mountpoint(
            cluster, uses_common_base, route_host, configured_mountpoint
        )
        configured_base_host = str(selected_fixed_base.get("base_stream_host") or route_host).strip()
        configured_base_serial = str(selected_fixed_base.get("base_serial") or "").strip()
        configured_base_server_id = selected_fixed_base.get("base_server_id")
        base_stream_key = (configured_base_host, str(configured_mountpoint or ""), configured_base_serial, configured_base_server_id)

        if configured_mountpoint and base_stream_key not in suspended_bases:
            await self._emit_progress(
                project_id,
                f"Đã khóa topology Base cố định {configured_mountpoint}; giữ stream hoạt động qua preflight.",
            )
            suspended_bases.add(base_stream_key)
            await self._prepare_conflict_bases_sleep(project_id, cluster, session, disabled_conflict_bases)

        self._exclude_fixed_base_records(
            cluster, post_seed_start_index, flag="EXCLUDE_POST_SEED_TRANSITION",
            diagnostic="Fixed-BASE epoch arrived after the common seed window was frozen; retained for audit only.",
        )
        return {
            "rovers": rovers,
            "route_host": route_host,
            "route_port": route_port,
            "configured_mountpoint": configured_mountpoint,
            "route_password": route_password,
            "uses_common_base": uses_common_base,
            "temporary_route_mountpoint": temporary_route_mountpoint,
            "configured_base_host": configured_base_host,
            "configured_base_serial": configured_base_serial,
            "configured_base_server_id": configured_base_server_id,
            "frozen_base_coordinates": frozen_base_coordinates,
        }

    @staticmethod
    def _extract_eligible_server_mountpoint(
        config: dict, server_id: int, normalized_route_host: str, fallback_host: str
    ) -> Optional[str]:
        if not config.get(f"server{server_id}_enabled", False):
            return None
        mountpoint = str(config.get(f"mountpoint{server_id}") or "").strip()
        if not mountpoint:
            return None
        candidate_host = str(config.get(f"serverhost{server_id}") or fallback_host or "").strip()
        if normalized_route_host and candidate_host.casefold() != normalized_route_host:
            return None
        return mountpoint

    def _resolve_temporary_route_mountpoint(
        self, cluster: dict, uses_common_base: bool, route_host: str, configured_mountpoint: Optional[str]
    ) -> Optional[str]:
        temporary_route_mountpoints: list[str] = []
        if configured_mountpoint:
            temporary_route_mountpoints.append(str(configured_mountpoint).strip())
        selected_service_config = cluster.get("base_service_config") or {}
        normalized_route_host = str(route_host or "").strip().casefold()
        for server_id in ((1, 2) if uses_common_base else ()):
            candidate_mountpoint = self._extract_eligible_server_mountpoint(
                selected_service_config, server_id, normalized_route_host, route_host
            )
            if candidate_mountpoint and not any(
                existing.casefold() == candidate_mountpoint.casefold()
                for existing in temporary_route_mountpoints
            ):
                temporary_route_mountpoints.append(candidate_mountpoint)
        return ",".join(temporary_route_mountpoints) if temporary_route_mountpoints else None

    @staticmethod
    def _compute_solver_eligible_cross_coverage(observations: list) -> tuple[set[tuple[str, str]], set[str]]:
        edges: set[tuple[str, str]] = set()
        participants: set[str] = set()
        for record in observations:
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
                or max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M
                or _vector_length(observation.baseline_neu) < 1.0
            ):
                continue
            edge = tuple(sorted((from_name, to_name), key=str.casefold))
            edges.add(edge)
            participants.update(edge)
        return edges, participants

    @staticmethod
    def _find_productive_temporary_bases(rovers: list, observations: list) -> list[str]:
        productive = []
        for candidate in rovers:
            cand_key = str(candidate).casefold()
            for record in observations:
                observation = getattr(record, "observation", None)
                if (
                    observation is None
                    or not getattr(record, "solver_eligible", True)
                    or str(getattr(record, "base_name", "") or "").casefold() != cand_key
                    or max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M
                    or _vector_length(observation.baseline_neu) < 1.0
                ):
                    continue
                productive.append(str(candidate))
                break
        return productive

    @staticmethod
    def _resolve_recovery_targets(rover_code: str, rovers: list, cross_edges: set) -> set[str]:
        components = _graph_components(rovers, cross_edges)
        rover_key = str(rover_code).casefold()
        current_comp = next((c for c in components if rover_key in {name.casefold() for name in c}), {str(rover_code)})
        current_keys = {name.casefold() for name in current_comp}
        return {str(candidate) for candidate in rovers if str(candidate).casefold() not in current_keys}

    def _filter_eligible_records_from(
        self, observations: list, start_index: int, current_rover: str, require_solver_eligible: bool
    ) -> list:
        eligible = []
        for record in observations[start_index:]:
            observation = getattr(record, "observation", None)
            if (
                getattr(record, "base_name", None) != current_rover
                or observation is None
                or (require_solver_eligible and not getattr(record, "solver_eligible", True))
                or (not require_solver_eligible and "EXCLUDE_UNCONFIRMED_SOURCE" in tuple(getattr(record, "quality_flags", ()) or ()))
                or max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M
                or _vector_length(observation.baseline_neu) < 1.0
            ):
                continue
            eligible.append(record)
        return eligible

    def _build_collection_status_dict(
        self, cluster_index: int, rover_code: str, session: dict,
        monitoring: list, solver_eligible: list
    ) -> dict:
        def epoch_map(records: list) -> Dict[str, set[int]]:
            result: Dict[str, set[int]] = {}
            for record in records:
                rover_name = str(record.observation.rover_name)
                result.setdefault(rover_name, set()).add(int(record.observation.epoch_ts))
            return result

        epochs_by_rover = epoch_map(monitoring)
        solver_epochs_by_rover = epoch_map(solver_eligible)
        samples_by_rover: Dict[str, list[tuple[int, tuple[float, float, float]]]] = {}
        for record in monitoring:
            rover_name = str(record.observation.rover_name)
            samples_by_rover.setdefault(rover_name, []).append((
                int(record.observation.epoch_ts), tuple(float(value) for value in record.observation.baseline_neu)
            ))
        online_states = session.setdefault("online_baseline_states", {})
        for rover_name in tuple(samples_by_rover):
            online_state = online_states.get(self._online_baseline_key(cluster_index, rover_code, rover_name))
            if online_state is not None:
                samples_by_rover[rover_name] = online_state.recent_samples()
        return {
            "sample_count": len(monitoring),
            "rover_names": set(epochs_by_rover),
            "sample_counts_by_rover": {rn: len(ep) for rn, ep in epochs_by_rover.items()},
            "solver_sample_counts_by_rover": {rn: len(ep) for rn, ep in solver_epochs_by_rover.items()},
            "solver_durations_by_rover_seconds": {rn: max(ep) - min(ep) for rn, ep in solver_epochs_by_rover.items() if ep},
            "rolling_stability_by_rover": {
                rn: _rolling_mean_stability(
                    samples, window_seconds=self.STABILITY_WINDOW_SECONDS,
                    min_samples_per_window=self.STABILITY_MIN_SAMPLES_PER_WINDOW,
                    max_sample_gap_seconds=self.STABILITY_MAX_SAMPLE_GAP_SECONDS,
                    horizontal_component_limit_m=self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M,
                    up_component_limit_m=self.STABILITY_UP_COMPONENT_LIMIT_M,
                    horizontal_std_limit_m=self.STABILITY_HORIZONTAL_STD_LIMIT_M,
                    up_std_limit_m=self.STABILITY_UP_STD_LIMIT_M,
                    horizontal_slope_limit_mps=self.STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS,
                    up_slope_limit_mps=self.STABILITY_UP_SLOPE_LIMIT_MPS,
                    ewma_fast_tau_seconds=self.STABILITY_EWMA_FAST_TAU_SECONDS,
                    ewma_slow_tau_seconds=self.STABILITY_EWMA_SLOW_TAU_SECONDS,
                    ewma_horizontal_limit_m=self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M,
                    ewma_up_limit_m=self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M,
                )
                for rn, samples in samples_by_rover.items()
            },
            "online_information_by_rover": {
                rn: online_states[self._online_baseline_key(cluster_index, rover_code, rn)].audit_snapshot()
                for rn in samples_by_rover if self._online_baseline_key(cluster_index, rover_code, rn) in online_states
            },
        }

    async def _execute_single_rotation_attempt(
        self, project_id: int, cluster_index: int, cluster: dict, rover_code: str,
        expected_cross_rovers: set[str], cluster_ctx: dict, session: dict
    ) -> bool:
        configured_mountpoint = cluster_ctx["configured_mountpoint"]
        configured_base_host = cluster_ctx["configured_base_host"]
        fixed_base_identity_kwargs = {
            "selected_serial": cluster_ctx["configured_base_serial"],
            "selected_server_id": (cluster_ctx["configured_base_server_id"] or None),
        }
        solver_start = [len(cluster["observations"])]
        stable_window_idx = [0]

        def on_coll_started():
            self._clear_cluster_fragment_buffers(project_id, cluster)
            self._reset_online_baseline_states(session, cluster_index, rover_code)
            session["active_bases"][cluster_index] = rover_code

        def on_coll_stopped():
            session["active_bases"].pop(cluster_index, None)
            self._clear_cluster_fragment_buffers(project_id, cluster)

        def on_stable_started():
            records = cluster["observations"]
            for record in records[solver_start[0]:]:
                if record.base_name == rover_code and record.solver_eligible:
                    record.solver_eligible = False
                    record.quality_flags = tuple(dict.fromkeys((*record.quality_flags, "EXCLUDE_PRE_STABLE_WINDOW")))
                    record.source_diagnostic = "Temporary-base source was verified, but this epoch belongs to handover window."
            solver_start[0] = len(records)
            cluster["current_stable_window_index"] = stable_window_idx[0]
            stable_window_idx[0] += 1
            self._clear_cluster_fragment_buffers(project_id, cluster)

        def on_stable_invalid(reason: str = "stability"):
            flag = {"drift": "EXCLUDE_STABILITY_LOST", "duration": "EXCLUDE_INSUFFICIENT_DURATION", "source": "EXCLUDE_SOURCE_NOT_CONFIRMED"}.get(reason.casefold(), "EXCLUDE_STABILITY_NOT_REACHED")
            records = cluster["observations"]
            for record in records[solver_start[0]:]:
                if record.base_name == rover_code and record.solver_eligible:
                    record.solver_eligible = False
                    record.quality_flags = tuple(dict.fromkeys((*record.quality_flags, flag)))
                    record.source_diagnostic = f"Solver window quarantined: {reason}"
            solver_start[0] = len(records)
            cluster["current_stable_window_index"] = None
            self._clear_cluster_fragment_buffers(project_id, cluster)

        def coll_status():
            mon = self._filter_eligible_records_from(cluster["observations"], 0, rover_code, False)
            sol = self._filter_eligible_records_from(cluster["observations"], solver_start[0], rover_code, True)
            return self._build_collection_status_dict(cluster_index, rover_code, session, mon, sol)

        async def wake_base():
            await self._set_cors_fixed_base_enabled(str(configured_mountpoint), enabled=True, selected_host=configured_base_host, **fixed_base_identity_kwargs)
            loop = asyncio.get_running_loop()
            dl = loop.time() + self.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS
            while loop.time() < dl:
                cli = await self._find_client_info(rover_code, project_id=project_id, log_missing=False)
                if cli: return cli
                await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)
            raise RuntimeError(f"{rover_code}: fixed BASE returned but client did not reconnect")

        async def sleep_base():
            await self._set_cors_fixed_base_enabled(str(configured_mountpoint), enabled=False, selected_host=configured_base_host, all_streams=cluster_ctx["uses_common_base"], **fixed_base_identity_kwargs)

        await self._set_rover_as_temporary_base(
            rover_code, project_id=project_id, route_host=cluster_ctx["route_host"], route_port=cluster_ctx["route_port"],
            route_mountpoint=(cluster_ctx["temporary_route_mountpoint"] or configured_mountpoint),
            route_password=str(cluster_ctx["route_password"]),
            on_collection_started=on_coll_started, on_stable_collection_started=on_stable_started,
            on_stable_collection_invalid=on_stable_invalid, on_collection_stopped=on_coll_stopped,
            collection_status_callback=coll_status, expected_cross_rovers=expected_cross_rovers,
            base_llh_override=cluster_ctx["frozen_base_coordinates"].get(str(rover_code)),
            before_rover_restore=wake_base if configured_mountpoint else None,
            before_route_start=sleep_base if configured_mountpoint else None,
        )
        eligible = self._filter_eligible_records_from(cluster["observations"], solver_start[0], rover_code, True)
        return len(eligible) > 0

    async def _handle_rotation_skip(
        self, exc: _SafeRoverRotationSkip, project_id: int, cluster_index: int,
        rover_code: str, collection_attempt: int, session: dict
    ) -> bool:
        warning = str(exc) or f"{rover_code}: temporary-base rotation skipped"
        if collection_attempt < self.CROSS_BASE_COLLECTION_ATTEMPTS:
            await self._emit_progress(project_id, f"{rover_code}: retrying temporary-BASE rotation after skip.")
            return True
        session.setdefault("rotation_warnings", []).append({"cluster_index": cluster_index, "rover": rover_code, "message": warning})
        await self._emit_progress(project_id, f"{rover_code}: rotation skipped after safe ROVER recovery. {warning}")
        return False

    async def _execute_rover_rotation_loop(
        self, project_id: int, cluster_index: int, cluster: dict, rover_code: str,
        expected_cross_rovers: set[str], cluster_ctx: dict, session: dict,
        is_graph_recovery: bool, completed_mandatory_rotations: set[str]
    ) -> bool:
        for collection_attempt in range(1, self.CROSS_BASE_COLLECTION_ATTEMPTS + 1):
            try:
                ok = await self._execute_single_rotation_attempt(
                    project_id, cluster_index, cluster, rover_code, expected_cross_rovers, cluster_ctx, session
                )
                if ok:
                    if not is_graph_recovery:
                        completed_mandatory_rotations.add(str(rover_code).casefold())
                    await self._emit_progress(project_id, f"{rover_code}: mandatory temporary-BASE rotation complete.")
                    return True
                if collection_attempt < self.CROSS_BASE_COLLECTION_ATTEMPTS:
                    await self._emit_progress(project_id, f"{rover_code}: temporary-base coverage incomplete; retrying.")
                    continue
            except _SafeRoverRotationSkip as exc:
                should_continue = await self._handle_rotation_skip(
                    exc, project_id, cluster_index, rover_code, collection_attempt, session
                )
                if should_continue:
                    continue
                return False
            except Exception:
                session["active_bases"].pop(cluster_index, None)
                raise
        return False

    async def _reacquire_next_rover_if_needed(
        self, project_id: int, cluster: dict, rotation_index: int, initial_rotation_count: int,
        rotation_queue: list, skipped_offline: set[str], waived_uncontrolled: set[str],
        cluster_ctx: dict
    ) -> None:
        configured_mountpoint = cluster_ctx["configured_mountpoint"]
        if not configured_mountpoint or rotation_index + 1 >= initial_rotation_count:
            return
        fixed_base_identity_kwargs = {
            "selected_serial": cluster_ctx["configured_base_serial"],
            "selected_server_id": (cluster_ctx["configured_base_server_id"] or None),
        }
        for next_index in range(rotation_index + 1, initial_rotation_count):
            next_candidate = str(rotation_queue[next_index])
            if next_candidate.casefold() in (skipped_offline | waived_uncontrolled):
                continue
            reacquired = await self._reacquire_fixed_base_between_rotations(
                project_id, cluster, next_rover=next_candidate, mountpoint=str(configured_mountpoint),
                selected_host=cluster_ctx["configured_base_host"], **fixed_base_identity_kwargs,
            )
            if reacquired:
                break
            skip_mode = cluster.pop("_last_reacquire_skip_mode", "offline")
            if skip_mode == "uncontrolled":
                waived_uncontrolled.add(next_candidate.casefold())
            else:
                skipped_offline.add(next_candidate.casefold())

    async def _resolve_cluster_rotation_targets(
        self, project_id: int, rover_code: str, rovers: list, is_graph_recovery: bool,
        observations: list, skipped_offline: set[str]
    ) -> Optional[set[str]]:
        if is_graph_recovery:
            existing_edges, _ = self._compute_solver_eligible_cross_coverage(observations)
            expected_cross_rovers = self._resolve_recovery_targets(rover_code, rovers, existing_edges)
            if not expected_cross_rovers:
                return None
            await self._emit_progress(project_id, f"{rover_code}: targeted graph recovery.")
            return expected_cross_rovers
        return {
            str(cand) for cand in rovers
            if str(cand).casefold() != str(rover_code).casefold() and str(cand).casefold() not in skipped_offline
        }

    def _maybe_schedule_graph_recovery(
        self, rovers: list, observations: list, rotation_queue: list
    ) -> bool:
        existing_edges, _ = self._compute_solver_eligible_cross_coverage(observations)
        productive_bases = self._find_productive_temporary_bases(rovers, observations)
        if productive_bases and len(_graph_components(rovers, existing_edges)) > 1:
            rotation_queue.extend(productive_bases)
            return True
        return False

    async def _execute_cluster_rotations(
        self, project_id: int, session: dict, cluster: dict, cluster_index: int, cluster_ctx: dict
    ) -> tuple[set[str], set[str], set[str], int]:
        rovers = cluster_ctx["rovers"]
        rotation_queue = list(rovers)
        initial_rotation_count = len(rotation_queue)
        completed_mandatory: set[str] = set()
        skipped_offline: set[str] = set()
        waived_uncontrolled: set[str] = set()
        graph_recovery_scheduled = False

        for rotation_index, rover_code in enumerate(rotation_queue):
            if str(rover_code).casefold() in (skipped_offline | waived_uncontrolled):
                continue
            cluster["current_rotation_index"] = rotation_index + 1
            is_graph_recovery = rotation_index >= initial_rotation_count
            expected_cross_rovers = await self._resolve_cluster_rotation_targets(
                project_id, rover_code, rovers, is_graph_recovery, cluster["observations"], skipped_offline
            )
            if expected_cross_rovers is None:
                continue

            await self._execute_rover_rotation_loop(
                project_id, cluster_index, cluster, rover_code, expected_cross_rovers, cluster_ctx, session,
                is_graph_recovery, completed_mandatory
            )
            session["active_bases"].pop(cluster_index, None)
            if not is_graph_recovery:
                await self._reacquire_next_rover_if_needed(
                    project_id, cluster, rotation_index, initial_rotation_count, rotation_queue,
                    skipped_offline, waived_uncontrolled, cluster_ctx
                )
            if not graph_recovery_scheduled and rotation_index + 1 == initial_rotation_count:
                graph_recovery_scheduled = self._maybe_schedule_graph_recovery(
                    rovers, cluster["observations"], rotation_queue
                )

        return completed_mandatory, skipped_offline, waived_uncontrolled, initial_rotation_count

    async def _verify_final_cluster_coverage(
        self, project_id: int, cluster: dict, cluster_index: int, rovers: list,
        completed_rotations: set[str], skipped_offline: set[str], waived_uncontrolled: set[str],
        initial_rotation_count: int
    ) -> None:
        required_keys = {str(c).casefold() for c in rovers}
        missing_keys = required_keys - completed_rotations - skipped_offline - waived_uncontrolled
        final_cross_edges, _ = self._compute_solver_eligible_cross_coverage(cluster["observations"])
        if missing_keys:
            cross_graph_connected = (
                len(final_cross_edges) >= max(len(rovers) - 1, 1)
                and len(_graph_components(rovers, final_cross_edges)) == 1
            )
            if not cross_graph_connected:
                components = _graph_components(rovers, final_cross_edges)
                raise RuntimeError(
                    "Temporary-BASE coverage is insufficient: missing productive base rotation(s) "
                    + ", ".join(sorted(missing_keys)) + "; cross-baseline graph remains disconnected (components: "
                    + " | ".join(", ".join(sorted(c)) for c in components) + ")"
                )
            warning = f"Proceeding with connected partial rotation coverage; skipped base rotation(s): {', '.join(sorted(missing_keys))}."
            session = self._sessions.get(project_id) or {}
            session.setdefault("rotation_warnings", []).append({
                "cluster_index": cluster_index, "rover": ",".join(sorted(missing_keys)), "message": warning,
            })
            await self._emit_progress(project_id, warning)

        await self._emit_progress(
            project_id,
            f"{cluster.get('name', cluster_index + 1)}: {len(completed_rotations)}/{initial_rotation_count} temporary-BASE rotations completed.",
        )

    async def _restore_cycle_bases(
        self, project_id: int, suspended_bases: set, disabled_conflict_bases: dict, cycle_error: Optional[Exception]
    ) -> Optional[Exception]:
        restore_errors: List[str] = []
        for selected_host, mp, selected_serial, selected_server_id in suspended_bases:
            try:
                await self._emit_progress(project_id, f"Khôi phục stream Base cố định {mp}.")
                restore_identity = {}
                if selected_serial: restore_identity["selected_serial"] = selected_serial
                if selected_server_id: restore_identity["selected_server_id"] = selected_server_id
                await self._set_cors_fixed_base_enabled(mp, enabled=True, selected_host=selected_host, **restore_identity)
            except Exception as e:
                restore_errors.append(f"{mp}: {e}")
        for snapshot in reversed(list(disabled_conflict_bases.values())):
            try:
                await asyncio.to_thread(self._cors_configure_service_sync, snapshot["serial"], copy.deepcopy(snapshot["service_config"]))
            except Exception as e:
                restore_errors.append(f"{snapshot['serial']}: {e}")
        try:
            await self.restore_common_fixed_base_topology(project_id)
        except Exception as e:
            restore_errors.append(str(e))
        self.running_tasks.pop(project_id, None)
        if restore_errors and cycle_error is None:
            return RuntimeError("could not restore fixed-base stream mode: " + "; ".join(restore_errors))
        return cycle_error

    async def _complete_cycle_results(self, project_id: int, session: dict) -> None:
        completed_results: List[dict] = []
        for cluster_index, cluster in enumerate(session["clusters"]):
            self._exclude_fixed_base_records(
                cluster, int(cluster.get("fixed_base_seed_cutoff_index", len(cluster["observations"]))),
                flag="EXCLUDE_POST_SEED_TRANSITION",
                diagnostic="Fixed-BASE epoch arrived after common seed window; retained for audit only.",
            )
            await self._emit_progress(
                project_id,
                (
                    f"{cluster.get('name', cluster_index + 1)}: aggregating repeated baselines "
                    "to one covariance-weighted value per geometric edge and solving the network."
                ),
            )
            result = self._build_cluster_result(project_id, cluster_index, cluster)
            rotation_warnings = [item for item in session.get("rotation_warnings", []) if item.get("cluster_index") == cluster_index]
            if rotation_warnings:
                result["rotation_warnings"] = rotation_warnings
                result.setdefault("quality", {})["rotation_warning_count"] = len(rotation_warnings)
            completed_results.append(result)

        for result in completed_results:
            if self.result_callback:
                res = self.result_callback(project_id, result)
                if inspect.isawaitable(res):
                    await res

    async def _handle_cycle_error(self, project_id: int, cycle_error: Exception) -> None:
        logger.error("RoundRobin cycle failed for project %s: %s", project_id, cycle_error)
        if self.error_callback:
            callback_result = self.error_callback(project_id, str(cycle_error))
            if inspect.isawaitable(callback_result):
                await callback_result

    async def _run_cycle(self, project_id: int) -> None:
        suspended_bases: set[tuple[str, str, str, int]] = set()
        disabled_conflict_bases: dict[str, dict] = {}
        cycle_error: Optional[Exception] = None
        try:
            session = self._sessions[project_id]
            for cluster_index, cluster in enumerate(session["clusters"]):
                cluster_ctx = await self._init_cycle_cluster(
                    project_id, cluster_index, cluster, session, suspended_bases, disabled_conflict_bases
                )
                completed_mandatory, skipped_offline, waived_uncontrolled, initial_count = (
                    await self._execute_cluster_rotations(project_id, session, cluster, cluster_index, cluster_ctx)
                )
                await self._verify_final_cluster_coverage(
                    project_id, cluster, cluster_index, cluster_ctx["rovers"],
                    completed_mandatory, skipped_offline, waived_uncontrolled, initial_count
                )
        except asyncio.CancelledError:
            logger.info("RoundRobin cycle cancelled for project %s", project_id)
            raise
        except Exception as exc:
            cycle_error = exc
        finally:
            cycle_error = await self._restore_cycle_bases(project_id, suspended_bases, disabled_conflict_bases, cycle_error)

        if cycle_error is not None:
            await self._handle_cycle_error(project_id, cycle_error)
            return

        try:
            await self._complete_cycle_results(project_id, session)
        except Exception as exc:
            await self._handle_cycle_error(project_id, exc)


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
