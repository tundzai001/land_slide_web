import asyncio
import base64
import copy
import inspect
import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np
from scipy.stats import chi2

logger = logging.getLogger(__name__)


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

class RoundRobinAdjustmentManager:
    """Collect base-to-rover and rover-to-rover baselines for the existing solver.

    The mathematical adjustment remains in ``gnss_adjustment.solver``.  This
    class only manages the observation lifecycle and provides that solver with
    correctly connected ECEF baselines.
    """

    # A single 1 Hz FIXED epoch only proves that the station is alive. Keep one
    # continuous, source-verified seed session: the initial epochs are useful
    # observations, not a disposable warm-up followed by a second collection.
    SEED_COLLECTION_MIN_DISTINCT_EPOCHS = 20
    SEED_COLLECTION_MIN_DURATION_SECONDS = 15
    SEED_COLLECTION_MAX_STEPS = 20
    # AGRICA arrives at roughly 0.4--0.7 distinct epochs/s in the field. Thirty
    # distinct epochs over at least 30 seconds therefore normally takes about
    # 45--75 seconds of wall time and gives useful temporal coverage without
    # making the old mistake of discarding 20 good epochs and then waiting for
    # another complete 60-second window.
    SEED_SOLVER_MIN_DISTINCT_EPOCHS = 30
    SEED_SOLVER_MIN_DURATION_SECONDS = 30
    SEED_STABILITY_TIMEOUT_SECONDS = 300
    # After the CORS pair has been forced onto one physical receiver, discard
    # the caster/rover handover interval before opening the common seed window.
    FIXED_BASE_HANDOVER_SETTLE_SECONDS = 5
    STABILITY_WINDOW_SECONDS = 10
    STABILITY_MIN_SAMPLES_PER_WINDOW = 4
    STABILITY_MAX_SAMPLE_GAP_SECONDS = 5
    STABILITY_HORIZONTAL_COMPONENT_LIMIT_M = 0.003
    STABILITY_UP_COMPONENT_LIMIT_M = 0.005
    STABILITY_HORIZONTAL_STD_LIMIT_M = 0.010
    STABILITY_UP_STD_LIMIT_M = 0.015
    STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS = 0.001
    STABILITY_UP_SLOPE_LIMIT_MPS = 0.002
    STABILITY_EWMA_FAST_TAU_SECONDS = 3.0
    STABILITY_EWMA_SLOW_TAU_SECONDS = 30.0
    STABILITY_HOLD_SECONDS = 10
    # Once a solver window is open, use a wider abort envelope and require
    # repeated receiver epochs outside it. This prevents a 0.1 mm boundary
    # crossing or a repeated UI poll from discarding a full minute of data.
    STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M = 0.008
    STABILITY_ABORT_UP_COMPONENT_LIMIT_M = 0.015
    STABILITY_ABORT_CONSECUTIVE_EPOCHS = 3
    BASE_IDENTITY_TOLERANCE_M = 20.0
    FIXED_BASE_LENGTH_TOLERANCE_M = 20.0
    # This is only a last-resort gross-error barrier. Normal GNSS loop closure
    # should be orders of magnitude smaller; a metre-scale closure means that
    # at least one observation was assigned to the wrong correction source.
    GROSS_LOOP_CLOSURE_MIN_LIMIT_M = 1.0
    GROSS_LOOP_CLOSURE_RELATIVE_LIMIT = 1.0 / 1000.0
    CROSS_BASE_SETTLE_SECONDS = 5
    # A rover that was tracking the stopped fixed source may need well over a
    # minute to reconnect, decode the replacement ephemerides and regain a
    # solver-eligible FIX.  The live Sin Quyen handover showed 45 seconds is
    # too short for the slower receiver, so keep validating source/length for
    # up to two minutes instead of prematurely cycling the base again.
    CROSS_BASE_SWITCH_TIMEOUT_SECONDS = 120
    CROSS_BASE_HANDOVER_MIN_SAMPLES = 5
    CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS = 5
    CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS = 5
    CROSS_BASE_STABLE_COLLECTION_SECONDS = 60
    CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS = 30
    CROSS_BASE_STABLE_MIN_DURATION_SECONDS = 60
    CROSS_BASE_STABILITY_TIMEOUT_SECONDS = 300
    CROSS_BASE_STATUS_POLL_SECONDS = 1
    CROSS_BASE_COLLECTION_ATTEMPTS = 2
    INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS = 3
    # If the fixed stream is demonstrably serving another rover while the next
    # candidate remains completely silent, do not burn the full reacquisition
    # timeout on a data-plane-stale receiver.
    INTER_ROTATION_STALE_ROVER_GRACE_SECONDS = 45
    INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
    # A slow receiver can keep publishing transition AGRICA for almost the
    # entire nominal wait and acquire the fixed source a few seconds later.
    # Give recent activity a bounded sliding grace period, but retain a hard
    # ceiling so a permanently stale stream cannot block the rotation forever.
    INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
    INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
    INTER_ROTATION_CLIENT_POLL_SECONDS = 5
    MODE_COMMAND_BURST_COUNT = 6
    UNLOGALL_COMMAND_BURST_COUNT = 3
    GPGGA_COMMAND_BURST_COUNT = 6
    AGRICA_COMMAND_BURST_COUNT = 6
    RTCM_COMMAND_BURST_COUNT = 3
    COMMAND_BURST_INTERVAL_SECONDS = 0.25
    PREFLIGHT_CONNECTION_ATTEMPTS = 2
    ROVER_RESTORE_TRANSPORT_ATTEMPTS = 6
    ROVER_RESTORE_RETRY_SECONDS = 2.0
    RTCM_ROUTE_RECOVERY_ATTEMPTS = 2
    OPTIONAL_BASE_RTCM_COMMANDS = (
        "rtcm1077 com2 1",
        "rtcm1127 com2 1",
        "rtcm1087 com2 1",
        "rtcm1097 com2 1",
    )

    def __init__(
        self,
        mqtt_client,
        caster_host: str = "",
        caster_hosts: Optional[List[str]] = None,
        caster_port: int = 2101,
        source_host: Optional[str] = None,
        source_port: int = 2101,
        control_password: str = "12345",
        source_password: str = "12345",
        web_cors_api_base_url: str = "",
        web_cors_api_token: str = "",
        web_cors_api_username: str = "",
        web_cors_api_password: str = "",
        route_start_callback: Optional[Callable[[str, str, int, str, str], Any]] = None,
        route_wait_callback: Optional[Callable[[str, float], Any]] = None,
        route_stop_callback: Optional[Callable[[str], Any]] = None,
        result_callback: Optional[Callable[[int, dict], Any]] = None,
        error_callback: Optional[Callable[[int, str], Any]] = None,
        progress_callback: Optional[Callable[[int, str], Any]] = None,
    ):
        self.mqtt_client = mqtt_client
        self.caster_host = caster_host
        self.caster_hosts = list(dict.fromkeys(
            str(host).strip()
            for host in (caster_hosts or [caster_host])
            if str(host).strip()
        ))
        self.caster_port = caster_port
        self.source_host = source_host or caster_host
        self.source_port = source_port
        self.control_password = control_password
        self.source_password = source_password
        if not web_cors_api_base_url:
            try:
                from app.config import settings as app_settings

                web_cors_api_base_url = app_settings.WEB_CORS_API_BASE_URL
            except Exception:
                web_cors_api_base_url = ""
        self.web_cors_api_base_url = str(web_cors_api_base_url or "").rstrip("/")
        self._web_cors_access_token = str(web_cors_api_token or "").strip()
        self.web_cors_api_username = str(web_cors_api_username or "").strip()
        self.web_cors_api_password = str(web_cors_api_password or "")
        self._cors_fixed_base_snapshots: Dict[tuple[Any, ...], Dict[str, Any]] = {}
        self._cors_failover_last_state: Dict[tuple[Any, ...], str] = {}
        self.route_start_callback = route_start_callback
        self.route_wait_callback = route_wait_callback
        self.route_stop_callback = route_stop_callback
        self.result_callback = result_callback
        self.error_callback = error_callback
        self.progress_callback = progress_callback
        self._last_set_error: Optional[str] = None
        self._last_set_response: Optional[str] = None
        self._last_set_warnings: List[str] = []
        # Paho invokes MQTT callbacks from its own thread while SET commands run
        # in the asyncio event loop.  Protect the short-lived waiter registry so
        # an ACK can safely cross that boundary.
        self._command_ack_lock = threading.Lock()
        self._command_ack_waiters: Dict[str, _CommandAckWaiter] = {}
        self.running_tasks: Dict[int, asyncio.Task] = {}
        self.rover_llh_cache: Dict[str, Dict[str, float]] = {}
        self._sessions: Dict[int, dict] = {}
        self._last_ingest_diagnostics: Dict[int, dict] = {}
        # UM980 AGRICA output can be split across MQTT payloads.  Buffers are
        # isolated per project/station so fragments from different rovers never
        # get concatenated.
        self._agrica_fragment_buffers: Dict[tuple[int, int], str] = {}

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

    def add_receiver_command_payload(
        self,
        raw_payload: str,
        info: Dict[str, Any],
        topic: str,
    ) -> bool:
        """Feed receiver echo/response text from the rover's subscribed MQTT topic.

        A response is accepted only after the same MQTT topic first emits a line
        exactly equal to the command sent to that rover.  This deliberately
        rejects socket echoes, unrelated ``OK`` text, and replies from another
        station/topic.
        """

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
            for line in lines:
                framed = _COMMAND_RESPONSE_RE.search(line)
                if framed:
                    framed_command = framed.group("command").strip()
                    framed_response = framed.group("response").strip()
                    expected_command = _normalized_receiver_command(waiter.command)
                    actual_command = _normalized_receiver_command(framed_command)
                    expected_key = expected_command.split(" ", 1)[0]
                    actual_key = actual_command.split(" ", 1)[0]

                    # A full command in $COMMAND can establish identity itself.
                    # A key-only response (for example "$COMMAND,MODE,...") is
                    # accepted only after this topic emitted the exact command.
                    if actual_command == expected_command:
                        waiter.echo_seen = True
                        waiter.topic = incoming_topic
                    elif not (
                        waiter.echo_seen
                        and waiter.topic == incoming_topic
                        and actual_key == expected_key
                    ):
                        continue

                    accepted = _receiver_response_result(framed_response)
                    if accepted is not None:
                        result = {
                            "accepted": accepted,
                            "response": framed_response,
                            "raw_response": line[framed.start():].strip(),
                            "topic": incoming_topic,
                            "command": waiter.command,
                        }
                        break

                if not waiter.echo_seen:
                    if _normalized_receiver_command(line) != _normalized_receiver_command(waiter.command):
                        continue
                    waiter.echo_seen = True
                    waiter.topic = incoming_topic
                    logger.info(
                        "MQTT receiver command echo station=%s topic=%s command=%s",
                        waiter.station_code,
                        waiter.topic,
                        waiter.command,
                    )
                    continue

                if waiter.topic != incoming_topic:
                    continue
                accepted = _receiver_response_result(line)
                if accepted is True:
                    result = {
                        "accepted": True,
                        "response": line,
                        "raw_response": line,
                        "topic": incoming_topic,
                        "command": waiter.command,
                    }
                    break
                if accepted is False:
                    result = {
                        "accepted": False,
                        "response": line,
                        "raw_response": line,
                        "topic": incoming_topic,
                        "command": waiter.command,
                    }
                    break

            if result is not None:
                self._command_ack_waiters.pop(key, None)

        if result is not None and waiter is not None:
            loop = waiter.future.get_loop()

            def deliver() -> None:
                if not waiter.future.done():
                    waiter.future.set_result(result)

            loop.call_soon_threadsafe(deliver)
            return True
        return bool(waiter and waiter.echo_seen)

    def configure_project(self, project_id: int, clusters: List[dict]) -> None:
        """Start a new collection session using normalized cluster settings."""

        prepared_clusters = []
        assigned_station_ids: set[int] = set()
        for raw_cluster in clusters or []:
            if not isinstance(raw_cluster, dict):
                continue
            station_ids = []
            for station_id in raw_cluster.get("stations", []):
                try:
                    station_ids.append(int(station_id))
                except (TypeError, ValueError):
                    continue
            station_ids = list(dict.fromkeys(station_ids))
            rover_codes = [str(code).strip() for code in raw_cluster.get("rovers", []) if str(code).strip()]

            if len(station_ids) < 2:
                raise ValueError("each GNSS adjustment cluster needs at least two stations")
            if len(rover_codes) != len(station_ids):
                raise ValueError("cluster station IDs and rover codes are inconsistent")
            overlap = assigned_station_ids.intersection(station_ids)
            if overlap:
                raise ValueError(f"a station cannot belong to more than one active cluster: {sorted(overlap)}")
            assigned_station_ids.update(station_ids)

            cluster = dict(raw_cluster)
            cluster["stations"] = station_ids
            cluster["rovers"] = rover_codes
            cluster["observations"] = []
            prepared_clusters.append(cluster)

        if not prepared_clusters:
            raise ValueError("no valid GNSS adjustment clusters were supplied")

        self.clear_project(project_id)
        self._sessions[project_id] = {
            "clusters": prepared_clusters,
            "active_bases": {},
            "seed_collection_steps": set(),
            "seed_window_states": {},
            "online_baseline_states": {},
            "seed_station_reports": {},
            "seed_started_monotonic": time.monotonic(),
        }

    def clear_project(self, project_id: int) -> None:
        task = self.running_tasks.pop(project_id, None)
        if task and not task.done():
            task.cancel()
        self._sessions.pop(project_id, None)
        self._last_ingest_diagnostics.pop(project_id, None)
        for key in [key for key in self._agrica_fragment_buffers if key[0] == project_id]:
            self._agrica_fragment_buffers.pop(key, None)

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

    def _update_rover_llh_from_observation(self, observation: Any) -> None:
        """Cache an ellipsoidal temporary-base coordinate from AGRICA.

        Field receivers report AGRICA ``lat/lon/alt`` with an MSL-like height,
        while AGRICA ECEF is WGS84 and therefore yields ellipsoidal height. The
        UM980 ``MODE BASE lat lon height`` coordinate must stay in one datum.
        Prefer the ECEF-derived LLH only after its horizontal position agrees
        with the reported LLH; malformed ECEF then cannot poison the cache.
        """

        rover_llh = getattr(observation, "rover_llh", None)
        rover_ecef = getattr(observation, "rover_ecef", None)
        selected = rover_llh
        if rover_ecef and len(rover_ecef) == 3:
            try:
                ecef_values = tuple(float(value) for value in rover_ecef)
                if (
                    all(math.isfinite(value) for value in ecef_values)
                    and _vector_length(ecef_values) > 1_000_000.0
                ):
                    ecef_llh = _ecef_to_llh(*ecef_values)
                    if (
                        not rover_llh
                        or _llh_horizontal_distance_m(ecef_llh, rover_llh) <= 5.0
                    ):
                        selected = ecef_llh
            except (TypeError, ValueError, OverflowError):
                pass
        if selected:
            self.update_rover_llh(
                observation.rover_name,
                float(selected[0]),
                float(selected[1]),
                float(selected[2]),
            )
            cache = self.rover_llh_cache.get(observation.rover_name) or {}
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
            self.rover_llh_cache[observation.rover_name] = cache

    def has_pending_agrica_fragment(self, project_id: int, station_id: int) -> bool:
        return (int(project_id), int(station_id)) in self._agrica_fragment_buffers

    def _consume_agrica_fragments(
        self,
        project_id: int,
        station_id: int,
        raw_payload: str,
    ) -> tuple[list[str], int]:
        """Return complete AGRICA sentences and retain an unfinished tail.

        The sentence is only released after its eight-digit CRC arrives.  This
        prevents a partial payload such as ``#AGRICA,...,0.0`` from being parsed
        as a complete observation.
        """

        key = (int(project_id), int(station_id))
        payload = str(raw_payload or "").replace("\x00", "")
        pending = self._agrica_fragment_buffers.get(key, "")
        marker_index = payload.find("#AGRICA")
        if marker_index >= 0:
            # A fresh AGRICA header supersedes an incomplete stale sentence.
            pending = payload[marker_index:]
        elif pending:
            pending += payload
        else:
            return [], 0

        # A valid UM980 message ends in * followed by eight hexadecimal CRC
        # characters. However, if the payload is truncated by hardware buffers,
        # we still process it as long as the * is reached, since all GNSS data
        # is before the asterisk.
        complete_matches = list(re.finditer(r"#AGRICA[^*]*\*[0-9A-Fa-f]*", pending, re.DOTALL))
        if complete_matches:
            completed = [match.group(0) for match in complete_matches]
            tail = pending[complete_matches[-1].end():]
            tail_marker = tail.find("#AGRICA")
            if tail_marker >= 0:
                tail = tail[tail_marker:]
            else:
                tail = ""
            if tail:
                self._agrica_fragment_buffers[key] = tail
            else:
                self._agrica_fragment_buffers.pop(key, None)
            return completed, len(tail)

        # Protect the service from an indefinitely growing corrupt buffer.  If
        # another AGRICA header is present keep only the newest sentence start.
        if len(pending) > 8192:
            newest_marker = pending.rfind("#AGRICA")
            pending = pending[newest_marker:] if newest_marker >= 0 else ""
        if pending:
            self._agrica_fragment_buffers[key] = pending
        else:
            self._agrica_fragment_buffers.pop(key, None)
        return [], len(pending)

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
            project_id,
            station_id,
            raw_payload,
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
            logger.error("Error parsing AGRICA in RoundRobin: %s", exc)
            self._last_ingest_diagnostics[project_id] = {
                "level": "error",
                "message": f"AGRICA parse failed: {exc}",
                "station_id": station_id,
            }
            return []

        valid_observations = []
        ignored_reasons = []
        accepted_diagnostics = []
        for observation in observations:
            cluster_index = self._cluster_index_for_station(
                session, observation.station_id
            )
            if cluster_index is not None:
                session.setdefault("seed_station_reports", {})[
                    int(observation.station_id)
                ] = {
                    "position_type": int(observation.position_type),
                    "epoch_ts": int(observation.epoch_ts or 0),
                    "received_monotonic": time.monotonic(),
                    "solver_eligible": False,
                    "reason": "awaiting baseline validation",
                }
            if observation.position_type not in (4, 7):
                reason = (
                    f"position_type={observation.position_type}; requires RTK "
                    "Fixed (4) or Input Fixed (7)"
                )
                ignored_reasons.append(reason)
                if cluster_index is not None:
                    session["seed_station_reports"][
                        int(observation.station_id)
                    ]["reason"] = reason
                continue
            if cluster_index is None:
                ignored_reasons.append("station is not included in the active GNSS cluster")
                continue
            active_base = session["active_bases"].get(cluster_index, "BASE")
            if active_base == observation.rover_name:
                ignored_reasons.append("ignored self-observation while this rover is the temporary base")
                continue
            cluster = session["clusters"][cluster_index]
            base_matches, base_diagnostic = self._observation_matches_active_base(
                cluster,
                active_base,
                observation,
            )
            if not base_matches:
                # Preserve the receiver evidence under the source label that
                # was active in the controller, but quarantine it permanently.
                # Similarity to another edge is not authority to relabel it.
                session["clusters"][cluster_index]["observations"].append(
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
                session["seed_station_reports"][
                    int(observation.station_id)
                ]["reason"] = base_diagnostic
                ignored_reasons.append(base_diagnostic)
                logger.warning(
                    "Round-Robin project=%s cluster=%s station=%s: %s",
                    project_id,
                    cluster_index,
                    station_id,
                    base_diagnostic,
                )
                continue
            session["clusters"][cluster_index]["observations"].append(
                _CollectedObservation(
                    active_base,
                    observation,
                    rotation_index=cluster.get("current_rotation_index", 0),
                    stable_window_index=cluster.get("current_stable_window_index", 0),
                )
            )
            if max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M:
                reason = (
                    "baseline STD exceeds 0.1 m; stored for RAW_AUDIT but "
                    "excluded from solver"
                )
                ignored_reasons.append(reason)
                session["seed_station_reports"][
                    int(observation.station_id)
                ]["reason"] = reason
                if observation.rover_llh or observation.rover_ecef:
                    self._update_rover_llh_from_observation(observation)
                continue
            valid_observations.append(observation)
            session["seed_station_reports"][int(observation.station_id)].update({
                "solver_eligible": True,
                "reason": "RTK Fixed baseline accepted",
            })
            self._update_online_baseline_state(
                session,
                cluster_index,
                active_base,
                observation,
            )
            accepted_diagnostics.append(base_diagnostic)
            if active_base == "BASE":
                # Count GNSS epochs, not server wall-clock seconds. MQTT can
                # deliver many buffered observations in one burst; wall-clock
                # counting made a healthy 10 Hz/1 Hz stream appear stuck at
                # step 1-4 and delayed exclusion of a genuinely silent rover.
                session["seed_collection_steps"].add(
                    int(observation.epoch_ts or time.time())
                )
            if observation.rover_llh or observation.rover_ecef:
                self._update_rover_llh_from_observation(observation)
        if valid_observations:
            rejection_note = (
                f" Rejected: {'; '.join(dict.fromkeys(ignored_reasons))}."
                if ignored_reasons
                else ""
            )
            self._last_ingest_diagnostics[project_id] = {
                "level": "success",
                "message": (
                    f"Accepted {len(valid_observations)} valid AGRICA baseline(s)."
                    f" {'; '.join(dict.fromkeys(accepted_diagnostics))}."
                    f"{rejection_note}"
                ),
                "station_id": station_id,
                "position_types": [obs.position_type for obs in valid_observations],
            }
        else:
            self._last_ingest_diagnostics[project_id] = {
                "level": "warning",
                "message": (
                    "; ".join(dict.fromkeys(ignored_reasons))
                    if ignored_reasons
                    else "No complete AGRICA observation was parsed from this payload."
                ),
                "station_id": station_id,
            }
        return valid_observations

    def get_last_ingest_diagnostic(self, project_id: int) -> Optional[dict]:
        diagnostic = self._last_ingest_diagnostics.get(project_id)
        return dict(diagnostic) if diagnostic else None

    @staticmethod
    def _cluster_index_for_station(session: dict, station_id: int) -> Optional[int]:
        for index, cluster in enumerate(session["clusters"]):
            if station_id in cluster["stations"]:
                return index
        return None

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

    def get_seed_collection_status(self, project_id: int) -> dict:
        """Return fixed-base window readiness and offline-rover fallback state."""
        session = self._sessions.get(project_id)
        if session is None:
            return {"complete": False, "fallback_ready": False, "step_count": 0,
                    "max_steps": self.SEED_COLLECTION_MAX_STEPS,
                    "missing_station_ids": [], "warming_station_ids": [],
                    "clusters": []}

        steps = min(len(session["seed_collection_steps"]), self.SEED_COLLECTION_MAX_STEPS)
        seed_elapsed = max(
            0.0,
            time.monotonic() - float(session.get("seed_started_monotonic") or 0.0),
        )
        elapsed_timeout = seed_elapsed >= self.SEED_STABILITY_TIMEOUT_SECONDS

        cluster_statuses = []
        missing_all = []
        silent_all = []
        invalid_fix_all = []
        warming_all = []
        timeout_skippable_all = []
        timeout_fallback_blocked = False
        complete = True
        can_continue = True
        for index, cluster in enumerate(session["clusters"]):
            fixed_base_llh = self._cluster_base_llh(cluster)
            source_valid_indexed = [
                (record_index, record)
                for record_index, record in enumerate(cluster["observations"])
                if record.base_name == "BASE"
                and "EXCLUDE_UNCONFIRMED_SOURCE"
                not in tuple(getattr(record, "quality_flags", ()) or ())
                and max(
                    float(value) for value in record.observation.std_neu
                ) <= _BASELINE_STD_REJECTION_THRESHOLD_M
                and _vector_length(
                    self._baseline_ecef(record.observation, fixed_base_llh)
                ) >= 1.0
            ]
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
                online_state = online_states.get(self._online_baseline_key(
                    index, "BASE", rover_code
                ))
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
                    max(epochs_by_station[station_id])
                    - min(epochs_by_station[station_id])
                    if epochs_by_station.get(station_id) else 0
                )
                for station_id in expected
            }
            warmup_ready_by_station = {
                station_id: bool(
                    sample_counts_by_station[station_id]
                    >= self.SEED_COLLECTION_MIN_DISTINCT_EPOCHS
                    and durations_by_station[station_id]
                    >= self.SEED_COLLECTION_MIN_DURATION_SECONDS
                )
                for station_id in expected
            }
            stability_by_station = {
                station_id: _rolling_mean_stability(
                    vectors_by_station.get(station_id, ()),
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
                    up_component_limit_m=self.STABILITY_UP_COMPONENT_LIMIT_M,
                    horizontal_std_limit_m=self.STABILITY_HORIZONTAL_STD_LIMIT_M,
                    up_std_limit_m=self.STABILITY_UP_STD_LIMIT_M,
                    horizontal_slope_limit_mps=(
                        self.STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS
                    ),
                    up_slope_limit_mps=self.STABILITY_UP_SLOPE_LIMIT_MPS,
                    ewma_fast_tau_seconds=self.STABILITY_EWMA_FAST_TAU_SECONDS,
                    ewma_slow_tau_seconds=self.STABILITY_EWMA_SLOW_TAU_SECONDS,
                    ewma_horizontal_limit_m=(
                        self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                    ),
                    ewma_up_limit_m=self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M,
                )
                for station_id in expected
            }
            window_states = session.setdefault("seed_window_states", {})

            def quarantine_seed_window(
                station_id: int,
                start_index: int,
                flag: str,
                diagnostic_message: str,
            ) -> None:
                records = cluster["observations"]
                for record_index, record in source_valid_indexed:
                    if (
                        record_index < start_index
                        or int(record.observation.station_id) != station_id
                        or not getattr(record, "solver_eligible", True)
                    ):
                        continue
                    flags = tuple(dict.fromkeys((
                        *tuple(getattr(record, "quality_flags", ()) or ()),
                        flag,
                    )))
                    record.solver_eligible = False
                    record.quality_flags = flags
                    record.source_diagnostic = diagnostic_message

            ready = set()
            solver_counts_by_station: Dict[int, int] = {}
            solver_durations_by_station: Dict[int, int] = {}
            window_open_by_station: Dict[int, bool] = {}
            reset_counts_by_station: Dict[int, int] = {}
            drift_failure_counts_by_station: Dict[int, int] = {}
            for station_id in expected:
                diagnostic = stability_by_station[station_id]
                state_key = (index, station_id)
                state = window_states.setdefault(state_key, {
                    "open": False,
                    "solver_start_index": 0,
                    "reset_count": 0,
                    "drift_failure_count": 0,
                    "last_drift_evaluation_epoch": None,
                })
                state.setdefault("drift_failure_count", 0)
                state.setdefault("last_drift_evaluation_epoch", None)
                latest_epoch = diagnostic.get("latest_epoch")
                abort_exceeded = _rolling_drift_exceeds_abort_limits(
                    diagnostic,
                    horizontal_component_limit_m=(
                        self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                    ),
                    up_component_limit_m=(
                        self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M
                    ),
                )
                if (
                    state["open"]
                    and latest_epoch is not None
                    and latest_epoch != state.get("last_drift_evaluation_epoch")
                ):
                    state["last_drift_evaluation_epoch"] = latest_epoch
                    state["drift_failure_count"] = (
                        int(state.get("drift_failure_count") or 0) + 1
                        if abort_exceeded else 0
                    )
                if (
                    state["open"]
                    and int(state.get("drift_failure_count") or 0)
                    >= self.STABILITY_ABORT_CONSECUTIVE_EPOCHS
                ):
                    quarantine_seed_window(
                        station_id,
                        int(state.get("solver_start_index") or 0),
                        "EXCLUDE_STABILITY_LOST",
                        "Fixed-BASE solver session lost stationarity according to "
                        "the rolling-window/EWMA abort envelope; the complete "
                        "continuous seed session was reset.",
                    )
                    state["solver_start_index"] = len(cluster["observations"])
                    state["reset_count"] = int(state.get("reset_count") or 0) + 1
                    state["drift_failure_count"] = 0
                    state["last_drift_evaluation_epoch"] = latest_epoch
                # There is no correction-source handover during fixed-base
                # collection: source identity and gross geometry were already
                # verified when each AGRICA record was accepted. Natural RTK
                # millimetre-level wander must not prevent the solver window
                # from ever opening. Rolling N/E/U remains an audit diagnostic;
                # only epoch/time warm-up controls this transition.
                if (
                    not state["open"]
                    and warmup_ready_by_station[station_id]
                ):
                    # Source identity and gross BASE geometry were already
                    # verified before records reached this state. Reuse the
                    # warm-up epochs in the same independent seed session;
                    # restarting here doubled field collection time and gave
                    # no statistical independence benefit.
                    state["open"] = True
                    state["drift_failure_count"] = 0
                    state["last_drift_evaluation_epoch"] = latest_epoch

                solver_epochs = {
                    int(record.observation.epoch_ts)
                    for record_index, record in enumerate(cluster["observations"])
                    if record_index >= int(state["solver_start_index"])
                    and record.base_name == "BASE"
                    and int(record.observation.station_id) == station_id
                    and getattr(record, "solver_eligible", True)
                    and max(float(value) for value in record.observation.std_neu)
                    <= _BASELINE_STD_REJECTION_THRESHOLD_M
                }
                solver_count = len(solver_epochs)
                solver_duration = (
                    max(solver_epochs) - min(solver_epochs) if solver_epochs else 0
                )
                solver_counts_by_station[station_id] = solver_count
                solver_durations_by_station[station_id] = solver_duration
                window_open_by_station[station_id] = bool(state["open"])
                reset_counts_by_station[station_id] = int(state.get("reset_count") or 0)
                drift_failure_counts_by_station[station_id] = int(
                    state.get("drift_failure_count") or 0
                )
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
            if missing or warming:
                complete = False
                missing_all.extend(missing)
                silent_all.extend(silent_station_ids)
                invalid_fix_all.extend(invalid_fix_station_ids)
                warming_all.extend(warming)
            if elapsed_timeout and not_ready_station_ids:
                if len(ready_station_ids) >= 2:
                    timeout_skippable_all.extend(not_ready_station_ids)
                else:
                    timeout_fallback_blocked = True
            if len(available) < 2:
                can_continue = False
            cluster_statuses.append({
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
                "solver_drift_failure_counts_by_station": (
                    drift_failure_counts_by_station
                ),
            })

        stability_timeout = not complete and elapsed_timeout
        timeout_fallback_ready = (
            not complete
            and stability_timeout
            and bool(timeout_skippable_all)
            and not timeout_fallback_blocked
        )
        return {
            "complete": complete,
            # Initially skip only truly silent stations after enough fixed-base
            # seed epochs exist.  If the hard stability timeout is reached,
            # stations that are still not ready are treated as degraded and may
            # be excluded, but only when each cluster still has at least two
            # ready rovers left for the network solve.
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
            "stability_min_samples_per_window": (
                self.STABILITY_MIN_SAMPLES_PER_WINDOW
            ),
            "stability_hold_seconds": self.STABILITY_HOLD_SECONDS,
            "seed_warmup_min_distinct_epochs": (
                self.SEED_COLLECTION_MIN_DISTINCT_EPOCHS
            ),
            "seed_warmup_min_duration_seconds": (
                self.SEED_COLLECTION_MIN_DURATION_SECONDS
            ),
            "solver_min_distinct_epochs": self.SEED_SOLVER_MIN_DISTINCT_EPOCHS,
            "solver_min_duration_seconds": self.SEED_SOLVER_MIN_DURATION_SECONDS,
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

    async def start_cycle(self, project_id: int) -> None:
        if project_id in self.running_tasks:
            # AGRICA seed payloads may race and all ask to start the same project.
            # The existing task is authoritative; this is expected de-duplication,
            # not an operational warning.
            logger.debug("RoundRobin cycle already running for project %s", project_id)
            return
        if project_id not in self._sessions:
            raise ValueError(f"project {project_id} has no configured adjustment session")
        self.running_tasks[project_id] = asyncio.create_task(self._run_cycle(project_id))

    def _cors_api_request_sync(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        *,
        access_token: Optional[str] = None,
    ) -> Any:
        url = f"{self.web_cors_api_base_url}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"CORS API HTTP {response.status} for {path}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"CORS API HTTP {exc.code} for {path}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CORS API unavailable for {path}: {exc.reason}") from exc
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CORS API returned non-JSON data for {path}") from exc

    def _cors_token_sync(self, *, force_login: bool = False) -> str:
        if self._web_cors_access_token and not force_login:
            return self._web_cors_access_token
        if not self.web_cors_api_username or not self.web_cors_api_password:
            raise RuntimeError(
                "WEB CORS API credentials are not configured; set WEB_CORS_API_TOKEN or "
                "WEB_CORS_API_USERNAME/WEB_CORS_API_PASSWORD"
            )
        login_result = self._cors_api_request_sync(
            "POST",
            "/api/auth/login",
            {
                "username": self.web_cors_api_username,
                "password": self.web_cors_api_password,
            },
        )
        token = str((login_result or {}).get("access_token") or "").strip()
        if not token:
            raise RuntimeError("CORS login succeeded without an access_token")
        self._web_cors_access_token = token
        return token

    def _cors_configure_service_sync(self, serial: str, service_config: dict) -> dict:
        path = f"/api/devices/{urllib.parse.quote(str(serial), safe='')}/configure-service"
        token = self._cors_token_sync()
        try:
            result = self._cors_api_request_sync(
                "POST",
                path,
                service_config,
                access_token=token,
            )
        except RuntimeError as exc:
            if "HTTP 401" not in str(exc) or not self.web_cors_api_username:
                raise
            self._web_cors_access_token = ""
            result = self._cors_api_request_sync(
                "POST",
                path,
                service_config,
                access_token=self._cors_token_sync(force_login=True),
            )
        if (result or {}).get("status") != "service_config_sent_and_saved":
            raise RuntimeError(
                f"CORS configure-service did not confirm device {serial}: "
                f"status={(result or {}).get('status') or 'missing'}"
            )
        return result

    @staticmethod
    def _cors_service_config_with_server_mode(
        service_config: dict,
        server_id: Optional[int],
        *,
        on_demand: bool,
    ) -> dict:
        """Build the same mode payload as the existing CORS S1/S2 form."""

        cfg = copy.deepcopy(service_config or {})
        global_on_demand = bool(cfg.get("stream_on_demand", False))
        global_active = bool(cfg.get("stream_active", False))
        
        target_sids = [1, 2] if server_id is None else [server_id]
        for sid in target_sids:
            cfg[f"server{sid}_stream_on_demand"] = bool(on_demand)
            cfg[f"server{sid}_stream_active"] = not bool(on_demand)

        any_on_demand = False
        any_can_push = False
        for sid in (1, 2):
            if not bool(cfg.get(f"server{sid}_enabled", False)):
                continue
            sid_on_demand = bool(
                cfg.get(f"server{sid}_stream_on_demand", global_on_demand)
            )
            sid_active = bool(
                cfg.get(f"server{sid}_stream_active", global_active)
            )
            if not sid_on_demand:
                sid_active = True
                cfg[f"server{sid}_stream_active"] = True
            any_on_demand = any_on_demand or sid_on_demand
            any_can_push = any_can_push or (not sid_on_demand) or sid_active
        cfg["stream_on_demand"] = any_on_demand
        cfg["stream_active"] = any_can_push
        return cfg

    @staticmethod
    def _normalize_stream_host(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        parsed = urllib.parse.urlsplit(
            raw if "://" in raw else f"//{raw}",
            allow_fragments=False,
        )
        return str(parsed.hostname or raw).strip().lower().rstrip(".")

    def _find_cors_station_sync(
        self,
        mountpoint: str,
        selected_host: str,
        selected_serial: str = "",
        selected_server_id: Optional[int] = None,
    ) -> tuple[str, int, dict]:
        stations = self._cors_api_request_sync("GET", "/api/public/map-stations")
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        target = str(mountpoint or "").strip().casefold()
        target_host = self._normalize_stream_host(selected_host)
        target_serial = str(selected_serial or "").strip().casefold()
        try:
            target_server_id = (
                int(selected_server_id) if selected_server_id not in (None, "") else None
            )
        except (TypeError, ValueError):
            target_server_id = None
        matches = []
        for station in stations or []:
            if not isinstance(station, dict):
                continue
            cfg = station.get("service_config")
            if not isinstance(cfg, dict):
                continue
            station_serial = str(station.get("serial") or "").strip()
            if target_serial and station_serial.casefold() != target_serial:
                continue
            for sid in (1, 2):
                if target_server_id is not None and sid != target_server_id:
                    continue
                candidate = str(cfg.get(f"mountpoint{sid}") or "").strip().casefold()
                candidate_host = self._normalize_stream_host(
                    cfg.get(f"serverhost{sid}") or cfg.get(f"server{sid}_host")
                )
                if (
                    candidate
                    and candidate == target
                    and (not target_host or candidate_host == target_host)
                ):
                    matches.append((station_serial, sid, cfg))
        if len(matches) != 1 or not matches[0][0]:
            raise RuntimeError(
                f"WEB CORS host={selected_host!r} mountpoint={mountpoint!r} "
                f"serial={selected_serial!r} S{selected_server_id or '*'} matched "
                f"{len(matches)} streams; expected exactly one"
            )
        return matches[0]

    def _sleep_conflict_base_sync(self, serial: str) -> None:
        stations = self._cors_api_request_sync("GET", "/api/public/map-stations")
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        for station in stations or []:
            if not isinstance(station, dict):
                continue
            station_serial = str(station.get("serial") or "").strip()
            if station_serial.casefold() == serial.casefold():
                cfg = station.get("service_config")
                if not isinstance(cfg, dict):
                    return
                new_cfg = copy.deepcopy(cfg)
                new_cfg["server1_stream_on_demand"] = True
                new_cfg["server1_stream_active"] = False
                new_cfg["server2_stream_on_demand"] = True
                new_cfg["server2_stream_active"] = False
                new_cfg["stream_on_demand"] = True
                new_cfg["stream_active"] = False
                self._cors_api_request_sync(
                    "PUT",
                    f"/api/admin/devices/{station_serial}/service-config",
                    json=new_cfg,
                )
                return
        logger.warning(f"Could not find conflict base with serial {serial} to sleep")

    async def _toggle_cors_fixed_base(
        self,
        mountpoint: str,
        sleep: bool,
        selected_host: str = "",
        selected_serial: str = "",
        selected_server_id: Optional[int] = None,
        sleep_all_streams: bool = False,
    ) -> None:
        if not mountpoint:
            return
        snapshot_key = (
            self._normalize_stream_host(selected_host),
            str(mountpoint).strip().casefold(),
            str(selected_serial or "").strip().casefold(),
            int(selected_server_id) if selected_server_id not in (None, "") else 0,
        )
        if sleep:
            if snapshot_key in self._cors_fixed_base_snapshots:
                return
            serial, server_id, original = await asyncio.to_thread(
                self._find_cors_station_sync,
                mountpoint,
                selected_host,
                selected_serial,
                selected_server_id,
            )
            self._cors_fixed_base_snapshots[snapshot_key] = {
                "serial": serial,
                "server_id": server_id,
                "service_config": copy.deepcopy(original),
            }
            sleep_config = self._cors_service_config_with_server_mode(
                original,
                None if sleep_all_streams else server_id,
                on_demand=True,
            )
            await asyncio.to_thread(
                self._cors_configure_service_sync,
                serial,
                sleep_config,
            )
            logger.info(
                "WEB CORS configure-service moved fixed base %s host=%s serial=%s S%s to On-Demand/Sleep",
                mountpoint,
                selected_host,
                serial,
                server_id,
            )
            return

        snapshot = self._cors_fixed_base_snapshots.get(snapshot_key)
        if snapshot is None:
            logger.warning(
                "No WEB CORS stream-mode snapshot exists for host=%s fixed base=%s",
                selected_host,
                mountpoint,
            )
            return
        await asyncio.to_thread(
            self._cors_configure_service_sync,
            snapshot["serial"],
            copy.deepcopy(snapshot["service_config"]),
        )
        self._cors_fixed_base_snapshots.pop(snapshot_key, None)
        logger.info(
            "WEB CORS configure-service restored fixed base %s host=%s serial=%s S%s",
            mountpoint,
            selected_host,
            snapshot["serial"],
            snapshot["server_id"],
        )

    @staticmethod
    def _cors_station_is_online(station: dict) -> bool:
        """Interpret physical receiver availability from WEB CORS map data."""

        for key in ("is_online", "online", "device_online"):
            if isinstance(station.get(key), bool):
                return bool(station[key])
        status = str(station.get("status") or "").strip().casefold()
        if status:
            return status in {"online", "active", "connected", "streaming"}
        return bool(station.get("ntrip_connected"))

    def _cors_stream_is_managed_by_adjustment(
        self,
        serial: str,
        server_id: int,
    ) -> bool:
        target_serial = str(serial or "").strip().casefold()
        fixed_stream_is_managed = any(
            str(key[2] or "").strip().casefold() == target_serial
            and int(key[3] or 0) == int(server_id)
            for key in self._cors_fixed_base_snapshots
        )
        if fixed_stream_is_managed:
            return True
        return any(
            target_serial in session.get("seed_topology_managed_serials", set())
            for session in self._sessions.values()
        )

    @staticmethod
    def _cors_stream_mode(service_config: dict, server_id: int) -> tuple[bool, bool]:
        on_demand = bool(
            service_config.get(
                f"server{server_id}_stream_on_demand",
                service_config.get("stream_on_demand", False),
            )
        )
        active = bool(
            service_config.get(
                f"server{server_id}_stream_active",
                service_config.get("stream_active", False),
            )
        )
        return on_demand, active

    @staticmethod
    def _cors_failover_stream(
        stations: list[dict],
        *,
        station_name: str,
        serial: str,
        server_id: Any,
        host: str,
        mountpoint: str,
    ) -> Optional[tuple[dict, int]]:
        target_name = str(station_name or "").strip().casefold()
        target_serial = str(serial or "").strip().casefold()
        target_host = RoundRobinAdjustmentManager._normalize_stream_host(host)
        target_mountpoint = str(mountpoint or "").strip().casefold()
        try:
            target_server_id = int(server_id)
        except (TypeError, ValueError):
            target_server_id = 0
        matches: list[tuple[dict, int]] = []
        for station in stations:
            if not isinstance(station, dict):
                continue
            candidate_serial = str(station.get("serial") or "").strip().casefold()
            candidate_name = str(
                station.get("name") or station.get("code") or ""
            ).strip().casefold()
            if target_serial:
                if candidate_serial != target_serial:
                    continue
            elif target_name and candidate_name != target_name:
                continue
            config = station.get("service_config")
            if not isinstance(config, dict):
                continue
            for candidate_server_id in (1, 2):
                if target_server_id and candidate_server_id != target_server_id:
                    continue
                candidate_host = RoundRobinAdjustmentManager._normalize_stream_host(
                    config.get(f"serverhost{candidate_server_id}")
                    or config.get(f"server{candidate_server_id}_host")
                )
                candidate_mountpoint = str(
                    config.get(f"mountpoint{candidate_server_id}") or ""
                ).strip().casefold()
                if target_host and candidate_host != target_host:
                    continue
                if target_mountpoint and candidate_mountpoint != target_mountpoint:
                    continue
                matches.append((station, candidate_server_id))
        return matches[0] if len(matches) == 1 else None

    async def reconcile_cors_failover_pairs(
        self,
        clusters: list[dict],
        *,
        stations: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Keep each primary S1 / cross-station backup S2 pair mutually exclusive.

        Example: SinQuyen1/S1 normally owns mountpoint SinQuyen1.  If its
        receiver is offline, SinQuyen2/S2 is switched from On-Demand/Sleep to
        Always and feeds that same mountpoint.  Once SinQuyen1 is online again,
        the backup is stopped before S1 is restored.
        """

        if stations is None:
            stations = await asyncio.to_thread(
                self._cors_api_request_sync,
                "GET",
                "/api/public/map-stations",
            )
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        stations = [item for item in (stations or []) if isinstance(item, dict)]
        outcomes: list[dict] = []
        for cluster in clusters or []:
            if not isinstance(cluster, dict) or not cluster.get("backup_base_station"):
                continue
            primary = self._cors_failover_stream(
                stations,
                station_name=cluster.get("base_station"),
                serial=cluster.get("base_serial"),
                server_id=cluster.get("base_server_id"),
                host=cluster.get("base_stream_host"),
                mountpoint=cluster.get("base_stream_mp"),
            )
            backup = self._cors_failover_stream(
                stations,
                station_name=cluster.get("backup_base_station"),
                serial=cluster.get("backup_base_serial"),
                server_id=cluster.get("backup_base_server_id"),
                host=cluster.get("backup_base_stream_host"),
                mountpoint=cluster.get("backup_base_stream_mp"),
            )
            name = str(cluster.get("name") or "GNSS cluster")
            if primary is None or backup is None:
                outcomes.append({"cluster": name, "state": "INVALID_STREAM_IDENTITY"})
                continue
            primary_station, primary_server_id = primary
            backup_station, backup_server_id = backup
            primary_serial = str(primary_station.get("serial") or "").strip()
            backup_serial = str(backup_station.get("serial") or "").strip()
            primary_mp = str(cluster.get("base_stream_mp") or "").strip()
            backup_mp = str(cluster.get("backup_base_stream_mp") or "").strip()
            if not primary_mp or primary_mp.casefold() != backup_mp.casefold():
                outcomes.append({"cluster": name, "state": "MOUNTPOINT_MISMATCH"})
                continue
            if (
                self._cors_stream_is_managed_by_adjustment(primary_serial, primary_server_id)
                or self._cors_stream_is_managed_by_adjustment(backup_serial, backup_server_id)
            ):
                outcomes.append({"cluster": name, "state": "PAUSED_FOR_ADJUSTMENT"})
                continue

            primary_online = self._cors_station_is_online(primary_station)
            backup_online = self._cors_station_is_online(backup_station)
            pair_key = (
                primary_serial.casefold(),
                primary_server_id,
                backup_serial.casefold(),
                backup_server_id,
                primary_mp.casefold(),
            )

            if not primary_online and not backup_online:
                desired_state = "NO_SOURCE_BOTH_OFFLINE"
                self._cors_failover_last_state[pair_key] = desired_state
                outcomes.append({"cluster": name, "state": desired_state})
                continue

            if not primary_online:
                desired_state = "BACKUP_ACTIVE"
                backup_config = backup_station.get("service_config") or {}
                if self._cors_stream_mode(backup_config, backup_server_id) != (False, True):
                    enabled_config = self._cors_service_config_with_server_mode(
                        backup_config,
                        backup_server_id,
                        on_demand=False,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        backup_serial,
                        enabled_config,
                    )
                    backup_station["service_config"] = enabled_config
                    logger.warning(
                        "CORS automatic failover: %s offline; enabled %s/S%s -> %s",
                        cluster.get("base_station"),
                        cluster.get("backup_base_station"),
                        backup_server_id,
                        primary_mp,
                    )
            else:
                desired_state = "PRIMARY_ACTIVE"
                # Break-before-make on failback: never leave S1 and backup S2
                # publishing the same mountpoint concurrently.
                backup_config = backup_station.get("service_config") or {}
                if self._cors_stream_mode(backup_config, backup_server_id) != (True, False):
                    disabled_config = self._cors_service_config_with_server_mode(
                        backup_config,
                        backup_server_id,
                        on_demand=True,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        backup_serial,
                        disabled_config,
                    )
                    backup_station["service_config"] = disabled_config
                primary_config = primary_station.get("service_config") or {}
                if self._cors_stream_mode(primary_config, primary_server_id) != (False, True):
                    enabled_config = self._cors_service_config_with_server_mode(
                        primary_config,
                        primary_server_id,
                        on_demand=False,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        primary_serial,
                        enabled_config,
                    )
                    primary_station["service_config"] = enabled_config
                    logger.info(
                        "CORS automatic failback: restored %s/S%s -> %s and stopped %s/S%s",
                        cluster.get("base_station"),
                        primary_server_id,
                        primary_mp,
                        cluster.get("backup_base_station"),
                        backup_server_id,
                    )

            self._cors_failover_last_state[pair_key] = desired_state
            outcomes.append({
                "cluster": name,
                "state": desired_state,
                "primary_online": primary_online,
                "backup_online": backup_online,
                "mountpoint": primary_mp,
                "primary_station": str(cluster.get("base_station") or ""),
                "primary_serial": primary_serial,
                "primary_server_id": primary_server_id,
                "backup_station": str(cluster.get("backup_base_station") or ""),
                "backup_serial": backup_serial,
                "backup_server_id": backup_server_id,
            })
        return outcomes

    async def prepare_common_fixed_base_seed(self, project_id: int) -> list[dict]:
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
            candidates = self._fixed_base_candidates(cluster)
            selected_config = candidates[0].get("base_service_config") or {}
            return len(candidates) >= 2 or all(
                bool(selected_config.get(f"server{server_id}_enabled", False))
                and bool(str(selected_config.get(f"mountpoint{server_id}") or "").strip())
                for server_id in (1, 2)
            )

        if not any(has_dual_selected_stream(cluster) for cluster in session["clusters"]):
            for cluster in session["clusters"]:
                self._lock_fixed_base_candidate(
                    cluster,
                    self._fixed_base_candidates(cluster)[0],
                    "configured fixed base selected before seed collection",
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
                selected = candidates[0]
                # A mixed request may still contain a legacy single-stream
                # base alongside a dual-stream total cluster.
                if not has_dual_selected_stream(cluster):
                    self._lock_fixed_base_candidate(
                        cluster,
                        selected,
                        "configured fixed base selected before seed collection",
                    )
                    continue

                selected_match = self._cors_failover_stream(
                    stations,
                    station_name=selected.get("base_station"),
                    serial=selected.get("base_serial"),
                    server_id=selected.get("base_server_id"),
                    host=selected.get("base_stream_host"),
                    mountpoint=selected.get("base_stream_mp"),
                )
                if selected_match is None:
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: could not resolve "
                        "the selected CORS stream uniquely"
                    )

                selected_station, _ = selected_match
                selected_serial = str(selected_station.get("serial") or "").strip()
                selected_service_config = selected_station.get("service_config") or {}
                if not all(
                    bool(selected_service_config.get(f"server{server_id}_enabled", False))
                    and bool(str(selected_service_config.get(f"mountpoint{server_id}") or "").strip())
                    for server_id in (1, 2)
                ):
                    raise RuntimeError(
                        f"{cluster.get('name', cluster_index + 1)}: selected physical base "
                        f"{selected.get('base_station')} must have both S1 and S2 enabled "
                        "with explicit mountpoints before a common-base seed can start"
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
                    and bool(selected_service_config.get(f"server{server_id}_enabled", False))
                    and str(selected_service_config.get(f"mountpoint{server_id}") or "").strip()
                }
                physical_matches = []
                for station in stations:
                    serial = str(station.get("serial") or "").strip()
                    if not serial or serial.casefold() == selected_serial.casefold():
                        continue
                    service_config = station.get("service_config") or {}
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
                other = candidates[1] if len(candidates) >= 2 else {}
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
                            "service_config": copy.deepcopy(station.get("service_config") or {}),
                        },
                    )
                session.setdefault("seed_topology_managed_serials", set()).update({
                    selected_serial.casefold(),
                    other_serial.casefold(),
                })

                other_online = self._cors_station_is_online(other_station)
                if other_online:
                    other_disabled = self._cors_service_config_with_server_mode(
                        other_station.get("service_config") or {},
                        None,
                        on_demand=True,
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
                selected_enabled = self._cors_service_config_with_server_mode(
                    selected_original,
                    None,
                    on_demand=False,
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
                        f"selected {selected.get('base_station')} was forced onto both S1/S2; "
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
                # No pre-handover fragment or observation may enter the seed.
                for cluster in session["clusters"]:
                    cluster["observations"].clear()
                    self._clear_cluster_fragment_buffers(project_id, cluster)
                session["seed_started_monotonic"] = time.monotonic()
            return outcomes
        except Exception:
            await self.restore_common_fixed_base_topology(project_id)
            raise

    async def restore_common_fixed_base_topology(self, project_id: int) -> None:
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
        sleep_all_streams: bool = False,
    ) -> bool:
        """Reconnect every rover to the fixed BASE before the next rotation.

        Once a temporary pusher stops, rover NTRIP sessions disappear if the
        configured fixed stream remains asleep.  A later rover therefore cannot
        receive its SET BASE command.  Restore the original stream, require new
        solver-eligible BASE observations from every rover, confirm the next
        AICaster session, and only then put the fixed stream back to sleep.
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
        await self._toggle_cors_fixed_base(
            mountpoint,
            sleep=False,
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
                # A physical CORS base can publish the same RTCM source through
                # both S1 and S2 (for example SinQuyen2 -> SinQuyen2,SinQuyen1).
                # Temporary rover bases must replace both outputs as well;
                # otherwise clients attached to the reciprocal mountpoint keep
                # receiving the fixed base and never complete the handover.
                temporary_route_mountpoints: list[str] = []
                if configured_mountpoint:
                    temporary_route_mountpoints.append(str(configured_mountpoint).strip())
                selected_service_config = cluster.get("base_service_config") or {}
                normalized_route_host = str(route_host or "").strip().casefold()
                for server_id in (1, 2):
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
                
                # Tạm chuyển Base cố định sang On-Demand/Sleep trước khi quay
                # vòng các rover. Trạng thái gốc được phục hồi ở finally.
                base_stream_key = (
                    configured_base_host,
                    str(configured_mountpoint or ""),
                    configured_base_serial,
                    configured_base_server_id,
                )
                is_multi_mp = True
                if configured_mountpoint and base_stream_key not in suspended_bases:
                    await self._emit_progress(
                        project_id,
                        f"Đã khóa topology Base cố định {configured_mountpoint}; giữ stream hoạt động "
                        "qua preflight và chỉ Sleep ngay trước khi mở fanout BASE tạm.",
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
                        
                        cb_key = ("conflict", cb_serial)
                        if cb_key not in suspended_bases:
                            await self._emit_progress(
                                project_id,
                                f"Tắt trạm Base phụ thuộc {cb_name} (theo cấu hình Cụm Tổng) để tránh xung đột dữ liệu.",
                            )
                            suspended_bases.add(cb_key)
                            try:
                                await asyncio.to_thread(self._sleep_conflict_base_sync, cb_serial)
                                await asyncio.sleep(2.0)
                            except Exception as e:
                                logger.error(f"Failed to sleep conflict base {cb_name}: {e}")

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

                cluster_coverage_complete = False
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
                    mandatory_rotation_completed = False
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
                                record.source_diagnostic = (
                                    "Stationarity was lost after the solver window opened; "
                                    "the complete window was reset."
                                    if reason_key == "drift" else
                                    "Temporary-base source identity was not confirmed."
                                    if reason_key == "source" else
                                    "Stationarity was confirmed but minimum solver duration "
                                    "was not reached before timeout."
                                    if reason_key == "duration" else
                                    "Collection duration was sufficient, but the non-overlapping "
                                    "windows never satisfied mean/scatter/slope stationarity."
                                )
                            solver_start_index = len(records)
                            current_cluster["current_stable_window_index"] = None
                            self._clear_cluster_fragment_buffers(project_id, current_cluster)

                        def collection_status() -> dict:
                            monitoring = monitoring_records()
                            solver_eligible = eligible_attempt_records()

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
                                await self._toggle_cors_fixed_base(
                                    str(configured_mountpoint),
                                    sleep=False,
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
                                await self._toggle_cors_fixed_base(
                                    str(configured_mountpoint),
                                    sleep=True,
                                    selected_host=configured_base_host,
                                    sleep_all_streams=True,
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
                        cross_edges, cross_participants = current_solver_eligible_cross_coverage()
                        required_cross_edges = max(len(rovers) - 1, 1)
                        components = _graph_components(rovers, cross_edges)
                        cluster_coverage_complete = (
                            len(cross_edges) >= required_cross_edges
                            and len(components) == 1
                        )
                        if collected_count > 0:
                            mandatory_rotation_completed = True
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
                        # Always sleep ALL streams (S1 & S2) of the fixed base to ensure cross-base streams are also stopped
                        is_multi_mp = True
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
                                sleep_all_streams=is_multi_mp,
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
                    await self._toggle_cors_fixed_base(
                        mp,
                        sleep=False,
                        selected_host=selected_host,
                        **restore_identity_kwargs,
                    )
                    await self._emit_progress(
                        project_id,
                        f"Khôi phục Base cố định {mp} thành công; chế độ stream ban đầu đã được áp dụng.",
                    )
                except Exception as e:
                    logger.error("Failed to restore fixed base %s in finally block: %s", mp, e)
                    restore_errors.append(f"{mp}: {e}")
            try:
                await self.restore_common_fixed_base_topology(project_id)
            except Exception as e:
                logger.error(
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
            logger.error("Network adjustment failed for project %s: %s", project_id, exc)
            if self.error_callback:
                callback_result = self.error_callback(project_id, str(exc))
                if inspect.isawaitable(callback_result):
                    await callback_result

    async def _emit_progress(self, project_id: Optional[int], message: str) -> None:
        logger.info("[Round-Robin PHASE] %s", message)
        if project_id is None or not self.progress_callback:
            return
        try:
            callback_result = self.progress_callback(project_id, message)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning("Could not broadcast Round-Robin PHASE: %s", exc)

    async def _set_rover_as_temporary_base(
        self,
        rover_code: str,
        project_id: Optional[int] = None,
        route_host: Optional[str] = None,
        route_port: Optional[int] = None,
        route_mountpoint: Optional[str] = None,
        route_password: Optional[str] = None,
        on_collection_started: Optional[Callable[[], None]] = None,
        on_stable_collection_started: Optional[Callable[[], None]] = None,
        on_stable_collection_invalid: Optional[Callable[[str], None]] = None,
        on_collection_stopped: Optional[Callable[[], None]] = None,
        collection_status_callback: Optional[Callable[[], dict]] = None,
        expected_cross_rovers: Optional[set[str]] = None,
        base_llh_override: Optional[dict] = None,
        before_route_start: Optional[Callable[[], Any]] = None,
        before_rover_restore: Optional[Callable[[], Any]] = None,
        after_rover_restore: Optional[Callable[[], Any]] = None,
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        await self._emit_progress(
            project_id,
            f"{rover_code}: querying {self.caster_hosts} for an active AICaster client session.",
        )
        restore_llh = self.rover_llh_cache.get(rover_code) or {}
        llh = base_llh_override or restore_llh
        if not llh:
            raise _SafeRoverRotationSkip(
                f"No LLH cache found for {rover_code}; receiver was not changed."
            )

        client_info = await self._find_client_info(
            rover_code,
            project_id=project_id,
        )
        if not client_info:
            raise _SafeRoverRotationSkip(
                f"Could not find an active AICaster client session for {rover_code}; receiver was not changed."
            )
        mountpoint = client_info.get("Mountpoint", "")
        if not mountpoint:
            raise _SafeRoverRotationSkip(
                f"AICaster client session for {rover_code} has no mountpoint; receiver was not changed."
            )
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: matched AICaster "
                f"{client_info.get('CasterHost')}:{client_info.get('CasterPort')} "
                f"username={client_info.get('Username')} "
                f"receiverID={client_info.get('receiverID')} mountpoint={mountpoint}."
            ),
        )

        commands = self._build_unicore_base_config(
            setup_method="FIXED",
            lat=llh["lat"],
            lon=llh["lon"],
            alt=llh["alt"],
            ecef_xyz=llh.get("ecef_xyz"),
        )
        rover_commands = self._build_unicore_rover_config(
            restore_undulation=restore_llh.get("undulation")
        )
        preflight_command = rover_commands[0]
        preflight_text = preflight_command.decode("ascii", errors="replace").strip()
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: preflight {preflight_text}; BASE mode is blocked until "
                "the same MQTT topic confirms the command and receiver response."
            ),
        )
        preflight_verified = False
        for preflight_attempt in range(1, self.PREFLIGHT_CONNECTION_ATTEMPTS + 1):
            preflight_verified = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                [preflight_command],
                password=self.control_password,
                caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"),
                ack_station_code=rover_code,
            )
            if preflight_verified:
                break
            if preflight_attempt < self.PREFLIGHT_CONNECTION_ATTEMPTS:
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: preflight connection failed; opening a fresh "
                        "SET connection and retrying before BASE mode."
                    ),
                )
                await asyncio.sleep(1)
        if not preflight_verified:
            detail = self._last_set_error or "no verified MQTT receiver response"
            raise _SafeRoverRotationSkip(
                f"Refusing to set {rover_code} as BASE because ROVER recovery "
                f"preflight was not verified: {detail}"
            )

        route_started = False
        collection_started = False
        restore_error: Optional[str] = None
        target_route_host = route_host or self.source_host
        target_route_port = int(route_port or self.source_port)
        target_route_mountpoint = route_mountpoint or f"{rover_code}_BASE"
        target_route_password = self.source_password if route_password is None else route_password
        operation_error: Optional[Exception] = None
        if before_route_start:
            try:
                before_route_result = before_route_start()
                if inspect.isawaitable(before_route_result):
                    await before_route_result
            except Exception as route_prepare_exc:
                if before_rover_restore:
                    recovery_result = before_rover_restore()
                    if inspect.isawaitable(recovery_result):
                        await recovery_result
                raise _SafeRoverRotationSkip(
                    f"{rover_code}: could not stop the fixed BASE immediately before "
                    f"temporary fanout; receiver remains ROVER: {route_prepare_exc}"
                ) from route_prepare_exc
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: priming MQTT-to-NTRIP fanout "
                f"{target_route_host}:{target_route_port}/{target_route_mountpoint} "
                "before BASE mode to minimize the correction-source handover gap."
            ),
        )
        try:
            await self._start_ntrip_route(
                rover_code,
                target_route_mountpoint,
                host=target_route_host,
                port=target_route_port,
                password=target_route_password,
            )
            route_started = True
        except Exception as route_exc:
            if before_rover_restore:
                recovery_result = before_rover_restore()
                if inspect.isawaitable(recovery_result):
                    await recovery_result
            raise _SafeRoverRotationSkip(
                f"{rover_code}: could not prime every temporary SOURCE target; "
                f"receiver remains ROVER: {route_exc}"
            ) from route_exc

        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: sending SET BASE to {client_info.get('CasterHost')}:"
                f"{client_info.get('CasterPort')} (HTTP Basic auth "
                f"{'enabled' if self.control_password else 'disabled'})."
            ),
        )
        try:
            base_verified = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                commands,
                password=self.control_password,
                caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"),
                ack_station_code=rover_code,
            )
        except Exception:
            await self._stop_ntrip_route(rover_code)
            route_started = False
            raise
        if not base_verified:
            detail = self._last_set_error or "AICaster returned no rejection detail"
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: SET BASE was not fully verified; sending an "
                    "immediate ROVER recovery sequence before aborting."
                ),
            )
            try:
                await self._stop_ntrip_route(rover_code)
            finally:
                route_started = False
            try:
                await self._restore_rover_output_sequence(
                    rover_code=rover_code,
                    mountpoint=mountpoint,
                    client_info=client_info,
                    commands=rover_commands,
                    project_id=project_id,
                )
                recovered = True
            except Exception as recovery_exc:
                recovered = False
                recovery_detail = str(recovery_exc) or "no verified MQTT recovery ACK"
                logger.critical(
                    "Emergency ROVER recovery was not verified for %s: %s",
                    rover_code,
                    recovery_detail,
                )
                detail = f"{detail}; ROVER recovery also unverified: {recovery_detail}"
            error_message = f"AICaster rejected the SET command for {rover_code}: {detail}"
            if recovered:
                raise _SafeRoverRotationSkip(error_message)
            raise RuntimeError(error_message)
        warning_suffix = ""
        if self._last_set_warnings:
            warning_suffix = " Optional RTCM fallbacks: " + "; ".join(self._last_set_warnings)
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: SET BASE accepted; response="
                f"{self._last_set_response or '200 OK'}.{warning_suffix}"
            ),
        )

        try:
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: BASE profile acknowledged; waiting for every primed "
                    "SOURCE target to forward its first verified RTCM3 frame."
                ),
            )
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: verifying MQTT-to-NTRIP fanout "
                    f"{target_route_host}:{target_route_port}/{target_route_mountpoint}."
                ),
            )
            for route_attempt in range(1, self.RTCM_ROUTE_RECOVERY_ATTEMPTS + 1):
                try:
                    if not route_started:
                        await self._start_ntrip_route(
                            rover_code,
                            target_route_mountpoint,
                            host=target_route_host,
                            port=target_route_port,
                            password=target_route_password,
                        )
                        route_started = True
                    await self._wait_for_ntrip_route(rover_code, timeout=25.0)
                    break
                except Exception as route_exc:
                    is_missing_rtcm = "no valid rtcm3 frame" in str(route_exc).casefold()
                    if (
                        not is_missing_rtcm
                        or route_attempt >= self.RTCM_ROUTE_RECOVERY_ATTEMPTS
                    ):
                        raise
                    # A receiver may ACK output commands while retaining a stale
                    # rover log configuration on COM2. Reapply the clean, minimal
                    # base profile over a new SET connection and prove the output
                    # again before abandoning this rotation.
                    try:
                        await self._stop_ntrip_route(rover_code)
                        route_started = False
                    except Exception as stop_exc:
                        logger.warning(
                            "Could not stop failed RTCM route for %s before recovery: %s",
                            rover_code,
                            stop_exc,
                        )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: receiver ACKed BASE commands but emitted no "
                            "RTCM3; clearing stale COM2 logs and reapplying the minimal "
                            "UM980 base profile on a fresh SET connection."
                        ),
                    )
                    reapplied = await self._send_set_command(
                        mountpoint,
                        client_info.get("Username", rover_code),
                        client_info.get("receiverID", ""),
                        commands,
                        password=self.control_password,
                        caster_host=client_info.get("CasterHost"),
                        caster_port=client_info.get("CasterPort"),
                        ack_station_code=rover_code,
                    )
                    if not reapplied:
                        raise RuntimeError(
                            f"{rover_code}: RTCM recovery profile was not verified: "
                            f"{self._last_set_error or 'no receiver ACK'}"
                        ) from route_exc
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: recovered BASE profile acknowledged; retrying "
                            "the route immediately."
                        ),
                    )
            await self._reset_cross_rovers_for_temporary_base(
                temporary_base_code=rover_code,
                target_rovers=expected_cross_rovers,
                project_id=project_id,
            )
            if on_collection_started:
                on_collection_started()
            collection_started = True
            if collection_status_callback is None:
                # Compatibility path for callers that cannot inspect incoming
                # AGRICA observations. Production injects a status callback and
                # uses the verified, adaptive handover path below.
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: RTCM route is live; waiting "
                        f"{self.CROSS_BASE_SETTLE_SECONDS}s for rover correction sources "
                        "to report the temporary base_llh. Transition observations are rejected."
                    ),
                )
                await asyncio.sleep(self.CROSS_BASE_SETTLE_SECONDS)
                if on_stable_collection_started:
                    on_stable_collection_started()
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: NTRIP SOURCE accepted and first RTCM frame "
                        f"forwarded; collecting cross-baselines for "
                        f"{self.CROSS_BASE_STABLE_COLLECTION_SECONDS}s."
                    ),
                )
                await asyncio.sleep(self.CROSS_BASE_STABLE_COLLECTION_SECONDS)
            else:
                expected = set(expected_cross_rovers or ())
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: RTCM route is live; waiting up to "
                        f"{self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS}s for AGRICA to "
                        "verify the temporary base and a solver-eligible baseline."
                    ),
                )
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS
                latest_status: dict = {}
                handover_verified = False
                verified_participants: set[str] = set()
                partial_handover_started_at: Optional[float] = None
                while True:
                    latest_status = dict(collection_status_callback() or {})
                    participants = set(latest_status.get("rover_names") or ())
                    sample_counts_by_rover = {
                        str(name): int(count)
                        for name, count in (
                            latest_status.get("sample_counts_by_rover") or {}
                        ).items()
                    }
                    # Compatibility callbacks may not expose per-rover counts.
                    # Production does, and requires several distinct GNSS epochs
                    # before declaring the RTCM handover stable.
                    stable_participants = (
                        {
                            name
                            for name, count in sample_counts_by_rover.items()
                            if count >= self.CROSS_BASE_HANDOVER_MIN_SAMPLES
                        }
                        if sample_counts_by_rover
                        else participants
                    )
                    sample_count = int(latest_status.get("sample_count") or 0)
                    verified_participants = (
                        stable_participants & expected
                        if expected else set(stable_participants)
                    )
                    # One stable rover is sufficient to prove that this
                    # temporary RTCM source is live. Requiring every configured
                    # rover made one silent receiver invalidate useful edges
                    # from all the other receivers. Overall solvability is
                    # enforced later by the connected cross-baseline graph. A
                    # short grace window still lets other healthy rovers join
                    # before the stability target set is frozen.
                    now = loop.time()
                    if sample_count > 0 and verified_participants:
                        if partial_handover_started_at is None:
                            partial_handover_started_at = now
                        all_expected_verified = (
                            not expected or expected.issubset(stable_participants)
                        )
                        handover_verified = all_expected_verified or (
                            now - partial_handover_started_at
                            >= self.CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS
                        )
                    if handover_verified or loop.time() >= deadline:
                        break
                    await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

                participants = set(latest_status.get("rover_names") or ())
                if handover_verified:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: temporary-base handover verified from "
                            f"{', '.join(sorted(verified_participants))} after at least "
                            f"{self.CROSS_BASE_HANDOVER_MIN_SAMPLES} distinct epochs each; waiting "
                            f"{self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS}s for the new FIXED "
                            "solution to settle before opening the solver window."
                        ),
                    )
                    unavailable_targets = sorted(expected - verified_participants)
                    if unavailable_targets:
                        await self._emit_progress(
                            project_id,
                            (
                                f"{rover_code}: continuing with partial live coverage; "
                                f"no verified handover from {', '.join(unavailable_targets)}. "
                                "These rovers will not invalidate the useful cross-baselines; "
                                "the final connected-graph check remains mandatory."
                            ),
                        )
                    await asyncio.sleep(self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS)
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: monitoring baseline mean, scatter and slope in two "
                            f"{self.STABILITY_WINDOW_SECONDS}-second windows "
                            f"(at least {self.STABILITY_MIN_SAMPLES_PER_WINDOW} epochs each); require "
                            f"|dN|/|dE| <= {self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.1f} mm, "
                            f"|dU| <= {self.STABILITY_UP_COMPONENT_LIMIT_M * 1000:.1f} mm "
                            f"with STD <= {self.STABILITY_HORIZONTAL_STD_LIMIT_M * 1000:.0f}/"
                            f"{self.STABILITY_UP_STD_LIMIT_M * 1000:.0f} mm (horizontal/up); "
                            "fast/slow EWMA is an early transition detector only; "
                            f"continuously for {self.STABILITY_HOLD_SECONDS}s before opening "
                            "the solver window."
                        ),
                    )
                    stability_targets = set(verified_participants)
                    solver_window_open = False
                    reset_count = 0
                    drift_failure_counts = {
                        name: 0 for name in stability_targets
                    }
                    drift_evaluation_epochs = {
                        name: None for name in stability_targets
                    }
                    stability_deadline = (
                        loop.time() + self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS
                    )
                    while True:
                        latest_status = dict(collection_status_callback() or {})
                        rolling = {
                            str(name): dict(diagnostic or {})
                            for name, diagnostic in (
                                latest_status.get("rolling_stability_by_rover") or {}
                            ).items()
                        }
                        now = loop.time()
                        stable_held = bool(stability_targets) and all(
                            rolling.get(name, {}).get("stable") is True
                            and not rolling.get(name, {}).get(
                                "ewma_transition_detected", False
                            )
                            and int(
                                rolling.get(name, {}).get("stable_run_seconds") or 0
                            ) >= self.STABILITY_HOLD_SECONDS
                            for name in stability_targets
                        )

                        if solver_window_open:
                            aborting_now = set()
                            for name in stability_targets:
                                diagnostic = rolling.get(name, {})
                                latest_epoch = diagnostic.get("latest_epoch")
                                abort_exceeded = _rolling_drift_exceeds_abort_limits(
                                    diagnostic,
                                    horizontal_component_limit_m=(
                                        self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                                    ),
                                    up_component_limit_m=(
                                        self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M
                                    ),
                                )
                                if abort_exceeded:
                                    aborting_now.add(name)
                                if (
                                    latest_epoch is not None
                                    and latest_epoch
                                    != drift_evaluation_epochs.get(name)
                                ):
                                    drift_evaluation_epochs[name] = latest_epoch
                                    drift_failure_counts[name] = (
                                        int(drift_failure_counts.get(name) or 0) + 1
                                        if abort_exceeded else 0
                                    )
                            aborting_repeatedly = {
                                name
                                for name, count in drift_failure_counts.items()
                                if count >= self.STABILITY_ABORT_CONSECUTIVE_EPOCHS
                            }
                            if aborting_repeatedly:
                                reset_count += 1
                                drift_details = []
                                for name in sorted(aborting_repeatedly):
                                    delta = rolling.get(name, {}).get("delta_neu_m")
                                    if delta and len(delta) == 3:
                                        drift_details.append(
                                            f"{name} dN/E/U="
                                            f"{float(delta[0]) * 1000:.1f}/"
                                            f"{float(delta[1]) * 1000:.1f}/"
                                            f"{float(delta[2]) * 1000:.1f} mm"
                                        )
                                if on_stable_collection_invalid:
                                    on_stable_collection_invalid("drift")
                                solver_window_open = False
                                drift_failure_counts = {
                                    name: 0 for name in stability_targets
                                }
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: rolling-window or EWMA transition diagnostic exceeded the "
                                        f"{self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.0f}/"
                                        f"{self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M * 1000:.0f} mm "
                                        f"abort envelope for {self.STABILITY_ABORT_CONSECUTIVE_EPOCHS} "
                                        "consecutive receiver epochs; "
                                        f"quarantined solver window #{reset_count} and reset "
                                        "the stability hold timer. "
                                        f"{'; '.join(drift_details) or 'rolling threshold exceeded'}."
                                    ),
                                )
                            else:
                                solver_counts = {
                                    str(name): int(count)
                                    for name, count in (
                                        latest_status.get(
                                            "solver_sample_counts_by_rover"
                                        ) or {}
                                    ).items()
                                }
                                solver_durations = {
                                    str(name): int(duration)
                                    for name, duration in (
                                        latest_status.get(
                                            "solver_durations_by_rover_seconds"
                                        ) or {}
                                    ).items()
                                }
                                solver_ready = {
                                    name
                                    for name in stability_targets
                                    if solver_counts.get(name, 0)
                                    >= self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS
                                    and solver_durations.get(name, 0)
                                    >= self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
                                }
                                if (
                                    not aborting_now
                                    and stability_targets.issubset(solver_ready)
                                ):
                                    await self._emit_progress(
                                        project_id,
                                        (
                                            f"{rover_code}: stationary solver window complete "
                                            f"for {', '.join(sorted(stability_targets))}; "
                                            f"at least {self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS} "
                                            f"epochs and {self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS}s "
                                            "per rover."
                                        ),
                                    )
                                    break
                        elif stable_held:
                            if on_stable_collection_started:
                                on_stable_collection_started()
                            solver_window_open = True
                            # The stability timeout governs how long we wait to
                            # open a clean window.  Once it opens, always grant
                            # the full mandatory solver duration; otherwise a
                            # window opened near the deadline is quarantined
                            # before it can possibly accumulate enough epochs.
                            stability_deadline = max(
                                stability_deadline,
                                now
                                + self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
                                + self.CROSS_BASE_STATUS_POLL_SECONDS * 2,
                            )
                            drift_failure_counts = {
                                name: 0 for name in stability_targets
                            }
                            drift_evaluation_epochs = {
                                name: rolling.get(name, {}).get("latest_epoch")
                                for name in stability_targets
                            }
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: rolling mean/scatter/slope remained stationary for "
                                    f"{self.STABILITY_HOLD_SECONDS}s; solver window opened. "
                                    f"Collecting at least {self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS}s."
                                ),
                            )

                        if now >= stability_deadline:
                            if on_stable_collection_invalid:
                                on_stable_collection_invalid(
                                    "duration" if solver_window_open else "stability"
                                )
                            raise RuntimeError(
                                f"{rover_code}: no complete stationary solver window within "
                                f"{self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS}s; "
                                f"rolling threshold N/E={self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.1f} mm, "
                                f"U={self.STABILITY_UP_COMPONENT_LIMIT_M * 1000:.1f} mm; "
                                f"STD horizontal/up={self.STABILITY_HORIZONTAL_STD_LIMIT_M * 1000:.0f}/"
                                f"{self.STABILITY_UP_STD_LIMIT_M * 1000:.0f} mm"
                            )
                        await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)
                else:
                    missing = sorted(expected - participants)
                    unstable = sorted(expected - stable_participants)
                    handover_counts = {
                        name: sample_counts_by_rover.get(name, 0)
                        for name in sorted(expected or participants)
                    }
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: temporary-base handover was not fully "
                            f"verified before timeout; seen rovers="
                            f"{', '.join(sorted(participants)) or 'none'}, missing="
                            f"{', '.join(missing) or 'none'}, below "
                            f"{self.CROSS_BASE_HANDOVER_MIN_SAMPLES}-epoch requirement="
                            f"{', '.join(unstable) or 'none'}, epoch counts="
                            f"{handover_counts}. The rotation will be "
                            "retried after safe ROVER restore."
                        ),
                    )
                    if on_stable_collection_invalid:
                        on_stable_collection_invalid("source")
                    raise RuntimeError(
                        f"{rover_code}: temporary-base handover was not verified"
                    )
        except Exception as exc:
            operation_error = exc
        finally:
            if collection_started and on_collection_stopped:
                on_collection_stopped()
            if collection_started:
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: cross-baseline collection window closed.",
                )
            if route_started:
                try:
                    await self._stop_ntrip_route(rover_code)
                except Exception as exc:
                    logger.error("Could not stop temporary NTRIP route for %s: %s", rover_code, exc)

            if before_rover_restore:
                try:
                    refreshed_client = before_rover_restore()
                    if inspect.isawaitable(refreshed_client):
                        refreshed_client = await refreshed_client
                    if isinstance(refreshed_client, dict) and refreshed_client:
                        client_info = refreshed_client
                        refreshed_mountpoint = str(
                            refreshed_client.get("Mountpoint") or ""
                        ).strip()
                        if refreshed_mountpoint:
                            mountpoint = refreshed_mountpoint
                except Exception as wake_exc:
                    restore_error = (
                        f"Could not restore fixed BASE before returning {rover_code} "
                        f"to ROVER: {str(wake_exc) or wake_exc.__class__.__name__}"
                    )
                    logger.error(restore_error)

            # A temporary base must never be left in BASE mode. Restore the
            # receiver without FRESET so its persistent NTRIP setup and baud
            # rate remain intact.
            await self._emit_progress(
                project_id,
                f"{rover_code}: sending SET ROVER to restore normal AGRICA operation.",
            )
            if restore_error:
                restored = False
            else:
                try:
                    await self._restore_rover_output_sequence(
                        rover_code=rover_code,
                        mountpoint=mountpoint,
                        client_info=client_info,
                        commands=rover_commands,
                        project_id=project_id,
                    )
                    restored = True
                except Exception as restore_exc:
                    restored = False
                    restore_error = (
                        f"Could not restore {rover_code} to ROVER mode: "
                        f"{str(restore_exc) or restore_exc.__class__.__name__}"
                    )
                    logger.error(restore_error)
            if restored:
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: SET ROVER accepted; receiver restored.",
                )
                if after_rover_restore:
                    try:
                        after_result = after_rover_restore()
                        if inspect.isawaitable(after_result):
                            await after_result
                    except Exception as sleep_exc:
                        restore_error = (
                            f"{rover_code} is back in ROVER mode, but fixed BASE could "
                            f"not return to Sleep: "
                            f"{str(sleep_exc) or sleep_exc.__class__.__name__}"
                        )
                        logger.error(restore_error)
            await asyncio.sleep(5)
        if restore_error:
            raise RuntimeError(restore_error) from operation_error
        if operation_error:
            raise _SafeRoverRotationSkip(
                f"{rover_code}: temporary-base operation failed after verified ROVER restore: {operation_error}"
            ) from operation_error

    async def _start_ntrip_route(
        self,
        station_code: str,
        mountpoint: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
    ) -> None:
        target_host = host or self.source_host
        target_port = int(port or self.source_port)
        target_password = self.source_password if password is None else password
        if self.route_start_callback:
            result = self.route_start_callback(
                station_code,
                target_host,
                target_port,
                mountpoint,
                target_password,
            )
            if inspect.isawaitable(result):
                result = await result
            if result is False:
                raise ConnectionError(f"NTRIP SOURCE route was rejected for {station_code}")
            return

        # Compatibility fallback for deployments where route control is handled
        # by a separate MQTT consumer.  In-process deployments inject an async
        # callback and wait for the SOURCE handshake before collecting.
        route_payload = {
            "station_code": station_code,
            "host": target_host,
            "port": target_port,
            "mountpoint": mountpoint,
            "password": target_password,
        }
        self.mqtt_client.publish("command/ntrip/route/start", json.dumps(route_payload))

    async def _wait_for_ntrip_route(
        self,
        station_code: str,
        timeout: float = 25.0,
    ) -> None:
        if not self.route_wait_callback:
            return
        result = self.route_wait_callback(station_code, timeout)
        if inspect.isawaitable(result):
            await result

    async def _stop_ntrip_route(self, station_code: str) -> None:
        if self.route_stop_callback:
            result = self.route_stop_callback(station_code)
            if inspect.isawaitable(result):
                await result
            return
        self.mqtt_client.publish(
            "command/ntrip/route/stop",
            json.dumps({"station_code": station_code}),
        )

    @staticmethod
    def _cluster_base_llh(cluster: dict) -> tuple[float, float, float]:
        selected = cluster.get("selected_fixed_base_candidate")
        source = selected if isinstance(selected, dict) else cluster
        try:
            llh = (
                float(source["base_lat"]),
                float(source["base_lon"]),
                float(source.get("base_alt") or 0.0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("cluster is missing a valid fixed-base coordinate") from exc
        if not _is_usable_llh(llh):
            raise ValueError("cluster fixed-base coordinate is invalid")
        return llh

    @staticmethod
    def _fixed_base_candidates(cluster: dict) -> list[dict]:
        configured = [
            dict(candidate)
            for candidate in cluster.get("fixed_base_candidates", ())
            if isinstance(candidate, dict)
        ]
        if configured:
            return configured
        return [{
            "role": "primary",
            "base_station": cluster.get("base_station") or "BASE",
            "base_lat": cluster.get("base_lat"),
            "base_lon": cluster.get("base_lon"),
            "base_alt": cluster.get("base_alt") or 0.0,
            "base_stream": cluster.get("base_stream"),
            "base_stream_host": cluster.get("base_stream_host"),
            "base_stream_port": cluster.get("base_stream_port"),
            "base_stream_mp": cluster.get("base_stream_mp"),
            "base_service_config": cluster.get("base_service_config") or {},
            "base_serial": cluster.get("base_serial") or "",
            "base_server_id": cluster.get("base_server_id"),
        }]

    @staticmethod
    def _lock_fixed_base_candidate(
        cluster: dict,
        candidate: dict,
        diagnostic: str,
    ) -> None:
        locked = copy.deepcopy(candidate)
        cluster["selected_fixed_base_candidate"] = locked
        cluster["fixed_base_selection_diagnostic"] = str(diagnostic)
        for key in (
            "base_station",
            "base_lat",
            "base_lon",
            "base_alt",
            "base_stream",
            "base_stream_host",
            "base_stream_port",
            "base_stream_mp",
            "base_service_config",
            "base_serial",
            "base_server_id",
        ):
            if key in locked:
                cluster[key] = copy.deepcopy(locked[key])

    def _identify_fixed_base_candidate(
        self,
        cluster: dict,
        observation: Any,
    ) -> tuple[Optional[dict], str]:
        candidates = self._fixed_base_candidates(cluster)
        if len(candidates) == 1:
            return candidates[0], "only one fixed-base candidate is configured"

        reported = getattr(observation, "base_llh", None)
        ranked: list[tuple[float, dict, str]] = []
        if _is_usable_llh(reported):
            for candidate in candidates:
                candidate_llh = (
                    float(candidate["base_lat"]),
                    float(candidate["base_lon"]),
                    float(candidate.get("base_alt") or 0.0),
                )
                separation = _llh_horizontal_distance_m(reported, candidate_llh)
                ranked.append((separation, candidate, "AGRICA base_llh"))
        else:
            rover_llh = getattr(observation, "rover_llh", None)
            baseline_neu = getattr(observation, "baseline_neu", None)
            if not rover_llh or not baseline_neu:
                return None, (
                    "cannot choose primary/backup fixed base: AGRICA base_llh is missing "
                    "and rover geometry is unavailable"
                )
            baseline_length = math.hypot(baseline_neu[0], baseline_neu[1])
            for candidate in candidates:
                candidate_llh = (
                    float(candidate["base_lat"]),
                    float(candidate["base_lon"]),
                    float(candidate.get("base_alt") or 0.0),
                )
                expected_length = _llh_horizontal_distance_m(rover_llh, candidate_llh)
                ranked.append((
                    abs(expected_length - baseline_length),
                    candidate,
                    "baseline geometry",
                ))

        ranked.sort(key=lambda item: item[0])
        best_error, best, evidence = ranked[0]
        if best_error > self.BASE_IDENTITY_TOLERANCE_M:
            return None, (
                f"no configured fixed-base candidate matches {evidence}; "
                f"best={best.get('base_station')} error={best_error:.2f} m"
            )
        if len(ranked) > 1 and ranked[1][0] - best_error < 1.0:
            return None, (
                "fixed-base candidate is ambiguous; primary and backup match within "
                f"1 m using {evidence}"
            )
        return best, (
            f"selected {best.get('role', 'fixed')} fixed base "
            f"{best.get('base_station')} using {evidence} (error {best_error:.2f} m)"
        )

    @staticmethod
    def _baseline_ecef(observation: Any, base_llh: tuple[float, float, float]) -> tuple[float, float, float]:
        return _neu_to_ecef_delta(
            base_llh[0],
            base_llh[1],
            observation.baseline_neu[0],
            observation.baseline_neu[1],
            observation.baseline_neu[2],
        )

    def _build_cluster_result(self, project_id: int, cluster_index: int, cluster: dict) -> dict:
        """Adjust one network using exactly one weighted-mean value per edge."""

        try:
            from backend.processors.gnss_adjustment.models import Baseline, Network, Point
            from backend.processors.gnss_adjustment.solver import adjust_network
            from backend.processors.gnss_adjustment.transforms import (
                covariance_standard_deviation,
                ecef_to_enu_rotation,
                ecef_point_covariance_to_enu,
                neu_standard_deviation_to_ecef_covariance,
            )
            from backend.processors.gnss_adjustment.runtime import _llh_to_ecef
        except ModuleNotFoundError:
            from processors.gnss_adjustment.models import Baseline, Network, Point
            from processors.gnss_adjustment.solver import adjust_network
            from processors.gnss_adjustment.transforms import (
                covariance_standard_deviation,
                ecef_to_enu_rotation,
                ecef_point_covariance_to_enu,
                neu_standard_deviation_to_ecef_covariance,
            )
            from processors.gnss_adjustment.runtime import _llh_to_ecef

        std_warning_threshold = _BASELINE_STD_REJECTION_THRESHOLD_M
        raw_ecef_tolerance = 0.05
        high_std_fallback_min_samples = 3
        high_std_fallback_max_repeatability_m = 0.05
        vector_outlier_min_samples = 5
        vector_outlier_absolute_floor_m = 0.25
        vector_outlier_sigma_multiplier = 8.0
        fixed_base_llh = self._cluster_base_llh(cluster)
        fixed_base_ecef = _llh_to_ecef(*fixed_base_llh)
        live_records: List[_CollectedObservation] = cluster["observations"]
        seed_snapshot = cluster.get("fixed_base_seed_records_snapshot")
        if isinstance(seed_snapshot, list):
            seed_cutoff = int(cluster.get("fixed_base_seed_cutoff_index", len(seed_snapshot)))
            if seed_cutoff < 0 or seed_cutoff > len(live_records):
                raise ValueError(
                    "fixed-base seed cutoff is outside the collected observation range"
                )
            # Use the exact seed state that produced the frozen rover coordinates.
            # Post-seed records remain present for transition audit and cross-edge
            # solving, but can never rewrite or invalidate this authoritative seed.
            records: List[_CollectedObservation] = [
                *seed_snapshot,
                *live_records[seed_cutoff:],
            ]
        else:
            # Backward compatibility for direct/unit callers that build a result
            # without running the production freeze step first.
            records = live_records

        configured_names = dict(zip(cluster["stations"], cluster["rovers"], strict=True))
        station_names = {
            station_id: next(
                (
                    record.observation.rover_name
                    for record in records
                    if record.observation.station_id == station_id
                ),
                configured_names[station_id],
            )
            for station_id in cluster["stations"]
        }
        if len(set(station_names.values())) != len(station_names):
            raise ValueError("duplicate rover name in adjustment cluster")

        def filter_vector_outliers(samples: List[dict]) -> tuple[List[dict], List[dict]]:
            """Reject isolated vector jumps per geometric edge without trusting reported STD."""

            groups: Dict[tuple[str, str], List[tuple[dict, np.ndarray]]] = {}
            for sample in samples:
                edge, vector, _direction = _canonical_baseline(
                    sample["from"], sample["to"], sample["delta"]
                )
                groups.setdefault((edge[0], edge[1]), []).append(
                    (sample, np.asarray(vector, dtype=float))
                )

            rejected_ids: set[int] = set()
            diagnostics: List[dict] = []
            for (from_name, to_name), rows in groups.items():
                if len(rows) < vector_outlier_min_samples:
                    for sample, _vector in rows:
                        diagnostics.append({
                            "raw_index": sample.get("raw_index"),
                            "vector_filter_status": "NOT_EVALUATED_INSUFFICIENT_GROUP",
                        })
                    continue
                vectors = np.vstack([vector for _sample, vector in rows])
                center = np.median(vectors, axis=0)
                deviations = np.linalg.norm(vectors - center, axis=1)
                median_deviation = float(np.median(deviations))
                mad = float(np.median(np.abs(deviations - median_deviation)))
                robust_sigma = 1.4826 * mad
                threshold = max(
                    vector_outlier_absolute_floor_m,
                    median_deviation + vector_outlier_sigma_multiplier * robust_sigma,
                )
                for (sample, _vector), deviation in zip(rows, deviations, strict=True):
                    is_outlier = float(deviation) > threshold
                    diagnostics.append({
                        "raw_index": sample.get("raw_index"),
                        "vector_deviation_from_edge_m": float(deviation),
                        "vector_outlier_threshold_m": threshold,
                        "vector_filter_status": "EVALUATED_OUTLIER" if is_outlier else "EVALUATED_INLIER",
                    })
                    if is_outlier:
                        rejected_ids.add(id(sample))
            return [sample for sample in samples if id(sample) not in rejected_ids], diagnostics

        def filter_position_type_mixes(
            samples: List[dict],
        ) -> tuple[List[dict], List[dict]]:
            """Prefer RTK Fixed (4) per edge; use Input Fixed (7) only as fallback."""

            groups: Dict[tuple[str, str], List[dict]] = {}
            for sample in samples:
                edge, _vector, _direction = _canonical_baseline(
                    sample["from"], sample["to"], sample["delta"]
                )
                groups.setdefault(edge, []).append(sample)

            rejected_ids: set[int] = set()
            diagnostics: List[dict] = []
            for (from_name, to_name), rows in groups.items():
                available_types = sorted({
                    int(row["position_type"])
                    for row in rows
                    if row.get("position_type") is not None
                })
                if 4 not in available_types:
                    continue
                rejected_rows = [
                    row for row in rows if int(row.get("position_type") or 0) != 4
                ]
                if not rejected_rows:
                    continue
                for row in rejected_rows:
                    rejected_ids.add(id(row))
                diagnostics.append({
                    "from": from_name,
                    "to": to_name,
                    "selected_position_type": 4,
                    "available_position_types": available_types,
                    "rejected_position_types": sorted({
                        int(row["position_type"])
                        for row in rejected_rows
                    }),
                    "rejected_count": len(rejected_rows),
                    "raw_indices": [row.get("raw_index") for row in rejected_rows],
                })
            return [
                sample for sample in samples if id(sample) not in rejected_ids
            ], diagnostics

        def weighted_edges(samples: List[dict]) -> List[dict]:
            groups: Dict[tuple[str, str], List[dict]] = {}
            for sample in samples:
                key, vector, direction = _canonical_baseline(
                    sample["from"], sample["to"], sample["delta"]
                )
                normalized = dict(sample)
                normalized["from"], normalized["to"] = key
                normalized["delta"] = np.asarray(vector, dtype=float)
                normalized["direction"] = direction
                groups.setdefault(key, []).append(normalized)

            pooled_lag_one = _pooled_lag_one_autocorrelations(groups)
            result = []
            for key, rows in groups.items():
                information_state = _InformationAccumulator()
                for row in rows:
                    information_state.add(
                        int(row.get("observation_epoch") or 0),
                        row["delta"],
                        row["covariance"],
                        fast_tau_seconds=self.STABILITY_EWMA_FAST_TAU_SECONDS,
                        slow_tau_seconds=self.STABILITY_EWMA_SLOW_TAU_SECONDS,
                        retention_seconds=1,
                    )
                mean_covariance = information_state.formal_covariance
                mean = information_state.mean
                if mean_covariance is None or mean is None:
                    continue

                # Samples within one uninterrupted RTK FIXED window share the
                # same ambiguity solution and correction-source state.  Their
                # statistical independence is therefore not established.  The
                # published solution conservatively assigns one independent
                # observation to each contiguous source/direction session.
                # ACF ESS is retained for audit/sensitivity only.
                acf_effective_sample_size, ess_sessions = _edge_effective_sample_size(
                    rows,
                    pooled_lag_one,
                )
                contiguous_sessions = _split_effective_sample_sessions(rows)
                effective_sample_size = float(len(contiguous_sessions))
                session_summaries = []
                for session_index, session_rows in enumerate(contiguous_sessions, 1):
                    session_state = _InformationAccumulator()
                    for session_row in session_rows:
                        session_state.add(
                            int(session_row.get("observation_epoch") or 0),
                            session_row["delta"],
                            session_row["covariance"],
                            fast_tau_seconds=self.STABILITY_EWMA_FAST_TAU_SECONDS,
                            slow_tau_seconds=self.STABILITY_EWMA_SLOW_TAU_SECONDS,
                            retention_seconds=1,
                        )
                    session_mean = np.asarray(session_state.mean, dtype=float)
                    session_summary = {
                        "session": session_index,
                        "session_id": session_rows[0].get("session_id"),
                        "observation_count": len(session_rows),
                        "mean_xyz": tuple(float(value) for value in session_mean),
                    }
                    session_summaries.append(session_summary)

                max_session_mean_separation = 0.0
                max_session_mean_difference = None
                max_session_mean_pair = None
                for left in range(len(session_summaries)):
                    for right in range(left + 1, len(session_summaries)):
                        difference = (
                            np.asarray(session_summaries[right]["mean_xyz"], dtype=float)
                            - np.asarray(session_summaries[left]["mean_xyz"], dtype=float)
                        )
                        separation = float(np.linalg.norm(difference))
                        if separation > max_session_mean_separation:
                            max_session_mean_separation = separation
                            max_session_mean_difference = tuple(
                                float(value) for value in difference
                            )
                            max_session_mean_pair = (
                                session_summaries[left]["session_id"]
                                or session_summaries[left]["session"],
                                session_summaries[right]["session_id"]
                                or session_summaries[right]["session"],
                            )

                for session_diagnostic, session_summary in zip(
                    ess_sessions, session_summaries, strict=True
                ):
                    session_diagnostic["acf_estimated_effective_sample_size"] = (
                        session_diagnostic.pop("effective_sample_size")
                    )
                    session_diagnostic["published_effective_sample_size"] = 1.0
                    session_diagnostic["session_id"] = session_summary["session_id"]
                    session_diagnostic["mean_xyz"] = session_summary["mean_xyz"]
                temporal_inflation = len(rows) / effective_sample_size
                scatter_scale = 1.0
                if len(rows) > 1:
                    scatter = sum(
                        float(
                            (row["delta"] - mean).T
                            @ _spd_solve(row["covariance"], np.eye(3, dtype=float))
                            @ (row["delta"] - mean)
                        )
                        for row in rows
                    )
                    scatter_scale = max(1.0, scatter / (3.0 * (len(rows) - 1)))
                covariance = mean_covariance * temporal_inflation * scatter_scale
                covariance = 0.5 * (covariance + covariance.T)
                independent_covariance = mean_covariance * scatter_scale
                independent_covariance = 0.5 * (
                    independent_covariance + independent_covariance.T
                )
                position_types = sorted({
                    int(row["position_type"])
                    for row in rows
                    if row.get("position_type") is not None
                })
                type_means = []
                for position_type in position_types:
                    type_rows = [
                        row for row in rows
                        if row.get("position_type") == position_type
                    ]
                    type_precision_sum = np.zeros((3, 3), dtype=float)
                    type_weighted_sum = np.zeros(3, dtype=float)
                    for row in type_rows:
                        type_precision = _spd_solve(
                            row["covariance"], np.eye(3, dtype=float)
                        )
                        type_precision_sum += type_precision
                        type_weighted_sum += type_precision @ row["delta"]
                    type_means.append(
                        np.linalg.solve(type_precision_sum, type_weighted_sum)
                    )
                position_type_separation = max(
                    (
                        float(np.linalg.norm(type_means[left] - type_means[right]))
                        for left in range(len(type_means))
                        for right in range(left + 1, len(type_means))
                    ),
                    default=0.0,
                )
                result.append({
                    "from": key[0],
                    "to": key[1],
                    "delta": tuple(float(value) for value in mean),
                    "covariance": covariance,
                    "formal_covariance": mean_covariance,
                    "session_covariance_used": covariance,
                    "independent_covariance": independent_covariance,
                    "effective_sample_size": effective_sample_size,
                    "acf_estimated_effective_sample_size": acf_effective_sample_size,
                    "temporal_scale_factor": temporal_inflation,
                    "scatter_scale_factor": scatter_scale,
                    "effective_sample_size_sessions": ess_sessions,
                    "session_count": len(session_summaries),
                    "max_session_mean_separation_m": max_session_mean_separation,
                    "max_session_mean_difference_xyz": max_session_mean_difference,
                    "max_session_mean_pair": max_session_mean_pair,
                    "pooled_lag_one_autocorrelations": pooled_lag_one,
                    "observation_count": len(rows),
                    "raw_indices": [row["raw_index"] for row in rows],
                    "directions": [row["direction"] for row in rows],
                    "position_types": position_types,
                    "position_type_mean_separation_m": position_type_separation,
                    "ratio": next((row["ratio"] for row in reversed(rows) if row["ratio"] is not None), None),
                    "velocity_up_std": (
                        sum(row["velocity_up_std"] for row in rows if row["velocity_up_std"] is not None)
                        / sum(row["velocity_up_std"] is not None for row in rows)
                        if any(row["velocity_up_std"] is not None for row in rows)
                        else None
                    ),
                })
            return result

        seed_samples = []
        for record in records:
            observation = record.observation
            rover_name = station_names.get(observation.station_id)
            if record.base_name != "BASE" or rover_name is None:
                continue
            if not getattr(record, "solver_eligible", True):
                continue
            delta = self._baseline_ecef(observation, fixed_base_llh)
            if _vector_length(delta) < 1.0:
                continue
            if max(float(value) for value in observation.std_neu) > std_warning_threshold:
                continue
            seed_samples.append({
                "from": "BASE",
                "to": rover_name,
                "delta": delta,
                "covariance": neu_standard_deviation_to_ecef_covariance(
                    observation.std_neu, fixed_base_llh[0], fixed_base_llh[1]
                ),
                "raw_index": -1,
                "session_id": str(cluster_index),
                "observation_epoch": observation.epoch_ts,
                "position_type": observation.position_type,
                "ratio": observation.full_data.get("ratio"),
                "velocity_up_std": observation.full_data.get("velocity_up_std"),
            })
        filtered_seed_samples, _seed_position_type_diagnostics = (
            filter_position_type_mixes(seed_samples)
        )
        filtered_seed_samples, _seed_outliers = filter_vector_outliers(
            filtered_seed_samples
        )
        seed_edges = {
            edge["to"]: edge
            for edge in weighted_edges(filtered_seed_samples)
            if edge["from"] == "BASE"
        }
        missing_seed = [
            station_id
            for station_id, name in station_names.items()
            if name not in seed_edges
        ]
        if missing_seed:
            raise ValueError(f"missing valid fixed-base observations for stations {missing_seed}")

        points: Dict[str, Point] = {"BASE": Point("BASE", fixed_base_ecef, fixed=True)}
        for station_id, name in station_names.items():
            delta = seed_edges[name]["delta"]
            approximate = tuple(fixed_base_ecef[axis] + delta[axis] for axis in range(3))
            points[name] = Point(name, approximate, fixed=False, identifier=station_id)

        raw_rows: List[dict] = []
        solver_samples: List[dict] = []
        high_std_cross_candidates: List[dict] = []
        raw_ecef_candidates: Dict[str, list[tuple[int, tuple[float, float, float]]]] = {
            name: [] for name in station_names.values()
        }

        for record in records:
            observation = record.observation
            rover_name = station_names.get(observation.station_id)
            if rover_name is None:
                continue
            from_name = "BASE" if record.base_name == "BASE" else record.base_name
            if from_name != "BASE" and (from_name not in points or from_name == rover_name):
                continue

            if from_name == "BASE":
                base_llh = fixed_base_llh
                base_ecef = fixed_base_ecef
            else:
                cached = (
                    cluster.get("temporary_base_llh_by_rover", {}).get(from_name)
                    or self.rover_llh_cache.get(from_name)
                )
                if cached:
                    base_llh = (float(cached["lat"]), float(cached["lon"]), float(cached["alt"]))
                else:
                    base_llh = _ecef_to_llh(*points[from_name].approximate)
                base_ecef = points[from_name].approximate

            delta = self._baseline_ecef(observation, base_llh)
            covariance = neu_standard_deviation_to_ecef_covariance(
                observation.std_neu, base_llh[0], base_llh[1]
            )
            length = _vector_length(delta)
            flags = list(getattr(record, "quality_flags", ()) or ())
            if length < 1.0:
                flags.append("REJECTED_TOO_SHORT")
            if max(float(value) for value in observation.std_neu) > std_warning_threshold:
                flags.append("BASELINE_STD_WARNING")
                flags.append("REJECTED_BASELINE_STD")

            consistency_error = None
            consistency_residual_enu = None
            if observation.rover_ecef:
                expected = tuple(base_ecef[axis] + delta[axis] for axis in range(3))
                consistency_residual_ecef = tuple(
                    observation.rover_ecef[axis] - expected[axis] for axis in range(3)
                )
                consistency_error = _vector_length(consistency_residual_ecef)
                consistency_residual_enu_array = (
                    ecef_to_enu_rotation(base_llh[0], base_llh[1])
                    @ np.asarray(consistency_residual_ecef, dtype=float)
                )
                consistency_residual_enu = tuple(
                    float(value) for value in consistency_residual_enu_array
                )
                if consistency_error > raw_ecef_tolerance:
                    horizontal_error = math.hypot(
                        consistency_residual_enu[0], consistency_residual_enu[1]
                    )
                    if (
                        horizontal_error <= raw_ecef_tolerance
                        and abs(consistency_residual_enu[2]) > raw_ecef_tolerance
                    ):
                        # The independent rover ECEF and baseline agree in plan
                        # but use different vertical datums. Keep the validated
                        # baseline, while never using this rover ECEF as a raw
                        # point-coordinate observation.
                        flags.append("ROVER_ECEF_VERTICAL_DATUM_OFFSET_DIAGNOSTIC")
                    else:
                        flags.append("BASELINE_POSITION_INCONSISTENT")

            raw_index = len(raw_rows)
            raw_rows.append({
                "from": from_name,
                "to": rover_name,
                "session_id": str(cluster_index),
                "observation_epoch": observation.epoch_ts,
                "position_type": observation.position_type,
                "gps_satellites": observation.full_data.get("gps_satellites"),
                "bds_satellites": observation.full_data.get("bds_satellites"),
                "glonass_satellites": observation.full_data.get("glonass_satellites"),
                "galileo_satellites": observation.full_data.get("galileo_satellites"),
                "diff_age": observation.full_data.get("diff_age"),
                "baseline_neu": observation.baseline_neu,
                "baseline_ecef_xyz": delta,
                "raw_base_llh": observation.base_llh,
                "base_llh": base_llh,
                "baseline_std_neu_raw": observation.std_neu_raw,
                "baseline_std_neu": observation.std_neu,
                "velocity_up_std": observation.full_data.get("velocity_up_std"),
                "rover_ecef": observation.rover_ecef,
                "rover_position_std_ecef_raw": observation.rover_position_std_ecef_raw,
                "rover_position_std_ecef": observation.rover_position_std_ecef,
                "raw_ecef_consistency_error_m": consistency_error,
                "raw_ecef_consistency_residual_enu_m": consistency_residual_enu,
                "quality_flags": flags,
                "source_validation_diagnostic": getattr(
                    record, "source_diagnostic", None
                ),
                "rotation_index": getattr(record, "rotation_index", None),
                "stable_window_index": getattr(record, "stable_window_index", None),
                "effective_session_id": (
                    f"R{getattr(record, 'rotation_index'):03d}-W{getattr(record, 'stable_window_index'):02d}-{from_name}>{rover_name}"
                    if getattr(record, "rotation_index", None) is not None
                    and getattr(record, "stable_window_index", None) is not None
                    else None
                ),
                "raw_payload": observation.raw,
                "vector_deviation_from_edge_m": None,
                "vector_outlier_threshold_m": None,
                "vector_filter_status": "SKIPPED_PRIOR_FILTER",
                "residual_xyz": None,
                "standardized_residual": None,
            })
            if observation.rover_ecef and getattr(record, "solver_eligible", True):
                raw_ecef_candidates[rover_name].append((raw_index, observation.rover_ecef))
            solver_sample = {
                "from": from_name,
                "to": rover_name,
                "delta": delta,
                "covariance": covariance,
                "raw_index": raw_index,
                "session_id": raw_rows[-1]["effective_session_id"] or str(cluster_index),
                "observation_epoch": observation.epoch_ts,
                "position_type": observation.position_type,
                "ratio": observation.full_data.get("ratio"),
                "velocity_up_std": observation.full_data.get("velocity_up_std"),
            }
            rejected_flags = {
                str(flag)
                for flag in flags
                if str(flag).startswith("REJECTED_")
            }
            if getattr(record, "solver_eligible", True) and not rejected_flags:
                solver_samples.append(solver_sample)
            elif (
                from_name != "BASE"
                and rejected_flags == {"REJECTED_BASELINE_STD"}
            ):
                # Some UM980 field sessions report metre-level baseline STD
                # while the RTK-Fixed ECEF vectors themselves repeat at the
                # centimetre level. Keep these rows quarantined until the whole
                # edge can prove repeatability; an isolated high-STD epoch must
                # never create a network edge by itself.
                high_std_cross_candidates.append(solver_sample)

        baseline_std_repeatability_fallback_edges: List[dict] = []
        accepted_cross_edge_keys = {
            _canonical_baseline(sample["from"], sample["to"], sample["delta"])[0]
            for sample in solver_samples
            if sample["from"] != "BASE" and sample["to"] != "BASE"
        }
        candidate_groups: Dict[tuple[str, str], List[dict]] = {}
        for sample in high_std_cross_candidates:
            edge_key, _vector, _direction = _canonical_baseline(
                sample["from"], sample["to"], sample["delta"]
            )
            candidate_groups.setdefault(edge_key, []).append(sample)

        for edge_key, candidates in candidate_groups.items():
            if edge_key in accepted_cross_edge_keys:
                continue
            epochs = {
                int(sample["observation_epoch"])
                for sample in candidates
                if sample.get("observation_epoch") is not None
            }
            if (
                len(candidates) < high_std_fallback_min_samples
                or len(epochs) < high_std_fallback_min_samples
                or any(int(sample.get("position_type") or 0) != 4 for sample in candidates)
            ):
                continue

            canonical_vectors = []
            consistency_errors = []
            for sample in candidates:
                _key, vector, _direction = _canonical_baseline(
                    sample["from"], sample["to"], sample["delta"]
                )
                canonical_vectors.append(np.asarray(vector, dtype=float))
                consistency_error = raw_rows[sample["raw_index"]].get(
                    "raw_ecef_consistency_error_m"
                )
                if consistency_error is None:
                    consistency_errors = []
                    break
                consistency_errors.append(float(consistency_error))
            if (
                len(consistency_errors) != len(candidates)
                or max(consistency_errors) > raw_ecef_tolerance
            ):
                continue

            vector_matrix = np.vstack(canonical_vectors)
            vector_center = np.median(vector_matrix, axis=0)
            deviations = np.linalg.norm(vector_matrix - vector_center, axis=1)
            max_deviation = float(np.max(deviations))
            if max_deviation > high_std_fallback_max_repeatability_m:
                continue

            for sample in candidates:
                flags = raw_rows[sample["raw_index"]]["quality_flags"]
                if "REJECTED_BASELINE_STD" in flags:
                    flags.remove("REJECTED_BASELINE_STD")
                if "BASELINE_STD_REPEATABILITY_FALLBACK" not in flags:
                    flags.append("BASELINE_STD_REPEATABILITY_FALLBACK")
                solver_samples.append(sample)
            accepted_cross_edge_keys.add(edge_key)
            baseline_std_repeatability_fallback_edges.append({
                "from": edge_key[0],
                "to": edge_key[1],
                "observation_count": len(candidates),
                "distinct_epoch_count": len(epochs),
                "max_vector_deviation_m": max_deviation,
                "max_ecef_consistency_error_m": max(consistency_errors),
                "covariance_policy": (
                    "Retain the receiver-reported high covariance; repeatability "
                    "restores topology but does not increase this edge's weight"
                ),
            })

        solver_samples, position_type_filter_diagnostics = (
            filter_position_type_mixes(solver_samples)
        )
        for diagnostic in position_type_filter_diagnostics:
            for raw_index in diagnostic.get("raw_indices") or []:
                if raw_index is None or raw_index < 0:
                    continue
                flags = raw_rows[raw_index]["quality_flags"]
                if "REJECTED_POSITION_TYPE_7" not in flags:
                    flags.append("REJECTED_POSITION_TYPE_7")

        solver_samples, vector_outlier_diagnostics = filter_vector_outliers(
            solver_samples
        )
        for diagnostic in vector_outlier_diagnostics:
            raw_index = diagnostic.get("raw_index")
            if raw_index is None or raw_index < 0:
                continue
            row = raw_rows[raw_index]
            
            row["vector_filter_status"] = diagnostic.get("vector_filter_status")
            if "vector_deviation_from_edge_m" in diagnostic:
                row["vector_deviation_from_edge_m"] = diagnostic["vector_deviation_from_edge_m"]
            if "vector_outlier_threshold_m" in diagnostic:
                row["vector_outlier_threshold_m"] = diagnostic["vector_outlier_threshold_m"]
                
            if row["vector_filter_status"] == "EVALUATED_OUTLIER":
                if "REJECTED_VECTOR_OUTLIER" not in row["quality_flags"]:
                    row["quality_flags"].append("REJECTED_VECTOR_OUTLIER")

        averaged_edges = weighted_edges(solver_samples)
        rover_names = set(station_names.values())
        cross_edges = [
            edge
            for edge in averaged_edges
            if edge["from"] != "BASE" and edge["to"] != "BASE"
        ]
        if not cross_edges:
            raw_cross_rows = [row for row in raw_rows if row["from"] != "BASE"]
            rejected_std = sum(
                "REJECTED_BASELINE_STD" in row["quality_flags"]
                for row in raw_cross_rows
            )
            rejected_short = sum(
                "REJECTED_TOO_SHORT" in row["quality_flags"]
                for row in raw_cross_rows
            )
            rejected_position_type = sum(
                "REJECTED_POSITION_TYPE_7" in row["quality_flags"]
                for row in raw_cross_rows
            )
            rejected_outlier = sum(
                "REJECTED_VECTOR_OUTLIER" in row["quality_flags"]
                for row in raw_cross_rows
            )
            raise ValueError(
                "no solver-eligible rover-to-rover baseline was collected during "
                f"Round-Robin; raw cross samples={len(raw_cross_rows)}, "
                f"rejected STD>{std_warning_threshold:.3f}m={rejected_std}, "
                f"too-short={rejected_short}, position-type={rejected_position_type}, "
                f"vector-outlier={rejected_outlier}"
            )
        required_cross_edges = max(len(rover_names) - 1, 1)
        cross_participants = {
            point_name
            for edge in cross_edges
            for point_name in (edge["from"], edge["to"])
            if point_name in rover_names
        }
        missing_cross_participants = sorted(rover_names - cross_participants)
        cross_components = _graph_components(
            rover_names,
            ((edge["from"], edge["to"]) for edge in cross_edges),
        )
        disconnected_detail = (
            "; disconnected rover components: "
            + " | ".join(", ".join(sorted(component)) for component in cross_components)
            if len(cross_components) > 1
            else ""
        )
        if (
            len(cross_edges) < required_cross_edges
            or missing_cross_participants
            or len(cross_components) > 1
        ):
            missing_detail = (
                f"; rovers absent from cross-baselines: {', '.join(missing_cross_participants)}"
                if missing_cross_participants else ""
            )
            raise ValueError(
                "insufficient rover-to-rover network coverage: "
                f"need at least {required_cross_edges} distinct cross-edge(s) for "
                f"{len(rover_names)} rovers, collected {len(cross_edges)}"
                f"{missing_detail}{disconnected_detail}. Adjustment was not published; "
                "collect the missing rotations again"
            )

        baselines = [
            Baseline(
                edge["from"], edge["to"], edge["delta"],
                covariance=tuple(tuple(float(value) for value in row) for row in edge["covariance"]),
            )
            for edge in averaged_edges
        ]
        result = adjust_network(Network.from_items(points.values(), baselines))
        independent_baselines = [
            Baseline(
                edge["from"], edge["to"], edge["delta"],
                covariance=tuple(
                    tuple(float(value) for value in row)
                    for row in edge["independent_covariance"]
                ),
            )
            for edge in averaged_edges
        ]
        independent_result = adjust_network(
            Network.from_items(points.values(), independent_baselines)
        )

        adjusted_points = {}
        for point in result.points:
            if point.fixed:
                continue
            raw_candidates = raw_ecef_candidates.get(point.name, [])
            raw_values = [
                value
                for raw_index, value in raw_candidates
                if not any(
                    str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                    or flag in {
                        "BASELINE_POSITION_INCONSISTENT",
                        "ROVER_ECEF_VERTICAL_DATUM_OFFSET_DIAGNOSTIC",
                    }
                    for flag in raw_rows[raw_index]["quality_flags"]
                )
            ]
            raw_mean = (
                tuple(sum(row[axis] for row in raw_values) / len(raw_values) for axis in range(3))
                if raw_values else None
            )
            std_enu = covariance_standard_deviation(
                ecef_point_covariance_to_enu(point.covariance, tuple(point.coordinate))
            )
            posterior_std_enu = covariance_standard_deviation(
                ecef_point_covariance_to_enu(
                    point.posterior_covariance,
                    tuple(point.coordinate),
                )
            )
            adjusted_points[point.name] = {
                "station_id": points[point.name].identifier,
                "adjusted_n": point.coordinate[0], "adjusted_e": point.coordinate[1], "adjusted_u": point.coordinate[2],
                "adjusted_x": point.coordinate[0], "adjusted_y": point.coordinate[1], "adjusted_z": point.coordinate[2],
                "correction_n": point.correction[0], "correction_e": point.correction[1], "correction_u": point.correction[2],
                "dx": point.correction[0], "dy": point.correction[1], "dz": point.correction[2],
                "std_n": point.standard_deviation[0], "std_e": point.standard_deviation[1], "std_u": point.standard_deviation[2],
                "std_x": point.standard_deviation[0], "std_y": point.standard_deviation[1], "std_z": point.standard_deviation[2],
                "std_x_a_priori": point.standard_deviation[0],
                "std_y_a_priori": point.standard_deviation[1],
                "std_z_a_priori": point.standard_deviation[2],
                "std_x_a_posteriori": point.posterior_standard_deviation[0],
                "std_y_a_posteriori": point.posterior_standard_deviation[1],
                "std_z_a_posteriori": point.posterior_standard_deviation[2],
                "standard_deviation_enu": std_enu,
                "posterior_standard_deviation_enu": posterior_std_enu,
                "covariance_ecef_a_priori": point.covariance,
                "covariance_ecef_a_posteriori": point.posterior_covariance,
                "raw_rover_ecef": raw_mean,
                "raw_rover_ecef_observation_count": len(raw_values),
                "raw_rover_ecef_rejected_count": len(raw_candidates) - len(raw_values),
            }

        adjusted_baselines = []
        for index, adjusted in enumerate(result.baselines):
            edge = averaged_edges[index]
            std_xyz = covariance_standard_deviation(edge["covariance"])
            item = {
                "from": adjusted.from_point, "to": adjusted.to_point,
                "observed_xyz": adjusted.observed, "adjusted_xyz": adjusted.adjusted,
                "residual_xyz": adjusted.residual,
                "standard_deviation_xyz": std_xyz,
                "formal_covariance_xyz": tuple(
                    tuple(float(value) for value in row)
                    for row in edge["formal_covariance"]
                ),
                "session_covariance_used_xyz": tuple(
                    tuple(float(value) for value in row)
                    for row in edge["session_covariance_used"]
                ),
                "variance_inflation": edge.get("scatter_scale_factor"),
                "observed_length": _vector_length(adjusted.observed),
                "adjusted_length": _vector_length(adjusted.adjusted),
                "observation_count": edge["observation_count"],
                "effective_sample_size": edge["effective_sample_size"],
                "temporal_inflation_factor": edge["temporal_scale_factor"],
                "scatter_scale_factor": edge["scatter_scale_factor"],
                "total_covariance_inflation_factor": (
                    edge["temporal_scale_factor"] * edge["scatter_scale_factor"]
                ),
                "session_count": edge["session_count"],
                "max_session_mean_separation_m": edge[
                    "max_session_mean_separation_m"
                ],
                "max_session_mean_difference_xyz": edge[
                    "max_session_mean_difference_xyz"
                ],
                "max_session_mean_pair": edge["max_session_mean_pair"],
                "position_types": edge["position_types"],
                "position_type_mean_separation_m": edge["position_type_mean_separation_m"],
                "velocity_up_std": edge["velocity_up_std"], "ratio": edge["ratio"],
                "observed_neu": adjusted.observed, "adjusted_neu": adjusted.adjusted,
                "residual_neu": adjusted.residual,
                "standardized_residual": adjusted.standardized_residual,
                "redundancy": adjusted.redundancy,
            }
            adjusted_baselines.append(item)
            for raw_index, direction in zip(edge["raw_indices"], edge["directions"], strict=True):
                raw_rows[raw_index]["residual_xyz"] = tuple(direction * value for value in adjusted.residual)
                raw_rows[raw_index]["standardized_residual"] = tuple(
                    direction * value for value in adjusted.standardized_residual
                )

        loops = _build_fundamental_loops(adjusted_baselines)
        if not loops:
            raise ValueError("adjusted graph contains no geometric closed loop")
        network_components = _graph_components(
            points.keys(),
            ((edge["from"], edge["to"]) for edge in adjusted_baselines),
        )
        cycle_space_dimension = (
            len(adjusted_baselines) - len(points) + len(network_components)
        )
        cycle_edge_matrix = np.zeros(
            (len(loops), len(adjusted_baselines)),
            dtype=float,
        )
        for loop_index, loop in enumerate(loops):
            baseline_indices = loop.get("baseline_indices") or []
            baseline_directions = loop.get("baseline_directions") or []
            if len(baseline_indices) != len(baseline_directions):
                raise RuntimeError(
                    "fundamental loop basis is missing directed edge metadata"
                )
            for baseline_index, direction in zip(
                baseline_indices,
                baseline_directions,
            ):
                cycle_edge_matrix[loop_index, int(baseline_index)] = float(direction)
        cycle_basis_rank = int(np.linalg.matrix_rank(cycle_edge_matrix))
        if (
            len(loops) != cycle_space_dimension
            or cycle_basis_rank != cycle_space_dimension
        ):
            raise RuntimeError(
                "fundamental loop basis verification failed: "
                f"dimension={cycle_space_dimension}, loops={len(loops)}, "
                f"rank={cycle_basis_rank}"
            )

        observation_sessions = []
        for edge in averaged_edges:
            epochs = [raw_rows[index]["observation_epoch"] for index in edge["raw_indices"]]
            observation_sessions.append({
                "session_id": str(cluster_index), "from": edge["from"], "to": edge["to"],
                "start_epoch": min(epochs), "end_epoch": max(epochs),
                "observation_count": edge["observation_count"],
            })

        temporal_scaling_applied = any(
            edge["temporal_scale_factor"] > 1.0 + 1e-12
            for edge in averaged_edges
        )
        global_test = None
        stochastic_model_test = None
        if result.global_test:
            statistic = float(result.global_test.statistic)
            significance = float(result.global_test.significance_level)
            upper_critical = float(
                chi2.ppf(1.0 - significance, result.degrees_of_freedom)
            )
            upper_tail_p_value = float(
                chi2.sf(statistic, result.degrees_of_freedom)
            )
            network_passed = statistic <= upper_critical
            global_test = {
                "method": "UPPER_TAIL_NETWORK_QUALITY",
                "statistic": statistic,
                "upper_critical_value": upper_critical,
                "p_value": upper_tail_p_value,
                "p_value_tail": "UPPER",
                "significance_level": significance,
                "passed": network_passed,
                "applicable": True,
                "approximate": temporal_scaling_applied,
                "conclusion": (
                    "PASSED" if network_passed else "FAILED_HIGH_RESIDUAL"
                ),
                "interpretation": (
                    "One-sided upper-tail Chi-square network quality test. A statistic "
                    "below the critical value passes; a very small statistic does not "
                    "fail the network and is diagnosed separately as conservative weighting."
                ),
            }

            if statistic < result.global_test.lower_critical_value:
                stochastic_status = "CONSERVATIVE_WEIGHTS"
            elif statistic > result.global_test.upper_critical_value:
                stochastic_status = "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR"
            else:
                stochastic_status = "CONSISTENT"
            stochastic_model_test = {
                "method": "TWO_SIDED_MODEL_CALIBRATION",
                "statistic": statistic,
                "lower_critical_value": result.global_test.lower_critical_value,
                "upper_critical_value": result.global_test.upper_critical_value,
                "p_value": result.global_test.p_value,
                "significance_level": significance,
                "within_expected_range": result.global_test.passed,
                "status": stochastic_status,
                "approximate": temporal_scaling_applied,
                "interpretation": (
                    "Two-sided diagnostic of the stochastic model only. A value below "
                    "the lower bound means assigned covariance is conservative; it is "
                    "not a network-quality failure."
                ),
            }
        independent_global_test = (
            {
                "statistic": independent_result.global_test.statistic,
                "lower_critical_value": independent_result.global_test.lower_critical_value,
                "upper_critical_value": independent_result.global_test.upper_critical_value,
                "p_value": independent_result.global_test.p_value,
                "passed": independent_result.global_test.passed,
                "applicable": True,
                "assumption": "All accepted raw epochs are statistically independent.",
                "used_for_published_solution": False,
                "weighted_residual_sum": independent_result.weighted_residual_sum,
                "reference_standard_deviation": (
                    math.sqrt(independent_result.variance_factor)
                    if independent_result.variance_factor is not None
                    and independent_result.variance_factor >= 0
                    else None
                ),
            }
            if independent_result.global_test else None
        )
        accepted_raw = [
            row for row in raw_rows
            if not any(
                str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                for flag in row["quality_flags"]
            )
        ]
        trusted_raw = [row for row in accepted_raw if "BASELINE_STD_WARNING" not in row["quality_flags"]]
        mixed_position_type_edges = [
            {
                "from": edge["from"],
                "to": edge["to"],
                "position_types": edge["position_types"],
                "mean_separation_m": edge["position_type_mean_separation_m"],
            }
            for edge in averaged_edges
            if len(edge["position_types"]) > 1
        ]
        max_observed_closure = max(
            (float(loop.get("observed_closure") or 0.0) for loop in loops),
            default=0.0,
        )
        network_quality_passed = bool(global_test and global_test.get("passed"))
        # Loop closure is a diagnostic, not an acceptance threshold. In particular,
        # it must never reduce the retained observation count or independently block
        # publishing a solved network. Source/window validation happens before the
        # solver; the statistical network test remains the publish quality gate.
        quality_gate_passed = network_quality_passed
        quality_gate_reasons = []
        if not network_quality_passed:
            quality_gate_reasons.append("network quality test is not PASS")
        diagnostic_warnings = []
        if (
            network_quality_passed
            and result.max_standardized_residual is not None
            and float(result.max_standardized_residual) >= 2.5
        ):
            diagnostic_warnings.append({
                "code": "LOCAL_STANDARDIZED_RESIDUAL_ELEVATED",
                "message": (
                    "The global network test passes, but at least one local "
                    "standardized residual is >= 2.5 sigma. Review the affected edge; "
                    "this warning alone is not authority to reject the point."
                ),
                "max_standardized_residual": float(
                    result.max_standardized_residual
                ),
            })
        
        worst_scatter_edge = max(
            averaged_edges,
            key=lambda edge: float(edge.get("scatter_scale_factor") or 1.0),
            default=None,
        )
        max_variance_inflation = float(
            (worst_scatter_edge or {}).get("scatter_scale_factor") or 1.0
        )
        if max_variance_inflation > 1.5:
            max_session_separation = float(
                (worst_scatter_edge or {}).get("max_session_mean_separation_m")
                or 0.0
            )
            diagnostic_warnings.append({
                "code": "HIGH_INTER_SESSION_SCATTER",
                "message": (
                    "High pooled edge scatter detected (scatter scale > 1.5). "
                    "Review the displayed session-mean repeatability together with "
                    "multipath, physical movement, and source changes."
                ),
                "max_variance_inflation": max_variance_inflation,
                "from": (worst_scatter_edge or {}).get("from"),
                "to": (worst_scatter_edge or {}).get("to"),
                "max_session_mean_separation_m": max_session_separation,
            })
        interpretation_status = (
            "FAILED_QUALITY_GATE"
            if not quality_gate_passed else
            "PASS_WITH_WARNINGS"
            if diagnostic_warnings else
            "PASS"
        )

        return {
            "type": "gnss_adjusted",
            "source": "AGRICA_ROUND_ROBIN",
            "adjustment_engine": "backend.processors.gnss_adjustment.adjust_network",
            "project_id": project_id, "cluster_index": cluster_index,
            "cluster_name": cluster.get("name"), "computed_at": int(time.time()),
            "base": {
                "name": cluster.get("base_station") or "BASE", "fixed": True,
                "role": (
                    (cluster.get("selected_fixed_base_candidate") or {}).get("role")
                    or "primary"
                ),
                "lat": fixed_base_llh[0], "lon": fixed_base_llh[1], "h": fixed_base_llh[2],
                "ecef_xyz": fixed_base_ecef,
                "selection_diagnostic": cluster.get(
                    "fixed_base_selection_diagnostic"
                ),
                "configured_candidates": copy.deepcopy(
                    cluster.get("fixed_base_candidates", [])
                ),
            },
            "temporary_bases": copy.deepcopy(
                cluster.get("temporary_base_llh_by_rover", {})
            ),
            "rover_count": len(adjusted_points), "points": adjusted_points,
            "baselines": adjusted_baselines, "baseline_observations": raw_rows,
            "loops": loops,
            "official_publish_allowed": quality_gate_passed,
            "quality_gate": {
                "status": "PASS" if quality_gate_passed else "FAILED_QUALITY_GATE",
                "interpretation_status": interpretation_status,
                "passed": quality_gate_passed,
                "pre_adjustment_loop_closure_limit_m": None,
                "max_pre_adjustment_loop_closure_m": max_observed_closure,
                "closure_failures": [],
                "loop_closure_diagnostic_only": True,
                "network_quality_passed": network_quality_passed,
                "reasons": quality_gate_reasons,
                "diagnostic_warnings": diagnostic_warnings,
                "audit_report_allowed": True,
                "official_coordinate_publish_allowed": quality_gate_passed,
            },
            "quality": {
                "observation_baseline_count": len(accepted_raw),
                "averaged_baseline_count": len(averaged_edges),
                "observation_session_count": len(observation_sessions),
                "observation_sessions": observation_sessions,
                "baseline_std_warning_count": sum("BASELINE_STD_WARNING" in row["quality_flags"] for row in accepted_raw),
                "baseline_std_raw_warning_count": sum(
                    "BASELINE_STD_WARNING" in row["quality_flags"]
                    for row in raw_rows
                ),
                "baseline_std_rejected_count": sum(
                    "REJECTED_BASELINE_STD" in row["quality_flags"]
                    for row in raw_rows
                ),
                "baseline_std_repeatability_fallback_count": sum(
                    "BASELINE_STD_REPEATABILITY_FALLBACK" in row["quality_flags"]
                    for row in raw_rows
                ),
                "baseline_std_repeatability_fallback_edges": (
                    baseline_std_repeatability_fallback_edges
                ),
                "baseline_std_repeatability_fallback_policy": (
                    "Only when an edge has no normal-STD observation: require at least "
                    f"{high_std_fallback_min_samples} distinct RTK-Fixed epochs, maximum "
                    f"vector deviation <= {high_std_fallback_max_repeatability_m:.3f} m, "
                    f"and ECEF consistency error <= {raw_ecef_tolerance:.3f} m; retain "
                    "the original high covariance"
                ),
                "raw_observation_count": len(raw_rows),
                "raw_rejected_count": len(raw_rows) - len(accepted_raw),
                "raw_exclusion_reason_counts_overlap": True,
                "unconfirmed_source_excluded_count": sum(
                    "EXCLUDE_UNCONFIRMED_SOURCE" in row["quality_flags"]
                    for row in raw_rows
                ),
                "pre_stable_window_excluded_count": sum(
                    "EXCLUDE_PRE_STABLE_WINDOW" in row["quality_flags"]
                    for row in raw_rows
                ),
                "insufficient_stable_window_excluded_count": sum(
                    (
                        "EXCLUDE_INSUFFICIENT_STABLE_WINDOW" in row["quality_flags"]
                        or "EXCLUDE_STABILITY_NOT_REACHED" in row["quality_flags"]
                    )
                    for row in raw_rows
                ),
                "stability_not_reached_excluded_count": sum(
                    "EXCLUDE_STABILITY_NOT_REACHED" in row["quality_flags"]
                    for row in raw_rows
                ),
                "insufficient_duration_excluded_count": sum(
                    "EXCLUDE_INSUFFICIENT_DURATION" in row["quality_flags"]
                    for row in raw_rows
                ),
                "source_not_confirmed_excluded_count": sum(
                    "EXCLUDE_SOURCE_NOT_CONFIRMED" in row["quality_flags"]
                    for row in raw_rows
                ),
                "unstable_solver_window_excluded_count": sum(
                    (
                        "EXCLUDE_UNSTABLE_SOLVER_WINDOW" in row["quality_flags"]
                        or "EXCLUDE_STABILITY_LOST" in row["quality_flags"]
                    )
                    for row in raw_rows
                ),
                "stability_lost_excluded_count": sum(
                    "EXCLUDE_STABILITY_LOST" in row["quality_flags"]
                    for row in raw_rows
                ),
                "inter_rotation_reacquisition_excluded_count": sum(
                    "EXCLUDE_INTER_ROTATION_REACQUISITION" in row["quality_flags"]
                    for row in raw_rows
                ),
                "post_seed_transition_excluded_count": sum(
                    "EXCLUDE_POST_SEED_TRANSITION" in row["quality_flags"]
                    for row in raw_rows
                ),
                "rolling_stability_policy": {
                    "window_seconds": self.STABILITY_WINDOW_SECONDS,
                    "minimum_samples_per_window": (
                        self.STABILITY_MIN_SAMPLES_PER_WINDOW
                    ),
                    "maximum_sample_gap_seconds": (
                        self.STABILITY_MAX_SAMPLE_GAP_SECONDS
                    ),
                    "horizontal_component_limit_m": (
                        self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M
                    ),
                    "up_component_limit_m": self.STABILITY_UP_COMPONENT_LIMIT_M,
                    "horizontal_std_limit_m": self.STABILITY_HORIZONTAL_STD_LIMIT_M,
                    "up_std_limit_m": self.STABILITY_UP_STD_LIMIT_M,
                    "horizontal_slope_limit_mps": (
                        self.STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS
                    ),
                    "up_slope_limit_mps": self.STABILITY_UP_SLOPE_LIMIT_MPS,
                    "ewma_fast_tau_seconds": self.STABILITY_EWMA_FAST_TAU_SECONDS,
                    "ewma_slow_tau_seconds": self.STABILITY_EWMA_SLOW_TAU_SECONDS,
                    "ewma_role": (
                        "Early transition detector only; formal acceptance still "
                        "requires two non-overlapping windows plus continuous hold"
                    ),
                    "continuous_hold_seconds": self.STABILITY_HOLD_SECONDS,
                    "abort_horizontal_component_limit_m": (
                        self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                    ),
                    "abort_up_component_limit_m": (
                        self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M
                    ),
                    "abort_consecutive_epochs": (
                        self.STABILITY_ABORT_CONSECUTIVE_EPOCHS
                    ),
                    "solver_min_distinct_epochs": (
                        self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS
                    ),
                    "solver_min_duration_seconds": (
                        self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
                    ),
                    "reset_complete_window_when_sustained_drift_returns": True,
                },
                "temporary_base_coordinate_policy": (
                    "One immutable covariance-weighted ECEF endpoint per rover, "
                    "derived from the common initial fixed-BASE solver window and "
                    "reused for MODE BASE, source validation, and network reduction"
                ),
                "pre_adjustment_loop_closure_limit_m": None,
                "max_pre_adjustment_loop_closure_m": max_observed_closure,
                "loop_closure_diagnostic_only": True,
                "quality_gate_status": (
                    "PASS" if quality_gate_passed else "FAILED_QUALITY_GATE"
                ),
                "quality_interpretation_status": interpretation_status,
                "diagnostic_warnings": diagnostic_warnings,
                "max_session_mean_separation_m": max(
                    (
                        float(edge.get("max_session_mean_separation_m") or 0.0)
                        for edge in averaged_edges
                    ),
                    default=0.0,
                ),
                "vector_outlier_count": sum(
                    diagnostic.get("vector_filter_status") == "EVALUATED_OUTLIER"
                    for diagnostic in vector_outlier_diagnostics
                ),
                "vector_outlier_filter": (
                    "Per edge/session coordinate-wise median center; reject 3-D deviation above "
                    f"max({vector_outlier_absolute_floor_m:.2f} m, median deviation + "
                    f"{vector_outlier_sigma_multiplier:.0f} x 1.4826 x MAD), minimum "
                    f"{vector_outlier_min_samples} samples"
                ),
                "mixed_position_type_edges": mixed_position_type_edges,
                "mixed_position_type_edge_count": len(mixed_position_type_edges),
                "mixed_position_type_warning_threshold_m": 0.01,
                "position_type_selection_policy": (
                    "Per geometric edge prefer RTK Fixed position type 4; use Input "
                    "Fixed type 7 only when that edge has no accepted type 4 observation"
                ),
                "position_type_filter_edges": position_type_filter_diagnostics,
                "position_type_rejected_count": sum(
                    "REJECTED_POSITION_TYPE_7" in row["quality_flags"]
                    for row in raw_rows
                ),
                "raw_ecef_inconsistent_count": sum("BASELINE_POSITION_INCONSISTENT" in row["quality_flags"] for row in raw_rows),
                "raw_ecef_vertical_datum_offset_count": sum(
                    "ROVER_ECEF_VERTICAL_DATUM_OFFSET_DIAGNOSTIC"
                    in row["quality_flags"]
                    for row in raw_rows
                ),
                "baseline_std_warning_threshold_m": std_warning_threshold,
                "raw_ecef_consistency_tolerance_m": raw_ecef_tolerance,
                "baseline_covariance_model": (
                    "Published session covariance: C_used = (n / n_eff) * scatter_scale * "
                    "C_formal, where C_formal solves P_sum*C=I and P_sum=sum(solve(C_i,I)); "
                    "n_eff is the number of contiguous "
                    "source/direction sessions, with no independence claimed between "
                    "1 Hz epochs inside one RTK FIXED session"
                ),
                "independent_epoch_covariance_model": (
                    "Sensitivity only: C_edge = scatter_scale * "
                    "inverse(sum(inverse(C_i))); assumes n_eff=n"
                ),
                "temporal_scaling_applied": temporal_scaling_applied,
                "effective_sample_size_method": (
                    "Published n_eff: one independent observation per contiguous "
                    "source/direction session separated by direction change or >5 s gap. "
                    "Per-component ACF ESS is diagnostic only"
                ),
                "effective_sample_size_edges": [
                    {
                        "from": edge["from"],
                        "to": edge["to"],
                        "observation_count": edge["observation_count"],
                        "effective_sample_size": edge["effective_sample_size"],
                        "acf_estimated_effective_sample_size": edge[
                            "acf_estimated_effective_sample_size"
                        ],
                        "temporal_inflation_factor": edge["temporal_scale_factor"],
                        "scatter_scale_factor": edge["scatter_scale_factor"],
                        "total_covariance_inflation_factor": (
                            edge["temporal_scale_factor"]
                            * edge["scatter_scale_factor"]
                        ),
                        "session_count": edge["session_count"],
                        "max_session_mean_separation_m": edge[
                            "max_session_mean_separation_m"
                        ],
                        "max_session_mean_difference_xyz": edge[
                            "max_session_mean_difference_xyz"
                        ],
                        "max_session_mean_pair": edge["max_session_mean_pair"],
                        "pooled_lag_one_autocorrelations": edge[
                            "pooled_lag_one_autocorrelations"
                        ],
                        "sessions": edge["effective_sample_size_sessions"],
                    }
                    for edge in averaged_edges
                ],
                "chi_square_conclusion": (
                    global_test.get("conclusion") if global_test else None
                ),
                "full_covariance_available": True,
                "source_cross_covariance_available": False,
                "repeated_observations_independence_verified": False,
                "control_point_uncertainty_included": False,
                "published_point_std_scale": "a_priori",
                "reported_point_std_scales": ["a_priori", "a_posteriori"],
                "normalized_residual_scale": "a_priori",
                "degrees_of_freedom": result.degrees_of_freedom,
                "variance_factor": result.variance_factor,
                "reference_standard_deviation": math.sqrt(result.variance_factor) if result.variance_factor is not None and result.variance_factor >= 0 else None,
                "reference_standard_deviation_m_at_1mm": 0.001 * math.sqrt(result.variance_factor) if result.variance_factor is not None and result.variance_factor >= 0 else None,
                "weighted_residual_sum": result.weighted_residual_sum,
                "rank": result.rank, "condition_number": result.condition_number,
                "cycle_space_dimension": cycle_space_dimension,
                "fundamental_loop_count": len(loops),
                "fundamental_loop_basis_rank": cycle_basis_rank,
                "rover_only_loop_count": sum(
                    1 for loop in loops if "BASE" not in loop.get("points", [])
                ),
                "base_anchored_loop_count": sum(
                    1 for loop in loops if "BASE" in loop.get("points", [])
                ),
                "loop_basis_independence_verified": True,
                "loop_basis_method": (
                    "Rover-to-rover-first spanning forest plus one fundamental "
                    "cycle per chord; BASE edges only anchor rover components and "
                    "dependent cycles are intentionally omitted"
                ),
                "max_standardized_residual": result.max_standardized_residual,
                "global_test": global_test,
                "stochastic_model_test": stochastic_model_test,
                "independent_epoch_sensitivity": independent_global_test,
                "trusted_subset": {"observation_baseline_count": len(trusted_raw)},
                "residual_flags": [
                    {
                        "from": flag.from_point, "to": flag.to_point,
                        "component": flag.component,
                        "normalized_residual": flag.normalized_residual,
                        "p_value": flag.p_value, "critical_value": flag.critical_value,
                    }
                    for flag in result.residual_flags
                ],
            },
        }

    async def _find_client_info(
        self,
        station_code: str,
        *,
        project_id: Optional[int] = None,
        log_missing: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Find a rover across every configured AICaster client table."""

        candidates, successful_hosts, query_errors = await self._fetch_active_client_candidates()
        binding = self._configured_aicaster_user(project_id, station_code)
        configured_username = str(binding.get("username") or "").strip()
        configured_host = str(binding.get("caster_host") or "").strip()
        eligible_candidates = candidates
        if configured_host:
            eligible_candidates = [
                item
                for item in candidates
                if str(item.get("CasterHost") or "").casefold()
                == configured_host.casefold()
            ]

        lookup_name = configured_username or station_code
        selected = self._select_client_candidate(eligible_candidates, lookup_name)
        if selected:
            logger.info(
                "Matched station %s%s to AICaster %s:%s (username=%s receiverID=%s mountpoint=%s)",
                station_code,
                f" via configured username {configured_username}" if configured_username else "",
                selected["CasterHost"],
                selected["CasterPort"],
                selected["Username"],
                selected["receiverID"],
                selected["Mountpoint"],
            )
            return selected

        if not successful_hosts:
            raise RuntimeError(
                "Could not query any configured AICaster client table: "
                + "; ".join(query_errors)
            )
        if log_missing:
            logger.error(
                "No AICaster client session matched station %s (configured username=%s host=%s). "
                "Queried=%s errors=%s available=%s",
                station_code,
                configured_username or "<station-code fallback>",
                configured_host or "<any>",
                successful_hosts,
                query_errors,
                [
                    {
                        "host": item["CasterHost"],
                        "username": item["Username"],
                        "receiver_id": item["receiverID"],
                        "mountpoint": item["Mountpoint"],
                    }
                    for item in candidates
                ],
            )
        return None

    def _configured_aicaster_user(
        self,
        project_id: Optional[int],
        station_code: str,
    ) -> Dict[str, Any]:
        if project_id is None:
            return {}
        session = self._sessions.get(int(project_id)) or {}
        target = str(station_code or "").strip().casefold()
        for cluster in session.get("clusters", []):
            bindings = cluster.get("aicaster_users") or {}
            for code, binding in bindings.items():
                if str(code).strip().casefold() == target and isinstance(binding, dict):
                    return binding
        return {}

    async def _fetch_active_client_candidates(
        self,
    ) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
        results = await asyncio.gather(
            *(self._query_client_table(host) for host in self.caster_hosts),
            return_exceptions=True,
        )
        candidates: List[Dict[str, Any]] = []
        query_errors: List[str] = []
        successful_hosts: List[str] = []
        for host, result in zip(self.caster_hosts, results):
            if isinstance(result, BaseException):
                detail = str(result).strip() or result.__class__.__name__
                query_errors.append(f"{host}:{self.caster_port} ({detail})")
                continue
            successful_hosts.append(host)
            candidates.extend(
                self._parse_client_table(
                    result,
                    caster_host=host,
                    caster_port=self.caster_port,
                )
            )
        return candidates, successful_hosts, query_errors

    async def list_aicaster_users(self) -> List[Dict[str, Any]]:
        """Return configured AICaster users without exposing their passwords."""

        results = await asyncio.gather(
            *(self._query_user_table(host) for host in self.caster_hosts),
            return_exceptions=True,
        )
        users: List[Dict[str, Any]] = []
        successful_hosts: List[str] = []
        query_errors: List[str] = []
        for host, result in zip(self.caster_hosts, results):
            if isinstance(result, BaseException):
                detail = str(result).strip() or result.__class__.__name__
                query_errors.append(f"{host}:{self.caster_port} ({detail})")
                continue
            successful_hosts.append(host)
            users.extend(
                self._parse_user_table(
                    result,
                    caster_host=host,
                    caster_port=self.caster_port,
                )
            )
        if not successful_hosts:
            raise RuntimeError(
                "Could not query any configured AICaster user table: "
                + "; ".join(query_errors)
            )
        unique: Dict[tuple[str, str], Dict[str, Any]] = {}
        for item in users:
            key = (
                str(item.get("CasterHost") or "").casefold(),
                str(item.get("Username") or "").casefold(),
            )
            unique[key] = item
        return sorted(
            unique.values(),
            key=lambda item: (
                str(item.get("CasterHost") or "").casefold(),
                str(item.get("Username") or "").casefold(),
            ),
        )

    def _observation_matches_active_base(
        self,
        cluster: dict,
        active_base: str,
        observation: Any,
    ) -> tuple[bool, str]:
        """Verify AGRICA's reported base coordinate before assigning an edge."""

        reported = observation.base_llh
        if active_base == "BASE":
            selected_candidate = cluster.get("selected_fixed_base_candidate")
            if not isinstance(selected_candidate, dict):
                selected_candidate, selection_diagnostic = (
                    self._identify_fixed_base_candidate(cluster, observation)
                )
                if selected_candidate is None:
                    return False, selection_diagnostic
                self._lock_fixed_base_candidate(
                    cluster,
                    selected_candidate,
                    selection_diagnostic,
                )
                logger.info(
                    "Fixed-base failover selection cluster=%s: %s",
                    cluster.get("name"),
                    selection_diagnostic,
                )
            try:
                expected = self._cluster_base_llh(cluster)
            except ValueError as exc:
                return False, f"cannot verify fixed BASE: {exc}"
        else:
            cached = (
                cluster.get("temporary_base_llh_by_rover", {}).get(active_base)
                or self.rover_llh_cache.get(active_base)
            )
            if not cached:
                return False, f"cannot verify temporary base {active_base}: LLH cache is unavailable"
            expected = (
                float(cached["lat"]),
                float(cached["lon"]),
                float(cached["alt"]),
            )

        if not _is_usable_llh(reported):
            if active_base == "BASE":
                # Several UM980 rover profiles emit zeroes for BASE_lat/lon/h.
                # Never treat that as proof that the correction source is the
                # configured fixed base: after a temporary-base route closes,
                # the receiver can retain a Fixed solution from that old RTCM
                # stream for tens of seconds. Verify the baseline length against
                # the configured fixed-base-to-rover geometry instead.
                rover_llh = getattr(observation, "rover_llh", None)
                baseline_neu = getattr(observation, "baseline_neu", None)
                if not rover_llh or not baseline_neu:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                        "and missing rover_llh or baseline_neu to verify configured fixed BASE"
                    )
                rover_to_fixed_dist = _llh_horizontal_distance_m(rover_llh, expected)
                baseline_horiz_len = math.hypot(baseline_neu[0], baseline_neu[1])
                fixed_error = abs(rover_to_fixed_dist - baseline_horiz_len)
                if fixed_error > self.BASE_IDENTITY_TOLERANCE_M:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                        f"and baseline length ({baseline_horiz_len:.1f} m) does not match "
                        f"distance to configured fixed BASE ({rover_to_fixed_dist:.1f} m; "
                        f"error {fixed_error:.2f} m). The receiver may still hold the "
                        "previous temporary-base Fixed solution"
                    )
                return True, (
                    "AGRICA has no usable base_llh; baseline geometry matches configured "
                    f"fixed BASE (error {fixed_error:.2f} m)"
                )
            rover_llh = getattr(observation, "rover_llh", None)
            baseline_neu = getattr(observation, "baseline_neu", None)
            if not rover_llh or not baseline_neu:
                return False, (
                    f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                    f"and missing rover_llh or baseline_neu to verify expected base"
                )
            
            rover_to_expected_dist = _llh_horizontal_distance_m(rover_llh, expected)
            baseline_horiz_len = math.hypot(baseline_neu[0], baseline_neu[1])
            fixed_base = self._cluster_base_llh(cluster)
            rover_to_fixed_dist = _llh_horizontal_distance_m(rover_llh, fixed_base)
            expected_error = abs(rover_to_expected_dist - baseline_horiz_len)
            fixed_error = abs(rover_to_fixed_dist - baseline_horiz_len)

            if fixed_error + 1.0 < expected_error:
                return False, (
                    f"rejected {observation.rover_name}: baseline vector still matches fixed BASE; "
                    f"fixed-BASE error={fixed_error:.2f} m, temporary-base error={expected_error:.2f} m"
                )
            
            if expected_error > self.BASE_IDENTITY_TOLERANCE_M:
                return False, (
                    f"rejected {observation.rover_name}: missing base_llh, and baseline length "
                    f"({baseline_horiz_len:.1f} m) does not match distance to expected base {active_base} "
                    f"({rover_to_expected_dist:.1f} m)"
                )

            return True, (
                f"baseline vector matches temporary base {active_base} "
                f"(error {expected_error:.2f} m; fixed-BASE error={fixed_error:.2f} m)"
            )

        separation = _llh_horizontal_distance_m(reported, expected)
        height_delta = abs(float(reported[2]) - float(expected[2]))
        if active_base != "BASE":
            try:
                fixed_base = self._cluster_base_llh(cluster)
            except ValueError:
                fixed_base = None
            if fixed_base is not None:
                fixed_base_separation = _llh_horizontal_distance_m(reported, fixed_base)
                if fixed_base_separation + 1.0 < separation:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA base_llh matches fixed BASE "
                        f"({fixed_base_separation:.2f} m) more closely than temporary base "
                        f"{active_base} ({separation:.2f} m); correction source has not switched yet"
                    )
        if separation > self.BASE_IDENTITY_TOLERANCE_M:
            return False, (
                f"rejected {observation.rover_name}: AGRICA base_llh is {separation:.2f} m horizontally "
                f"from expected {active_base} (limit {self.BASE_IDENTITY_TOLERANCE_M:.1f} m); "
                "correction source has not switched yet or this is a transition fragment"
            )

        # A matching BASE_lat/lon alone is not enough during a caster handover:
        # a receiver can briefly combine a new/stale metadata sentence with a
        # baseline vector from the previous correction stream. Independently
        # estimate the horizontal base-to-rover distance and require the AGRICA
        # N/E vector length to agree before admitting this epoch to the seed.
        geometry_diagnostic = ""
        if active_base == "BASE" and cluster.get("require_fixed_base_length_check"):
            rover_llh = getattr(observation, "rover_llh", None)
            baseline_neu = getattr(observation, "baseline_neu", None)
            if not _is_usable_llh(rover_llh) or not baseline_neu:
                return False, (
                    f"rejected {observation.rover_name}: fixed-base identity matched, "
                    "but rover_llh or baseline_neu is unavailable for the mandatory "
                    "baseline-length handover check"
                )
            estimated_length = _llh_horizontal_distance_m(expected, rover_llh)
            measured_length = math.hypot(
                float(baseline_neu[0]),
                float(baseline_neu[1]),
            )
            length_error = abs(estimated_length - measured_length)
            if length_error > self.FIXED_BASE_LENGTH_TOLERANCE_M:
                return False, (
                    f"rejected {observation.rover_name}: base coordinate matches {active_base}, "
                    f"but baseline horizontal length is {measured_length:.1f} m while "
                    f"selected-base geometry estimates {estimated_length:.1f} m "
                    f"(error {length_error:.2f} m, limit "
                    f"{self.FIXED_BASE_LENGTH_TOLERANCE_M:.1f} m); rover is probably still "
                    "using the previous RTCM source"
                )
            geometry_diagnostic = (
                f", baseline length {measured_length:.1f}/{estimated_length:.1f} m "
                f"(error {length_error:.2f} m)"
            )
        return True, (
            f"verified base {active_base} (horizontal delta {separation:.2f} m, "
            f"height delta {height_delta:.2f} m{geometry_diagnostic})"
        )

    def _clear_cluster_fragment_buffers(self, project_id: int, cluster: dict) -> None:
        for station_id in cluster.get("stations", []):
            self._agrica_fragment_buffers.pop((int(project_id), int(station_id)), None)

    async def _query_client_table(self, caster_host: str) -> str:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(caster_host, self.caster_port),
                timeout=10.0,
            )
            writer.write(b"GET /clienttable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=10.0)
            return data.decode(errors="ignore")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _query_user_table(self, caster_host: str) -> str:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(caster_host, self.caster_port),
                timeout=10.0,
            )
            writer.write(b"GET /usertable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=10.0)
            return data.decode(errors="ignore")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    @staticmethod
    def _parse_user_table(
        user_table: str,
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        users = []
        for line in user_table.strip().splitlines():
            parts = [part.strip() for part in line.split(";")]
            if len(parts) <= 3 or parts[0] != "STR" or not parts[1]:
                continue
            # parts[2] is the password. It is intentionally discarded here and
            # must never leave the backend API.
            users.append({
                "Username": parts[1],
                "Mountpoints": [
                    mountpoint.strip()
                    for mountpoint in parts[3].split(",")
                    if mountpoint.strip()
                ],
                "Status": parts[5] if len(parts) > 5 else "",
                "Identifier": parts[6] if len(parts) > 6 else "",
                "ActiveClientCount": parts[7] if len(parts) > 7 else "",
                "CasterHost": caster_host,
                "CasterPort": caster_port,
            })
        return users

    @staticmethod
    def _parse_client_table(
        client_table: str,
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        candidates = []
        for line in client_table.strip().splitlines():
            parts = [part.strip() for part in line.split(";")]
            if len(parts) <= 4 or parts[0] != "STR":
                continue
            candidates.append({
                "Username": parts[1],
                "receiverID": parts[2],
                "Mountpoint": parts[3],
                "CasterHost": caster_host,
                "CasterPort": caster_port,
            })
        return candidates

    @staticmethod
    def _select_client_candidate(
        candidates: List[Dict[str, Any]],
        station_code: str,
    ) -> Optional[Dict[str, Any]]:
        target = station_code.strip().lower()
        exact_matches = []
        fuzzy_matches = []
        for candidate in candidates:
            username = candidate["Username"]
            receiver_id = candidate["receiverID"]
            mountpoint = candidate["Mountpoint"]
            # Depending on the AICaster build, the station code can be exposed
            # as Username, receiverID, or Mountpoint.
            fields = {username.lower(), receiver_id.lower(), mountpoint.lower()}
            if target in fields:
                exact_matches.append(candidate)
            elif any(target in field for field in fields):
                fuzzy_matches.append(candidate)

        if exact_matches:
            return exact_matches[0]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]
        if len(fuzzy_matches) > 1:
            logger.error(
                "Ambiguous AICaster client sessions for %s: %s",
                station_code,
                [item["Mountpoint"] for item in fuzzy_matches],
            )
        return None

    @classmethod
    def _select_client_info(cls, client_table: str, station_code: str) -> Optional[Dict[str, Any]]:
        """Compatibility helper used by focused parser tests."""

        return cls._select_client_candidate(cls._parse_client_table(client_table), station_code)

    async def _send_set_command(
        self,
        mountpoint: str,
        username: str,
        receiver_id: str,
        commands: List[bytes],
        password: str = "12345",
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
        wait_for_command_response: bool = True,
        # Field MQTT command ACKs commonly arrive around 8.1--8.3 seconds.
        # Twelve seconds avoids an unnecessary duplicate idempotent command
        # while retaining bounded retries for a genuinely lost response.
        command_response_timeout: float = 12.0,
        ack_station_code: Optional[str] = None,
        optional_unacknowledged_commands: Optional[List[str]] = None,
    ) -> bool:
        """Send a Caster SET request and Unicore commands to the selected rover."""
        target_host = caster_host or self.caster_host
        target_port = int(caster_port or self.caster_port)
        self._last_set_error = None
        self._last_set_response = None
        self._last_set_warnings = []
        optional_commands = {
            _normalized_receiver_command(command)
            for command in (optional_unacknowledged_commands or [])
        }
        writer = None
        active_mqtt_waiter = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=10.0,
            )
            auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = (
                f"SET /{mountpoint} HTTP/1.1\r\n"
                f"Authorization: Basic {auth_str}\r\n"
                f"User-Agent: NTRIP Client/1.0/{receiver_id}\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"\r\n"
            )
            logger.info(
                "SET request target=%s:%s/%s username=%s receiverID=%s command_count=%s",
                target_host,
                target_port,
                mountpoint,
                username,
                receiver_id,
                len(commands),
            )
            writer.write(headers.encode("ascii"))
            await writer.drain()
            response = (
                await asyncio.wait_for(reader.read(1024), timeout=10.0)
            ).decode("ascii", errors="ignore")
            self._last_set_response = " ".join(response.strip().split()) or "empty response"
            logger.info(
                "SET response target=%s:%s/%s response=%s",
                target_host,
                target_port,
                mountpoint,
                self._last_set_response[:500],
            )
            if "200 OK" not in response:
                self._last_set_error = (
                    f"{target_host}:{target_port} mountpoint={mountpoint} "
                    f"username={username} auth={'enabled' if password else 'disabled'} "
                    f"response={self._last_set_response[:500]}"
                )
                logger.error("SET request rejected by Caster: %s", self._last_set_error)
                return False
            for command in commands:
                command_str = command.decode("ascii", errors="replace").strip()
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    logger.info("SET Unicore command mountpoint=%s command=%s (Attempt %d/%d)", mountpoint, command_str, attempt, max_retries)
                    mqtt_waiter = None
                    if wait_for_command_response and ack_station_code:
                        mqtt_waiter = self._register_command_ack_waiter(
                            ack_station_code,
                            command_str,
                        )
                        active_mqtt_waiter = mqtt_waiter
                    normalized_command = _normalized_receiver_command(command_str)
                    is_optional_command = normalized_command in optional_commands
                    if normalized_command.startswith("mode "):
                        burst_count = self.MODE_COMMAND_BURST_COUNT
                    elif normalized_command == "unlogall":
                        # UNLOGALL is idempotent, and field links occasionally
                        # lose its first command/ACK. A bounded burst avoids an
                        # otherwise unnecessary full response-timeout delay.
                        burst_count = self.UNLOGALL_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("gpgga "):
                        # A field rotation showed that the first GPGGA enable can
                        # be dropped immediately after UNLOGALL.  Use the same
                        # bounded, ACK-aware recovery pattern as AGRICA so rover
                        # telemetry is restored without waiting through several
                        # full command retries.
                        burst_count = self.GPGGA_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("agrica "):
                        # Field UM980 units can ignore an isolated AGRICA enable
                        # immediately after UNLOGALL/mode changes. A short burst
                        # matches the reliable manual recovery procedure and is
                        # stopped as soon as the MQTT command ACK arrives.
                        burst_count = self.AGRICA_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("rtcm"):
                        burst_count = self.RTCM_COMMAND_BURST_COUNT
                    else:
                        burst_count = 1
                    # Bursts are an MQTT-ACK recovery mechanism.  Legacy/socket
                    # response callers have no asynchronous ACK signal that can
                    # stop a burst, so preserve their one-command exchange.
                    if mqtt_waiter is None:
                        burst_count = 1

                    for burst_index in range(1, burst_count + 1):
                        logger.info(
                            "SET command burst mountpoint=%s command=%s shot=%d/%d",
                            mountpoint,
                            command_str,
                            burst_index,
                            burst_count,
                        )
                        writer.write(command)
                        await writer.drain()
                        if burst_index >= burst_count:
                            break
                        await asyncio.sleep(self.COMMAND_BURST_INTERVAL_SECONDS)
                        if mqtt_waiter is not None and mqtt_waiter.future.done():
                            break
                    if wait_for_command_response:
                        try:
                            if mqtt_waiter is not None:
                                mqtt_result = await asyncio.wait_for(
                                    mqtt_waiter.future,
                                    timeout=(
                                        min(command_response_timeout, 3.0)
                                        if is_optional_command
                                        else command_response_timeout
                                    ),
                                )
                                success = bool(mqtt_result["accepted"])
                                rejected = not success
                                compact_response = (
                                    f"MQTT topic={mqtt_result['topic']} "
                                    f"echo={mqtt_result['command']} "
                                    f"response={mqtt_result['response']} "
                                    f"raw={mqtt_result.get('raw_response', mqtt_result['response'])}"
                                )
                            else:
                                end_time = asyncio.get_event_loop().time() + command_response_timeout
                                accumulated = ""
                                success = False
                                rejected = False

                                while asyncio.get_event_loop().time() < end_time:
                                    timeout_left = max(0.1, end_time - asyncio.get_event_loop().time())
                                    try:
                                        chunk = await asyncio.wait_for(reader.read(1024), timeout=timeout_left)
                                        if not chunk:
                                            break
                                        accumulated += chunk.decode("ascii", errors="ignore")
                                    except asyncio.TimeoutError:
                                        break

                                    upper_acc = accumulated.upper()
                                    if any(marker in upper_acc for marker in ("ERROR", "FAILED", "INVALID", "NO FUNCTION")):
                                        rejected = True
                                        break
                                    if "OK" in upper_acc:
                                        success = True
                                        break

                                compact_response = " ".join(accumulated.split())
                            self._last_set_response = compact_response
                            
                            if success:
                                logger.info(
                                    "SET receiver response mountpoint=%s command=%s response=%s",
                                    mountpoint,
                                    command_str,
                                    compact_response[:500],
                                )
                                break  # Break retry loop and proceed to next command
                                
                            if rejected:
                                logger.warning(
                                    "Command rejected mountpoint=%s command=%s response=%s",
                                    mountpoint,
                                    command_str,
                                    compact_response[:500],
                                )
                            else:
                                logger.warning(
                                    "No OK response for mountpoint=%s command=%s (attempt %d). Got: %s",
                                    mountpoint,
                                    command_str,
                                    attempt,
                                    compact_response[:500] or "empty",
                                )
                                
                            if attempt == max_retries:
                                failure_detail = (
                                    f"receiver rejected or ignored command {command_str}: "
                                    f"{compact_response[:500]}"
                                )
                                if is_optional_command:
                                    self._last_set_warnings.append(failure_detail)
                                    logger.warning(
                                        "Optional RTCM command was not acknowledged; continuing with MSM4 fallback: %s",
                                        failure_detail,
                                    )
                                    break
                                self._last_set_error = failure_detail
                                return False
                            await asyncio.sleep(1.0)
                        except Exception as loop_err:
                            response_error = str(loop_err).strip() or loop_err.__class__.__name__
                            if is_optional_command:
                                logger.warning(
                                    "No MQTT ACK yet for optional RTCM command %s: %s",
                                    command_str,
                                    response_error,
                                )
                            else:
                                logger.error(
                                    "Error reading command response for %s: %s",
                                    command_str,
                                    response_error,
                                )
                            if attempt == max_retries:
                                failure_detail = (
                                    f"no verified MQTT ACK for command {command_str} "
                                    f"from station {ack_station_code}: {loop_err.__class__.__name__}"
                                    if ack_station_code
                                    else str(loop_err)
                                )
                                if is_optional_command:
                                    self._last_set_warnings.append(failure_detail)
                                    logger.warning(
                                        "Optional RTCM command timed out; continuing with MSM4 fallback: %s",
                                        failure_detail,
                                    )
                                    break
                                self._last_set_error = failure_detail
                                return False
                        finally:
                            if mqtt_waiter is not None:
                                self._remove_command_ack_waiter(mqtt_waiter)
                                active_mqtt_waiter = None
                    else:
                        await asyncio.sleep(0.1)
                        break  # No need to retry if we don't wait for response
            return True
        except Exception as exc:
            if active_mqtt_waiter is not None:
                self._remove_command_ack_waiter(active_mqtt_waiter)
                active_mqtt_waiter = None
            detail = str(exc).strip() or exc.__class__.__name__
            self._last_set_error = (
                f"{target_host}:{target_port} mountpoint={mountpoint} "
                f"username={username} auth={'enabled' if password else 'disabled'} "
                f"error={detail}"
            )
            logger.error(
                "Error sending SET command to %s via %s:%s: %s",
                mountpoint,
                target_host,
                target_port,
                detail,
            )
            return False
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _reset_cross_rovers_for_temporary_base(
        self,
        *,
        temporary_base_code: str,
        target_rovers: Optional[Iterable[str]],
        project_id: Optional[int],
    ) -> None:
        """Reboot rover clients after the temporary RTCM source is live."""

        temporary_base_key = str(temporary_base_code).casefold()
        reset_targets = [
            str(name)
            for name in sorted(set(target_rovers or ()))
            if str(name).casefold() != temporary_base_key
        ]
        if not reset_targets:
            return

        await self._emit_progress(
            project_id,
            (
                f"{temporary_base_code}: temporary RTCM source is live; sending RESET "
                f"to rover clients {', '.join(reset_targets)} to reacquire FIXED faster."
            ),
        )
        for rover_code in reset_targets:
            try:
                client_info = await self._find_client_info(
                    rover_code,
                    project_id=project_id,
                    log_missing=False,
                )
                if not client_info:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: could not RESET {rover_code}; "
                            "no active AICaster client session was found."
                        ),
                    )
                    continue
                mountpoint = str(client_info.get("Mountpoint") or "").strip()
                if not mountpoint:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: could not RESET {rover_code}; "
                            "AICaster client session has no mountpoint."
                        ),
                    )
                    continue
                accepted = await self._send_set_command(
                    mountpoint,
                    client_info.get("Username", rover_code),
                    client_info.get("receiverID", ""),
                    [b"RESET\r\n"],
                    password=self.control_password,
                    caster_host=client_info.get("CasterHost"),
                    caster_port=client_info.get("CasterPort"),
                    wait_for_command_response=False,
                )
                if accepted:
                    await self._emit_progress(
                        project_id,
                        f"{temporary_base_code}: RESET sent to rover client {rover_code}.",
                    )
                else:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: RESET was not accepted for "
                            f"{rover_code}: {self._last_set_error or 'no Caster response'}."
                        ),
                    )
            except Exception as exc:
                logger.warning(
                    "Could not send temporary-base RESET to rover=%s via base=%s: %s",
                    rover_code,
                    temporary_base_code,
                    exc,
                )
                await self._emit_progress(
                    project_id,
                    (
                        f"{temporary_base_code}: RESET failed for {rover_code}: "
                        f"{str(exc) or exc.__class__.__name__}."
                    ),
                )

    async def _restore_rover_output_sequence(
        self,
        *,
        rover_code: str,
        mountpoint: str,
        client_info: Dict[str, Any],
        commands: List[bytes],
        project_id: Optional[int],
        max_attempts: int = 3,
    ) -> None:
        """Restore ROVER mode/output, requiring ACKs for every state-changing step.

        Some UM980 units apply ``saveconfig`` but emit no command response while
        writing flash.  Once all preceding ROVER/output commands were verified,
        a missing ACK for that final persistence-only command must not falsely
        report that the receiver is still in BASE mode.
        """

        safe_max_attempts = max(1, int(max_attempts))
        for command_index, command in enumerate(commands, start=1):
            command_text = command.decode("ascii", errors="replace").strip()
            attempt = 0
            attempt_limit = safe_max_attempts
            while attempt < attempt_limit:
                attempt += 1
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: restore step {command_index}/{len(commands)} "
                        f"{command_text} (attempt {attempt}); waiting for receiver response."
                    ),
                )
                acknowledged = await self._send_set_command(
                    mountpoint,
                    client_info.get("Username", rover_code),
                    client_info.get("receiverID", ""),
                    [command],
                    password=self.control_password,
                    caster_host=client_info.get("CasterHost"),
                    caster_port=client_info.get("CasterPort"),
                    wait_for_command_response=True,
                    ack_station_code=rover_code,
                )
                if acknowledged:
                    await self._emit_progress(
                        project_id,
                        f"{rover_code}: ACK received for {command_text}.",
                    )
                    break
                detail = self._last_set_error or "no receiver response"
                set_transport_failure = (
                    "mountpoint=" in detail.casefold()
                    and any(
                        marker in detail.casefold()
                        for marker in ("response=", "error=")
                    )
                )
                if set_transport_failure:
                    attempt_limit = max(
                        safe_max_attempts,
                        int(self.ROVER_RESTORE_TRANSPORT_ATTEMPTS),
                    )
                else:
                    attempt_limit = safe_max_attempts
                logger.warning(
                    "Rover restore retry rover=%s command=%s attempt=%s/%s "
                    "transport_failure=%s detail=%s",
                    rover_code,
                    command_text,
                    attempt,
                    attempt_limit,
                    set_transport_failure,
                    detail,
                )
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: AICaster SET session is not ready for "
                        f"{command_text}; retrying in "
                        f"{self.ROVER_RESTORE_RETRY_SECONDS:g}s ({detail})."
                        if set_transport_failure
                        else f"{rover_code}: no ACK for {command_text}; retrying in "
                        f"{self.ROVER_RESTORE_RETRY_SECONDS:g}s ({detail})."
                    ),
                )
                if attempt < attempt_limit:
                    await asyncio.sleep(self.ROVER_RESTORE_RETRY_SECONDS)
                    if set_transport_failure:
                        try:
                            refreshed_client = await self._find_client_info(
                                rover_code,
                                project_id=project_id,
                                log_missing=False,
                            )
                        except Exception as refresh_exc:
                            logger.warning(
                                "Could not refresh AICaster client session while restoring "
                                "%s: %s",
                                rover_code,
                                str(refresh_exc) or refresh_exc.__class__.__name__,
                            )
                        else:
                            if refreshed_client:
                                client_info = refreshed_client
                                refreshed_mountpoint = str(
                                    refreshed_client.get("Mountpoint") or ""
                                ).strip()
                                if refreshed_mountpoint:
                                    mountpoint = refreshed_mountpoint
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: refreshed AICaster SET session "
                                        f"username={client_info.get('Username')} "
                                        f"receiverID={client_info.get('receiverID')} "
                                        f"mountpoint={mountpoint}; retrying {command_text}."
                                    ),
                                )
            else:
                is_optional_undulation = (
                    command_index > 1
                    and command_text.lower().startswith("config undulation ")
                )
                if is_optional_undulation:
                    detail = self._last_set_error or "no receiver response"
                    logger.warning(
                        "ROVER mode verified for %s, but optional undulation command "
                        "was not acknowledged; continuing to mandatory UNLOGALL and "
                        "AGRICA recovery. detail=%s",
                        rover_code,
                        detail,
                    )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: optional {command_text} was not ACKed; "
                            "continuing with mandatory BASE-log shutdown and ROVER outputs."
                        ),
                    )
                    continue
                is_final_saveconfig = (
                    command_index == len(commands)
                    and command_index > 1
                    and command_text.lower() == "saveconfig"
                )
                if is_final_saveconfig:
                    detail = self._last_set_error or "no receiver response"
                    logger.warning(
                        "ROVER mode/output verified for %s, but saveconfig ACK was not "
                        "received after %s attempt(s); continuing because saveconfig "
                        "does not change receiver mode. detail=%s",
                        rover_code,
                        attempt,
                        detail,
                    )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: ROVER mode and AGRICA output restored; "
                            "saveconfig was sent but its ACK was not observed. "
                            "Continuing with the verified ROVER state."
                        ),
                    )
                    return
                if set_transport_failure:
                    raise RuntimeError(
                        f"AICaster SET session for {rover_code} was not ready after "
                        f"{attempt} attempt(s); {command_text} was not sent: "
                        f"{self._last_set_error or 'no Caster response'}"
                    )
                raise RuntimeError(
                    f"{command_text} was not acknowledged after {attempt} attempt(s): "
                    f"{self._last_set_error or 'no receiver response'}"
                )

    def _build_unicore_base_config(
        self,
        setup_method: str,
        duration: int = 60,
        lat: float = 0,
        lon: float = 0,
        alt: float = 0,
        ecef_xyz: Optional[Iterable[float]] = None,
    ) -> list[bytes]:
        """Build a deterministic UM980 base profile for the COM2 MQTT bridge.

        Temporary bases start from a persisted rover profile which normally has
        GPGGA and AGRICA enabled.  Clear those rover logs *before* entering BASE
        mode, then keep the documented MODE BASE -> RTCM -> SAVECONFIG sequence
        contiguous.  Some field units continued to emit no-fix GGA only when
        UNLOGALL was inserted after MODE BASE, despite ACKing every RTCM command.
        MSM7 and ephemeris logs are intentionally omitted here: the four MSM4
        streams are sufficient for the short cross-baseline rotation and fit
        comfortably on every supported COM2 baud rate.
        """
        commands = [b"unlogall\r\n"]
        port = "com2"
        if setup_method.upper() == "SURVEY_IN":
            commands.append(f"mode base time {duration}\r\n".encode("ascii"))
        elif ecef_xyz is not None:
            xyz = tuple(float(value) for value in ecef_xyz)
            if (
                len(xyz) != 3
                or not all(math.isfinite(value) for value in xyz)
                or _vector_length(xyz) < 1_000_000.0
            ):
                raise ValueError("ecef_xyz must contain a usable Earth-centered XYZ coordinate")
            # N4 receivers distinguish ECEF from geodetic MODE BASE by param1:
            # an X coordinate outside latitude range [-90, 90] selects ECEF.
            # Four decimals preserve 0.1 mm while matching the official examples.
            commands.append(
                f"mode base {xyz[0]:.4f} {xyz[1]:.4f} {xyz[2]:.4f}\r\n".encode(
                    "ascii"
                )
            )
        else:
            # Unicore MODE BASE interprets its height as altitude unless the
            # undulation is explicitly zero. ``alt`` here is WGS84 ellipsoidal
            # height derived from AGRICA ECEF, so bind the datum before MODE BASE.
            commands.append(b"config undulation 0.0\r\n")
            commands.append(f"mode base {lat} {lon} {alt}\r\n".encode("ascii"))
        for message, interval in (
            ("1006", 10),
            ("1033", 10),
            ("1074", 1),
            ("1124", 1),
            ("1084", 1),
            ("1094", 1),
        ):
            commands.append(f"rtcm{message} {port} {interval}\r\n".encode("ascii"))
        commands.append(b"saveconfig\r\n")
        return commands

    @staticmethod
    def _build_unicore_rover_config(
        restore_undulation: Optional[float] = None,
    ) -> list[bytes]:
        """Restore UM980 rover output after one temporary-base collection."""

        undulation = "auto"
        if restore_undulation is not None:
            try:
                numeric_undulation = float(restore_undulation)
            except (TypeError, ValueError):
                numeric_undulation = math.nan
            if math.isfinite(numeric_undulation) and -1000.0 <= numeric_undulation <= 1000.0:
                # N4 command manual specifies four decimal places for a
                # user-supplied geoid separation.
                undulation = f"{numeric_undulation:.4f}"
        return [
            b"mode rover survey\r\n",
            f"config undulation {undulation}\r\n".encode("ascii"),
            b"unlogall\r\n",
            b"gpgga com2 1\r\n",
            b"AGRICA COM2 1\r\n",
            b"saveconfig\r\n",
        ]
