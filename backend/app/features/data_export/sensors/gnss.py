"""GNSS history and audit export writer."""

from __future__ import annotations

from typing import Any, Mapping

from .common import build_sensor_export

GNSS_FIELDS = (
    "raw_gngga",
    "fix_quality",
    "fix_mode",
    "accepted",
    "reason",
    "message",
    "total_displacement_mm",
    "speed_2d_mm_s",
    "forward_action",
    "forward_topic",
    "forward_broker",
    "forward_rc",
)


def dataset_for(record: object) -> str | None:
    sensor_type = str(getattr(record, "sensor_type", "") or "").lower()
    if sensor_type == "gnss":
        return "gnss"
    if sensor_type != "gnss_audit":
        return None
    # Keep routine and anomalous raw evidence in one ordered stream. The
    # reason/forward fields remain in the row, so no raw GNSS is discarded and
    # the archive never creates duplicate files when audit kinds interleave.
    return "gnss_audit"


def export_record(record: object, mapping: Mapping[str, Any]) -> dict[str, Any] | None:
    dataset = dataset_for(record)
    if dataset is None:
        return None
    return build_sensor_export(
        record,
        mapping,
        dataset,
        payload_fields=GNSS_FIELDS,
        include_forward_payload=True,
    )
