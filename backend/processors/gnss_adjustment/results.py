"""Round-Robin results responsibilities."""

from __future__ import annotations

import copy
import math
import time
from typing import Any, Callable, Dict, Iterable, List, Optional
import numpy as np
from scipy.stats import chi2
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

class RoundRobinResultsMixin:
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


    @staticmethod
    def _filter_vector_outliers(
        samples: List[dict],
        min_samples: int = 5,
        absolute_floor_m: float = 0.25,
        sigma_multiplier: float = 8.0,
    ) -> tuple[List[dict], List[dict]]:
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
            if len(rows) < min_samples:
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
                absolute_floor_m,
                median_deviation + sigma_multiplier * robust_sigma,
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

    @staticmethod
    def _filter_position_type_mixes(
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

    def _accumulate_session_summaries(
        self, contiguous_sessions: List[List[dict]]
    ) -> List[dict]:
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
            session_summaries.append({
                "session": session_index,
                "session_id": session_rows[0].get("session_id"),
                "observation_count": len(session_rows),
                "mean_xyz": tuple(float(value) for value in session_mean),
            })
        return session_summaries

    @staticmethod
    def _find_max_session_mean_separation(
        session_summaries: List[dict],
    ) -> tuple[float, Optional[tuple[float, ...]], Optional[tuple[Any, Any]]]:
        max_separation = 0.0
        max_difference = None
        max_pair = None
        for left in range(len(session_summaries)):
            for right in range(left + 1, len(session_summaries)):
                difference = (
                    np.asarray(session_summaries[right]["mean_xyz"], dtype=float)
                    - np.asarray(session_summaries[left]["mean_xyz"], dtype=float)
                )
                separation = float(np.linalg.norm(difference))
                if separation > max_separation:
                    max_separation = separation
                    max_difference = tuple(float(v) for v in difference)
                    max_pair = (
                        session_summaries[left]["session_id"] or session_summaries[left]["session"],
                        session_summaries[right]["session_id"] or session_summaries[right]["session"],
                    )
        return max_separation, max_difference, max_pair

    def _weighted_edges(self, samples: List[dict]) -> List[dict]:
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

            acf_effective_sample_size, ess_sessions = _edge_effective_sample_size(
                rows,
                pooled_lag_one,
            )
            contiguous_sessions = _split_effective_sample_sessions(rows)
            effective_sample_size = float(len(contiguous_sessions))
            session_summaries = self._accumulate_session_summaries(contiguous_sessions)
            (
                max_session_mean_separation,
                max_session_mean_difference,
                max_session_mean_pair,
            ) = self._find_max_session_mean_separation(session_summaries)

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
                    row
                    for row in rows
                    if int(row.get("position_type") or 0) == position_type
                ]
                if not type_rows:
                    continue
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

        filter_vector_outliers = lambda samples: self._filter_vector_outliers(
            samples,
            min_samples=vector_outlier_min_samples,
            absolute_floor_m=vector_outlier_absolute_floor_m,
            sigma_multiplier=vector_outlier_sigma_multiplier,
        )

        filter_position_type_mixes = self._filter_position_type_mixes

        weighted_edges = self._weighted_edges

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
        independent_global_test = None
        if independent_result.global_test:
            ref_std = (
                math.sqrt(independent_result.variance_factor)
                if independent_result.variance_factor is not None and independent_result.variance_factor >= 0
                else None
            )
            independent_global_test = {
                "statistic": independent_result.global_test.statistic,
                "lower_critical_value": independent_result.global_test.lower_critical_value,
                "upper_critical_value": independent_result.global_test.upper_critical_value,
                "p_value": independent_result.global_test.p_value,
                "passed": independent_result.global_test.passed,
                "applicable": True,
                "assumption": "All accepted raw epochs are statistically independent.",
                "used_for_published_solution": False,
                "weighted_residual_sum": independent_result.weighted_residual_sum,
                "reference_standard_deviation": ref_std,
            }
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
        if not quality_gate_passed:
            interpretation_status = "FAILED_QUALITY_GATE"
        elif diagnostic_warnings:
            interpretation_status = "PASS_WITH_WARNINGS"
        else:
            interpretation_status = "PASS"

        return {
            "type": "gnss_adjusted",
            "source": "AGRICA_ROUND_ROBIN",
            "adjustment_engine": "backend.processors.gnss_adjustment.adjust_network",
            "project_id": project_id,
            "project_code": cluster.get("project_code"),
            "cluster_index": cluster_index,
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
