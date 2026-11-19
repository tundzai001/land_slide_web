"""Statistical diagnostics and covariance accumulation for GNSS adjustment."""
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

_ESS_MIN_SESSION_SAMPLES = 8
_ESS_MAX_CONTIGUOUS_GAP_SECONDS = 5
_BASELINE_STD_REJECTION_THRESHOLD_M = 0.1
def _spd_solve(matrix: Any, right_hand_side: Any) -> np.ndarray:
    """Solve a symmetric positive-definite system without forming an inverse."""

    covariance = np.asarray(matrix, dtype=float)
    covariance = 0.5 * (covariance + covariance.T)
    if covariance.shape != (3, 3) or not np.all(np.isfinite(covariance)):
        raise ValueError("covariance must be a finite 3x3 matrix")
    minimum_eigenvalue = float(np.min(np.linalg.eigvalsh(covariance)))
    if minimum_eigenvalue <= np.finfo(float).eps:
        raise ValueError(
            "covariance is not positive definite; "
            f"minimum eigenvalue={minimum_eigenvalue:.3e}"
        )
    cholesky = np.linalg.cholesky(covariance)
    intermediate = np.linalg.solve(cholesky, np.asarray(right_hand_side, dtype=float))
    return np.linalg.solve(cholesky.T, intermediate)


def _formal_covariance_from_precision(precision_sum: Any) -> np.ndarray:
    covariance = _spd_solve(precision_sum, np.eye(3, dtype=float))
    return 0.5 * (covariance + covariance.T)


def _rolling_mean_stability(
    samples: Iterable[tuple[int, Iterable[float]]],
    *,
    window_seconds: int = 10,
    min_samples_per_window: int = 4,
    max_sample_gap_seconds: int = 5,
    horizontal_component_limit_m: float = 0.003,
    up_component_limit_m: float = 0.005,
    horizontal_std_limit_m: float = 0.010,
    up_std_limit_m: float = 0.015,
    horizontal_slope_limit_mps: float = 0.001,
    up_slope_limit_mps: float = 0.002,
    ewma_fast_tau_seconds: float = 3.0,
    ewma_slow_tau_seconds: float = 30.0,
    **kwargs,
) -> dict:
    """Compare two consecutive time-based baseline-mean windows.

    FIXED/source validation says where a vector came from; it does not prove
    that the ambiguity solution is stationary.  This diagnostic is deliberately
    component-wise so a vertical drift cannot hide inside a 3-D norm.  The
    windows are measured in receiver time rather than sample count because the
    field AGRICA stream is commonly slower and more irregular than 1 Hz.
    """

    ewma_horizontal_limit_m = kwargs.get("ewma_horizontal_limit_m", 0.008)
    ewma_up_limit_m = kwargs.get("ewma_up_limit_m", 0.015)

    by_epoch: Dict[int, np.ndarray] = {}
    for epoch, vector in samples:
        try:
            epoch_value = int(epoch)
            vector_value = np.asarray(tuple(vector), dtype=float)
        except (TypeError, ValueError):
            continue
        if vector_value.shape != (3,) or not np.all(np.isfinite(vector_value)):
            continue
        by_epoch[epoch_value] = vector_value

    ordered = sorted(by_epoch.items())
    window_seconds = max(1, int(window_seconds))
    min_samples_per_window = max(1, int(min_samples_per_window))
    max_sample_gap_seconds = max(1, int(max_sample_gap_seconds))
    result = {
        "stable": False,
        "enough_samples": False,
        "distinct_epoch_count": len(ordered),
        "window_seconds": window_seconds,
        "min_samples_per_window": min_samples_per_window,
        "max_sample_gap_seconds": max_sample_gap_seconds,
        "horizontal_component_limit_m": float(horizontal_component_limit_m),
        "up_component_limit_m": float(up_component_limit_m),
        "horizontal_std_limit_m": float(horizontal_std_limit_m),
        "up_std_limit_m": float(up_std_limit_m),
        "horizontal_slope_limit_mps": float(horizontal_slope_limit_mps),
        "up_slope_limit_mps": float(up_slope_limit_mps),
        "delta_neu_m": None,
        "delta_3d_m": None,
        "previous_window_std_neu_m": None,
        "recent_window_std_neu_m": None,
        "previous_window_slope_neu_mps": None,
        "recent_window_slope_neu_mps": None,
        "ewma_delta_neu_m": None,
        "ewma_transition_detected": False,
        "latest_epoch": ordered[-1][0] if ordered else None,
        "stable_run_start_epoch": None,
        "stable_run_seconds": 0,
    }
    if len(ordered) < min_samples_per_window * 2:
        return result

    def window_statistics(rows: list[tuple[int, np.ndarray]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        epochs = np.asarray([epoch for epoch, _vector in rows], dtype=float)
        vectors = np.vstack([vector for _epoch, vector in rows])
        mean = np.mean(vectors, axis=0)
        std = np.std(vectors, axis=0, ddof=1) if len(rows) > 1 else np.zeros(3)
        centered_time = epochs - float(np.mean(epochs))
        denominator = float(centered_time @ centered_time)
        slope = (
            centered_time @ (vectors - mean) / denominator
            if denominator > np.finfo(float).eps
            else np.zeros(3)
        )
        return mean, std, np.asarray(slope, dtype=float)

    def diagnostic_at(end_index: int) -> Optional[dict]:
        end_epoch = int(ordered[end_index][0])
        recent_start = end_epoch - window_seconds + 1
        previous_start = end_epoch - 2 * window_seconds + 1
        previous_end = end_epoch - window_seconds
        previous = [
            (epoch, vector)
            for epoch, vector in ordered[:end_index + 1]
            if previous_start <= epoch <= previous_end
        ]
        recent = [
            (epoch, vector)
            for epoch, vector in ordered[:end_index + 1]
            if recent_start <= epoch <= end_epoch
        ]
        if (
            len(previous) < min_samples_per_window
            or len(recent) < min_samples_per_window
        ):
            return None
        previous_mean, previous_std, previous_slope = window_statistics(previous)
        recent_mean, recent_std, recent_slope = window_statistics(recent)
        delta = recent_mean - previous_mean
        mean_stable = bool(
            abs(float(delta[0])) <= horizontal_component_limit_m
            and abs(float(delta[1])) <= horizontal_component_limit_m
            and abs(float(delta[2])) <= up_component_limit_m
        )
        scatter_stable = bool(
            max(abs(float(previous_std[0])), abs(float(recent_std[0])))
            <= horizontal_std_limit_m
            and max(abs(float(previous_std[1])), abs(float(recent_std[1])))
            <= horizontal_std_limit_m
            and max(abs(float(previous_std[2])), abs(float(recent_std[2])))
            <= up_std_limit_m
        )
        slope_stable = bool(
            max(abs(float(previous_slope[0])), abs(float(recent_slope[0])))
            <= horizontal_slope_limit_mps
            and max(abs(float(previous_slope[1])), abs(float(recent_slope[1])))
            <= horizontal_slope_limit_mps
            and max(abs(float(previous_slope[2])), abs(float(recent_slope[2])))
            <= up_slope_limit_mps
        )
        return {
            "stable": mean_stable and scatter_stable and slope_stable,
            "mean_stable": mean_stable,
            "scatter_stable": scatter_stable,
            "slope_stable": slope_stable,
            "delta_neu_m": tuple(float(value) for value in delta),
            "delta_3d_m": float(np.linalg.norm(delta)),
            "previous_window_std_neu_m": tuple(float(value) for value in previous_std),
            "recent_window_std_neu_m": tuple(float(value) for value in recent_std),
            "previous_window_slope_neu_mps": tuple(float(value) for value in previous_slope),
            "recent_window_slope_neu_mps": tuple(float(value) for value in recent_slope),
            "previous_window_start_epoch": previous[0][0],
            "previous_window_end_epoch": previous[-1][0],
            "previous_window_sample_count": len(previous),
            "recent_window_start_epoch": recent[0][0],
            "recent_window_end_epoch": recent[-1][0],
            "recent_window_sample_count": len(recent),
        }

    stable_run_start_epoch = None
    previous_diagnostic_epoch = None
    latest_diagnostic = None
    latest_diagnostic_epoch = None
    for end_index in range(len(ordered)):
        current_diagnostic = diagnostic_at(end_index)
        if current_diagnostic is None:
            continue
        current_epoch = int(ordered[end_index][0])
        latest_diagnostic = current_diagnostic
        latest_diagnostic_epoch = current_epoch
        if (
            current_diagnostic["stable"]
            and (
                previous_diagnostic_epoch is None
                or current_epoch - previous_diagnostic_epoch
                <= max_sample_gap_seconds
            )
        ):
            if stable_run_start_epoch is None:
                stable_run_start_epoch = current_epoch
        else:
            stable_run_start_epoch = current_epoch if current_diagnostic["stable"] else None
        previous_diagnostic_epoch = current_epoch

    if latest_diagnostic is None:
        return result

    fast_mean = ordered[0][1].astype(float, copy=True)
    slow_mean = ordered[0][1].astype(float, copy=True)
    previous_epoch = int(ordered[0][0])
    for epoch, vector in ordered[1:]:
        dt = max(0.0, float(int(epoch) - previous_epoch))
        alpha_fast = 1.0 - math.exp(-dt / max(float(ewma_fast_tau_seconds), 1e-6))
        alpha_slow = 1.0 - math.exp(-dt / max(float(ewma_slow_tau_seconds), 1e-6))
        fast_mean += alpha_fast * (vector - fast_mean)
        slow_mean += alpha_slow * (vector - slow_mean)
        previous_epoch = int(epoch)
    ewma_delta = fast_mean - slow_mean
    ewma_transition = bool(
        abs(float(ewma_delta[0])) > ewma_horizontal_limit_m
        or abs(float(ewma_delta[1])) > ewma_horizontal_limit_m
        or abs(float(ewma_delta[2])) > ewma_up_limit_m
    )
    result.update(latest_diagnostic)
    result["ewma_delta_neu_m"] = tuple(float(value) for value in ewma_delta)
    result["ewma_transition_detected"] = ewma_transition
    result["ewma_fast_tau_seconds"] = float(ewma_fast_tau_seconds)
    result["ewma_slow_tau_seconds"] = float(ewma_slow_tau_seconds)
    result["latest_epoch"] = latest_diagnostic_epoch
    result["enough_samples"] = True
    if result["stable"] and stable_run_start_epoch is not None:
        result["stable_run_start_epoch"] = stable_run_start_epoch
        result["stable_run_seconds"] = max(
            0, int(result["latest_epoch"]) - int(stable_run_start_epoch)
        )
    return result


def _rolling_drift_exceeds_abort_limits(
    diagnostic: dict,
    *,
    horizontal_component_limit_m: float,
    up_component_limit_m: float,
) -> bool:
    """Return true only when a complete rolling diagnostic exceeds hysteresis."""

    delta = diagnostic.get("delta_neu_m")
    if not diagnostic.get("enough_samples") or not delta or len(delta) != 3:
        return False
    rolling_exceeded = bool(
        abs(float(delta[0])) > horizontal_component_limit_m
        or abs(float(delta[1])) > horizontal_component_limit_m
        or abs(float(delta[2])) > up_component_limit_m
    )
    return rolling_exceeded or bool(diagnostic.get("ewma_transition_detected"))


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

@dataclass
class _InformationAccumulator:
    """Mergeable online baseline state; formal covariance is never published directly."""

    count: int = 0
    first_epoch: Optional[int] = None
    last_epoch: Optional[int] = None
    precision_sum: np.ndarray = field(
        default_factory=lambda: np.zeros((3, 3), dtype=float)
    )
    information_sum: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=float)
    )
    recent_blocks: Dict[int, dict] = field(default_factory=dict)
    fast_ewma: Optional[np.ndarray] = None
    slow_ewma: Optional[np.ndarray] = None

    def add(
        self,
        epoch: int,
        vector: Iterable[float],
        covariance: Any,
        *,
        fast_tau_seconds: float,
        slow_tau_seconds: float,
        retention_seconds: int,
    ) -> None:
        epoch = int(epoch)
        value = np.asarray(tuple(vector), dtype=float)
        if value.shape != (3,) or not np.all(np.isfinite(value)):
            raise ValueError("baseline vector must contain three finite values")
        precision = _spd_solve(covariance, np.eye(3, dtype=float))
        self.precision_sum += precision
        self.information_sum += precision @ value
        previous_epoch = self.last_epoch
        self.count += 1
        self.first_epoch = epoch if self.first_epoch is None else min(self.first_epoch, epoch)
        self.last_epoch = epoch if self.last_epoch is None else max(self.last_epoch, epoch)

        if self.fast_ewma is None:
            self.fast_ewma = value.copy()
            self.slow_ewma = value.copy()
        else:
            dt = max(0.0, float(epoch - int(previous_epoch or epoch)))
            alpha_fast = 1.0 - math.exp(-dt / max(float(fast_tau_seconds), 1e-6))
            alpha_slow = 1.0 - math.exp(-dt / max(float(slow_tau_seconds), 1e-6))
            self.fast_ewma += alpha_fast * (value - self.fast_ewma)
            self.slow_ewma += alpha_slow * (value - self.slow_ewma)

        block = self.recent_blocks.setdefault(epoch, {
            "count": 0,
            "sum": np.zeros(3, dtype=float),
            "sum_outer": np.zeros((3, 3), dtype=float),
            "precision_sum": np.zeros((3, 3), dtype=float),
            "information_sum": np.zeros(3, dtype=float),
        })
        block["count"] += 1
        block["sum"] += value
        block["sum_outer"] += np.outer(value, value)
        block["precision_sum"] += precision
        block["information_sum"] += precision @ value
        cutoff = epoch - max(1, int(retention_seconds))
        for expired_epoch in [item for item in self.recent_blocks if item < cutoff]:
            self.recent_blocks.pop(expired_epoch, None)

    @property
    def mean(self) -> Optional[np.ndarray]:
        if self.count <= 0:
            return None
        return np.linalg.solve(self.precision_sum, self.information_sum)

    @property
    def formal_covariance(self) -> Optional[np.ndarray]:
        if self.count <= 0:
            return None
        return _formal_covariance_from_precision(self.precision_sum)

    def recent_samples(self) -> list[tuple[int, tuple[float, float, float]]]:
        return [
            (
                epoch,
                tuple(float(value) for value in block["sum"] / block["count"]),
            )
            for epoch, block in sorted(self.recent_blocks.items())
            if int(block["count"]) > 0
        ]

    def audit_snapshot(self) -> dict:
        mean = self.mean
        formal_covariance = self.formal_covariance
        return {
            "count": self.count,
            "first_epoch": self.first_epoch,
            "last_epoch": self.last_epoch,
            "duration_seconds": (
                int(self.last_epoch) - int(self.first_epoch)
                if self.first_epoch is not None and self.last_epoch is not None else 0
            ),
            "weighted_mean_neu": (
                tuple(float(value) for value in mean) if mean is not None else None
            ),
            "formal_covariance_neu": (
                tuple(tuple(float(value) for value in row) for row in formal_covariance)
                if formal_covariance is not None else None
            ),
            "fast_ewma_neu": (
                tuple(float(value) for value in self.fast_ewma)
                if self.fast_ewma is not None else None
            ),
            "slow_ewma_neu": (
                tuple(float(value) for value in self.slow_ewma)
                if self.slow_ewma is not None else None
            ),
            "recent_second_block_count": len(self.recent_blocks),
        }

