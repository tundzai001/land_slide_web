"""IMU history export writer."""

from __future__ import annotations

from typing import Any, Mapping

from .common import build_sensor_export

IMU_FIELDS = (
    "roll",
    "pitch",
    "yaw",
    "drift_len_mm",
    "drift_dir",
    "raw_roll",
    "raw_pitch",
    "raw_yaw",
    "battery",
    "status",
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
    "total_accel",
)


def export_record(record: object, mapping: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(getattr(record, "sensor_type", "") or "").lower() != "imu":
        return None
    return build_sensor_export(record, mapping, "imu", payload_fields=IMU_FIELDS)
