"""Input/output helpers for legacy text files and a documented JSON format."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import AdjustmentResult, Baseline, Network, NetworkError, Point


_SPLIT = re.compile(r"[\s,]+")


def _tokens(line: str) -> list[str]:
    return [token for token in _SPLIT.split(line.strip()) if token]


def read_legacy_text(path: str | Path) -> Network:
    """Read the text format accepted by the original C# application.

    The point section starts at a header containing ``Point_name`` and the
    baseline section at a header containing ``From_Point``. Values are N/E/H.
    """

    source = Path(path)
    points: list[Point] = []
    baselines: list[Baseline] = []
    section: str | None = None

    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        lines = source.read_text(encoding="cp1258").splitlines()

    for line_number, raw_line in enumerate(lines, start=1):
        if "Point_name" in raw_line:
            section = "points"
            continue
        if "From_Point" in raw_line:
            section = "baselines"
            continue
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        values = _tokens(line)
        try:
            if section == "points":
                if len(values) < 5:
                    raise NetworkError("point row needs at least 5 columns")
                points.append(
                    Point(
                        identifier=int(values[0]),
                        name=values[1],
                        approximate=(float(values[2]), float(values[3]), float(values[4])),
                        fixed=any(value.lower() in {"fix", "fixed", "control"} for value in values[5:]),
                    )
                )
            elif section == "baselines":
                if len(values) < 9:
                    raise NetworkError("baseline row needs at least 9 columns")
                baselines.append(
                    Baseline(
                        identifier=int(values[0]),
                        from_point=values[1],
                        to_point=values[2],
                        delta=(float(values[3]), float(values[4]), float(values[5])),
                        standard_deviation=(float(values[6]), float(values[7]), float(values[8])),
                    )
                )
            else:
                raise NetworkError("data appears before a recognized section header")
        except (ValueError, NetworkError) as exc:
            raise NetworkError(f"{source}:{line_number}: {exc}") from exc

    network = Network.from_items(points, baselines)
    network.validate()
    return network


def read_json(path: str | Path) -> Network:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        points = [
            Point(
                name=item["name"],
                approximate=tuple(item["coordinate"]),
                fixed=bool(item.get("fixed", False)),
                identifier=item.get("id"),
            )
            for item in payload["points"]
        ]
        baselines = []
        for item in payload["baselines"]:
            kwargs: dict[str, Any] = {
                "from_point": item["from"],
                "to_point": item["to"],
                "delta": tuple(item["delta"]),
                "identifier": item.get("id"),
            }
            if "covariance" in item:
                kwargs["covariance"] = tuple(tuple(row) for row in item["covariance"])
            else:
                kwargs["standard_deviation"] = tuple(item["std"])
            baselines.append(Baseline(**kwargs))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, NetworkError) as exc:
        raise NetworkError(f"invalid network JSON {source}: {exc}") from exc
    network = Network.from_items(points, baselines)
    network.validate()
    return network


def read_network(path: str | Path) -> Network:
    source = Path(path)
    return read_json(source) if source.suffix.lower() == ".json" else read_legacy_text(source)


def result_to_dict(result: AdjustmentResult) -> dict[str, Any]:
    return {
        "summary": {
            "variance_factor": result.variance_factor,
            "reference_standard_deviation": (
                result.variance_factor**0.5 if result.variance_factor is not None else None
            ),
            "degrees_of_freedom": result.degrees_of_freedom,
            "weighted_residual_sum": result.weighted_residual_sum,
            "rank": result.rank,
            "condition_number": result.condition_number,
            "max_standardized_residual": result.max_standardized_residual,
            "a_priori_variance_factor": result.a_priori_variance_factor,
            "global_test": asdict(result.global_test) if result.global_test else None,
            "flagged_residual_count": len(result.residual_flags),
            "csharp_compatible": result.csharp_compatible,
            "csharp_reference_standard_deviation": result.csharp_reference_standard_deviation,
        },
        "points": [asdict(point) for point in result.points],
        "baselines": [asdict(baseline) for baseline in result.baselines],
        "residual_flags": [asdict(flag) for flag in result.residual_flags],
    }


def write_result_json(result: AdjustmentResult, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(result_to_dict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
