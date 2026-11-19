import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.stats import chi2

from .models import Baseline, Network, NetworkError, Point
from .solver import adjust_network
from .transforms import (
    covariance_standard_deviation,
    ecef_point_covariance_to_enu,
    neu_standard_deviation_to_ecef_covariance,
)


def _llh_to_ecef(lat_deg: float, lon_deg: float, h_m: float) -> tuple[float, float, float]:
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2*f - f**2
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = a / math.sqrt(1 - e2 * sin_lat**2)
    x = (N + h_m) * cos_lat * math.cos(lon)
    y = (N + h_m) * cos_lat * math.sin(lon)
    z = (N * (1 - e2) + h_m) * sin_lat
    return x, y, z


@dataclass(frozen=True)
class AgricaObservation:
    project_id: int
    station_id: int
    rover_name: str
    epoch_ts: int
    position_type: Optional[int]
    baseline_neu: tuple[float, float, float]
    std_neu_raw: tuple[Optional[float], Optional[float], Optional[float]]
    std_neu: tuple[float, float, float]
    rover_position_std_ecef_raw: Optional[tuple[float, float, float]]
    rover_position_std_ecef: Optional[tuple[float, float, float]]
    rover_llh: Optional[tuple[float, float, float]]
    rover_ecef: Optional[tuple[float, float, float]]
    base_llh: Optional[tuple[float, float, float]]
    raw: str
    full_data: Dict[str, Any]


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(str(value).strip())
        if not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value).strip()))
    except Exception:
        return None


def _positive_std(value: Optional[float], fallback: float = 0.02) -> float:
    if value is None or value <= 0:
        return fallback
    return max(float(value), 1e-4)


def extract_agrica_sentences(raw_payload: str) -> list[str]:
    if not raw_payload:
        return []
    compact = raw_payload.replace("\r", "").replace("\n", "")
    return [
        match.strip()
        for match in re.findall(r"#AGRICA[^;]*;GNSS,[^*]*(?:\*[0-9A-Fa-f]+)?", compact)
        if match.strip()
    ]


def _parse_agrica_epoch(parts: list[str], received_ts: Optional[int]) -> int:
    year = _safe_int(parts[2])
    month = _safe_int(parts[3])
    day = _safe_int(parts[4])
    hour = _safe_int(parts[5])
    minute = _safe_int(parts[6])
    second = _safe_float(parts[7])
    epoch_ts = int(received_ts or time.time())
    if None not in (year, month, day, hour, minute) and second is not None:
        try:
            import calendar
            full_year = year if year and year > 1900 else 2000 + int(year or 0)
            epoch_ts = int(calendar.timegm((
                int(full_year), int(month), int(day),
                int(hour), int(minute), int(second),
            )))
        except Exception:
            pass
    return epoch_ts


def _parse_agrica_positions(parts: list[str]) -> tuple[Optional[tuple], Optional[tuple], Optional[tuple]]:
    rover_llh = None
    lat, lon, alt = _safe_float(parts[29]), _safe_float(parts[30]), _safe_float(parts[31])
    if lat is not None and lon is not None and alt is not None:
        rover_llh = (lat, lon, alt)

    rover_ecef = None
    x, y, z = _safe_float(parts[32]), _safe_float(parts[33]), _safe_float(parts[34])
    if x is not None and y is not None and z is not None:
        rover_ecef = (x, y, z)

    base_llh = None
    base_lat, base_lon, base_alt = _safe_float(parts[41]), _safe_float(parts[42]), _safe_float(parts[43])
    if base_lat is not None and base_lon is not None and base_alt is not None:
        base_llh = (base_lat, base_lon, base_alt)
    return rover_llh, rover_ecef, base_llh


def _parse_agrica_stds(parts: list[str]) -> tuple[Optional[tuple], Optional[tuple], tuple]:
    rover_std_raw = None
    rover_std = None
    std_x, std_y, std_z = _safe_float(parts[38]), _safe_float(parts[39]), _safe_float(parts[40])
    if std_x is not None and std_y is not None and std_z is not None:
        rover_std_raw = (float(std_x), float(std_y), float(std_z))
        rover_std = (_positive_std(std_x), _positive_std(std_y), _positive_std(std_z))

    std_neu_raw = (_safe_float(parts[16]), _safe_float(parts[17]), _safe_float(parts[18]))
    return rover_std_raw, rover_std, std_neu_raw


def _parse_single_agrica_sentence(
    sentence: str, project_id: int, station_id: int, rover_name: str, received_ts: Optional[int]
) -> Optional[AgricaObservation]:
    if ";" not in sentence:
        return None
    data_part = sentence.split(";", 1)[1].split("*", 1)[0]
    parts = data_part.split(",")
    if len(parts) < 44 or parts[0] != "GNSS":
        return None

    baseline_n, baseline_e, baseline_u = _safe_float(parts[13]), _safe_float(parts[14]), _safe_float(parts[15])
    if baseline_n is None or baseline_e is None or baseline_u is None:
        return None

    epoch_ts = _parse_agrica_epoch(parts, received_ts)
    rover_llh, rover_ecef, base_llh = _parse_agrica_positions(parts)
    rover_std_raw, rover_std, std_neu_raw = _parse_agrica_stds(parts)

    return AgricaObservation(
        project_id=int(project_id),
        station_id=int(station_id),
        rover_name=str(rover_name or station_id),
        epoch_ts=epoch_ts,
        position_type=_safe_int(parts[8]),
        baseline_neu=(float(baseline_n), float(baseline_e), float(baseline_u)),
        std_neu_raw=std_neu_raw,
        std_neu=(_positive_std(std_neu_raw[0]), _positive_std(std_neu_raw[1]), _positive_std(std_neu_raw[2])),
        rover_position_std_ecef_raw=rover_std_raw,
        rover_position_std_ecef=rover_std,
        rover_llh=rover_llh,
        rover_ecef=rover_ecef,
        base_llh=base_llh,
        raw=sentence,
        full_data={
            "parts": parts,
            "gps_satellites": _safe_int(parts[10]),
            "bds_satellites": _safe_int(parts[11]),
            "glonass_satellites": _safe_int(parts[12]),
            "galileo_satellites": _safe_int(parts[53]) if len(parts) > 53 else None,
            "velocity_up_std": _safe_float(parts[28]),
            "diff_age": _safe_float(parts[48]) if len(parts) > 48 else None,
            "undulation": _safe_float(parts[50]) if len(parts) > 50 else None,
            "baseline_std_neu_raw": std_neu_raw,
            "rover_position_std_ecef_raw": rover_std_raw,
            "rover_position_std_ecef_used": rover_std,
        }
    )


def parse_agrica(
    raw_payload: str,
    *,
    project_id: int,
    station_id: int,
    rover_name: str,
    received_ts: Optional[int] = None,
) -> list[AgricaObservation]:
    observations = []
    for sentence in extract_agrica_sentences(raw_payload):
        obs = _parse_single_agrica_sentence(sentence, project_id, station_id, rover_name, received_ts)
        if obs is not None:
            observations.append(obs)
    return observations
    return observations


class AgricaAdjustmentRuntime:
    """AGRICA -> tested gnss_adjustment.Network -> tested adjust_network()."""

    def __init__(self, epoch_tolerance_s: int = 2, max_epoch_age_s: int = 15):
        self.epoch_tolerance_s = int(epoch_tolerance_s)
        self.max_epoch_age_s = int(max_epoch_age_s)
        self._buffers: dict[tuple[int, int], dict[int, AgricaObservation]] = {}

    def add_payload(self, raw_payload: str, info: Dict[str, Any], received_ts: Optional[int] = None) -> Optional[Dict[str, Any]]:
        project_id = int(info.get("project_id") or info.get("station_id") or 0)
        station_id = int(info.get("station_id") or 0)
        rover_name = str(info.get("station_code") or info.get("station_name") or f"station_{station_id}")
        observations = parse_agrica(
            raw_payload,
            project_id=project_id,
            station_id=station_id,
            rover_name=rover_name,
            received_ts=received_ts,
        )
        if not observations:
            return None

        latest = None
        now_ts = int(received_ts or time.time())
        project_gnss_clusters = info.get("project_gnss_clusters")
        station_origins = info.get("station_origins") or {}

        for obs in observations:
            epoch_bucket = int(round(obs.epoch_ts / self.epoch_tolerance_s) * self.epoch_tolerance_s)
            key = (obs.project_id, epoch_bucket)
            bucket = self._buffers.setdefault(key, {})
            bucket[obs.station_id] = obs
            latest = self._adjust_bucket(key, now_ts, project_gnss_clusters, station_origins)

        self._prune(now_ts)
        return latest

    def _prune(self, now_ts: int) -> None:
        stale = [key for key in self._buffers if abs(now_ts - key[1]) > self.max_epoch_age_s]
        for key in stale:
            self._buffers.pop(key, None)

    @staticmethod
    def _extract_cluster_base_info(c: dict, c_idx: int, cluster_bases: dict, cluster_base_info: dict) -> None:
        b_lat, b_lon, b_alt = c.get("base_lat"), c.get("base_lon"), c.get("base_alt")
        if b_lat is None or b_lon is None:
            return
        try:
            cluster_bases[c_idx] = _llh_to_ecef(float(b_lat), float(b_lon), float(b_alt or 0))
            cluster_base_info[c_idx] = {
                "name": c.get("base_station", "CORS_BASE"),
                "host": c.get("base_stream_host", ""),
                "port": c.get("base_stream_port", ""),
                "mp": c.get("base_stream_mp", "")
            }
        except Exception:
            pass

    @classmethod
    def _prepare_clusters_and_bases(
        cls, gnss_clusters: Optional[list], observations: list[AgricaObservation]
    ) -> tuple[list[set], dict, dict]:
        clusters = []
        cluster_bases = {}
        cluster_base_info = {}
        if gnss_clusters and isinstance(gnss_clusters, list):
            for c in gnss_clusters:
                if isinstance(c, list):
                    clusters.append(set(c))
                elif isinstance(c, dict):
                    stations_in_cluster = c.get("stations", [])
                    if isinstance(stations_in_cluster, list):
                        clusters.append(set(stations_in_cluster))
                        cls._extract_cluster_base_info(c, len(clusters) - 1, cluster_bases, cluster_base_info)
        if not clusters:
            clusters = [{obs.station_id for obs in observations}]
        else:
            assigned = set().union(*clusters)
            unassigned = {obs.station_id for obs in observations if obs.station_id not in assigned}
            if unassigned:
                clusters.append(unassigned)
        return clusters, cluster_bases, cluster_base_info

    @staticmethod
    def _match_base_from_origins(cluster_obs: list[AgricaObservation], station_origins: dict) -> Optional[tuple]:
        best_base_match = None
        min_diff = 5.0
        for obs in cluster_obs:
            if not (obs.rover_ecef and obs.base_llh and station_origins.get(obs.station_id)):
                continue
            rep_base_ecef = _llh_to_ecef(obs.base_llh[0], obs.base_llh[1], obs.base_llh[2])
            actual_baseline = (
                obs.rover_ecef[0] - rep_base_ecef[0],
                obs.rover_ecef[1] - rep_base_ecef[1],
                obs.rover_ecef[2] - rep_base_ecef[2],
            )
            rover_origin = station_origins[obs.station_id]
            for cand_sid, cand_origin in station_origins.items():
                if cand_sid == obs.station_id:
                    continue
                expected_baseline = (
                    cand_origin[0] - rover_origin[0],
                    cand_origin[1] - rover_origin[1],
                    cand_origin[2] - rover_origin[2],
                )
                diff = math.sqrt(sum((actual_baseline[k] - expected_baseline[k])**2 for k in range(3)))
                if diff < min_diff:
                    min_diff = diff
                    best_base_match = cand_origin
        return best_base_match

    def _resolve_cluster_base(
        self, cluster_obs: list[AgricaObservation], cluster_bases: dict,
        cluster_base_info: dict, c_idx: int, station_origins: dict, steps_list: list
    ) -> Optional[tuple]:
        resolved_base_ecef = cluster_bases.get(c_idx)
        base_info = cluster_base_info.get(c_idx)
        if resolved_base_ecef:
            base_name = base_info.get("name") if base_info else "BASE"
            host_str = f" ({base_info.get('host', '')}:{base_info.get('port', '')}/{base_info.get('mp', '')})" if base_info and base_info.get('host') else ""
            steps_list.append({
                "step": 3,
                "title": "Chốt điểm Base gốc",
                "message": f"Base chốt cố định từ cấu hình dự án: {base_name}{host_str} tại tọa độ ECEF: {[round(x,3) for x in resolved_base_ecef]}",
                "data": {"base_ecef": list(resolved_base_ecef), "base_info": base_info}
            })
            return resolved_base_ecef

        best_base_match = self._match_base_from_origins(cluster_obs, station_origins)
        if best_base_match:
            resolved_base_ecef = best_base_match
        else:
            base_llh = next((obs.base_llh for obs in cluster_obs if obs.base_llh), None)
            if not base_llh:
                return None
            resolved_base_ecef = _llh_to_ecef(base_llh[0], base_llh[1], base_llh[2])

        steps_list.append({
            "step": 3,
            "title": "Chốt điểm Base gốc",
            "message": f"Base chốt cố định tại tọa độ ECEF: {[round(x,3) for x in resolved_base_ecef]}",
            "data": {"base_ecef": list(resolved_base_ecef)}
        })
        return resolved_base_ecef

    def _adjust_single_cluster(
        self, cluster_obs: list[AgricaObservation], resolved_base_ecef: tuple, steps_list: list,
        final_adjusted_points: dict, final_adjusted_baselines: list, now_ts: int
    ) -> None:
        points = [Point("BASE", resolved_base_ecef, fixed=True)]
        baselines = []
        for obs in cluster_obs:
            if not obs.base_llh:
                continue
            north, east, up = obs.baseline_neu
            lat, lon = math.radians(obs.base_llh[0]), math.radians(obs.base_llh[1])
            baseline_ecef = (
                -math.sin(lat) * math.cos(lon) * north - math.sin(lon) * east + math.cos(lat) * math.cos(lon) * up,
                -math.sin(lat) * math.sin(lon) * north + math.cos(lon) * east + math.cos(lat) * math.sin(lon) * up,
                math.cos(lat) * north + math.sin(lat) * up,
            )
            rover_ecef_in = tuple(resolved_base_ecef[k] + baseline_ecef[k] for k in range(3))
            points.append(Point(obs.rover_name, rover_ecef_in, fixed=False, identifier=obs.station_id))
            baselines.append(Baseline(
                "BASE", obs.rover_name, baseline_ecef, identifier=obs.station_id,
                covariance=neu_standard_deviation_to_ecef_covariance(obs.std_neu, obs.base_llh[0], obs.base_llh[1]),
            ))

        if len(points) < 2:
            return None

        try:
            result = adjust_network(Network.from_items(points, baselines))
            steps_list.append({
                "step": 4,
                "title": "Giải phương trình Mạng GNSS",
                "message": f"Ma trận thiết kế (A), Trọng số (P). Bậc tự do (DoF): {result.degrees_of_freedom}, Rank: {result.rank}. Giải thuật Least Squares thành công."
            })
        except NetworkError:
            return None

        obs_by_name = {obs.rover_name: obs for obs in cluster_obs}
        for point in result.points:
            if point.name == "BASE":
                continue
            obs = obs_by_name.get(point.name)
            final_adjusted_points[point.name] = {
                "station_id": obs.station_id if obs else None,
                "position_type": obs.position_type if obs else None,
                "adjusted_x": point.coordinate[0],
                "adjusted_y": point.coordinate[1],
                "adjusted_z": point.coordinate[2],
                "covariance_enu": ecef_point_covariance_to_enu(point.covariance, tuple(point.coordinate)),
                "posterior_covariance_enu": ecef_point_covariance_to_enu(point.posterior_covariance, tuple(point.coordinate)),
                "timestamp": now_ts,
            }

        for baseline in result.baselines:
            final_adjusted_baselines.append({
                "from": baseline.from_point,
                "to": baseline.to_point,
                "dx": baseline.adjusted[0],
                "dy": baseline.adjusted[1],
                "dz": baseline.adjusted[2],
                "residual_x": baseline.residual[0],
                "residual_y": baseline.residual[1],
                "residual_z": baseline.residual[2],
                "redundancy": baseline.redundancy,
                "standardized_residual": baseline.standardized_residual,
            })
        return result

    @staticmethod
    def _compute_stochastic_and_quality_tests(result: Any) -> tuple[Optional[dict], Optional[dict]]:
        if not result or not result.global_test:
            return None, None
        statistic = float(result.global_test.statistic)
        significance = float(result.global_test.significance_level)
        upper_critical = float(chi2.ppf(1.0 - significance, result.degrees_of_freedom))
        network_passed = statistic <= upper_critical
        network_quality_test = {
            "method": "UPPER_TAIL_NETWORK_QUALITY",
            "statistic": statistic,
            "upper_critical_value": upper_critical,
            "p_value": float(chi2.sf(statistic, result.degrees_of_freedom)),
            "p_value_tail": "UPPER",
            "significance_level": significance,
            "passed": network_passed,
            "applicable": True,
            "approximate": False,
            "conclusion": ("PASSED" if network_passed else "FAILED_HIGH_RESIDUAL"),
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
            "approximate": False,
        }
        return network_quality_test, stochastic_model_test

    def _process_clusters(
        self, clusters: list[set], observations: list[AgricaObservation],
        cluster_bases: dict, cluster_base_info: dict, station_origins: dict,
        steps_list: list, final_adjusted_points: dict, final_adjusted_baselines: list, now_ts: int
    ) -> Any:
        last_result = None
        for c_idx, cluster_stations in enumerate(clusters):
            cluster_obs = [obs for obs in observations if obs.station_id in cluster_stations]
            if not cluster_obs:
                continue
            resolved_base_ecef = self._resolve_cluster_base(
                cluster_obs, cluster_bases, cluster_base_info, c_idx, station_origins, steps_list
            )
            if not resolved_base_ecef:
                continue
            c_result = self._adjust_single_cluster(
                cluster_obs, resolved_base_ecef, steps_list, final_adjusted_points, final_adjusted_baselines, now_ts
            )
            if c_result is not None:
                last_result = c_result
        return last_result

    @staticmethod
    def _build_adjustment_payload(
        key: tuple[int, int], now_ts: int, global_base_llh: Optional[tuple],
        final_adjusted_points: dict, final_adjusted_baselines: list,
        steps_list: list, last_result: Any, network_quality_test: Any, stochastic_model_test: Any
    ) -> dict[str, Any]:
        return {
            "type": "gnss_adjusted",
            "steps": steps_list,
            "source": "AGRICA",
            "adjustment_engine": "backend.processors.gnss_adjustment.adjust_network_ecef",
            "project_id": key[0],
            "epoch_ts": key[1],
            "computed_at": now_ts,
            "base": {
                "name": "BASE",
                "fixed": True,
                "lat": global_base_llh[0] if global_base_llh else None,
                "lon": global_base_llh[1] if global_base_llh else None,
                "h": global_base_llh[2] if global_base_llh else None,
            },
            "rover_count": len(final_adjusted_points),
            "points": final_adjusted_points,
            "baselines": final_adjusted_baselines,
            "quality": {
                "published_point_std_scale": "a_priori",
                "normalized_residual_scale": "a_priori",
                "degrees_of_freedom": last_result.degrees_of_freedom if last_result else 0,
                "variance_factor": last_result.variance_factor if last_result else None,
                "reference_standard_deviation": (
                    math.sqrt(last_result.variance_factor)
                    if last_result and last_result.variance_factor is not None and last_result.variance_factor >= 0.0
                    else None
                ),
                "weighted_residual_sum": last_result.weighted_residual_sum if last_result else 0.0,
                "rank": last_result.rank if last_result else 0,
                "condition_number": last_result.condition_number if last_result else None,
                "max_standardized_residual": last_result.max_standardized_residual if last_result else None,
                "global_test": network_quality_test,
                "stochastic_model_test": stochastic_model_test,
                "residual_flags": [
                    {
                        "from": flag.from_point,
                        "to": flag.to_point,
                        "component": flag.component,
                        "normalized_residual": flag.normalized_residual,
                        "p_value": flag.p_value,
                        "critical_value": flag.critical_value,
                    }
                    for flag in (last_result.residual_flags if last_result else [])
                ],
                "note": (
                    "No redundant check yet if this epoch only has one BASE->Rover baseline per rover"
                    if (not last_result or last_result.degrees_of_freedom == 0) else "Redundant GNSS network adjusted"
                ),
            },
        }

    def _adjust_bucket(self, key: tuple[int, int], now_ts: int, gnss_clusters: Optional[list[list[int]]] = None, station_origins: Optional[dict[int, tuple[float, float, float]]] = None) -> Optional[Dict[str, Any]]:
        observations = [obs for obs in self._buffers.get(key, {}).values() if obs.position_type in (4, 7)]
        if not observations:
            return None

        global_base_llh = next((obs.base_llh for obs in observations if obs.base_llh), None)
        station_origins = station_origins or {}
        clusters, cluster_bases, cluster_base_info = self._prepare_clusters_and_bases(gnss_clusters, observations)
        final_adjusted_points = {}
        final_adjusted_baselines = []
        steps_list = [{
            "step": 1,
            "title": "Ghi nhận dữ liệu",
            "message": f"Đã thu thập dữ liệu LLH và AGRIC từ {len(observations)} trạm Rover.",
            "data": {obs.station_id: obs.rover_llh for obs in observations}
        }]

        last_result = self._process_clusters(
            clusters, observations, cluster_bases, cluster_base_info, station_origins,
            steps_list, final_adjusted_points, final_adjusted_baselines, now_ts
        )

        if not final_adjusted_points:
            return None

        steps_list.append({
            "step": 5,
            "title": "Kết quả Bình sai",
            "message": f"Hoàn tất tính toán! Cập nhật toạ độ chuẩn cho {len(final_adjusted_points)} Rovers."
        })

        network_quality_test, stochastic_model_test = self._compute_stochastic_and_quality_tests(last_result)
        return self._build_adjustment_payload(
            key, now_ts, global_base_llh, final_adjusted_points, final_adjusted_baselines,
            steps_list, last_result, network_quality_test, stochastic_model_test
        )
