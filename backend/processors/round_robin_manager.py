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
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np
from scipy.stats import chi2

logger = logging.getLogger(__name__)


_ESS_MIN_SESSION_SAMPLES = 8
_ESS_MAX_CONTIGUOUS_GAP_SECONDS = 5
_BASELINE_STD_REJECTION_THRESHOLD_M = 0.1


def _ar1_effective_sample_size(sample_count: int, lag_one_correlation: float) -> float:
    """Finite-sample ESS of a mean under a stationary AR(1) correlation model."""

    if sample_count <= 1:
        return 1.0
    rho = min(0.99, max(0.0, float(lag_one_correlation)))
    variance_inflation = 1.0 + 2.0 * sum(
        (1.0 - lag / sample_count) * rho**lag
        for lag in range(1, sample_count)
    )
    return min(
        float(sample_count),
        max(1.0, float(sample_count) / max(1.0, variance_inflation)),
    )


def _initial_positive_sequence_ess(
    values: List[float],
    fallback_lag_one_correlation: Optional[float] = None,
) -> float:
    """Estimate effective samples using a monotone initial-positive ACF sum.

    Short series cannot support a stable autocorrelation estimate and therefore
    count as one conservative independent observation.  For longer series the
    integrated autocorrelation time is estimated from positive adjacent ACF
    pairs and ESS is clamped to ``[1, n]``.
    """

    series = np.asarray(values, dtype=float)
    sample_count = int(series.size)
    if sample_count < _ESS_MIN_SESSION_SAMPLES:
        return (
            _ar1_effective_sample_size(sample_count, fallback_lag_one_correlation)
            if fallback_lag_one_correlation is not None
            else 1.0
        )
    centered = series - float(np.mean(series))
    denominator = float(centered @ centered)
    if not math.isfinite(denominator) or denominator <= np.finfo(float).eps:
        return (
            _ar1_effective_sample_size(sample_count, fallback_lag_one_correlation)
            if fallback_lag_one_correlation is not None
            else 1.0
        )

    autocorrelations = [1.0]
    for lag in range(1, sample_count):
        autocorrelations.append(
            float(centered[:-lag] @ centered[lag:] / denominator)
        )

    positive_pair_sum = 0.0
    previous_pair = math.inf
    for lag in range(1, sample_count - 1, 2):
        pair = autocorrelations[lag] + autocorrelations[lag + 1]
        if not math.isfinite(pair) or pair <= 0.0:
            break
        # Initial monotone sequence: sampling noise must not make later ACF
        # pairs larger than earlier ones.
        pair = min(pair, previous_pair)
        previous_pair = pair
        positive_pair_sum += pair

    integrated_autocorrelation_time = max(1.0, 1.0 + 2.0 * positive_pair_sum)
    return min(
        float(sample_count),
        max(1.0, float(sample_count) / integrated_autocorrelation_time),
    )


def _split_effective_sample_sessions(rows: List[dict]) -> List[List[dict]]:
    """Split an edge stream at route/direction changes and material time gaps."""

    sessions: List[List[dict]] = []
    current: List[dict] = []
    previous: Optional[dict] = None
    for row in rows:
        epoch = row.get("observation_epoch")
        starts_new_session = False
        if previous is not None:
            previous_epoch = previous.get("observation_epoch")
            if row.get("session_id") != previous.get("session_id"):
                starts_new_session = True
            elif row.get("direction") != previous.get("direction"):
                starts_new_session = True
            elif epoch is not None and previous_epoch is not None:
                gap = int(epoch) - int(previous_epoch)
                starts_new_session = (
                    gap < 0 or gap > _ESS_MAX_CONTIGUOUS_GAP_SECONDS
                )
        if starts_new_session and current:
            sessions.append(current)
            current = []
        current.append(row)
        previous = row
    if current:
        sessions.append(current)
    return sessions


def _pooled_lag_one_autocorrelations(
    grouped_rows: Dict[tuple[str, str], List[dict]],
) -> tuple[float, float, float]:
    """Pool long sessions to stabilize correlation for short cross-baselines."""

    numerators = np.zeros(3, dtype=float)
    denominators = np.zeros(3, dtype=float)
    for rows in grouped_rows.values():
        for session_rows in _split_effective_sample_sessions(rows):
            if len(session_rows) < _ESS_MIN_SESSION_SAMPLES:
                continue
            vectors = np.vstack([row["delta"] for row in session_rows])
            centered = vectors - np.mean(vectors, axis=0)
            numerators += np.sum(centered[:-1] * centered[1:], axis=0)
            denominators += np.sum(centered[:-1] * centered[:-1], axis=0)
    return tuple(
        min(0.99, max(0.0, float(numerators[axis] / denominators[axis])))
        if denominators[axis] > np.finfo(float).eps else 0.0
        for axis in range(3)
    )


def _edge_effective_sample_size(
    rows: List[dict],
    pooled_lag_one_autocorrelations: Optional[tuple[float, float, float]] = None,
) -> tuple[float, List[dict]]:
    """Estimate ESS per contiguous direction/session and sum independent runs."""

    if not rows:
        return 0.0, []

    sessions = _split_effective_sample_sessions(rows)

    diagnostics = []
    effective_sample_size = 0.0
    for session_index, session_rows in enumerate(sessions, 1):
        component_ess = [
            _initial_positive_sequence_ess([
                float(row["delta"][axis]) for row in session_rows
            ], (
                pooled_lag_one_autocorrelations[axis]
                if pooled_lag_one_autocorrelations is not None else None
            ))
            for axis in range(3)
        ]
        # A scalar inflation keeps the 3x3 covariance positive definite; use
        # the weakest ECEF component so published precision is not optimistic.
        session_ess = min(component_ess)
        effective_sample_size += session_ess
        diagnostics.append({
            "session": session_index,
            "observation_count": len(session_rows),
            "effective_sample_size": session_ess,
            "component_effective_sample_sizes": component_ess,
            "start_epoch": session_rows[0].get("observation_epoch"),
            "end_epoch": session_rows[-1].get("observation_epoch"),
            "direction": session_rows[0].get("direction"),
        })

    return min(float(len(rows)), max(1.0, effective_sample_size)), diagnostics


@dataclass(frozen=True)
class _CollectedObservation:
    """An AGRICA observation tagged with the rover acting as its base."""

    base_name: str
    observation: Any


@dataclass
class _CommandAckWaiter:
    """One receiver command awaiting echo and ACK on its GNSS MQTT topic."""

    station_code: str
    command: str
    future: asyncio.Future
    topic: Optional[str] = None
    echo_seen: bool = False


class _SafeRoverRotationSkip(RuntimeError):
    """A rover rotation failed after the receiver was confirmed safe in ROVER mode."""


_COMMAND_RESPONSE_RE = re.compile(
    r"\$COMMAND\s*,\s*(?P<command>.*?)\s*,\s*RESPONSE\s*:\s*(?P<response>[^*\r\n]+)",
    re.IGNORECASE,
)


def _normalized_receiver_command(value: Any) -> str:
    """Normalize command text without losing parameter-level identity."""

    return " ".join(str(value or "").strip().split()).casefold()


def _receiver_response_result(response: str) -> Optional[bool]:
    """Return True for ACK, False for an explicit receiver rejection."""

    upper = " ".join(str(response or "").strip().upper().split())
    if upper == "OK" or upper.startswith("OK "):
        return True
    if any(
        upper == marker or upper.startswith(f"{marker} ")
        for marker in (
            "ERROR",
            "FAILED",
            "INVALID",
            "NO FUNCTION",
            "NO FUNC",
            "NOFUNC",
            "NO MATCHING FUNC",
            "NO MATCHING FUNCTION",
        )
    ):
        return False
    return None


def _is_usable_llh(llh: Optional[tuple[float, float, float]]) -> bool:
    if llh is None:
        return False
    lat, lon, height = llh
    if not all(math.isfinite(value) for value in (lat, lon, height)):
        return False
    # UM980 uses 0,0,0 when no base coordinate is available.  It is not useful
    # for converting an N/E/U vector into ECEF in this workflow.
    if abs(lat) < 1e-12 and abs(lon) < 1e-12 and abs(height) < 1e-12:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _llh_horizontal_distance_m(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    """Horizontal separation used to identify a correction BASE.

    AGRICA and GGA heights may use ellipsoidal and MSL datums respectively;
    their geoid-sized height difference must not make the same BASE look like a
    different station.
    """

    mean_latitude = math.radians((float(first[0]) + float(second[0])) / 2.0)
    north = math.radians(float(first[0]) - float(second[0])) * 6378137.0
    east = (
        math.radians(float(first[1]) - float(second[1]))
        * 6378137.0
        * math.cos(mean_latitude)
    )
    return math.hypot(north, east)


def _ecef_to_llh(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert WGS84 ECEF metres to latitude, longitude and ellipsoidal height."""

    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f**2
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    height = 0.0
    for _ in range(8):
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1 - e2 * sin_lat**2)
        height = p / max(math.cos(lat), 1e-15) - n
        next_lat = math.atan2(z, p * (1 - e2 * n / (n + height)))
        if abs(next_lat - lat) < 1e-13:
            lat = next_lat
            break
        lat = next_lat
    return math.degrees(lat), math.degrees(lon), height


def _neu_to_ecef_delta(
    latitude_deg: float,
    longitude_deg: float,
    north: float,
    east: float,
    up: float,
) -> tuple[float, float, float]:
    """Rotate a local N/E/U baseline into the ECEF frame at its base point."""

    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    return (
        -sin_lat * cos_lon * north - sin_lon * east + cos_lat * cos_lon * up,
        -sin_lat * sin_lon * north + cos_lon * east + cos_lat * sin_lon * up,
        cos_lat * north + sin_lat * up,
    )


def _vector_length(vector: Any) -> float:
    """Return a 3-D vector length without involving the adjustment engine."""

    return math.sqrt(sum(float(value) ** 2 for value in vector))


def _canonical_baseline(
    start: str,
    end: str,
    vector: Any,
) -> tuple[tuple[str, str], tuple[float, float, float], int]:
    """Return a stable undirected edge key and a consistently signed vector."""

    start, end = str(start), str(end)
    values = tuple(float(value) for value in vector)
    if start == "BASE" or (end != "BASE" and start <= end):
        return (start, end), values, 1
    return (end, start), tuple(-value for value in values), -1


def _graph_components(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]],
) -> list[set[str]]:
    """Return case-insensitive connected components using configured node names."""

    name_by_key = {str(node).casefold(): str(node) for node in nodes}
    adjacency = {key: set() for key in name_by_key}
    for start, end in edges:
        start_key = str(start).casefold()
        end_key = str(end).casefold()
        if start_key not in adjacency or end_key not in adjacency or start_key == end_key:
            continue
        adjacency[start_key].add(end_key)
        adjacency[end_key].add(start_key)

    components: list[set[str]] = []
    remaining = set(adjacency)
    while remaining:
        seed = next(iter(remaining))
        pending = [seed]
        component_keys: set[str] = set()
        while pending:
            key = pending.pop()
            if key in component_keys:
                continue
            component_keys.add(key)
            pending.extend(adjacency[key] - component_keys)
        remaining -= component_keys
        components.append({name_by_key[key] for key in component_keys})
    return components


def _aggregate_parallel_baselines(baselines: List[dict]) -> List[dict]:
    """Collapse repeated/reverse report rows to one arithmetic mean per edge.

    Solver input uses covariance-weighted aggregation in ``_build_cluster_result``.
    """

    groups: Dict[tuple[str, str], list[tuple[dict, int]]] = {}
    for baseline in baselines:
        key, _, direction = _canonical_baseline(
            baseline["from"], baseline["to"], baseline["observed_xyz"]
        )
        groups.setdefault(key, []).append((baseline, direction))

    averaged = []
    for (start, end), rows in groups.items():
        item = dict(rows[0][0])
        item["from"], item["to"] = start, end
        item["observation_count"] = len(rows)
        for key in ("observed_xyz", "adjusted_xyz", "residual_xyz"):
            if all(row.get(key) is not None for row, _ in rows):
                item[key] = tuple(
                    sum(direction * float(row[key][axis]) for row, direction in rows)
                    / len(rows)
                    for axis in range(3)
                )
        if all(row.get("standard_deviation_xyz") is not None for row, _ in rows):
            item["standard_deviation_xyz"] = tuple(
                sum(float(row["standard_deviation_xyz"][axis]) for row, _ in rows)
                / len(rows)
                for axis in range(3)
            )
        for key in ("velocity_up_std", "ratio"):
            values = [float(row[key]) for row, _ in rows if row.get(key) is not None]
            if values:
                item[key] = sum(values) / len(values)
        if item.get("observed_xyz") is not None:
            item["observed_length"] = _vector_length(item["observed_xyz"])
        if item.get("adjusted_xyz") is not None:
            item["adjusted_length"] = _vector_length(item["adjusted_xyz"])
        averaged.append(item)
    return averaged


def _sum_cycle_vectors(
    steps: List[tuple[int, int]], baselines: List[dict], vector_key: str
) -> tuple[float, float, float]:
    total = [0.0, 0.0, 0.0]
    for edge_index, direction in steps:
        vector = baselines[edge_index][vector_key]
        for component in range(3):
            total[component] += direction * float(vector[component])
    return total[0], total[1], total[2]


def _build_fundamental_loops(baselines: List[dict]) -> List[dict]:
    """Find a deterministic independent cycle basis for a baseline multigraph.

    This is report-only graph post-processing. Each non-tree edge closes one
    fundamental loop. Callers must aggregate repeated observations first, so a
    loop always contains distinct geometric edges (at least three points).
    """

    parent: Dict[str, str] = {}
    tree: Dict[str, List[tuple[str, int, int]]] = {}
    chords: List[int] = []

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for edge_index, baseline in enumerate(baselines):
        start, end = str(baseline["from"]), str(baseline["to"])
        root_start, root_end = find(start), find(end)
        tree.setdefault(start, [])
        tree.setdefault(end, [])
        if root_start == root_end:
            chords.append(edge_index)
            continue
        parent[root_end] = root_start
        tree[start].append((end, edge_index, 1))
        tree[end].append((start, edge_index, -1))

    loops: List[dict] = []
    for loop_number, chord_index in enumerate(chords, start=1):
        chord = baselines[chord_index]
        start, end = str(chord["from"]), str(chord["to"])
        # Close the chord start->end by finding the unique tree path end->start.
        pending = [(end, [end], [])]
        visited = set()
        path_points: List[str] = []
        path_steps: List[tuple[int, int]] = []
        while pending:
            node, points, steps = pending.pop()
            if node == start:
                path_points, path_steps = points, steps
                break
            if node in visited:
                continue
            visited.add(node)
            for neighbor, edge_index, direction in reversed(tree.get(node, [])):
                if neighbor not in visited:
                    pending.append(
                        (neighbor, points + [neighbor], steps + [(edge_index, direction)])
                    )
        if not path_points:
            continue

        cycle_steps = [(chord_index, 1)] + path_steps
        cycle_points = [start, end] + path_points[1:]
        if len(set(cycle_points)) < 3:
            # Repeated measurements of the same edge are not a geometric loop.
            continue
        observed = _sum_cycle_vectors(cycle_steps, baselines, "observed_xyz")
        adjusted = _sum_cycle_vectors(cycle_steps, baselines, "adjusted_xyz")
        total_length = sum(
            float(baselines[index]["observed_length"]) for index, _ in cycle_steps
        )
        observed_closure = _vector_length(observed)
        adjusted_closure = _vector_length(adjusted)
        loops.append({
            "loop": loop_number,
            "points": cycle_points,
            "baseline_indices": [index for index, _ in cycle_steps],
            "observed_misclosure_xyz": observed,
            "observed_closure": observed_closure,
            "adjusted_misclosure_xyz": adjusted,
            "adjusted_closure": adjusted_closure,
            "total_length": total_length,
            "observed_relative_precision": (
                total_length / observed_closure if observed_closure > 1e-15 else None
            ),
            "adjusted_relative_precision": (
                total_length / adjusted_closure if adjusted_closure > 1e-15 else None
            ),
        })
    return loops


class RoundRobinAdjustmentManager:
    """Collect base-to-rover and rover-to-rover baselines for the existing solver.

    The mathematical adjustment remains in ``gnss_adjustment.solver``.  This
    class only manages the observation lifecycle and provides that solver with
    correctly connected ECEF baselines.
    """

    SEED_COLLECTION_MAX_STEPS = 10
    BASE_IDENTITY_TOLERANCE_M = 20.0
    CROSS_BASE_SETTLE_SECONDS = 5
    CROSS_BASE_SWITCH_TIMEOUT_SECONDS = 45
    CROSS_BASE_STABLE_COLLECTION_SECONDS = 15
    CROSS_BASE_STATUS_POLL_SECONDS = 1
    CROSS_BASE_COLLECTION_ATTEMPTS = 2
    MODE_COMMAND_BURST_COUNT = 6
    UNLOGALL_COMMAND_BURST_COUNT = 3
    GPGGA_COMMAND_BURST_COUNT = 6
    AGRICA_COMMAND_BURST_COUNT = 6
    RTCM_COMMAND_BURST_COUNT = 3
    COMMAND_BURST_INTERVAL_SECONDS = 0.25
    PREFLIGHT_CONNECTION_ATTEMPTS = 2
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
        caster_host: str = "127.0.0.1",
        caster_hosts: Optional[List[str]] = None,
        caster_port: int = 2101,
        source_host: Optional[str] = None,
        source_port: int = 2101,
        control_password: str = "12345",
        source_password: str = "12345",
        web_cors_api_base_url: str = "https://cors.aitogy.com",
        web_cors_api_token: str = "",
        web_cors_api_username: str = "",
        web_cors_api_password: str = "",
        route_start_callback: Optional[Callable[[str, str, int, str, str], Any]] = None,
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
        self.web_cors_api_base_url = str(
            web_cors_api_base_url or "https://cors.aitogy.com"
        ).rstrip("/")
        self._web_cors_access_token = str(web_cors_api_token or "").strip()
        self.web_cors_api_username = str(web_cors_api_username or "").strip()
        self.web_cors_api_password = str(web_cors_api_password or "")
        self._cors_fixed_base_snapshots: Dict[tuple[str, str], Dict[str, Any]] = {}
        self.route_start_callback = route_start_callback
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
            from backend.processors.gnss_adjustment_runtime import parse_agrica
        except ModuleNotFoundError:
            from processors.gnss_adjustment_runtime import parse_agrica

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
            if observation.position_type not in (4, 7):
                ignored_reasons.append(
                    f"position_type={observation.position_type}; requires RTK Fixed (4) or Input Fixed (7)"
                )
                continue
            cluster_index = self._cluster_index_for_station(session, observation.station_id)
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
                _CollectedObservation(active_base, observation)
            )
            if max(float(value) for value in observation.std_neu) > _BASELINE_STD_REJECTION_THRESHOLD_M:
                ignored_reasons.append(
                    "baseline STD exceeds 0.1 m; stored for RAW_AUDIT but excluded from solver"
                )
                if observation.rover_llh:
                    self.update_rover_llh(
                        observation.rover_name,
                        observation.rover_llh[0],
                        observation.rover_llh[1],
                        observation.rover_llh[2],
                    )
                continue
            valid_observations.append(observation)
            accepted_diagnostics.append(base_diagnostic)
            if active_base == "BASE":
                # Count GNSS epochs, not server wall-clock seconds. MQTT can
                # deliver many buffered observations in one burst; wall-clock
                # counting made a healthy 10 Hz/1 Hz stream appear stuck at
                # step 1-4 and delayed exclusion of a genuinely silent rover.
                session["seed_collection_steps"].add(
                    int(observation.epoch_ts or time.time())
                )
            if observation.rover_llh:
                self.update_rover_llh(
                    observation.rover_name,
                    observation.rover_llh[0],
                    observation.rover_llh[1],
                    observation.rover_llh[2],
                )
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
        """Return initial baseline coverage and 10-step fallback eligibility."""
        session = self._sessions.get(project_id)
        if session is None:
            return {"complete": False, "fallback_ready": False, "step_count": 0,
                    "max_steps": self.SEED_COLLECTION_MAX_STEPS,
                    "missing_station_ids": [], "clusters": []}

        cluster_statuses = []
        missing_all = []
        complete = True
        can_continue = True
        for index, cluster in enumerate(session["clusters"]):
            fixed_base_llh = self._cluster_base_llh(cluster)
            observed = {
                record.observation.station_id
                for record in cluster["observations"]
                if record.base_name == "BASE"
                and max(
                    float(value) for value in record.observation.std_neu
                ) <= _BASELINE_STD_REJECTION_THRESHOLD_M
                and _vector_length(
                    self._baseline_ecef(record.observation, fixed_base_llh)
                ) >= 1.0
            }
            expected = set(cluster["stations"])
            missing = sorted(expected - observed)
            available = sorted(expected & observed)
            if missing:
                complete = False
                missing_all.extend(missing)
            if len(available) < 2:
                can_continue = False
            cluster_statuses.append({"index": index, "missing_station_ids": missing, "available_station_ids": available})

        steps = min(len(session["seed_collection_steps"]), self.SEED_COLLECTION_MAX_STEPS)
        return {
            "complete": complete,
            "fallback_ready": not complete and can_continue and steps >= self.SEED_COLLECTION_MAX_STEPS,
            "step_count": steps,
            "max_steps": self.SEED_COLLECTION_MAX_STEPS,
            "missing_station_ids": sorted(set(missing_all)),
            "clusters": cluster_statuses,
        }

    def skip_missing_seed_stations(self, project_id: int) -> dict:
        """Temporarily exclude no-data rovers after ten valid seed epochs."""
        session = self._sessions.get(project_id)
        status = self.get_seed_collection_status(project_id)
        if session is None or not status["fallback_ready"]:
            return status

        skipped = []
        for item in status["clusters"]:
            missing = set(item["missing_station_ids"])
            if not missing:
                continue
            cluster = session["clusters"][item["index"]]
            rover_by_station = dict(zip(cluster["stations"], cluster["rovers"], strict=True))
            cluster["stations"] = [station_id for station_id in cluster["stations"] if station_id not in missing]
            cluster["rovers"] = [rover_by_station[station_id] for station_id in cluster["stations"]]
            skipped.extend(missing)

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
        server_id: int,
        *,
        on_demand: bool,
    ) -> dict:
        """Build the same mode payload as the existing CORS S1/S2 form."""

        cfg = copy.deepcopy(service_config or {})
        global_on_demand = bool(cfg.get("stream_on_demand", False))
        global_active = bool(cfg.get("stream_active", False))
        cfg[f"server{server_id}_stream_on_demand"] = bool(on_demand)
        cfg[f"server{server_id}_stream_active"] = not bool(on_demand)

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
    ) -> tuple[str, int, dict]:
        stations = self._cors_api_request_sync("GET", "/api/public/map-stations")
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        target = str(mountpoint or "").strip().casefold()
        target_host = self._normalize_stream_host(selected_host)
        matches = []
        for station in stations or []:
            if not isinstance(station, dict):
                continue
            cfg = station.get("service_config")
            if not isinstance(cfg, dict):
                continue
            for sid in (1, 2):
                candidate = str(cfg.get(f"mountpoint{sid}") or "").strip().casefold()
                candidate_host = self._normalize_stream_host(
                    cfg.get(f"serverhost{sid}") or cfg.get(f"server{sid}_host")
                )
                if (
                    candidate
                    and candidate == target
                    and (not target_host or candidate_host == target_host)
                ):
                    matches.append((str(station.get("serial") or "").strip(), sid, cfg))
        if len(matches) != 1 or not matches[0][0]:
            raise RuntimeError(
                f"WEB CORS host={selected_host!r} mountpoint={mountpoint!r} matched "
                f"{len(matches)} streams; expected exactly one"
            )
        return matches[0]

    async def _toggle_cors_fixed_base(
        self,
        mountpoint: str,
        sleep: bool,
        selected_host: str = "",
    ) -> None:
        if not mountpoint:
            return
        snapshot_key = (
            self._normalize_stream_host(selected_host),
            str(mountpoint).strip().casefold(),
        )
        if sleep:
            if snapshot_key in self._cors_fixed_base_snapshots:
                return
            serial, server_id, original = await asyncio.to_thread(
                self._find_cors_station_sync,
                mountpoint,
                selected_host,
            )
            self._cors_fixed_base_snapshots[snapshot_key] = {
                "serial": serial,
                "server_id": server_id,
                "service_config": copy.deepcopy(original),
            }
            sleep_config = self._cors_service_config_with_server_mode(
                original,
                server_id,
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

    async def _run_cycle(self, project_id: int) -> None:
        suspended_bases: set[tuple[str, str]] = set()
        cycle_error: Optional[Exception] = None
        try:
            session = self._sessions[project_id]
            for cluster_index, cluster in enumerate(session["clusters"]):
                rovers = cluster["rovers"]
                logger.info(
                    "Starting Round-Robin project=%s cluster=%s with %s rovers: %s",
                    project_id,
                    cluster.get("name", cluster_index + 1),
                    len(rovers),
                    rovers,
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
                # This is the exact S1/S2 host selected in Project Management.
                # Do not infer server 1 from the mountpoint alone: S1 and S2 may
                # expose the same mountpoint on different caster hosts.
                configured_base_host = str(
                    cluster.get("base_stream_host") or route_host or ""
                ).strip()
                route_password = cluster.get("round_robin_route_password")
                if route_password is None:
                    route_password = self.source_password
                
                # Tạm chuyển Base cố định sang On-Demand/Sleep trước khi quay
                # vòng các rover. Trạng thái gốc được phục hồi ở finally.
                base_stream_key = (configured_base_host, str(configured_mountpoint or ""))
                if configured_mountpoint and base_stream_key not in suspended_bases:
                    await self._emit_progress(
                        project_id,
                        f"Chuyển Base cố định {configured_mountpoint} sang On-Demand/Sleep và ngắt luồng NTRIP.",
                    )
                    suspended_bases.add(base_stream_key)
                    # Add it before the API call so finally also restores a
                    # configuration when the HTTP response is lost after CORS
                    # has already accepted the change.
                    await self._toggle_cors_fixed_base(
                        configured_mountpoint,
                        sleep=True,
                        selected_host=configured_base_host,
                    )
                    # Chờ 2s để đảm bảo caster đã xử lý ngắt
                    await asyncio.sleep(2.0)
                    
                def current_solver_eligible_cross_coverage() -> tuple[set[tuple[str, str]], set[str]]:
                    edges: set[tuple[str, str]] = set()
                    participants: set[str] = set()
                    for record in cluster["observations"]:
                        observation = getattr(record, "observation", None)
                        from_name = str(getattr(record, "base_name", "") or "")
                        to_name = str(getattr(observation, "rover_name", "") or "")
                        if (
                            observation is None
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
                graph_recovery_scheduled = False
                for rotation_index, rover_code in enumerate(rotation_queue):
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
                        }

                    def mark_collection_started(
                        *,
                        current_cluster_index: int = cluster_index,
                        current_cluster: dict = cluster,
                        current_rover: str = rover_code,
                    ) -> None:
                        self._clear_cluster_fragment_buffers(project_id, current_cluster)
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

                        def eligible_attempt_records(
                            *,
                            current_rover: str = rover_code,
                            start_index: int = attempt_start_index,
                            current_cluster: dict = cluster,
                        ) -> list:
                            eligible = []
                            for record in current_cluster["observations"][start_index:]:
                                observation = getattr(record, "observation", None)
                                if (
                                    getattr(record, "base_name", None) != current_rover
                                    or observation is None
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

                        def collection_status() -> dict:
                            eligible = eligible_attempt_records()
                            return {
                                "sample_count": len(eligible),
                                "rover_names": {
                                    str(record.observation.rover_name)
                                    for record in eligible
                                },
                            }

                        try:
                            await self._set_rover_as_temporary_base(
                                rover_code,
                                project_id=project_id,
                                route_host=route_host,
                                route_port=route_port,
                                route_mountpoint=configured_mountpoint,
                                route_password=str(route_password),
                                on_collection_started=mark_collection_started,
                                on_collection_stopped=mark_collection_stopped,
                                collection_status_callback=collection_status,
                                expected_cross_rovers=expected_cross_rovers,
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
                                f"{rover_code}: rotation skipped after safe ROVER recovery; continuing with the next rover. {warning}",
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
                        if cluster_coverage_complete:
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: cross-baseline graph is complete "
                                    f"({len(cross_edges)}/{required_cross_edges} distinct "
                                    "edges covering every rover); remaining temporary-BASE "
                                    "rotations are unnecessary."
                                ),
                            )
                            break
                        if collected_count > 0 and not missing_rovers:
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: collected {collected_count} "
                                    "solver-eligible rover-to-rover AGRICA baseline(s) "
                                    f"from {', '.join(sorted(collected_rovers))}."
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
                    if cluster_coverage_complete:
                        break
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

        except asyncio.CancelledError:
            logger.info("RoundRobin cycle cancelled for project %s", project_id)
            raise
        except Exception as exc:
            cycle_error = exc
        finally:
            restore_errors: List[str] = []
            for selected_host, mp in suspended_bases:
                try:
                    await self._emit_progress(
                        project_id,
                        f"Khôi phục đúng chế độ stream ban đầu của Base cố định {mp}.",
                    )
                    await self._toggle_cors_fixed_base(
                        mp,
                        sleep=False,
                        selected_host=selected_host,
                    )
                    await self._emit_progress(
                        project_id,
                        f"Khôi phục Base cố định {mp} thành công; chế độ stream ban đầu đã được áp dụng.",
                    )
                except Exception as e:
                    logger.error("Failed to restore fixed base %s in finally block: %s", mp, e)
                    restore_errors.append(f"{mp}: {e}")
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
        on_collection_stopped: Optional[Callable[[], None]] = None,
        collection_status_callback: Optional[Callable[[], dict]] = None,
        expected_cross_rovers: Optional[set[str]] = None,
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        await self._emit_progress(
            project_id,
            f"{rover_code}: querying {self.caster_hosts} for an active AICaster client session.",
        )
        llh = self.rover_llh_cache.get(rover_code)
        if not llh:
            raise _SafeRoverRotationSkip(
                f"No LLH cache found for {rover_code}; receiver was not changed."
            )

        client_info = await self._find_client_info(rover_code)
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
        )
        rover_commands = self._build_unicore_rover_config()
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
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: sending SET BASE to {client_info.get('CasterHost')}:"
                f"{client_info.get('CasterPort')} (HTTP Basic auth "
                f"{'enabled' if self.control_password else 'disabled'})."
            ),
        )
        if not await self._send_set_command(
            mountpoint,
            client_info.get("Username", rover_code),
            client_info.get("receiverID", ""),
            commands,
            password=self.control_password,
            caster_host=client_info.get("CasterHost"),
            caster_port=client_info.get("CasterPort"),
            ack_station_code=rover_code,
        ):
            detail = self._last_set_error or "AICaster returned no rejection detail"
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: SET BASE was not fully verified; sending an "
                    "immediate ROVER recovery sequence before aborting."
                ),
            )
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

        route_started = False
        collection_started = False
        restore_error: Optional[str] = None
        target_route_host = route_host or self.source_host
        target_route_port = int(route_port or self.source_port)
        target_route_mountpoint = route_mountpoint or f"{rover_code}_BASE"
        target_route_password = self.source_password if route_password is None else route_password
        operation_error: Optional[Exception] = None
        try:
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: BASE profile acknowledged; starting the MQTT-to-NTRIP "
                    "route and waiting adaptively for the first verified RTCM3 frame."
                ),
            )
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: starting MQTT-to-NTRIP route "
                    f"{target_route_host}:{target_route_port}/{target_route_mountpoint}."
                ),
            )
            for route_attempt in range(1, self.RTCM_ROUTE_RECOVERY_ATTEMPTS + 1):
                try:
                    await self._start_ntrip_route(
                        rover_code,
                        target_route_mountpoint,
                        host=target_route_host,
                        port=target_route_port,
                        password=target_route_password,
                    )
                    route_started = True
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
                while True:
                    latest_status = dict(collection_status_callback() or {})
                    participants = set(latest_status.get("rover_names") or ())
                    sample_count = int(latest_status.get("sample_count") or 0)
                    handover_verified = sample_count > 0 and (
                        not expected or expected.issubset(participants)
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
                            f"{', '.join(sorted(participants))}; collecting "
                            f"{self.CROSS_BASE_STABLE_COLLECTION_SECONDS}s of stable "
                            "cross-baselines."
                        ),
                    )
                    await asyncio.sleep(self.CROSS_BASE_STABLE_COLLECTION_SECONDS)
                else:
                    missing = sorted(expected - participants)
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: temporary-base handover was not fully "
                            f"verified before timeout; valid rovers="
                            f"{', '.join(sorted(participants)) or 'none'}, missing="
                            f"{', '.join(missing) or 'none'}. The rotation will be "
                            "retried after safe ROVER restore."
                        ),
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

            # A temporary base must never be left in BASE mode. Restore the
            # receiver without FRESET so its persistent NTRIP setup and baud
            # rate remain intact.
            await self._emit_progress(
                project_id,
                f"{rover_code}: sending SET ROVER to restore normal AGRICA operation.",
            )
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
        try:
            llh = (
                float(cluster["base_lat"]),
                float(cluster["base_lon"]),
                float(cluster.get("base_alt") or 0.0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("cluster is missing a valid fixed-base coordinate") from exc
        if not _is_usable_llh(llh):
            raise ValueError("cluster fixed-base coordinate is invalid")
        return llh

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
                ecef_point_covariance_to_enu,
                neu_standard_deviation_to_ecef_covariance,
            )
            from backend.processors.gnss_adjustment_runtime import _llh_to_ecef
        except ModuleNotFoundError:
            from processors.gnss_adjustment.models import Baseline, Network, Point
            from processors.gnss_adjustment.solver import adjust_network
            from processors.gnss_adjustment.transforms import (
                covariance_standard_deviation,
                ecef_point_covariance_to_enu,
                neu_standard_deviation_to_ecef_covariance,
            )
            from processors.gnss_adjustment_runtime import _llh_to_ecef

        std_warning_threshold = _BASELINE_STD_REJECTION_THRESHOLD_M
        raw_ecef_tolerance = 0.05
        high_std_fallback_min_samples = 3
        high_std_fallback_max_repeatability_m = 0.05
        vector_outlier_min_samples = 5
        vector_outlier_absolute_floor_m = 0.25
        vector_outlier_sigma_multiplier = 8.0
        fixed_base_llh = self._cluster_base_llh(cluster)
        fixed_base_ecef = _llh_to_ecef(*fixed_base_llh)
        records: List[_CollectedObservation] = cluster["observations"]

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

            groups: Dict[tuple[str, str, str], List[tuple[dict, np.ndarray]]] = {}
            for sample in samples:
                edge, vector, _direction = _canonical_baseline(
                    sample["from"], sample["to"], sample["delta"]
                )
                session_id = str(sample.get("session_id", cluster_index))
                groups.setdefault((edge[0], edge[1], session_id), []).append(
                    (sample, np.asarray(vector, dtype=float))
                )

            rejected_ids: set[int] = set()
            diagnostics: List[dict] = []
            for (from_name, to_name, session_id), rows in groups.items():
                if len(rows) < vector_outlier_min_samples:
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
                    if float(deviation) <= threshold:
                        continue
                    rejected_ids.add(id(sample))
                    diagnostics.append({
                        "raw_index": sample.get("raw_index"),
                        "from": from_name,
                        "to": to_name,
                        "session_id": session_id,
                        "deviation_m": float(deviation),
                        "threshold_m": threshold,
                    })
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
                precision_sum = np.zeros((3, 3), dtype=float)
                weighted_sum = np.zeros(3, dtype=float)
                for row in rows:
                    precision = np.linalg.inv(row["covariance"])
                    precision_sum += precision
                    weighted_sum += precision @ row["delta"]
                mean_covariance = np.linalg.inv(precision_sum)
                mean = mean_covariance @ weighted_sum

                # Convert temporal correlation into an effective sample count.
                # n_eff=1 reproduces the former fully-conservative model;
                # n_eff=n reproduces the independent-epoch weighted mean.
                effective_sample_size, ess_sessions = _edge_effective_sample_size(
                    rows,
                    pooled_lag_one,
                )
                temporal_inflation = len(rows) / effective_sample_size
                scatter_scale = 1.0
                if len(rows) > 1:
                    scatter = sum(
                        float(
                            (row["delta"] - mean).T
                            @ np.linalg.inv(row["covariance"])
                            @ (row["delta"] - mean)
                        )
                        for row in rows
                    )
                    scatter_scale = max(1.0, scatter / (3.0 * (len(rows) - 1)))
                covariance = mean_covariance * temporal_inflation * scatter_scale
                independent_covariance = mean_covariance * scatter_scale
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
                        type_precision = np.linalg.inv(row["covariance"])
                        type_precision_sum += type_precision
                        type_weighted_sum += type_precision @ row["delta"]
                    type_means.append(
                        np.linalg.inv(type_precision_sum) @ type_weighted_sum
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
                    "independent_covariance": independent_covariance,
                    "effective_sample_size": effective_sample_size,
                    "temporal_scale_factor": temporal_inflation,
                    "scatter_scale_factor": scatter_scale,
                    "effective_sample_size_sessions": ess_sessions,
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
                cached = self.rover_llh_cache.get(from_name)
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
            flags = []
            if length < 1.0:
                flags.append("REJECTED_TOO_SHORT")
            if max(float(value) for value in observation.std_neu) > std_warning_threshold:
                flags.append("BASELINE_STD_WARNING")
                flags.append("REJECTED_BASELINE_STD")

            consistency_error = None
            if observation.rover_ecef:
                expected = tuple(base_ecef[axis] + delta[axis] for axis in range(3))
                consistency_error = _vector_length(tuple(
                    observation.rover_ecef[axis] - expected[axis] for axis in range(3)
                ))
                if consistency_error > raw_ecef_tolerance:
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
                "quality_flags": flags,
                "raw_payload": observation.raw,
                "vector_deviation_from_edge_m": None,
                "vector_outlier_threshold_m": None,
                "residual_xyz": None,
                "standardized_residual": None,
            })
            if observation.rover_ecef:
                raw_ecef_candidates[rover_name].append((raw_index, observation.rover_ecef))
            solver_sample = {
                "from": from_name,
                "to": rover_name,
                "delta": delta,
                "covariance": covariance,
                "raw_index": raw_index,
                "session_id": str(cluster_index),
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
            if not rejected_flags:
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
            if "REJECTED_VECTOR_OUTLIER" not in row["quality_flags"]:
                row["quality_flags"].append("REJECTED_VECTOR_OUTLIER")
            row["vector_deviation_from_edge_m"] = diagnostic["deviation_m"]
            row["vector_outlier_threshold_m"] = diagnostic["threshold_m"]

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
                    str(flag).startswith("REJECTED_")
                    or flag == "BASELINE_POSITION_INCONSISTENT"
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
            adjusted_points[point.name] = {
                "station_id": points[point.name].identifier,
                "adjusted_n": point.coordinate[0], "adjusted_e": point.coordinate[1], "adjusted_u": point.coordinate[2],
                "adjusted_x": point.coordinate[0], "adjusted_y": point.coordinate[1], "adjusted_z": point.coordinate[2],
                "correction_n": point.correction[0], "correction_e": point.correction[1], "correction_u": point.correction[2],
                "dx": point.correction[0], "dy": point.correction[1], "dz": point.correction[2],
                "std_n": point.standard_deviation[0], "std_e": point.standard_deviation[1], "std_u": point.standard_deviation[2],
                "std_x": point.standard_deviation[0], "std_y": point.standard_deviation[1], "std_z": point.standard_deviation[2],
                "standard_deviation_enu": std_enu,
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
                "observed_length": _vector_length(adjusted.observed),
                "adjusted_length": _vector_length(adjusted.adjusted),
                "observation_count": edge["observation_count"],
                "effective_sample_size": edge["effective_sample_size"],
                "temporal_inflation_factor": edge["temporal_scale_factor"],
                "scatter_scale_factor": edge["scatter_scale_factor"],
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
            for baseline_index in loop.get("baseline_indices") or []:
                cycle_edge_matrix[loop_index, int(baseline_index)] = 1.0
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
                str(flag).startswith("REJECTED_")
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
        return {
            "type": "gnss_adjusted",
            "source": "AGRICA_ROUND_ROBIN",
            "adjustment_engine": "backend.processors.gnss_adjustment.adjust_network",
            "project_id": project_id, "cluster_index": cluster_index,
            "cluster_name": cluster.get("name"), "computed_at": int(time.time()),
            "base": {
                "name": cluster.get("base_station") or "BASE", "fixed": True,
                "lat": fixed_base_llh[0], "lon": fixed_base_llh[1], "h": fixed_base_llh[2],
                "ecef_xyz": fixed_base_ecef,
            },
            "rover_count": len(adjusted_points), "points": adjusted_points,
            "baselines": adjusted_baselines, "baseline_observations": raw_rows,
            "loops": loops,
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
                "vector_outlier_count": len(vector_outlier_diagnostics),
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
                "baseline_std_warning_threshold_m": std_warning_threshold,
                "raw_ecef_consistency_tolerance_m": raw_ecef_tolerance,
                "baseline_covariance_model": (
                    "Published solution: C_edge = (n / n_eff) * scatter_scale * "
                    "inverse(sum(inverse(C_i))); n_eff estimated per contiguous "
                    "direction/session with a monotone initial-positive ACF sequence"
                ),
                "independent_epoch_covariance_model": (
                    "Sensitivity only: C_edge = scatter_scale * "
                    "inverse(sum(inverse(C_i))); assumes n_eff=n"
                ),
                "temporal_scaling_applied": temporal_scaling_applied,
                "effective_sample_size_method": (
                    "Per ECEF component integrated autocorrelation time; use minimum "
                    "component ESS; long sessions use a monotone initial-positive ACF; "
                    "sessions shorter than 8 epochs use a pooled lag-1 AR(1) correlation; "
                    "sum ESS across sessions separated by direction change or >5 s gap"
                ),
                "effective_sample_size_edges": [
                    {
                        "from": edge["from"],
                        "to": edge["to"],
                        "observation_count": edge["observation_count"],
                        "effective_sample_size": edge["effective_sample_size"],
                        "temporal_inflation_factor": edge["temporal_scale_factor"],
                        "scatter_scale_factor": edge["scatter_scale_factor"],
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
                "normalized_residual_scale": "a_priori",
                "degrees_of_freedom": result.degrees_of_freedom,
                "variance_factor": result.variance_factor,
                "reference_standard_deviation": math.sqrt(result.variance_factor) if result.variance_factor is not None and result.variance_factor >= 0 else None,
                "weighted_residual_sum": result.weighted_residual_sum,
                "rank": result.rank, "condition_number": result.condition_number,
                "cycle_space_dimension": cycle_space_dimension,
                "fundamental_loop_count": len(loops),
                "fundamental_loop_basis_rank": cycle_basis_rank,
                "loop_basis_independence_verified": True,
                "loop_basis_method": (
                    "Spanning forest plus one fundamental cycle per chord; "
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

    async def _find_client_info(self, station_code: str) -> Optional[Dict[str, Any]]:
        """Find a rover across every configured AICaster client table."""

        results = await asyncio.gather(
            *(self._query_client_table(host) for host in self.caster_hosts),
            return_exceptions=True,
        )
        candidates = []
        query_errors = []
        successful_hosts = []
        for host, result in zip(self.caster_hosts, results):
            if isinstance(result, BaseException):
                detail = str(result).strip() or result.__class__.__name__
                query_errors.append(f"{host}:{self.caster_port} ({detail})")
                continue
            successful_hosts.append(host)
            candidates.extend(
                self._parse_client_table(result, caster_host=host, caster_port=self.caster_port)
            )

        selected = self._select_client_candidate(candidates, station_code)
        if selected:
            logger.info(
                "Matched station %s to AICaster %s:%s (username=%s receiverID=%s mountpoint=%s)",
                station_code,
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
        logger.error(
            "No AICaster client session matched station %s. Queried=%s errors=%s available=%s",
            station_code,
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

    def _observation_matches_active_base(
        self,
        cluster: dict,
        active_base: str,
        observation: Any,
    ) -> tuple[bool, str]:
        """Verify AGRICA's reported base coordinate before assigning an edge."""

        if active_base == "BASE":
            try:
                expected = self._cluster_base_llh(cluster)
            except ValueError as exc:
                return False, f"cannot verify fixed BASE: {exc}"
        else:
            cached = self.rover_llh_cache.get(active_base)
            if not cached:
                return False, f"cannot verify temporary base {active_base}: LLH cache is unavailable"
            expected = (
                float(cached["lat"]),
                float(cached["lon"]),
                float(cached["alt"]),
            )

        reported = observation.base_llh
        if not _is_usable_llh(reported):
            if active_base == "BASE":
                return True, "AGRICA has no usable base_llh; using configured fixed BASE"
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
        return True, (
            f"verified base {active_base} (horizontal delta {separation:.2f} m, "
            f"height delta {height_delta:.2f} m)"
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
        command_response_timeout: float = 8.0,
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
                    else:
                        await asyncio.sleep(0.1)
                        break  # No need to retry if we don't wait for response
            return True
        except Exception as exc:
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
            while attempt < safe_max_attempts:
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
                logger.warning(
                    "Rover restore retry rover=%s command=%s attempt=%s detail=%s",
                    rover_code,
                    command_text,
                    attempt,
                    detail,
                )
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: no ACK for {command_text}; retrying in 2s ({detail}).",
                )
                if attempt < safe_max_attempts:
                    await asyncio.sleep(2)
            else:
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
                        safe_max_attempts,
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
                raise RuntimeError(
                    f"{command_text} was not acknowledged after {safe_max_attempts} attempt(s): "
                    f"{self._last_set_error or 'no receiver response'}"
                )

    def _build_unicore_base_config(self, setup_method: str, duration: int = 60, lat: float = 0, lon: float = 0, alt: float = 0) -> list[bytes]:
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
        else:
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
    def _build_unicore_rover_config() -> list[bytes]:
        """Restore UM980 rover output after one temporary-base collection."""

        return [
            b"mode rover survey\r\n",
            b"unlogall\r\n",
            b"gpgga com2 1\r\n",
            b"AGRICA COM2 1\r\n",
            b"saveconfig\r\n",
        ]
