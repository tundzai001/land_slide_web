"""Rain-gauge history export writer."""

from __future__ import annotations

from typing import Any, Mapping

from .common import build_sensor_export

RAIN_FIELDS = (
    "rainfall",
    "rain_mm",
    "precipitation",
    "rain_rate",
    "intensity",
    "status",
)


def export_record(record: object, mapping: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(getattr(record, "sensor_type", "") or "").lower() != "rain":
        return None
    return build_sensor_export(record, mapping, "rain", payload_fields=RAIN_FIELDS)
