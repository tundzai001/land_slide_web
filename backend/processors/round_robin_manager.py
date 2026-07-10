import asyncio
import base64
import inspect
import json
import logging
import math
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

    def __init__(
        self,
        mqtt_client,
        caster_host: str = "127.0.0.1",
        caster_port: int = 7054,
        result_callback: Optional[Callable[[int, dict], Any]] = None,
        error_callback: Optional[Callable[[int, str], Any]] = None,
    ):
        self.mqtt_client = mqtt_client
        self.caster_host = caster_host
        self.caster_port = caster_port
        self.result_callback = result_callback
        self.error_callback = error_callback
        self.running_tasks: Dict[int, asyncio.Task] = {}
        self.rover_llh_cache: Dict[str, Dict[str, float]] = {}
        self._sessions: Dict[int, dict] = {}

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
        }

    def clear_project(self, project_id: int) -> None:
        task = self.running_tasks.pop(project_id, None)
        if task and not task.done():
            task.cancel()
        self._sessions.pop(project_id, None)

    def update_rover_llh(self, station_code: str, lat: float, lon: float, alt: float) -> None:
        if station_code:
            self.rover_llh_cache[station_code] = {"lat": lat, "lon": lon, "alt": alt}

    def add_agrica_payload(self, raw_payload: str, info: Dict[str, Any]) -> List[Any]:
        """Store valid AGRICA measurements in the active project's cluster only."""

        from processors.gnss_adjustment_runtime import parse_agrica

        project_id = int(info.get("project_id") or info.get("station_id") or 0)
        session = self._sessions.get(project_id)
        if session is None:
            return []

        station_id = int(info.get("station_id") or 0)
        rover_name = str(info.get("station_code") or info.get("station_name") or f"station_{station_id}")
        try:
            observations = parse_agrica(
                raw_payload,
                project_id=project_id,
                station_id=station_id,
                rover_name=rover_name,
            )
        except Exception as exc:
            logger.error("Error parsing AGRICA in RoundRobin: %s", exc)
            return []

        valid_observations = []
        for observation in observations:
            if observation.position_type not in (4, 7):
                continue
            cluster_index = self._cluster_index_for_station(session, observation.station_id)
            if cluster_index is None:
                continue
            active_base = session["active_bases"].get(cluster_index, "BASE")
            if active_base == observation.rover_name:
                continue
            session["clusters"][cluster_index]["observations"].append(
                _CollectedObservation(active_base, observation)
            )
            valid_observations.append(observation)
            if observation.rover_llh:
                self.update_rover_llh(
                    observation.rover_name,
                    observation.rover_llh[0],
                    observation.rover_llh[1],
                    observation.rover_llh[2],
                )
        return valid_observations

    @staticmethod
    def _cluster_index_for_station(session: dict, station_id: int) -> Optional[int]:
        for index, cluster in enumerate(session["clusters"]):
            if station_id in cluster["stations"]:
                return index
        return None

    def has_complete_seed_observations(self, project_id: int) -> bool:
        """All selected rovers must first be observed from the fixed CORS base."""

        session = self._sessions.get(project_id)
        if session is None:
            return False
        for cluster in session["clusters"]:
            seed_station_ids = {
                record.observation.station_id
                for record in cluster["observations"]
                if record.base_name == "BASE"
            }
            if not set(cluster["stations"]).issubset(seed_station_ids):
                return False
        return True

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
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        llh = self.rover_llh_cache.get(rover_code)
        if not llh:
            logger.error("No LLH cache found for %s; skipping this base rotation", rover_code)
            return

        client_info = await self._find_client_info(rover_code)
        if not client_info:
            logger.error("Could not find active client session for %s; skipping", rover_code)
            return
        mountpoint = client_info.get("Mountpoint", "")
        if not mountpoint:
            logger.error("Missing mountpoint for %s; cannot send SET command", rover_code)
            return

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
        ):
            logger.error("Failed to set %s as temporary base", rover_code)
            return

        await asyncio.sleep(10)
        route_payload = {
            "ntrip_route": {
                "source_host": "127.0.0.1",
                "source_port": 5001,
                "target_host": self.caster_host,
                "target_port": self.caster_port,
                "mountpoint": f"{rover_code}_BASE",
                "password": "123",
            }
        }
        self.mqtt_client.publish("command/ntrip/route/start", json.dumps(route_payload))
        if on_collection_started:
            on_collection_started()
        logger.info("Waiting 15s for cross-baselines referenced to %s", rover_code)
        await asyncio.sleep(15)
        self.mqtt_client.publish(
            "command/ntrip/route/stop",
            json.dumps({"station_code": f"{rover_code}_BASE"}),
        )
        await asyncio.sleep(5)

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
        try:
            reader, writer = await asyncio.open_connection(self.caster_host, self.caster_port)
            writer.write(b"GET /clienttable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await reader.read()
            writer.close()
            await writer.wait_closed()
            for line in data.decode(errors="ignore").strip().split("\n"):
                parts = line.split(";")
                if len(parts) > 4 and parts[0] == "STR":
                    username, receiver_id, mountpoint = parts[1], parts[2], parts[3]
                    if station_code.lower() in username.lower() or station_code.lower() in mountpoint.lower():
                        return {"Username": username, "receiverID": receiver_id, "Mountpoint": mountpoint}
        except Exception as exc:
            logger.error("Error fetching /clienttable: %s", exc)
        return None

    async def _send_set_command(self, mountpoint: str, username: str, receiver_id: str, commands: List[bytes], password: str = "123") -> bool:
        """Send a Caster SET request and Unicore commands to the selected rover."""
        try:
            reader, writer = await asyncio.open_connection(self.caster_host, self.caster_port)
            auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = (
                f"SET /{mountpoint} HTTP/1.0\r\n"
                f"User-Agent: NTRIP SetBaseCmd/{receiver_id}\r\n"
                f"Authorization: Basic {auth_str}\r\n\r\n"
            )
            writer.write(headers.encode("ascii"))
            await writer.drain()
            response = (await reader.read(1024)).decode("ascii", errors="ignore")
            if "200 OK" not in response:
                logger.error("SET request rejected by Caster: %s", response)
                writer.close()
                await writer.wait_closed()
                return False
            for command in commands:
                writer.write(command)
                await writer.drain()
                await asyncio.sleep(0.1)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception as exc:
            logger.error("Error sending SET command to %s: %s", mountpoint, exc)
            return False

    def _build_geotek_lte_unicore_config(self, setup_method: str, duration: int = 60, lat: float = 0, lon: float = 0, alt: float = 0) -> list[bytes]:
        """Build the Unicore command sequence for a fixed or survey-in base."""
        commands = [b"FRESET\r\n", b"unlogall\r\n"]
        port = "com2"
        if setup_method.upper() == "SURVEY_IN":
            commands.append(f"mode base time {duration}\r\n".encode("ascii"))
        else:
            commands.append(f"mode base {lat} {lon} {alt}\r\n".encode("ascii"))
        commands.append(f"gpgga {port} 1\r\n".encode("ascii"))
        for message in ("1006", "1033", "1074", "1124", "1084", "1094", "1042", "1019", "1020", "1045", "1077", "1127", "1087", "1097"):
            commands.append(f"rtcm{message} {port} 1\r\n".encode("ascii"))
        commands.append(b"saveconfig\r\n")
        return commands
