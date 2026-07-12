"""Domain models for a three-dimensional GNSS baseline network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from numpy.typing import NDArray


Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]


class NetworkError(ValueError):
    """Raised when a network cannot be adjusted safely."""


def _vector3(values: Iterable[float], label: str) -> Vector3:
    result = tuple(float(value) for value in values)
    if len(result) != 3:
        raise NetworkError(f"{label} must contain exactly three values (N, E, H)")
    if not np.all(np.isfinite(result)):
        raise NetworkError(f"{label} contains a non-finite value")
    return result  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Point:
    """A network point in local/projected North, East, Height coordinates."""

    name: str
    approximate: Vector3
    fixed: bool = False
    identifier: int | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise NetworkError("point name cannot be empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "approximate", _vector3(self.approximate, f"point {name}"))


@dataclass(frozen=True, slots=True)
class Baseline:
    """An observed vector from ``from_point`` to ``to_point`` in N/E/H order."""

    from_point: str
    to_point: str
    delta: Vector3
    standard_deviation: Vector3 | None = None
    covariance: Matrix3 | None = None
    identifier: int | None = None

    def __post_init__(self) -> None:
        start, end = self.from_point.strip(), self.to_point.strip()
        if not start or not end or start == end:
            raise NetworkError("a baseline must connect two different named points")
        object.__setattr__(self, "from_point", start)
        object.__setattr__(self, "to_point", end)
        object.__setattr__(self, "delta", _vector3(self.delta, f"baseline {start}->{end}"))

        if (self.standard_deviation is None) == (self.covariance is None):
            raise NetworkError(
                f"baseline {start}->{end} needs exactly one of standard_deviation or covariance"
            )
        if self.standard_deviation is not None:
            std = _vector3(self.standard_deviation, f"standard deviation {start}->{end}")
            if any(value <= 0.0 for value in std):
                raise NetworkError(f"baseline {start}->{end} standard deviations must be positive")
            object.__setattr__(self, "standard_deviation", std)
        else:
            covariance = np.asarray(self.covariance, dtype=float)
            if covariance.shape != (3, 3) or not np.all(np.isfinite(covariance)):
                raise NetworkError(f"baseline {start}->{end} covariance must be a finite 3x3 matrix")
            if not np.allclose(covariance, covariance.T, rtol=1e-10, atol=1e-15):
                raise NetworkError(f"baseline {start}->{end} covariance must be symmetric")
            try:
                np.linalg.cholesky(covariance)
            except np.linalg.LinAlgError as exc:
                raise NetworkError(
                    f"baseline {start}->{end} covariance must be positive definite"
                ) from exc
            frozen = tuple(tuple(float(value) for value in row) for row in covariance)
            object.__setattr__(self, "covariance", frozen)

    def covariance_array(self) -> NDArray[np.float64]:
        if self.covariance is not None:
            return np.asarray(self.covariance, dtype=float)
        assert self.standard_deviation is not None
        return np.diag(np.square(self.standard_deviation))


@dataclass(slots=True)
class Network:
    points: dict[str, Point] = field(default_factory=dict)
    baselines: list[Baseline] = field(default_factory=list)

    @classmethod
    def from_items(cls, points: Iterable[Point], baselines: Iterable[Baseline]) -> "Network":
        point_map: dict[str, Point] = {}
        for point in points:
            if point.name in point_map:
                raise NetworkError(f"duplicate point name: {point.name}")
            point_map[point.name] = point
        return cls(point_map, list(baselines))

    def validate(self) -> None:
        if not self.points:
            raise NetworkError("network has no points")
        if not self.baselines:
            raise NetworkError("network has no baselines")
        fixed = {name for name, point in self.points.items() if point.fixed}
        if not fixed:
            raise NetworkError("network needs at least one fixed point to define its datum")

        adjacency = {name: set() for name in self.points}
        for baseline in self.baselines:
            for endpoint in (baseline.from_point, baseline.to_point):
                if endpoint not in self.points:
                    raise NetworkError(
                        f"baseline {baseline.from_point}->{baseline.to_point} references unknown point {endpoint}"
                    )
            adjacency[baseline.from_point].add(baseline.to_point)
            adjacency[baseline.to_point].add(baseline.from_point)

        unseen = set(self.points)
        while unseen:
            seed = next(iter(unseen))
            component, stack = set(), [seed]
            while stack:
                name = stack.pop()
                if name in component:
                    continue
                component.add(name)
                stack.extend(adjacency[name] - component)
            unseen -= component
            if component.isdisjoint(fixed):
                names = ", ".join(sorted(component))
                raise NetworkError(f"network component has no fixed point: {names}")


@dataclass(frozen=True, slots=True)
class AdjustedPoint:
    name: str
    coordinate: Vector3
    correction: Vector3
    standard_deviation: Vector3
    covariance: Matrix3
    posterior_standard_deviation: Vector3
    posterior_covariance: Matrix3
    fixed: bool


@dataclass(frozen=True, slots=True)
class AdjustedBaseline:
    from_point: str
    to_point: str
    observed: Vector3
    residual: Vector3
    adjusted: Vector3
    standardized_residual: Vector3
    redundancy: Vector3


@dataclass(frozen=True, slots=True)
class GlobalTestResult:
    """Two-sided global chi-square test of the a-priori stochastic model."""

    statistic: float
    lower_critical_value: float
    upper_critical_value: float
    p_value: float
    significance_level: float
    passed: bool


@dataclass(frozen=True, slots=True)
class ResidualFlag:
    """An observation component flagged by normalized-residual data snooping."""

    baseline_index: int
    from_point: str
    to_point: str
    component: str
    normalized_residual: float
    p_value: float
    critical_value: float
    redundancy: float


@dataclass(frozen=True, slots=True)
class AdjustmentResult:
    points: tuple[AdjustedPoint, ...]
    baselines: tuple[AdjustedBaseline, ...]
    variance_factor: float | None
    degrees_of_freedom: int
    weighted_residual_sum: float
    rank: int
    condition_number: float
    max_standardized_residual: float | None
    a_priori_variance_factor: float
    global_test: GlobalTestResult | None
    residual_flags: tuple[ResidualFlag, ...]
    csharp_compatible: bool
    csharp_reference_standard_deviation: float | None
