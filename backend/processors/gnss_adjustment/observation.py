"""Round-Robin observation responsibilities."""

from __future__ import annotations

import asyncio
import logging
import math
import re
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

AGRICA_HEADER = "#AGRICA"

class RoundRobinObservationMixin:
    @staticmethod
    def _command_station_key(station_code: Any) -> str:
        return str(station_code or "").strip().casefold()


    def _register_command_ack_waiter(
        self,
        station_code: str,
        command: str,
    ) -> _CommandAckWaiter:
        key = self._command_station_key(station_code)
        if not key:
            raise ValueError("station_code is required for MQTT command acknowledgement")
        waiter = _CommandAckWaiter(
            station_code=str(station_code).strip(),
            command=str(command).strip(),
            future=asyncio.get_running_loop().create_future(),
        )
        with self._command_ack_lock:
            previous = self._command_ack_waiters.get(key)
            if previous and not previous.future.done():
                raise RuntimeError(f"another receiver command is already pending for {station_code}")
            self._command_ack_waiters[key] = waiter
        return waiter


    def _remove_command_ack_waiter(self, waiter: _CommandAckWaiter) -> None:
        key = self._command_station_key(waiter.station_code)
        with self._command_ack_lock:
            if self._command_ack_waiters.get(key) is waiter:
                self._command_ack_waiters.pop(key, None)


    @staticmethod
    def _process_framed_command_line(waiter: _CommandAckWaiter, line: str, incoming_topic: str) -> Optional[dict]:
        framed = _COMMAND_RESPONSE_RE.search(line)
        if not framed:
            return None
        framed_command = framed.group("command").strip()
        framed_response = framed.group("response").strip()
        expected_command = _normalized_receiver_command(waiter.command)
        actual_command = _normalized_receiver_command(framed_command)
        expected_key = expected_command.split(" ", 1)[0]
        actual_key = actual_command.split(" ", 1)[0]

        if actual_command == expected_command:
            waiter.echo_seen = True
            waiter.topic = incoming_topic
        elif not (waiter.echo_seen and waiter.topic == incoming_topic and actual_key == expected_key):
            return None

        accepted = _receiver_response_result(framed_response)
        if accepted is not None:
            return {
                "accepted": accepted,
                "response": framed_response,
                "raw_response": line[framed.start():].strip(),
                "topic": incoming_topic,
                "command": waiter.command,
            }
        return None

    @staticmethod
    def _process_unframed_command_line(waiter: _CommandAckWaiter, line: str, incoming_topic: str) -> Optional[dict]:
        if not waiter.echo_seen:
            if _normalized_receiver_command(line) == _normalized_receiver_command(waiter.command):
                waiter.echo_seen = True
                waiter.topic = incoming_topic
                logger.info(
                    "MQTT receiver command echo station=%s topic=%s command=%s",
                    waiter.station_code,
                    waiter.topic,
                    waiter.command,
                )
            return None
        if waiter.topic != incoming_topic:
            return None
        accepted = _receiver_response_result(line)
        if accepted is not None:
            return {
                "accepted": accepted,
                "response": line,
                "raw_response": line,
                "topic": incoming_topic,
                "command": waiter.command,
            }
        return None

    def _scan_command_lines(
        self, waiter: Any, lines: list[str], incoming_topic: str
    ) -> Any:
        for line in lines:
            framed_res = self._process_framed_command_line(waiter, line, incoming_topic)
            if framed_res is not None:
                return framed_res
            unframed_res = self._process_unframed_command_line(waiter, line, incoming_topic)
            if unframed_res is not None:
                return unframed_res
        return None

    @staticmethod
    def _deliver_command_result(waiter: Any, result: Any) -> None:
        loop = waiter.future.get_loop()

        def deliver() -> None:
            if not waiter.future.done():
                waiter.future.set_result(result)

        loop.call_soon_threadsafe(deliver)

    def add_receiver_command_payload(
        self,
        raw_payload: str,
        info: Dict[str, Any],
        topic: str,
    ) -> bool:
        """Feed receiver echo/response text from the rover's subscribed MQTT topic."""
        station_code = str((info or {}).get("station_code") or "").strip()
        key = self._command_station_key(station_code)
        if not key or not raw_payload:
            return False

        result = None
        waiter = None
        with self._command_ack_lock:
            waiter = self._command_ack_waiters.get(key)
            if waiter is None or waiter.future.done():
                return False

            incoming_topic = str(topic or "")
            if waiter.echo_seen and waiter.topic != incoming_topic:
                return False

            payload_text = str(raw_payload).replace("\x00", "")
            lines = [
                line.strip()
                for line in re.split(r"[\r\n]+", payload_text)
                if line.strip()
            ]
            result = self._scan_command_lines(waiter, lines, incoming_topic)
            if result is not None:
                self._command_ack_waiters.pop(key, None)

        if result is not None and waiter is not None:
            self._deliver_command_result(waiter, result)
            return True
        return bool(waiter and waiter.echo_seen)


    @staticmethod
    def _detect_rtcm_preamble(raw: bytes) -> bool:
        if b"\xd3" not in raw:
            return False
        for index, value in enumerate(raw):
            if value != 0xD3 or index + 2 >= len(raw):
                continue
            frame_length = ((raw[index + 1] & 0x03) << 8) | raw[index + 2]
            if 0 < frame_length <= 1023:
                return True
        return False

    def observe_gnss_payload(self, info: Dict[str, Any], payload: bytes) -> None:
        """Remember what each receiver is actually publishing on its GNSS topic.

        This is deliberately fed before UTF-8 decoding because RTCM is binary and
        would otherwise disappear from the normal sensor pipeline.  The tracker is
        passive; adjustment preflight and the session-aware idle watchdog own
        any state-changing recovery, outside this MQTT callback.
        """

        station_code = str((info or {}).get("station_code") or "").strip()
        key = self._command_station_key(station_code)
        if not key or not payload:
            return

        raw = bytes(payload)
        upper = raw.upper()
        now = time.monotonic()
        has_agrica = b"#AGRICA" in upper
        has_gga = bool(re.search(rb"\$G[NP]GGA,", upper))
        has_rtcm = self._detect_rtcm_preamble(raw)

        with self._gnss_stream_health_lock:
            from app.mqtt.ntrip_pusher import Rtcm3FrameFilter

            frame_filter = self._gnss_rtcm_filters.get(key)
            if frame_filter is None:
                frame_filter = self._gnss_rtcm_filters[key] = Rtcm3FrameFilter()
            verified_rtcm = frame_filter.feed(raw)
            state = dict(self._gnss_stream_health.get(key) or {})
            state.update({
                "station_code": station_code,
                "station_id": (info or {}).get("station_id"),
                "last_payload_monotonic": now,
            })
            if has_agrica:
                state["last_agrica_monotonic"] = now
            if has_gga:
                state["last_gga_monotonic"] = now
            if has_rtcm:
                state["last_rtcm_monotonic"] = now
            if verified_rtcm:
                state["last_valid_rtcm_monotonic"] = now
                state["valid_rtcm_frames"] = frame_filter.valid_frame_count
            self._gnss_stream_health[key] = state


    def get_gnss_stream_health(
        self,
        station_code: str,
        *,
        freshness_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Return a stable snapshot of the receiver's recent output profile."""

        key = self._command_station_key(station_code)
        with self._gnss_stream_health_lock:
            state = dict(self._gnss_stream_health.get(key) or {})
        now = time.monotonic()

        def recent(field: str) -> bool:
            value = state.get(field)
            return value is not None and now - float(value) <= freshness_seconds

        state.update({
            "station_code": state.get("station_code") or str(station_code),
            "payload_recent": recent("last_payload_monotonic"),
            "agrica_recent": recent("last_agrica_monotonic"),
            "gga_recent": recent("last_gga_monotonic"),
            "rtcm_recent": recent("last_rtcm_monotonic"),
            "valid_rtcm_recent": recent("last_valid_rtcm_monotonic"),
        })
        state["ready_as_rover"] = bool(
            state["agrica_recent"]
            and state["gga_recent"]
            and not state["rtcm_recent"]
        )
        return state

    @staticmethod
    def _collect_diagnostics_raw_gnss(session: dict) -> list[dict]:
        raw_gnss = []
        seen_raw = set()
        for cluster in session.get("clusters", []):
            for record in cluster.get("observations", []):
                observation = record.observation
                raw_payload = str(observation.raw or "")
                seen_raw.add(raw_payload)
                raw_gnss.append({
                    "epoch_ts": int(observation.epoch_ts or 0),
                    "station_id": int(observation.station_id),
                    "rover": str(observation.rover_name),
                    "position_type": observation.position_type,
                    "base": str(record.base_name),
                    "solver_eligible": bool(record.solver_eligible),
                    "reason": "; ".join(record.quality_flags or ()),
                    "raw_payload": raw_payload,
                })
        for report in (session.get("seed_station_reports") or {}).values():
            raw_payload = str(report.get("raw_payload") or "")
            if raw_payload and raw_payload not in seen_raw:
                raw_gnss.append({
                    "epoch_ts": report.get("epoch_ts"),
                    "station_id": report.get("station_id"),
                    "rover": report.get("rover"),
                    "position_type": report.get("position_type"),
                    "base": None,
                    "solver_eligible": bool(report.get("solver_eligible")),
                    "reason": report.get("reason"),
                    "raw_payload": raw_payload,
                })
        return raw_gnss

    def get_adjustment_diagnostics(self, project_id: int) -> Dict[str, Any]:
        """Return JSON-safe runtime evidence for a failed adjustment run."""
        session = self._sessions.get(int(project_id)) or {}
        rover_codes = list(dict.fromkeys(
            str(rover).strip()
            for cluster in session.get("clusters", [])
            for rover in cluster.get("rovers", [])
            if str(rover).strip()
        ))
        raw_gnss = self._collect_diagnostics_raw_gnss(session)
        return {
            "run_id": int(project_id),
            "captured_at": int(time.time()),
            "clusters": [
                {
                    "name": str(cluster.get("name") or "Cụm"),
                    "rovers": list(cluster.get("rovers") or []),
                    "active_base": (session.get("active_bases") or {}).get(index),
                }
                for index, cluster in enumerate(session.get("clusters", []))
            ],
            "stream_health": {
                rover: self.get_gnss_stream_health(rover)
                for rover in rover_codes
            },
            "seed_status": self.get_seed_collection_status(int(project_id)),
            "last_ingest_diagnostic": self.get_last_ingest_diagnostic(int(project_id)),
            "raw_gnss": raw_gnss,
        }


    async def _heal_unready_rover(
        self,
        project_id: int,
        rover_code: str,
        before: dict,
        verify_seconds: float,
        allow_unavailable: bool,
    ) -> dict:
        reasons = []
        if not before["payload_recent"]:
            reasons.append("no recent GNSS payload")
        if not before["agrica_recent"]:
            reasons.append("AGRICA missing")
        if not before["gga_recent"]:
            reasons.append("GGA missing")
        if before["rtcm_recent"]:
            reasons.append("RTCM detected (receiver is in/still logging BASE output)")
        await self._emit_progress(
            project_id,
            f"{rover_code}: preflight found {', '.join(reasons)}; restoring the verified ROVER output profile.",
        )

        client_info = await self._find_client_info(
            rover_code,
            project_id=project_id,
            log_missing=not allow_unavailable,
        )
        if not client_info or not str(client_info.get("Mountpoint") or "").strip():
            if allow_unavailable:
                reason = (
                    f"{rover_code}: no active AICaster control session/mountpoint; "
                    "station is excluded from this run without changing the receiver"
                )
                await self._emit_progress(project_id, reason)
                return {
                    "station_code": rover_code,
                    "status": "excluded_no_control_session",
                    "reconfigured": False,
                    "reason": reason,
                    "observed": {
                        "agrica": bool(before["agrica_recent"]),
                        "gga": bool(before["gga_recent"]),
                        "rtcm": bool(before["rtcm_recent"]),
                    },
                }
            raise RuntimeError(
                f"{rover_code}: cannot self-heal receiver because no active "
                "AICaster control session/mountpoint was found"
            )
        await self.restore_rover_stream(
            rover_code, client_info=client_info,
            project_id=project_id, verify_seconds=verify_seconds,
        )
        await self._emit_progress(
            project_id,
            f"{rover_code}: live stream verified as ROVER (fresh GGA + AGRICA, RTCM stopped).",
        )
        return {
            "station_code": rover_code,
            "status": "recovered",
            "reconfigured": True,
            "reason": reasons,
            "observed": {"agrica": True, "gga": True, "rtcm": False},
        }

    async def ensure_rover_streams_ready(
        self,
        project_id: int,
        *,
        discovery_seconds: float = 5.0,
        verify_seconds: float = 30.0,
        allow_unavailable: bool = False,
    ) -> List[Dict[str, Any]]:
        """Inspect and self-heal every selected rover before seed collection.

        Healthy receivers are left untouched. A silent/misconfigured receiver is
        restored with the same ACK-verified ROVER profile used after a temporary
        BASE rotation, then must prove fresh GGA + AGRICA output and RTCM silence.
        """

        session = self._sessions.get(int(project_id))
        if session is None:
            raise KeyError(f"no active adjustment session for project {project_id}")
        rover_codes = list(dict.fromkeys(
            str(code).strip()
            for cluster in session.get("clusters", [])
            for code in cluster.get("rovers", [])
            if str(code).strip()
        ))
        if not rover_codes:
            raise RuntimeError("adjustment preflight has no selected rover")

        discovery_deadline = asyncio.get_running_loop().time() + max(0.0, discovery_seconds)
        while asyncio.get_running_loop().time() < discovery_deadline:
            if all(self.get_gnss_stream_health(code)["payload_recent"] for code in rover_codes):
                break
            await asyncio.sleep(0.25)

        outcomes: List[Dict[str, Any]] = []
        for rover_code in rover_codes:
            before = self.get_gnss_stream_health(rover_code)
            if before["ready_as_rover"]:
                outcomes.append({
                    "station_code": rover_code,
                    "status": "ready",
                    "reconfigured": False,
                    "observed": {"agrica": True, "gga": True, "rtcm": False},
                })
                continue

            outcome = await self._heal_unready_rover(
                project_id, rover_code, before, verify_seconds, allow_unavailable
            )
            outcomes.append(outcome)
        return outcomes

    async def restore_rover_stream(
        self, rover_code: str, *, client_info: dict,
        project_id: Optional[int] = None, verify_seconds: float = 30.0,
    ) -> None:
        """Restore the ACK-verified profile and prove fresh live ROVER output."""
        repair_started = time.monotonic()
        await self._restore_rover_output_sequence(
            rover_code=rover_code,
            mountpoint=str(client_info["Mountpoint"]).strip(),
            client_info=client_info,
            commands=self._build_unicore_rover_config(
                restore_undulation=(self.rover_llh_cache.get(rover_code) or {}).get("undulation")
            ),
            project_id=project_id,
        )
        verify_deadline = asyncio.get_running_loop().time() + max(1.0, verify_seconds)
        while asyncio.get_running_loop().time() < verify_deadline:
            candidate = self.get_gnss_stream_health(rover_code, freshness_seconds=5.0)
            agrica_fresh = bool(candidate["agrica_recent"]) and float(candidate.get("last_agrica_monotonic") or 0) > repair_started
            gga_fresh = bool(candidate["gga_recent"]) and float(candidate.get("last_gga_monotonic") or 0) > repair_started
            last_rtcm = float(candidate.get("last_rtcm_monotonic") or 0)
            rtcm_quiet = last_rtcm <= repair_started or time.monotonic() - last_rtcm >= 3.0
            if agrica_fresh and gga_fresh and rtcm_quiet:
                return
            await asyncio.sleep(0.25)
        raise RuntimeError(
            f"{rover_code}: ROVER commands were acknowledged but live output did "
            f"not prove fresh GGA + AGRICA with RTCM stopped within {verify_seconds:g}s"
        )


    def update_rover_llh(self, station_code: str, lat: float, lon: float, alt: float) -> None:
        if station_code:
            self.rover_llh_cache[station_code] = {"lat": lat, "lon": lon, "alt": alt}


    @staticmethod
    def _online_baseline_key(
        cluster_index: int,
        base_name: str,
        rover_name: str,
    ) -> tuple[int, str, str]:
        return (
            int(cluster_index),
            str(base_name).casefold(),
            str(rover_name).casefold(),
        )


    def _reset_online_baseline_states(
        self,
        session: dict,
        cluster_index: int,
        base_name: str,
    ) -> None:
        prefix = (int(cluster_index), str(base_name).casefold())
        states = session.setdefault("online_baseline_states", {})
        for key in [key for key in states if key[:2] == prefix]:
            states.pop(key, None)


    def _update_online_baseline_state(
        self,
        session: dict,
        cluster_index: int,
        base_name: str,
        observation: Any,
    ) -> None:
        key = self._online_baseline_key(
            cluster_index,
            base_name,
            observation.rover_name,
        )
        state = session.setdefault("online_baseline_states", {}).setdefault(
            key,
            _InformationAccumulator(),
        )
        standard_deviation = np.asarray(observation.std_neu, dtype=float)
        covariance = np.diag(np.maximum(
            standard_deviation * standard_deviation,
            np.finfo(float).eps,
        ))
        state.add(
            int(observation.epoch_ts),
            observation.baseline_neu,
            covariance,
            fast_tau_seconds=self.STABILITY_EWMA_FAST_TAU_SECONDS,
            slow_tau_seconds=self.STABILITY_EWMA_SLOW_TAU_SECONDS,
            retention_seconds=(
                2 * self.STABILITY_WINDOW_SECONDS
                + self.STABILITY_HOLD_SECONDS
                + self.STABILITY_MAX_SAMPLE_GAP_SECONDS
            ),
        )


    @staticmethod
    def _resolve_observation_best_llh(rover_llh: Any, rover_ecef: Any) -> Optional[tuple]:
        selected = rover_llh
        if rover_ecef and len(rover_ecef) == 3:
            try:
                ecef_values = tuple(float(value) for value in rover_ecef)
                if (
                    all(math.isfinite(value) for value in ecef_values)
                    and _vector_length(ecef_values) > 1_000_000.0
                ):
                    ecef_llh = _ecef_to_llh(*ecef_values)
                    if not rover_llh or _llh_horizontal_distance_m(ecef_llh, rover_llh) <= 5.0:
                        selected = ecef_llh
            except (TypeError, ValueError, OverflowError):
                pass
        return selected

    @staticmethod
    def _populate_rover_llh_cache_metadata(cache: dict, observation: Any, rover_llh: Any, selected: tuple) -> None:
        full_data = getattr(observation, "full_data", None) or {}
        undulation = full_data.get("undulation")
        try:
            undulation_value = float(undulation)
        except (TypeError, ValueError):
            undulation_value = None
        if undulation_value is not None and math.isfinite(undulation_value):
            cache["undulation"] = undulation_value
        if rover_llh and len(rover_llh) == 3:
            try:
                orthometric_height = float(rover_llh[2])
            except (TypeError, ValueError):
                orthometric_height = None
            if orthometric_height is not None and math.isfinite(orthometric_height):
                cache["orthometric_alt"] = orthometric_height
        cache["ellipsoid_alt"] = float(selected[2])

    def _update_rover_llh_from_observation(self, observation: Any) -> None:
        """Cache an ellipsoidal temporary-base coordinate from AGRICA."""
        rover_llh = getattr(observation, "rover_llh", None)
        rover_ecef = getattr(observation, "rover_ecef", None)
        selected = self._resolve_observation_best_llh(rover_llh, rover_ecef)
        if selected:
            self.update_rover_llh(
                observation.rover_name,
                float(selected[0]),
                float(selected[1]),
                float(selected[2]),
            )
            cache = self.rover_llh_cache.get(observation.rover_name) or {}
            self._populate_rover_llh_cache_metadata(cache, observation, rover_llh, selected)
            self.rover_llh_cache[observation.rover_name] = cache


    def has_pending_agrica_fragment(self, project_id: int, station_id: int) -> bool:
        return (int(project_id), int(station_id)) in self._agrica_fragment_buffers


    @staticmethod
    def _extract_agrica_complete_and_tail(pending: str) -> tuple[list[str], str]:
        complete_matches = list(re.finditer(r"#AGRICA[^*]*\*[0-9A-Fa-f]*", pending, re.DOTALL))
        if not complete_matches:
            return [], pending
        completed = [match.group(0) for match in complete_matches]
        tail = pending[complete_matches[-1].end():]
        tail_marker = tail.find(AGRICA_HEADER)
        tail = tail[tail_marker:] if tail_marker >= 0 else ""
        return completed, tail

    def _consume_agrica_fragments(
        self,
        project_id: int,
        station_id: int,
        raw_payload: str,
    ) -> tuple[list[str], int]:
        """Return complete AGRICA sentences and retain an unfinished tail."""
        key = (int(project_id), int(station_id))
        payload = str(raw_payload or "").replace("\x00", "")
        pending = self._agrica_fragment_buffers.get(key, "")
        marker_index = payload.find(AGRICA_HEADER)
        if marker_index >= 0:
            pending = payload[marker_index:]
        elif pending:
            pending += payload
        else:
            return [], 0

        completed, tail = self._extract_agrica_complete_and_tail(pending)
        if completed:
            if tail:
                self._agrica_fragment_buffers[key] = tail
            else:
                self._agrica_fragment_buffers.pop(key, None)
            return completed, len(tail)

        if len(pending) > 8192:
            newest_marker = pending.rfind(AGRICA_HEADER)
            pending = pending[newest_marker:] if newest_marker >= 0 else ""
        if pending:
            self._agrica_fragment_buffers[key] = pending
        else:
            self._agrica_fragment_buffers.pop(key, None)
        return [], len(pending)


    def _record_unconfirmed_base_observation(
        self, session: dict, cluster_index: int, active_base: str,
        observation: Any, base_diagnostic: str, project_id: int, station_id: int
    ) -> None:
        cluster = session["clusters"][cluster_index]
        cluster["observations"].append(
            _CollectedObservation(
                active_base,
                observation,
                solver_eligible=False,
                quality_flags=("EXCLUDE_UNCONFIRMED_SOURCE",),
                source_diagnostic=base_diagnostic,
                rotation_index=cluster.get("current_rotation_index", 0),
                stable_window_index=None,
            )
        )
        session["seed_station_reports"][int(observation.station_id)]["reason"] = base_diagnostic
        warning_key = (int(project_id), int(cluster_index), int(station_id))
        now_monotonic = time.monotonic()
        last_logged = self._ingest_warning_last_logged.get(warning_key, 0.0)
        if (now_monotonic - last_logged) >= 30.0:
            self._ingest_warning_last_logged[warning_key] = now_monotonic
            logger.warning(
                "Round-Robin project=%s cluster=%s station=%s: %s",
                project_id, cluster_index, station_id, base_diagnostic,
            )

    def _admit_agrica_observation(
        self,
        session: dict,
        observation: Any,
        project_id: int,
        station_id: int,
        cluster_index: Optional[int],
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Return (is_valid, accepted_diagnostic, ignored_reason)."""
        if observation.position_type not in (4, 7):
            reason = f"position_type={observation.position_type}; requires RTK Fixed (4) or Input Fixed (7)"
            if cluster_index is not None:
                session["seed_station_reports"][int(observation.station_id)]["reason"] = reason
            return False, None, reason

        if cluster_index is None:
            return False, None, "station is not included in the active GNSS cluster"

        active_base = session["active_bases"].get(cluster_index, "BASE")
        if active_base == observation.rover_name:
            return False, None, "ignored self-observation while this rover is the temporary base"

        cluster = session["clusters"][cluster_index]
        base_matches, base_diagnostic = self._observation_matches_active_base(
            cluster, active_base, observation
        )
        if not base_matches:
            self._record_unconfirmed_base_observation(
                session, cluster_index, active_base, observation, base_diagnostic, project_id, station_id
            )
            return False, None, base_diagnostic

        session["seed_station_reports"][int(observation.station_id)].update({
            "base_identity_verified": True,
            "base_identity_diagnostic": base_diagnostic,
        })
        session["clusters"][cluster_index]["observations"].append(
            _CollectedObservation(
                active_base,
                observation,
                rotation_index=cluster.get("current_rotation_index", 0),
                stable_window_index=cluster.get("current_stable_window_index", 0),
            )
        )
        if max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M:
            reason = "baseline STD exceeds 0.1 m; stored for RAW_AUDIT but excluded from solver"
            session["seed_station_reports"][int(observation.station_id)]["reason"] = reason
            if observation.rover_llh or observation.rover_ecef:
                self._update_rover_llh_from_observation(observation)
            return False, None, reason

        session["seed_station_reports"][int(observation.station_id)].update({
            "solver_eligible": True,
            "reason": "RTK Fixed baseline accepted",
        })
        self._update_online_baseline_state(session, cluster_index, active_base, observation)
        if active_base == "BASE":
            session["seed_collection_steps"].add(int(observation.epoch_ts or time.time()))
        if observation.rover_llh or observation.rover_ecef:
            self._update_rover_llh_from_observation(observation)
        return True, base_diagnostic, None

    def _process_single_observation(
        self, session: dict, observation: Any, project_id: int, station_id: int
    ) -> tuple[bool, Optional[str], Optional[str]]:
        cluster_index = self._cluster_index_for_station(session, observation.station_id)
        if cluster_index is not None:
            session.setdefault("seed_station_reports", {})[int(observation.station_id)] = {
                "position_type": int(observation.position_type),
                "epoch_ts": int(observation.epoch_ts or 0),
                "station_id": int(observation.station_id),
                "rover": str(observation.rover_name),
                "raw_payload": str(observation.raw or ""),
                "received_monotonic": time.monotonic(),
                "base_identity_verified": False,
                "solver_eligible": False,
                "reason": "awaiting baseline validation",
            }
        return self._admit_agrica_observation(session, observation, project_id, station_id, cluster_index)

    def _ingest_parsed_observations(
        self, session: dict, observations: List[Any], project_id: int, station_id: int
    ) -> List[Any]:
        valid_obs = []
        ignored = []
        accepted_diags = []
        for obs in observations:
            is_valid, accepted_diag, ignored_reason = self._process_single_observation(
                session, obs, project_id, station_id
            )
            if is_valid:
                valid_obs.append(obs)
                if accepted_diag:
                    accepted_diags.append(accepted_diag)
            elif ignored_reason:
                ignored.append(ignored_reason)

        if valid_obs:
            rejection_note = f" Rejected: {'; '.join(dict.fromkeys(ignored))}." if ignored else ""
            self._last_ingest_diagnostics[project_id] = {
                "level": "success",
                "message": (
                    f"Accepted {len(valid_obs)} valid AGRICA baseline(s)."
                    f" {'; '.join(dict.fromkeys(accepted_diags))}."
                    f"{rejection_note}"
                ),
                "station_id": station_id,
                "position_types": [obs.position_type for obs in valid_obs],
            }
        else:
            self._last_ingest_diagnostics[project_id] = {
                "level": "warning",
                "message": (
                    "; ".join(dict.fromkeys(ignored))
                    if ignored
                    else "No complete AGRICA observation was parsed from this payload."
                ),
                "station_id": station_id,
            }
        return valid_obs

    def add_agrica_payload(self, raw_payload: str, info: Dict[str, Any]) -> List[Any]:
        """Store valid AGRICA measurements in the active project's cluster only."""
        try:
            from backend.processors.gnss_adjustment.runtime import parse_agrica
        except ModuleNotFoundError:
            from processors.gnss_adjustment.runtime import parse_agrica

        project_id = int(info.get("project_id") or info.get("station_id") or 0)
        session = self._sessions.get(project_id)
        if session is None:
            self._last_ingest_diagnostics[project_id] = {
                "level": "error",
                "message": "No active adjustment session exists for this project.",
                "station_id": info.get("station_id"),
            }
            return []

        station_id = int(info.get("station_id") or 0)
        rover_name = str(info.get("station_code") or info.get("station_name") or f"station_{station_id}")
        completed_sentences, buffered_length = self._consume_agrica_fragments(
            project_id, station_id, raw_payload
        )
        if not completed_sentences:
            self._last_ingest_diagnostics[project_id] = {
                "level": "info",
                "message": (
                    f"Buffered AGRICA fragment ({buffered_length} chars); waiting for the remaining fields and *CRC."
                    if buffered_length
                    else "No AGRICA sentence is available to parse."
                ),
                "station_id": station_id,
            }
            return []
        try:
            observations = parse_agrica(
                "\n".join(completed_sentences),
                project_id=project_id,
                station_id=station_id,
                rover_name=rover_name,
            )
        except Exception as exc:
            logger.exception("Error parsing AGRICA in RoundRobin: %s", exc)
            self._last_ingest_diagnostics[project_id] = {
                "level": "error",
                "message": f"AGRICA parse failed: {exc}",
                "station_id": station_id,
            }
            return []

        return self._ingest_parsed_observations(session, observations, project_id, station_id)


    def get_last_ingest_diagnostic(self, project_id: int) -> Optional[dict]:
        diagnostic = self._last_ingest_diagnostics.get(project_id)
        return dict(diagnostic) if diagnostic else None


    def has_complete_seed_observations(self, project_id: int) -> bool:
        """All selected rovers must first be observed from the fixed CORS base."""

        return bool(self.get_seed_collection_status(project_id)["complete"])


    def get_active_base_for_station(self, project_id: int, station_id: int) -> str:
        session = self._sessions.get(project_id)
        if not session:
            return "BASE"
        cluster_index = self._cluster_index_for_station(session, station_id)
        if cluster_index is None:
            return "BASE"
        return session.get("active_bases", {}).get(cluster_index, "BASE")


    def _collect_source_valid_indexed(self, cluster: dict, fixed_base_llh: tuple) -> list[tuple[int, Any]]:
        return [
            (record_index, record)
            for record_index, record in enumerate(cluster["observations"])
            if record.base_name == "BASE"
            and "EXCLUDE_UNCONFIRMED_SOURCE" not in tuple(getattr(record, "quality_flags", ()) or ())
            and max(float(value) for value in record.observation.std_neu) <= _BASELINE_STD_REJECTION_THRESHOLD_M
            and _vector_length(self._baseline_ecef(record.observation, fixed_base_llh)) >= 1.0
        ]

    def _quarantine_drifting_records(
        self, state: dict, station_id: int, source_valid_indexed: list, cluster: dict, latest_epoch: Any
    ) -> None:
        start_idx = int(state.get("solver_start_index") or 0)
        for record_index, record in source_valid_indexed:
            if (
                record_index >= start_idx
                and int(record.observation.station_id) == station_id
                and getattr(record, "solver_eligible", True)
            ):
                record.solver_eligible = False
                record.quality_flags = tuple(dict.fromkeys((*tuple(getattr(record, "quality_flags", ()) or ()), "EXCLUDE_STABILITY_LOST")))
                record.source_diagnostic = "Fixed-BASE solver session lost stationarity according to the rolling-window/EWMA abort envelope; the complete continuous seed session was reset."
        state["solver_start_index"] = len(cluster["observations"])
        state["reset_count"] = int(state.get("reset_count") or 0) + 1
        state["drift_failure_count"] = 0
        state["last_drift_evaluation_epoch"] = latest_epoch

    def _update_station_drift_and_window(
        self, state: dict, diagnostic: dict, warmup_ready: bool,
        station_id: int, source_valid_indexed: list, cluster: dict
    ) -> None:
        latest_epoch = diagnostic.get("latest_epoch")
        abort_exceeded = _rolling_drift_exceeds_abort_limits(
            diagnostic,
            horizontal_component_limit_m=self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M,
            up_component_limit_m=self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M,
        )
        if state["open"] and latest_epoch is not None and latest_epoch != state.get("last_drift_evaluation_epoch"):
            state["last_drift_evaluation_epoch"] = latest_epoch
            state["drift_failure_count"] = int(state.get("drift_failure_count") or 0) + 1 if abort_exceeded else 0

        if state["open"] and int(state.get("drift_failure_count") or 0) >= self.STABILITY_ABORT_CONSECUTIVE_EPOCHS:
            self._quarantine_drifting_records(state, station_id, source_valid_indexed, cluster, latest_epoch)

        if not state["open"] and warmup_ready:
            state["open"] = True
            state["drift_failure_count"] = 0
            state["last_drift_evaluation_epoch"] = latest_epoch

    @staticmethod
    def _compute_station_solver_epochs(cluster: dict, state: dict, station_id: int) -> tuple[int, int]:
        solver_epochs = {
            int(record.observation.epoch_ts)
            for record_index, record in enumerate(cluster["observations"])
            if record_index >= int(state["solver_start_index"])
            and record.base_name == "BASE"
            and int(record.observation.station_id) == station_id
            and getattr(record, "solver_eligible", True)
            and max(float(value) for value in record.observation.std_neu) <= _BASELINE_STD_REJECTION_THRESHOLD_M
        }
        solver_count = len(solver_epochs)
        solver_duration = max(solver_epochs) - min(solver_epochs) if solver_epochs else 0
        return solver_count, solver_duration

    def _evaluate_seed_cluster_status(
        self,
        session: dict,
        index: int,
        cluster: dict,
    ) -> dict:
        fixed_base_llh = self._cluster_base_llh(cluster)
        source_valid_indexed = self._collect_source_valid_indexed(cluster, fixed_base_llh)
        epochs_by_station: Dict[int, set[int]] = {}
        vectors_by_station: Dict[int, list[tuple[int, tuple[float, float, float]]]] = {}
        for _record_index, record in source_valid_indexed:
            station_id = int(record.observation.station_id)
            epoch = int(record.observation.epoch_ts)
            epochs_by_station.setdefault(station_id, set()).add(epoch)
            vectors_by_station.setdefault(station_id, []).append((
                epoch,
                tuple(float(value) for value in record.observation.baseline_neu),
            ))
        online_states = session.setdefault("online_baseline_states", {})
        for station_id, rover_code in zip(
            cluster["stations"], cluster["rovers"], strict=True
        ):
            online_state = online_states.get(self._online_baseline_key(index, "BASE", rover_code))
            if online_state is not None:
                vectors_by_station[int(station_id)] = online_state.recent_samples()

        expected = set(cluster["stations"])
        observed = set(epochs_by_station)
        station_reports = session.setdefault("seed_station_reports", {})
        latest_position_type_by_station = {
            station_id: station_reports.get(station_id, {}).get("position_type")
            for station_id in sorted(expected)
        }
        invalid_fix_station_ids = sorted(
            station_id
            for station_id in expected - observed
            if latest_position_type_by_station.get(station_id) not in (None, 4, 7)
        )
        silent_station_ids = sorted(
            station_id
            for station_id in expected - observed
            if latest_position_type_by_station.get(station_id) is None
        )
        sample_counts_by_station = {
            station_id: len(epochs_by_station.get(station_id, ()))
            for station_id in expected
        }
        durations_by_station = {
            station_id: (
                max(epochs_by_station[station_id]) - min(epochs_by_station[station_id])
                if epochs_by_station.get(station_id) else 0
            )
            for station_id in expected
        }
        warmup_ready_by_station = {
            station_id: bool(
                sample_counts_by_station[station_id] >= self.SEED_COLLECTION_MIN_DISTINCT_EPOCHS
                and durations_by_station[station_id] >= self.SEED_COLLECTION_MIN_DURATION_SECONDS
            )
            for station_id in expected
        }
        stability_by_station = {
            station_id: _rolling_mean_stability(
                vectors_by_station.get(station_id, ()),
                window_seconds=self.STABILITY_WINDOW_SECONDS,
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
            for station_id in expected
        }
        window_states = session.setdefault("seed_window_states", {})

        ready = set()
        solver_counts_by_station: Dict[int, int] = {}
        solver_durations_by_station: Dict[int, int] = {}
        window_open_by_station: Dict[int, bool] = {}
        reset_counts_by_station: Dict[int, int] = {}
        drift_failure_counts_by_station: Dict[int, int] = {}
        for station_id in expected:
            state = window_states.setdefault((index, station_id), {
                "open": False,
                "solver_start_index": 0,
                "reset_count": 0,
                "drift_failure_count": 0,
                "last_drift_evaluation_epoch": None,
            })
            self._update_station_drift_and_window(
                state, stability_by_station[station_id], warmup_ready_by_station[station_id],
                station_id, source_valid_indexed, cluster
            )

            solver_count, solver_duration = self._compute_station_solver_epochs(cluster, state, station_id)
            solver_counts_by_station[station_id] = solver_count
            solver_durations_by_station[station_id] = solver_duration
            window_open_by_station[station_id] = bool(state["open"])
            reset_counts_by_station[station_id] = int(state.get("reset_count") or 0)
            drift_failure_counts_by_station[station_id] = int(state.get("drift_failure_count") or 0)
            if (
                state["open"]
                and solver_count >= self.SEED_SOLVER_MIN_DISTINCT_EPOCHS
                and solver_duration >= self.SEED_SOLVER_MIN_DURATION_SECONDS
            ):
                ready.add(station_id)

        missing = sorted(expected - observed)
        available = sorted(expected & observed)
        warming = sorted((expected & observed) - ready)
        ready_station_ids = sorted(expected & ready)
        not_ready_station_ids = sorted(expected - ready)

        status_dict = {
            "index": index,
            "missing_station_ids": missing,
            "silent_station_ids": silent_station_ids,
            "invalid_fix_station_ids": invalid_fix_station_ids,
            "latest_position_type_by_station": latest_position_type_by_station,
            "warming_station_ids": warming,
            "available_station_ids": available,
            "ready_station_ids": ready_station_ids,
            "not_ready_station_ids": not_ready_station_ids,
            "sample_counts_by_station": {
                station_id: sample_counts_by_station[station_id]
                for station_id in sorted(expected)
            },
            "durations_by_station_seconds": {
                station_id: durations_by_station[station_id]
                for station_id in sorted(expected)
            },
            "warmup_ready_by_station": warmup_ready_by_station,
            "rolling_stability_by_station": {
                station_id: stability_by_station[station_id]
                for station_id in sorted(expected)
            },
            "solver_window_open_by_station": window_open_by_station,
            "solver_sample_counts_by_station": solver_counts_by_station,
            "solver_durations_by_station_seconds": solver_durations_by_station,
            "solver_window_reset_counts_by_station": reset_counts_by_station,
            "solver_drift_failure_counts_by_station": drift_failure_counts_by_station,
        }
        return {
            "status_dict": status_dict,
            "missing": missing,
            "silent_station_ids": silent_station_ids,
            "invalid_fix_station_ids": invalid_fix_station_ids,
            "warming": warming,
            "ready_station_ids": ready_station_ids,
            "not_ready_station_ids": not_ready_station_ids,
            "available": available,
        }

    def _aggregate_seed_cluster_statuses(self, session: dict, elapsed_timeout: bool) -> tuple:
        cluster_statuses = []
        missing_all, silent_all, invalid_fix_all, warming_all = [], [], [], []
        timeout_skippable_all = []
        timeout_fallback_blocked = False
        complete = True
        can_continue = True
        for index, cluster in enumerate(session["clusters"]):
            c_res = self._evaluate_seed_cluster_status(session, index, cluster)
            if c_res["missing"] or c_res["warming"]:
                complete = False
                missing_all.extend(c_res["missing"])
                silent_all.extend(c_res["silent_station_ids"])
                invalid_fix_all.extend(c_res["invalid_fix_station_ids"])
                warming_all.extend(c_res["warming"])
            if elapsed_timeout and c_res["not_ready_station_ids"]:
                if len(c_res["ready_station_ids"]) >= 2:
                    timeout_skippable_all.extend(c_res["not_ready_station_ids"])
                else:
                    timeout_fallback_blocked = True
            if len(c_res["available"]) < 2:
                can_continue = False
            cluster_statuses.append(c_res["status_dict"])
        return (
            cluster_statuses, missing_all, silent_all, invalid_fix_all, warming_all,
            timeout_skippable_all, timeout_fallback_blocked, complete, can_continue
        )

    def get_seed_collection_status(self, project_id: int) -> dict:
        """Return fixed-base window readiness and offline-rover fallback state."""
        session = self._sessions.get(project_id)
        if session is None:
            return {"complete": False, "fallback_ready": False, "step_count": 0,
                    "max_steps": self.SEED_COLLECTION_MAX_STEPS,
                    "missing_station_ids": [], "warming_station_ids": [],
                    "clusters": []}

        steps = min(len(session["seed_collection_steps"]), self.SEED_COLLECTION_MAX_STEPS)
        seed_elapsed = max(0.0, time.monotonic() - float(session.get("seed_started_monotonic") or 0.0))
        elapsed_timeout = seed_elapsed >= self.SEED_STABILITY_TIMEOUT_SECONDS

        (
            cluster_statuses, missing_all, silent_all, invalid_fix_all, warming_all,
            timeout_skippable_all, timeout_fallback_blocked, complete, can_continue
        ) = self._aggregate_seed_cluster_statuses(session, elapsed_timeout)

        stability_timeout = not complete and elapsed_timeout
        timeout_fallback_ready = (
            not complete and stability_timeout and bool(timeout_skippable_all) and not timeout_fallback_blocked
        )
        return {
            "complete": complete,
            "fallback_ready": bool(
                (bool(missing_all) and can_continue and steps >= self.SEED_COLLECTION_MAX_STEPS)
                or timeout_fallback_ready
            ),
            "step_count": steps,
            "max_steps": self.SEED_COLLECTION_MAX_STEPS,
            "missing_station_ids": sorted(set(missing_all)),
            "silent_station_ids": sorted(set(silent_all)),
            "invalid_fix_station_ids": sorted(set(invalid_fix_all)),
            "warming_station_ids": sorted(set(warming_all)),
            "timeout_skippable_station_ids": sorted(set(timeout_skippable_all)),
            "stability_timeout": stability_timeout,
            "stability_elapsed_seconds": seed_elapsed,
            "stability_timeout_seconds": self.SEED_STABILITY_TIMEOUT_SECONDS,
            "stability_window_seconds": self.STABILITY_WINDOW_SECONDS,
            "stability_min_samples_per_window": self.STABILITY_MIN_SAMPLES_PER_WINDOW,
            "stability_hold_seconds": self.STABILITY_HOLD_SECONDS,
            "seed_warmup_min_distinct_epochs": self.SEED_COLLECTION_MIN_DISTINCT_EPOCHS,
            "seed_warmup_min_duration_seconds": self.SEED_COLLECTION_MIN_DURATION_SECONDS,
            "solver_min_distinct_epochs": self.SEED_SOLVER_MIN_DISTINCT_EPOCHS,
            "solver_min_duration_seconds": self.SEED_SOLVER_MIN_DURATION_SECONDS,
            "timeout_fallback_ready": timeout_fallback_ready,
            "clusters": cluster_statuses,
        }


    def skip_missing_seed_stations(self, project_id: int) -> dict:
        """Temporarily exclude no-data/degraded rovers after fixed-base seed."""
        session = self._sessions.get(project_id)
        status = self.get_seed_collection_status(project_id)
        if session is None or not status["fallback_ready"]:
            return status

        skipped = []
        for item in status["clusters"]:
            cluster = session["clusters"][item["index"]]
            skipped_station_ids = set(item["missing_station_ids"])
            if status.get("stability_timeout"):
                ready = {int(station_id) for station_id in item.get("ready_station_ids") or ()}
                if len(ready) >= 2:
                    skipped_station_ids.update(
                        int(station_id)
                        for station_id in cluster["stations"]
                        if int(station_id) not in ready
                    )
            if not skipped_station_ids:
                continue
            rover_by_station = dict(zip(cluster["stations"], cluster["rovers"], strict=True))
            cluster["stations"] = [
                station_id
                for station_id in cluster["stations"]
                if int(station_id) not in skipped_station_ids
            ]
            cluster["rovers"] = [rover_by_station[station_id] for station_id in cluster["stations"]]
            skipped.extend(skipped_station_ids)

        result = self.get_seed_collection_status(project_id)
        result["skipped_station_ids"] = sorted(set(skipped))
        return result
