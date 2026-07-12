import asyncio
import base64
import inspect
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CollectedObservation:
    """An AGRICA observation tagged with the rover acting as its base."""

    base_name: str
    observation: Any


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

    This is report-only graph post-processing.  Each non-tree edge closes one
    fundamental loop; parallel observations therefore correctly create a
    two-edge loop.  Stored vectors are signed according to traversal direction.
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
        observed = _sum_cycle_vectors(cycle_steps, baselines, "observed_xyz")
        adjusted = _sum_cycle_vectors(cycle_steps, baselines, "adjusted_xyz")
        total_length = sum(
            float(baselines[index]["observed_length"]) for index, _ in cycle_steps
        )
        observed_closure = _vector_length(observed)
        adjusted_closure = _vector_length(adjusted)
        loops.append({
            "loop": loop_number,
            "points": [start, end] + path_points[1:],
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
        self.route_start_callback = route_start_callback
        self.route_stop_callback = route_stop_callback
        self.result_callback = result_callback
        self.error_callback = error_callback
        self.progress_callback = progress_callback
        self._last_set_error: Optional[str] = None
        self._last_set_response: Optional[str] = None
        self.running_tasks: Dict[int, asyncio.Task] = {}
        self.rover_llh_cache: Dict[str, Dict[str, float]] = {}
        self._sessions: Dict[int, dict] = {}
        self._last_ingest_diagnostics: Dict[int, dict] = {}
        # UM980 AGRICA output can be split across MQTT payloads.  Buffers are
        # isolated per project/station so fragments from different rovers never
        # get concatenated.
        self._agrica_fragment_buffers: Dict[tuple[int, int], str] = {}

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
            valid_observations.append(observation)
            if active_base == "BASE":
                session["seed_collection_steps"].add(int(time.time()))
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
            observed = {
                record.observation.station_id
                for record in cluster["observations"]
                if record.base_name == "BASE"
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

        steps = len(session["seed_collection_steps"])
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
            logger.warning("RoundRobin cycle already running for project %s", project_id)
            return
        if project_id not in self._sessions:
            raise ValueError(f"project {project_id} has no configured adjustment session")
        self.running_tasks[project_id] = asyncio.create_task(self._run_cycle(project_id))

    async def _toggle_cors_fixed_base(self, mountpoint: str, sleep: bool) -> None:
        if not mountpoint:
            return
        action = "stop" if sleep else "wake"
        # API của CORS Dashboard nằm trên https://cors.aitogy.com và yêu cầu method POST
        url = f"https://cors.aitogy.com/api/ntrip/{action}-station"
        
        def do_req():
            import urllib.request
            import json
            payload = {"mountpoint": mountpoint}
            if action == "stop":
                payload["force"] = True
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    body = response.read().decode('utf-8')
                    logger.info(f"API {action}-station response for {mountpoint}: {response.status} {body.strip()}")
                    return response.status
            except Exception as e:
                logger.error("Failed to %s fixed base %s: %s", action, mountpoint, e)
                return None
                
        await asyncio.to_thread(do_req)

    async def _run_cycle(self, project_id: int) -> None:
        suspended_bases = set()
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
                route_password = cluster.get("round_robin_route_password")
                if route_password is None:
                    route_password = self.source_password
                
                # Ngắt luồng base cố định trước khi thu thập baseline rovers
                if configured_mountpoint and configured_mountpoint not in suspended_bases:
                    await self._emit_progress(project_id, f"Ngắt kết nối trạm Base cố định ({configured_mountpoint}) để tránh nhiễu tín hiệu.")
                    await self._toggle_cors_fixed_base(configured_mountpoint, sleep=True)
                    suspended_bases.add(configured_mountpoint)
                    # Chờ 2s để đảm bảo caster đã xử lý ngắt
                    await asyncio.sleep(2.0)
                    
                for rover_code in rovers:
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
                        )
                    finally:
                        session["active_bases"].pop(cluster_index, None)

            for cluster_index, cluster in enumerate(session["clusters"]):
                result = self._build_cluster_result(project_id, cluster_index, cluster)
                logger.info(
                    "Network adjustment completed for project=%s cluster=%s: %s rover points",
                    project_id,
                    cluster.get("name", cluster_index + 1),
                    result["rover_count"],
                )
                if self.result_callback:
                    callback_result = self.result_callback(project_id, result)
                    if inspect.isawaitable(callback_result):
                        await callback_result
        except asyncio.CancelledError:
            logger.info("RoundRobin cycle cancelled for project %s", project_id)
            raise
        except Exception as exc:
            logger.error("RoundRobin cycle failed for project %s: %s", project_id, exc)
            if self.error_callback:
                callback_result = self.error_callback(project_id, str(exc))
                if inspect.isawaitable(callback_result):
                    await callback_result
        finally:
            for mp in suspended_bases:
                try:
                    await self._emit_progress(project_id, f"Khôi phục kết nối trạm Base cố định ({mp}).")
                    await self._toggle_cors_fixed_base(mp, sleep=False)
                except Exception as e:
                    logger.error("Failed to wake base %s in finally block: %s", mp, e)
            self.running_tasks.pop(project_id, None)

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
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        await self._emit_progress(
            project_id,
            f"{rover_code}: querying {self.caster_hosts} for an active AICaster client session.",
        )
        llh = self.rover_llh_cache.get(rover_code)
        if not llh:
            raise RuntimeError(f"No LLH cache found for {rover_code}; cannot start base rotation")

        client_info = await self._find_client_info(rover_code)
        if not client_info:
            raise RuntimeError(f"Could not find an active AICaster client session for {rover_code}")
        mountpoint = client_info.get("Mountpoint", "")
        if not mountpoint:
            raise RuntimeError(f"AICaster client session for {rover_code} has no mountpoint")
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
        ):
            detail = self._last_set_error or "AICaster returned no rejection detail"
            raise RuntimeError(
                f"AICaster rejected the SET command for {rover_code}: {detail}"
            )
        await self._emit_progress(
            project_id,
            f"{rover_code}: SET BASE accepted; response={self._last_set_response or '200 OK'}.",
        )

        route_started = False
        collection_started = False
        restore_error: Optional[str] = None
        target_route_host = route_host or self.source_host
        target_route_port = int(route_port or self.source_port)
        target_route_mountpoint = route_mountpoint or f"{rover_code}_BASE"
        target_route_password = self.source_password if route_password is None else route_password
        try:
            await self._emit_progress(
                project_id,
                f"{rover_code}: waiting 10s for UM980 to enter BASE mode and emit RTCM.",
            )
            await asyncio.sleep(10)
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: starting MQTT-to-NTRIP route "
                    f"{target_route_host}:{target_route_port}/{target_route_mountpoint}."
                ),
            )
            await self._start_ntrip_route(
                rover_code,
                target_route_mountpoint,
                host=target_route_host,
                port=target_route_port,
                password=target_route_password,
            )
            route_started = True
            if on_collection_started:
                on_collection_started()
            collection_started = True
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
                f"{rover_code}: NTRIP SOURCE accepted and first RTCM frame forwarded; collecting cross-baselines for 15s.",
            )
            logger.info("Waiting 15s for cross-baselines referenced to %s", rover_code)
            await asyncio.sleep(15)
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

            # A temporary base must never be left in BASE mode.  Restore the
            # receiver without FRESET/SAVECONFIG so its persistent NTRIP setup
            # and baud rate remain intact.
            await self._emit_progress(
                project_id,
                f"{rover_code}: sending SET ROVER to restore normal AGRICA operation.",
            )
            restored = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                self._build_unicore_rover_config(),
                password=self.control_password,
                caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"),
            )
            if not restored:
                detail = self._last_set_error or "AICaster returned no rejection detail"
                restore_error = f"Could not restore {rover_code} to ROVER mode: {detail}"
                logger.error(restore_error)
            else:
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: SET ROVER accepted; receiver restored.",
                )
            await asyncio.sleep(5)
        if restore_error:
            raise RuntimeError(restore_error)

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
        try:
            from backend.processors.gnss_adjustment.models import Baseline, Network, Point
            from backend.processors.gnss_adjustment.solver import adjust_network
            from backend.processors.gnss_adjustment_runtime import _llh_to_ecef
        except ModuleNotFoundError:
            from processors.gnss_adjustment.models import Baseline, Network, Point
            from processors.gnss_adjustment.solver import adjust_network
            from processors.gnss_adjustment_runtime import _llh_to_ecef

        fixed_base_llh = self._cluster_base_llh(cluster)
        fixed_base_ecef = _llh_to_ecef(*fixed_base_llh)
        records: List[_CollectedObservation] = cluster["observations"]
        seed_by_station = {
            record.observation.station_id: record
            for record in records
            if record.base_name == "BASE"
        }
        missing_seed = set(cluster["stations"]) - set(seed_by_station)
        if missing_seed:
            raise ValueError(f"missing fixed-base observations for stations {sorted(missing_seed)}")

        points: Dict[str, Point] = {"BASE": Point("BASE", fixed_base_ecef, fixed=True)}
        station_names: Dict[int, str] = {}
        raw_ecef_by_name: Dict[str, Any] = {}
        for station_id in cluster["stations"]:
            seed = seed_by_station[station_id].observation
            name = seed.rover_name
            if name in points:
                raise ValueError(f"duplicate rover name in adjustment cluster: {name}")
            delta = self._baseline_ecef(seed, fixed_base_llh)
            approximate = tuple(fixed_base_ecef[i] + delta[i] for i in range(3))
            points[name] = Point(name, approximate, fixed=False, identifier=station_id)
            station_names[station_id] = name
            raw_ecef_by_name[name] = seed.rover_ecef

        baselines: List[Baseline] = []
        baseline_ratios: List[Optional[float]] = []
        baseline_sources: List[dict] = []
        raw_baseline_observations: List[dict] = []
        cross_baseline_count = 0
        for record in records:
            observation = record.observation
            rover_name = station_names.get(observation.station_id)
            if rover_name is None:
                continue
            if record.base_name == "BASE":
                from_name = "BASE"
                base_llh = fixed_base_llh
            else:
                from_name = record.base_name
                if from_name not in points or from_name == rover_name:
                    continue
                base_llh = _ecef_to_llh(*points[from_name].approximate)
                cross_baseline_count += 1
            delta = self._baseline_ecef(observation, base_llh)

            baseline_length = math.sqrt(delta[0]**2 + delta[1]**2 + delta[2]**2)
            consistency_error = None
            quality_flags = []

            if baseline_length < 1.0:
                logger.warning(
                    "RoundRobin cluster rejected baseline %s->%s: too short (%.2f m)",
                    from_name,
                    rover_name,
                    baseline_length,
                )
                quality_flags.append("REJECTED_TOO_SHORT")

            if observation.rover_ecef:
                base_ecef_temp = _llh_to_ecef(*base_llh)
                expected_rover_ecef = (
                    base_ecef_temp[0] + delta[0],
                    base_ecef_temp[1] + delta[1],
                    base_ecef_temp[2] + delta[2],
                )
                consistency_error = math.sqrt(
                    (observation.rover_ecef[0] - expected_rover_ecef[0])**2 +
                    (observation.rover_ecef[1] - expected_rover_ecef[1])**2 +
                    (observation.rover_ecef[2] - expected_rover_ecef[2])**2
                )
                if consistency_error > 50.0:
                    logger.warning(
                        "RoundRobin cluster rejected baseline %s->%s: ECEF consistency error (%.2f m) > 50m",
                        from_name,
                        rover_name,
                        consistency_error,
                    )
                    quality_flags.append("REJECTED_INCONSISTENT_ECEF")

            base_obs_data = {
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
                "baseline_std_neu": observation.std_neu,
                "velocity_up_std": observation.full_data.get("velocity_up_std"),
                "rover_position_std_ecef": observation.rover_position_std_ecef,
                "raw_ecef_consistency_error_m": consistency_error,
                "quality_flags": quality_flags,
                "raw_payload": observation.raw,
                "residual_xyz": None,
                "standardized_residual": None
            }
            raw_baseline_observations.append(base_obs_data)

            if quality_flags:
                continue

            standard_deviation = observation.rover_position_std_ecef or observation.std_neu
            baselines.append(
                Baseline(
                    from_name,
                    rover_name,
                    delta,
                    standard_deviation=standard_deviation,
                    identifier=observation.station_id,
                )
            )
            baseline_ratios.append(observation.full_data.get("ratio"))
            baseline_sources.append({
                "assigned_base": from_name,
                "reported_base_llh": observation.base_llh,
                "observation_epoch": observation.epoch_ts,
                "station_id": observation.station_id,
            })

        if cross_baseline_count == 0:
            raise ValueError("no rover-to-rover baseline was collected during Round-Robin")

        result = adjust_network(Network.from_items(points.values(), baselines))
        adjusted_points = {}
        for point in result.points:
            if point.fixed:
                continue
            adjusted_points[point.name] = {
                "station_id": points[point.name].identifier,
                "adjusted_n": point.coordinate[0],
                "adjusted_e": point.coordinate[1],
                "adjusted_u": point.coordinate[2],
                "correction_n": point.correction[0],
                "correction_e": point.correction[1],
                "correction_u": point.correction[2],
                # Keep the legacy Excel keys as well.
                "dx": point.correction[0],
                "dy": point.correction[1],
                "dz": point.correction[2],
                "std_n": point.standard_deviation[0],
                "std_e": point.standard_deviation[1],
                "std_u": point.standard_deviation[2],
                "raw_rover_ecef": raw_ecef_by_name.get(point.name),
            }

        adjusted_baselines = []
        for index, baseline in enumerate(result.baselines):
            source = baselines[index]
            standard_deviation = source.standard_deviation
            if standard_deviation is None:
                assert source.covariance is not None
                standard_deviation = tuple(
                    math.sqrt(source.covariance[component][component]) for component in range(3)
                )
            ratio = baseline_ratios[index] if index < len(baseline_ratios) else None
            source_metadata = baseline_sources[index] if index < len(baseline_sources) else {}
            item = {
                "from": baseline.from_point,
                "to": baseline.to_point,
                "observed_xyz": baseline.observed,
                "adjusted_xyz": baseline.adjusted,
                "residual_xyz": baseline.residual,
                "standard_deviation_xyz": standard_deviation,
                "observed_length": _vector_length(baseline.observed),
                "adjusted_length": _vector_length(baseline.adjusted),
                "ratio": ratio,
                **source_metadata,
                # Legacy keys retained for existing API/UI consumers.
                "observed_neu": baseline.observed,
                "adjusted_neu": baseline.adjusted,
                "residual_neu": baseline.residual,
                "standardized_residual": baseline.standardized_residual,
                "redundancy": baseline.redundancy,
            }
            adjusted_baselines.append(item)
            
            # Update the corresponding raw observation with residuals
            # We match by from_name and to_name (assuming 1 per pair for now)
            for raw_obs in raw_baseline_observations:
                if raw_obs["from"] == baseline.from_point and raw_obs["to"] == baseline.to_point:
                    raw_obs["residual_xyz"] = baseline.residual
                    raw_obs["standardized_residual"] = baseline.standardized_residual
            
        loops = _build_fundamental_loops(adjusted_baselines)
        return {
            "type": "gnss_adjusted",
            "source": "AGRICA_ROUND_ROBIN",
            "adjustment_engine": "backend.processors.gnss_adjustment.adjust_network",
            "project_id": project_id,
            "cluster_index": cluster_index,
            "cluster_name": cluster.get("name"),
            "computed_at": int(time.time()),
            "base": {
                "name": cluster.get("base_station") or "BASE",
                "fixed": True,
                "lat": fixed_base_llh[0],
                "lon": fixed_base_llh[1],
                "h": fixed_base_llh[2],
                "ecef_xyz": fixed_base_ecef,
            },
            "rover_count": len(adjusted_points),
            "points": adjusted_points,
            "baselines": adjusted_baselines,
            "baseline_observations": raw_baseline_observations,
            "loops": loops,
            "quality": {
                "degrees_of_freedom": result.degrees_of_freedom,
                "variance_factor": result.variance_factor,
                "reference_standard_deviation": (
                    math.sqrt(result.variance_factor)
                    if result.variance_factor is not None and result.variance_factor >= 0.0
                    else None
                ),
                "weighted_residual_sum": result.weighted_residual_sum,
                "rank": result.rank,
                "condition_number": result.condition_number,
                "max_standardized_residual": result.max_standardized_residual,
                "global_test": (
                    {
                        "statistic": result.global_test.statistic,
                        "lower_critical_value": result.global_test.lower_critical_value,
                        "upper_critical_value": result.global_test.upper_critical_value,
                        "p_value": result.global_test.p_value,
                        "passed": result.global_test.passed,
                    }
                    if result.global_test
                    else None
                ),
                "residual_flags": [
                    {
                        "from": flag.from_point,
                        "to": flag.to_point,
                        "component": flag.component,
                        "normalized_residual": flag.normalized_residual,
                        "p_value": flag.p_value,
                        "critical_value": flag.critical_value,
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
            if not observation.rover_llh or not observation.baseline_neu:
                return False, (
                    f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                    f"and missing rover_llh or baseline_neu to verify expected base"
                )
            
            rover_to_expected_dist = _llh_horizontal_distance_m(observation.rover_llh, expected)
            baseline_horiz_len = math.hypot(observation.baseline_neu[0], observation.baseline_neu[1])
            
            if abs(rover_to_expected_dist - baseline_horiz_len) > self.BASE_IDENTITY_TOLERANCE_M:
                return False, (
                    f"rejected {observation.rover_name}: missing base_llh, and baseline length "
                    f"({baseline_horiz_len:.1f} m) does not match distance to expected base {active_base} "
                    f"({rover_to_expected_dist:.1f} m)"
                )

            # Extra check for transition: make sure it's not actually closer to the fixed BASE's distance
            if active_base != "BASE":
                try:
                    fixed_base = self._cluster_base_llh(cluster)
                except ValueError:
                    fixed_base = None
                if fixed_base is not None:
                    rover_to_fixed_dist = _llh_horizontal_distance_m(observation.rover_llh, fixed_base)
                    if abs(rover_to_fixed_dist - baseline_horiz_len) + 1.0 < abs(rover_to_expected_dist - baseline_horiz_len):
                        return False, (
                            f"rejected {observation.rover_name}: AGRICA baseline length "
                            f"matches fixed BASE more closely than temporary base {active_base}"
                        )

            return True, (
                f"verified base {active_base} via baseline length matching "
                f"(delta {abs(rover_to_expected_dist - baseline_horiz_len):.2f} m)"
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
    ) -> bool:
        """Send a Caster SET request and Unicore commands to the selected rover."""
        target_host = caster_host or self.caster_host
        target_port = int(caster_port or self.caster_port)
        self._last_set_error = None
        self._last_set_response = None
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
                    writer.write(command)
                    await writer.drain()
                    if wait_for_command_response:
                        try:
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
                                self._last_set_error = (
                                    f"receiver rejected or ignored command {command_str}: "
                                    f"{compact_response[:500]}"
                                )
                                return False
                            await asyncio.sleep(1.0)
                        except Exception as loop_err:
                            logger.error("Error reading command response: %s", loop_err)
                            if attempt == max_retries:
                                return False
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
    ) -> None:
        """Send one restore command at a time and retry until its ACK arrives."""

        for command_index, command in enumerate(commands, start=1):
            command_text = command.decode("ascii", errors="replace").strip()
            attempt = 0
            while True:
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
                await asyncio.sleep(2)

    def _build_unicore_base_config(self, setup_method: str, duration: int = 60, lat: float = 0, lon: float = 0, alt: float = 0) -> list[bytes]:
        """Build the Unicore command sequence for a fixed or survey-in base."""
        commands = []
        port = "com2"
        if setup_method.upper() == "SURVEY_IN":
            commands.append(f"mode base time {duration}\r\n".encode("ascii"))
        else:
            commands.append(f"mode base {lat} {lon} {alt}\r\n".encode("ascii"))
        commands.append(f"gpgga {port} 1\r\n".encode("ascii"))
        for message in ("1006", "1033", "1074", "1124", "1084", "1094", "1042", "1019", "1020", "1045", "1077", "1127", "1087", "1097"):
            commands.append(f"rtcm{message} {port} 1\r\n".encode("ascii"))
        return commands

    @staticmethod
    def _build_unicore_rover_config() -> list[bytes]:
        """Restore UM980 rover output after one temporary-base collection."""

        return [
            b"unlogall\r\n",
            b"AGRICA COM2 1\r\n",
            b"saveconfig\r\n",
        ]
