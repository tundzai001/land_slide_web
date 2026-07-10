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


class RoundRobinAdjustmentManager:
    """Collect base-to-rover and rover-to-rover baselines for the existing solver.

    The mathematical adjustment remains in ``gnss_adjustment.solver``.  This
    class only manages the observation lifecycle and provides that solver with
    correctly connected ECEF baselines.
    """

    SEED_COLLECTION_MAX_STEPS = 10

    def __init__(
        self,
        mqtt_client,
        caster_host: str = "127.0.0.1",
        caster_port: int = 7054,
        source_host: Optional[str] = None,
        source_port: int = 2101,
        control_password: str = "123",
        source_password: str = "12345",
        route_start_callback: Optional[Callable[[str, str, int, str, str], Any]] = None,
        route_stop_callback: Optional[Callable[[str], Any]] = None,
        result_callback: Optional[Callable[[int, dict], Any]] = None,
        error_callback: Optional[Callable[[int, str], Any]] = None,
    ):
        self.mqtt_client = mqtt_client
        self.caster_host = caster_host
        self.caster_port = caster_port
        self.source_host = source_host or caster_host
        self.source_port = source_port
        self.control_password = control_password
        self.source_password = source_password
        self.route_start_callback = route_start_callback
        self.route_stop_callback = route_stop_callback
        self.result_callback = result_callback
        self.error_callback = error_callback
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
        # characters.  Multiple complete messages in one MQTT payload are also
        # accepted.
        complete_matches = list(re.finditer(r"#AGRICA[^*]*\*[0-9A-Fa-f]{8}", pending, re.DOTALL))
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
            self._last_ingest_diagnostics[project_id] = {
                "level": "success",
                "message": f"Accepted {len(valid_observations)} valid AGRICA baseline(s).",
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

    async def _run_cycle(self, project_id: int) -> None:
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
                for rover_code in rovers:
                    try:
                        await self._set_rover_as_temporary_base(
                            rover_code,
                            on_collection_started=lambda: session["active_bases"].__setitem__(
                                cluster_index, rover_code
                            ),
                            on_collection_stopped=lambda: session["active_bases"].pop(
                                cluster_index, None
                            ),
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
            self.running_tasks.pop(project_id, None)

    async def _set_rover_as_temporary_base(
        self,
        rover_code: str,
        on_collection_started: Optional[Callable[[], None]] = None,
        on_collection_stopped: Optional[Callable[[], None]] = None,
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        llh = self.rover_llh_cache.get(rover_code)
        if not llh:
            raise RuntimeError(f"No LLH cache found for {rover_code}; cannot start base rotation")

        client_info = await self._find_client_info(rover_code)
        if not client_info:
            raise RuntimeError(f"Could not find an active AICaster client session for {rover_code}")
        mountpoint = client_info.get("Mountpoint", "")
        if not mountpoint:
            raise RuntimeError(f"AICaster client session for {rover_code} has no mountpoint")

        commands = self._build_geotek_lte_unicore_config(
            setup_method="FIXED",
            lat=llh["lat"],
            lon=llh["lon"],
            alt=llh["alt"],
        )
        if not await self._send_set_command(
            mountpoint,
            client_info.get("Username", rover_code),
            client_info.get("receiverID", ""),
            commands,
            password=self.control_password,
        ):
            raise RuntimeError(f"AICaster rejected the SET command for {rover_code}")

        route_started = False
        collection_started = False
        restore_error: Optional[str] = None
        try:
            await asyncio.sleep(10)
            await self._start_ntrip_route(
                rover_code,
                f"{rover_code}_BASE",
            )
            route_started = True
            if on_collection_started:
                on_collection_started()
            collection_started = True
            logger.info("Waiting 15s for cross-baselines referenced to %s", rover_code)
            await asyncio.sleep(15)
        finally:
            if collection_started and on_collection_stopped:
                on_collection_stopped()
            if route_started:
                try:
                    await self._stop_ntrip_route(rover_code)
                except Exception as exc:
                    logger.error("Could not stop temporary NTRIP route for %s: %s", rover_code, exc)

            # A temporary base must never be left in BASE mode.  Restore the
            # receiver without FRESET/SAVECONFIG so its persistent NTRIP setup
            # and baud rate remain intact.
            restored = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                self._build_geotek_lte_unicore_rover_config(),
                password=self.control_password,
            )
            if not restored:
                restore_error = f"Could not restore {rover_code} to ROVER mode"
                logger.error(restore_error)
            await asyncio.sleep(5)
        if restore_error:
            raise RuntimeError(restore_error)

    async def _start_ntrip_route(self, station_code: str, mountpoint: str) -> None:
        if self.route_start_callback:
            result = self.route_start_callback(
                station_code,
                self.source_host,
                self.source_port,
                mountpoint,
                self.source_password,
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
            "host": self.source_host,
            "port": self.source_port,
            "mountpoint": mountpoint,
            "password": self.source_password,
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
            standard_deviation = observation.std_ecef or observation.std_neu
            baselines.append(
                Baseline(
                    from_name,
                    rover_name,
                    delta,
                    standard_deviation=standard_deviation,
                    identifier=observation.station_id,
                )
            )

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

        adjusted_baselines = [
            {
                "from": baseline.from_point,
                "to": baseline.to_point,
                "observed_neu": baseline.observed,
                "adjusted_neu": baseline.adjusted,
                "residual_neu": baseline.residual,
                "standardized_residual": baseline.standardized_residual,
                "redundancy": baseline.redundancy,
            }
            for baseline in result.baselines
        ]
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
            },
            "rover_count": len(adjusted_points),
            "points": adjusted_points,
            "baselines": adjusted_baselines,
            "quality": {
                "degrees_of_freedom": result.degrees_of_freedom,
                "variance_factor": result.variance_factor,
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
        """Read the AICaster client table to find a rover's active session."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.caster_host, self.caster_port),
                timeout=10.0,
            )
            writer.write(b"GET /clienttable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=10.0)
            client_table = data.decode(errors="ignore")
            selected = self._select_client_info(client_table, station_code)
            if selected is None:
                available_sessions = []
                for line in client_table.strip().splitlines():
                    parts = [part.strip() for part in line.split(";")]
                    if len(parts) > 4 and parts[0] == "STR":
                        available_sessions.append({
                            "username": parts[1],
                            "receiver_id": parts[2],
                            "mountpoint": parts[3],
                        })
                logger.error(
                    "No AICaster client session matched station %s. Available STR sessions: %s",
                    station_code,
                    available_sessions,
                )
            return selected
        except Exception as exc:
            logger.error("Error fetching /clienttable: %s", exc)
            raise RuntimeError(
                f"Could not query AICaster client table at {self.caster_host}:{self.caster_port}: {exc}"
            ) from exc
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        return None

    @staticmethod
    def _select_client_info(client_table: str, station_code: str) -> Optional[Dict[str, Any]]:
        target = station_code.strip().lower()
        exact_matches = []
        fuzzy_matches = []
        for line in client_table.strip().splitlines():
            parts = [part.strip() for part in line.split(";")]
            if len(parts) <= 4 or parts[0] != "STR":
                continue
            username, receiver_id, mountpoint = parts[1], parts[2], parts[3]
            candidate = {
                "Username": username,
                "receiverID": receiver_id,
                "Mountpoint": mountpoint,
            }
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

    async def _send_set_command(self, mountpoint: str, username: str, receiver_id: str, commands: List[bytes], password: str = "123") -> bool:
        """Send a Caster SET request and Unicore commands to the selected rover."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.caster_host, self.caster_port),
                timeout=10.0,
            )
            auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = (
                f"SET /{mountpoint} HTTP/1.0\r\n"
                f"User-Agent: NTRIP SetBaseCmd/{receiver_id}\r\n"
                f"Authorization: Basic {auth_str}\r\n\r\n"
            )
            writer.write(headers.encode("ascii"))
            await writer.drain()
            response = (
                await asyncio.wait_for(reader.read(1024), timeout=10.0)
            ).decode("ascii", errors="ignore")
            if "200 OK" not in response:
                logger.error("SET request rejected by Caster: %s", response)
                return False
            for command in commands:
                writer.write(command)
                await writer.drain()
                await asyncio.sleep(0.1)
            return True
        except Exception as exc:
            logger.error("Error sending SET command to %s: %s", mountpoint, exc)
            return False
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    def _build_geotek_lte_unicore_config(self, setup_method: str, duration: int = 60, lat: float = 0, lon: float = 0, alt: float = 0) -> list[bytes]:
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
    def _build_geotek_lte_unicore_rover_config() -> list[bytes]:
        """Restore UM980 rover output after one temporary-base collection."""

        return [
            b"mode rover survey\r\n",
            b"gpgga com2 1\r\n",
            b"agrica com2 1\r\n",
        ]
