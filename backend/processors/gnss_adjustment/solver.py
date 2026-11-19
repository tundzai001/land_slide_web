"""Numerically stable weighted least-squares adjustment for GNSS baselines."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2, norm

from .models import (
    AdjustedBaseline,
    AdjustedPoint,
    AdjustmentResult,
    GlobalTestResult,
    Network,
    NetworkError,
    ResidualFlag,
)
from .transforms import covariance_standard_deviation


def _block_diagonal(blocks: list[NDArray[np.float64]]) -> NDArray[np.float64]:
    size = sum(block.shape[0] for block in blocks)
    result = np.zeros((size, size), dtype=float)
    offset = 0
    for block in blocks:
        width = block.shape[0]
        result[offset : offset + width, offset : offset + width] = block
        offset += width
    return result


def _build_linearized_model(
    network: Network,
    unknown_index: dict[str, int],
    observation_count: int,
    parameter_count: int,
    csharp_compatible: bool,
) -> tuple[NDArray[np.float64], NDArray[np.float64], list[NDArray[np.float64]]]:
    design = np.zeros((observation_count, parameter_count), dtype=float)
    observed_minus_computed = np.zeros(observation_count, dtype=float)
    covariance_blocks: list[NDArray[np.float64]] = []

    for index, baseline in enumerate(network.baselines):
        rows = slice(3 * index, 3 * index + 3)
        if baseline.from_point in unknown_index:
            column = 3 * unknown_index[baseline.from_point]
            design[rows, column : column + 3] -= np.eye(3)
        if baseline.to_point in unknown_index:
            column = 3 * unknown_index[baseline.to_point]
            design[rows, column : column + 3] += np.eye(3)

        start = np.asarray(network.points[baseline.from_point].approximate)
        end = np.asarray(network.points[baseline.to_point].approximate)
        observed_minus_computed[rows] = np.asarray(baseline.delta) - (end - start)

        covariance = baseline.covariance_array()
        if csharp_compatible:
            if baseline.covariance is not None:
                raise NetworkError(
                    "C# compatibility mode only supports per-component standard deviations"
                )
            covariance = covariance + np.eye(3) * 1e-8
        covariance_blocks.append(covariance)
    return design, observed_minus_computed, covariance_blocks


def _build_adjusted_points(
    network: Network,
    unknown_index: dict[str, int],
    correction: NDArray[np.float64],
    covariance_parameters: NDArray[np.float64],
    posterior_covariance_parameters: NDArray[np.float64],
) -> list[AdjustedPoint]:
    adjusted_points: list[AdjustedPoint] = []
    for name, point in network.points.items():
        if point.fixed:
            p_corr = np.zeros(3)
            p_std = np.zeros(3)
            p_cov = np.zeros((3, 3), dtype=float)
            post_std = np.zeros(3)
            post_cov = np.zeros((3, 3), dtype=float)
        else:
            offset = 3 * unknown_index[name]
            p_corr = correction[offset : offset + 3]
            p_cov = covariance_parameters[offset : offset + 3, offset : offset + 3]
            p_cov = (p_cov + p_cov.T) / 2.0
            p_std = np.asarray(covariance_standard_deviation(p_cov), dtype=float)
            post_cov = posterior_covariance_parameters[offset : offset + 3, offset : offset + 3]
            post_cov = (post_cov + post_cov.T) / 2.0
            post_std = np.asarray(covariance_standard_deviation(post_cov), dtype=float)

        coord = np.asarray(point.approximate) + p_corr
        adjusted_points.append(
            AdjustedPoint(
                name=name,
                coordinate=tuple(float(v) for v in coord),
                correction=tuple(float(v) for v in p_corr),
                standard_deviation=tuple(float(v) for v in p_std),
                covariance=tuple(tuple(float(v) for v in row) for row in p_cov),
                posterior_standard_deviation=tuple(float(v) for v in post_std),
                posterior_covariance=tuple(tuple(float(v) for v in row) for row in post_cov),
                fixed=point.fixed,
            )
        )
    return adjusted_points


def _build_adjusted_baselines(
    network: Network,
    residual: NDArray[np.float64],
    standardized: NDArray[np.float64],
    redundancy: NDArray[np.float64],
) -> list[AdjustedBaseline]:
    adjusted_baselines: list[AdjustedBaseline] = []
    for index, baseline in enumerate(network.baselines):
        rows = slice(3 * index, 3 * index + 3)
        b_res = residual[rows]
        adjusted = np.asarray(baseline.delta) + b_res
        adjusted_baselines.append(
            AdjustedBaseline(
                from_point=baseline.from_point,
                to_point=baseline.to_point,
                observed=baseline.delta,
                residual=tuple(float(v) for v in b_res),
                adjusted=tuple(float(v) for v in adjusted),
                standardized_residual=tuple(float(v) for v in standardized[rows]),
                redundancy=tuple(float(v) for v in redundancy[rows]),
            )
        )
    return adjusted_baselines


def _validate_network_inputs(
    network: Network,
    a_priori_variance_factor: float,
    global_significance: float,
    local_significance: float,
    parameter_count: int,
    observation_count: int,
) -> None:
    network.validate()
    if not np.isfinite(a_priori_variance_factor) or a_priori_variance_factor <= 0.0:
        raise NetworkError("a_priori_variance_factor must be positive and finite")
    if not 0.0 < global_significance < 1.0:
        raise NetworkError("global_significance must be between 0 and 1")
    if not 0.0 < local_significance < 1.0:
        raise NetworkError("local_significance must be between 0 and 1")
    if parameter_count == 0:
        raise NetworkError("network has no unknown points to adjust")
    if observation_count < parameter_count:
        raise NetworkError(
            f"insufficient observations: {observation_count} equations for {parameter_count} unknowns"
        )


def adjust_network(
    network: Network,
    *,
    rcond: float | None = None,
    a_priori_variance_factor: float = 1.0,
    global_significance: float = 0.05,
    local_significance: float = 0.001,
    csharp_compatible: bool = False,
) -> AdjustmentResult:
    """Adjust a 3D baseline network using full-covariance weighted least squares."""
    unknown_names = [name for name, point in network.points.items() if not point.fixed]
    unknown_index = {name: index for index, name in enumerate(unknown_names)}
    observation_count = 3 * len(network.baselines)
    parameter_count = 3 * len(unknown_names)

    _validate_network_inputs(
        network,
        a_priori_variance_factor,
        global_significance,
        local_significance,
        parameter_count,
        observation_count,
    )

    design, observed_minus_computed, covariance_blocks = _build_linearized_model(
        network, unknown_index, observation_count, parameter_count, csharp_compatible
    )

    whitened_design = np.empty_like(design)
    whitened_rhs = np.empty_like(observed_minus_computed)
    for index, covariance in enumerate(covariance_blocks):
        rows = slice(3 * index, 3 * index + 3)
        cholesky = np.linalg.cholesky(covariance)
        whitened_design[rows] = np.linalg.solve(cholesky, design[rows])
        whitened_rhs[rows] = np.linalg.solve(cholesky, observed_minus_computed[rows])

    correction, _, rank, singular_values = np.linalg.lstsq(
        whitened_design, whitened_rhs, rcond=rcond
    )
    if rank != parameter_count:
        raise NetworkError(
            f"rank-deficient network: design rank {rank}, expected {parameter_count}; "
            "check connectivity and fixed points"
        )

    residual = design @ correction - observed_minus_computed
    whitened_residual = whitened_design @ correction - whitened_rhs
    weighted_residual_sum = float(whitened_residual @ whitened_residual)
    degrees_of_freedom = observation_count - parameter_count
    variance_factor = (
        weighted_residual_sum / degrees_of_freedom if degrees_of_freedom > 0 else None
    )

    _, singular_values_full, vt = np.linalg.svd(whitened_design, full_matrices=False)
    cofactor_parameters = (vt.T / np.square(singular_values_full)) @ vt
    covariance_parameters = a_priori_variance_factor * cofactor_parameters
    posterior_scale = variance_factor if variance_factor is not None else a_priori_variance_factor
    posterior_covariance_parameters = posterior_scale * cofactor_parameters

    covariance_observations = _block_diagonal(covariance_blocks)
    covariance_residual = covariance_observations - design @ cofactor_parameters @ design.T
    covariance_residual = (covariance_residual + covariance_residual.T) / 2.0

    residual_std = np.sqrt(
        np.maximum(a_priori_variance_factor * np.diag(covariance_residual), 0.0)
    )
    standardized = np.divide(
        residual,
        residual_std,
        out=np.zeros_like(residual),
        where=residual_std > np.finfo(float).eps,
    )
    observation_variance = np.diag(covariance_observations)
    redundancy = np.clip(
        np.divide(
            np.diag(covariance_residual),
            observation_variance,
            out=np.zeros_like(observation_variance),
            where=observation_variance > 0.0,
        ),
        0.0,
        1.0,
    )

    adjusted_points = _build_adjusted_points(
        network, unknown_index, correction, covariance_parameters, posterior_covariance_parameters
    )
    adjusted_baselines = _build_adjusted_baselines(network, residual, standardized, redundancy)

    nonzero_standardized = np.abs(standardized[residual_std > np.finfo(float).eps])
    max_standardized = (
        float(np.max(nonzero_standardized)) if nonzero_standardized.size else None
    )
    condition_number = (
        float(singular_values[0] / singular_values[-1]) if singular_values[-1] > 0 else math.inf
    )

    global_test: GlobalTestResult | None = None
    if degrees_of_freedom > 0:
        statistic = weighted_residual_sum / a_priori_variance_factor
        lower_probability = global_significance / 2.0
        lower_critical = float(chi2.ppf(lower_probability, degrees_of_freedom))
        upper_critical = float(chi2.ppf(1.0 - lower_probability, degrees_of_freedom))
        lower_tail = float(chi2.cdf(statistic, degrees_of_freedom))
        upper_tail = float(chi2.sf(statistic, degrees_of_freedom))
        global_test = GlobalTestResult(
            statistic=statistic,
            lower_critical_value=lower_critical,
            upper_critical_value=upper_critical,
            p_value=min(1.0, 2.0 * min(lower_tail, upper_tail)),
            significance_level=global_significance,
            passed=lower_critical <= statistic <= upper_critical,
        )

    local_critical = float(norm.isf(local_significance / 2.0))
    residual_flags: list[ResidualFlag] = []
    component_names = ("X", "Y", "Z")
    for flat_index, normalized_residual in enumerate(standardized):
        if residual_std[flat_index] <= np.finfo(float).eps:
            continue
        if abs(normalized_residual) <= local_critical:
            continue
        baseline_index, component_index = divmod(flat_index, 3)
        baseline = network.baselines[baseline_index]
        residual_flags.append(
            ResidualFlag(
                baseline_index=baseline_index,
                from_point=baseline.from_point,
                to_point=baseline.to_point,
                component=component_names[component_index],
                normalized_residual=float(normalized_residual),
                p_value=float(2.0 * norm.sf(abs(normalized_residual))),
                critical_value=local_critical,
                redundancy=float(redundancy[flat_index]),
            )
        )

    return AdjustmentResult(
        points=tuple(adjusted_points),
        baselines=tuple(adjusted_baselines),
        variance_factor=variance_factor,
        degrees_of_freedom=degrees_of_freedom,
        weighted_residual_sum=weighted_residual_sum,
        rank=int(rank),
        condition_number=condition_number,
        max_standardized_residual=max_standardized,
        a_priori_variance_factor=a_priori_variance_factor,
        global_test=global_test,
        residual_flags=tuple(residual_flags),
        csharp_compatible=csharp_compatible,
        csharp_reference_standard_deviation=(
            0.001 * math.sqrt(variance_factor)
            if csharp_compatible and variance_factor is not None
            else None
        ),
    )
