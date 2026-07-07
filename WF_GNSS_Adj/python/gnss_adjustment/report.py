"""Human-readable adjustment report."""

from __future__ import annotations

import math
from pathlib import Path

from .models import AdjustmentResult


def format_report(result: AdjustmentResult) -> str:
    lines = [
        "GNSS BASELINE NETWORK ADJUSTMENT",
        "Coordinate order: North, East, Height (metres)",
        "",
        "SUMMARY",
        f"Rank                     : {result.rank}",
        f"Degrees of freedom       : {result.degrees_of_freedom}",
        f"Condition number         : {result.condition_number:.6g}",
        f"Weighted residual sum    : {result.weighted_residual_sum:.9g}",
    ]
    if result.variance_factor is None:
        lines.append("Reference std. deviation  : n/a (network has no redundancy)")
    else:
        lines.append(f"Reference std. deviation  : {math.sqrt(result.variance_factor):.6f}")
    if result.csharp_reference_standard_deviation is not None:
        lines.append(
            f"C# legacy M (scale 0.001)  : {result.csharp_reference_standard_deviation:.6f}"
        )
    if result.max_standardized_residual is not None:
        lines.append(f"Max normalized residual   : {result.max_standardized_residual:.3f}")
    if result.global_test is not None:
        test = result.global_test
        lines.extend(
            [
                "",
                "GLOBAL CHI-SQUARE TEST",
                f"Statistic                  : {test.statistic:.6f}",
                f"Acceptance interval        : [{test.lower_critical_value:.6f}, "
                f"{test.upper_critical_value:.6f}]",
                f"Two-sided p-value          : {test.p_value:.6g}",
                f"Decision                   : {'PASS' if test.passed else 'FAIL'}",
            ]
        )
    if result.csharp_compatible:
        lines.extend(
            [
                "",
                "COMPATIBILITY MODE",
                "Replicates Adj.cs weights: Pii = 0.001^2 / (std_i^2 + 1e-8).",
            ]
        )

    lines.extend(
        [
            "",
            "ADJUSTED POINTS",
            "Name       Fixed          North           East         Height      sN      sE      sH",
        ]
    )
    for point in result.points:
        n, e, h = point.coordinate
        sn, se, sh = point.standard_deviation
        lines.append(
            f"{point.name:<10} {str(point.fixed):<5} {n:14.4f} {e:14.4f} {h:14.4f}"
            f" {sn:7.4f} {se:7.4f} {sh:7.4f}"
        )

    lines.extend(
        [
            "",
            "ADJUSTED BASELINES AND RESIDUALS",
            "From       To              dN            dE            dH"
            "          vN          vE          vH    max|w|",
        ]
    )
    for baseline in result.baselines:
        dn, de, dh = baseline.adjusted
        vn, ve, vh = baseline.residual
        max_w = max(abs(value) for value in baseline.standardized_residual)
        lines.append(
            f"{baseline.from_point:<10} {baseline.to_point:<10}"
            f" {dn:13.5f} {de:13.5f} {dh:13.5f}"
            f" {vn:11.5f} {ve:11.5f} {vh:11.5f} {max_w:9.3f}"
        )
    lines.extend(["", "DATA SNOOPING FLAGS (diagnostic only; observations were not removed)"])
    if result.global_test is not None and not result.global_test.passed:
        lines.append(
            "WARNING: global test failed; multiple flags can indicate an unrealistic stochastic model "
            "or systematic error, not independent blunders."
        )
    if not result.residual_flags:
        lines.append("No observation component exceeded the configured critical value.")
    else:
        lines.append("No.  Baseline       Axis       w        p-value   critical  redundancy")
        for flag in result.residual_flags:
            lines.append(
                f"{flag.baseline_index + 1:<4} {flag.from_point}->{flag.to_point:<10}"
                f" {flag.component:^4} {flag.normalized_residual:9.3f}"
                f" {flag.p_value:12.4g} {flag.critical_value:9.3f} {flag.redundancy:11.3f}"
            )
    return "\n".join(lines) + "\n"


def write_report(result: AdjustmentResult, path: str | Path) -> None:
    Path(path).write_text(format_report(result), encoding="utf-8")
