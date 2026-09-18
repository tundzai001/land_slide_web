"""Small export helpers and the explicit sensor-to-writer dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..cells import excel_chunks

COMMON_HEADERS = (
    "id",
    "time",
    "timestamp",
    "project_code",
    "station_code",
    "station_id",
    "sensor_type",
    "record_type",
)
VALUE_HEADERS = ("value_1", "value_2", "value_3", "value_4", "value_5")
JSON_HEADERS = tuple(f"data_json_{index}" for index in range(1, 9))


def _payload_of(record: object) -> dict[str, Any]:
    payload = getattr(record, "data", None)
    return payload if isinstance(payload, dict) else {"raw_value": payload}


def _time_text(timestamp: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def build_sensor_export(
    record: object,
    mapping: Mapping[str, Any],
    dataset: str,
    *,
    payload_fields: Sequence[str] = (),
    include_forward_payload: bool = False,
) -> dict[str, Any]:
    """Build the common row shape for a sensor writer."""
    payload = _payload_of(record)
    sensor_type = str(getattr(record, "sensor_type", "") or "")
    headers = list(COMMON_HEADERS)
    headers.extend(payload_fields)
    if include_forward_payload:
        headers.extend(f"forward_payload_{index}" for index in range(1, 9))
    headers.extend(VALUE_HEADERS)
    headers.extend(JSON_HEADERS)

    row: list[Any] = [
        getattr(record, "id", None),
        _time_text(getattr(record, "timestamp", None)),
        getattr(record, "timestamp", None),
        mapping.get("project_code", "UNKNOWN_PROJECT"),
        mapping.get("station_code", f"station_{getattr(record, 'station_id', 0)}"),
        getattr(record, "station_id", None),
        sensor_type,
        "audit" if sensor_type == "gnss_audit" else "measurement",
    ]
    row.extend(payload.get(field) for field in payload_fields)
    if include_forward_payload:
        row.extend(excel_chunks(payload.get("forward_payload"), 8))
    row.extend(getattr(record, field, None) for field in VALUE_HEADERS)
    row.extend(excel_chunks(payload, 8))
    return {
        "dataset": dataset,
        "filename": f"{dataset.upper()}.csv",
        "headers": tuple(headers),
        "row": tuple(row),
    }


def export_sensor_record(
    record: object, mapping: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Send each supported sensor type directly to its own writer."""
    sensor_type = str(getattr(record, "sensor_type", "") or "").lower()
    if sensor_type in {"gnss", "gnss_audit"}:
        from .gnss import export_record

        return export_record(record, mapping)
    if sensor_type == "imu":
        from .imu import export_record

        return export_record(record, mapping)
    if sensor_type == "rain":
        from .rain import export_record

        return export_record(record, mapping)
    if sensor_type == "water":
        from .water import export_record

        return export_record(record, mapping)
    return None
