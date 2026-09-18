"""Water-level history export writer."""

from __future__ import annotations

from typing import Any, Mapping

from .common import build_sensor_export

WATER_FIELDS = (
    "water_level",
    "water_level_cm",
    "water_display_value",
    "water_display_unit",
    "sensortype",
    "sensorname",
    "status",
)


def export_record(record: object, mapping: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(getattr(record, "sensor_type", "") or "").lower() != "water":
        return None
    return build_sensor_export(record, mapping, "water", payload_fields=WATER_FIELDS)
