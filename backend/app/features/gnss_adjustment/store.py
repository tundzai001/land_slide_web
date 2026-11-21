"""Persistence shape for GNSS adjustment results and raw evidence."""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...database import DataSessionLocal
from ...models import data as model_data
from ..data_export.reports.adjustment.artifacts import adjustment_report_links

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Normalize tuples and numeric library values for JSON database columns."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def compact_adjustment_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Remove verbose raw observations from the result stored in SensorData."""
    compact = copy.deepcopy(payload)
    evidence: list[dict[str, Any]] = []

    observations = compact.pop("baseline_observations", None)
    if isinstance(observations, list):
        evidence.extend(item for item in observations if isinstance(item, dict))

    context = compact.get("context")
    if isinstance(context, dict):
        context = copy.deepcopy(context)
        diagnostics = context.get("diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics = copy.deepcopy(diagnostics)
            raw_gnss = diagnostics.pop("raw_gnss", None)
            if isinstance(raw_gnss, list):
                evidence.extend(item for item in raw_gnss if isinstance(item, dict))
            context["diagnostics"] = diagnostics
        raw_gnss = context.pop("raw_gnss", None)
        if isinstance(raw_gnss, list):
            evidence.extend(item for item in raw_gnss if isinstance(item, dict))
        compact["context"] = context

    return _json_safe(compact), _json_safe(evidence)


def add_report_links(
    payload: dict[str, Any],
    *,
    project_id: int,
    timestamp: int,
) -> dict[str, Any]:
    """Add stable API links to a compact payload; links are not file paths."""
    result = dict(payload)
    result.update(
        adjustment_report_links(
            project_id,
            timestamp,
            project_code=result.get("project_code"),
            cluster_name=result.get("cluster_name"),
            run_id=result.get("run_id"),
        )
    )
    return result


def _extract_evidence_row(record: object) -> dict[str, Any]:
    if isinstance(record, dict):
        row = copy.deepcopy(record.get("data") if "data" in record else record)
        raw_payload = record.get("raw_payload")
    else:
        row = copy.deepcopy(getattr(record, "data", None) or {})
        raw_payload = getattr(record, "raw_payload", None)
    if raw_payload is not None:
        row["raw_payload"] = raw_payload
    return row


def hydrate_adjustment_payload(
    payload: dict[str, Any],
    evidence: Iterable[object],
) -> dict[str, Any]:
    """Reattach raw evidence only for a requested human-readable export."""
    if "baseline_observations" in payload:
        return copy.deepcopy(payload)
    result = copy.deepcopy(payload)
    observations = [_extract_evidence_row(record) for record in evidence]
    if observations:
        if str(result.get("status") or "").lower() == "failed":
            context = result.setdefault("context", {})
            diagnostics = context.setdefault("diagnostics", {})
            diagnostics["raw_gnss"] = observations
        else:
            result["baseline_observations"] = observations
    return result


def evidence_records(
    evidence: Iterable[dict[str, Any]],
    *,
    adjustment_key: str,
    project_id: int,
    cluster_index: int | None,
    timestamp: int,
) -> list[model_data.GnssAdjustmentEvidence]:
    records = []
    for source_index, item in enumerate(evidence):
        raw_item = dict(item)
        raw_payload = raw_item.pop("raw_payload", None)
        epoch_ts = raw_item.get("observation_epoch", raw_item.get("epoch_ts"))
        station_id = raw_item.get("station_id")
        try:
            epoch_ts = int(epoch_ts) if epoch_ts is not None else None
        except (TypeError, ValueError):
            epoch_ts = None
        try:
            station_id = int(station_id) if station_id is not None else None
        except (TypeError, ValueError):
            station_id = None
        records.append(
            model_data.GnssAdjustmentEvidence(
                adjustment_key=adjustment_key,
                project_id=int(project_id),
                cluster_index=cluster_index,
                timestamp=int(timestamp),
                source_index=source_index,
                station_id=station_id,
                epoch_ts=epoch_ts,
                raw_payload=str(raw_payload) if raw_payload is not None else None,
                data=_json_safe(raw_item),
            )
        )
    return records


async def persist_evidence(
    evidence: Iterable[dict[str, Any]],
    *,
    adjustment_key: str,
    project_id: int,
    cluster_index: int | None,
    timestamp: int,
) -> None:
    """Persist evidence idempotently; the result row remains compact."""
    records = evidence_records(
        evidence,
        adjustment_key=adjustment_key,
        project_id=project_id,
        cluster_index=cluster_index,
        timestamp=timestamp,
    )
    if not records:
        return
    async with DataSessionLocal() as db:
        existing = await db.execute(
            select(model_data.GnssAdjustmentEvidence.id)
            .where(model_data.GnssAdjustmentEvidence.adjustment_key == adjustment_key)
            .limit(1)
        )
        if existing.scalar_one_or_none() is None:
            db.add_all(records)
            await db.commit()


async def persist_adjustment_snapshot(
    payload: dict[str, Any],
    *,
    sensor_type: str,
) -> dict[str, Any]:
    """Persist one compact result plus its evidence in one data-DB transaction."""
    compact, evidence = compact_adjustment_payload(payload)
    project_id = int(compact.get("project_id") or 0)
    timestamp = int(compact.get("timestamp") or compact.get("computed_at") or 0)
    adjustment_key = str(compact.get("adjustment_key") or "").strip()
    if not adjustment_key:
        raise ValueError("GNSS adjustment snapshot has no adjustment_key")
    cluster_index = compact.get("cluster_index")
    try:
        cluster_index = int(cluster_index) if cluster_index is not None else None
    except (TypeError, ValueError):
        cluster_index = None
    station_id = next(
        (
            int(item["station_id"])
            for item in evidence
            if item.get("station_id") is not None
        ),
        0,
    )
    rows = evidence_records(
        evidence,
        adjustment_key=adjustment_key,
        project_id=project_id,
        cluster_index=cluster_index,
        timestamp=timestamp,
    )
    async with DataSessionLocal() as db:
        existing = await db.execute(
            select(model_data.SensorData.id)
            .where(model_data.SensorData.adjustment_key == adjustment_key)
            .limit(1)
        )
        if existing.scalar_one_or_none() is None:
            try:
                db.add(
                    model_data.SensorData(
                        station_id=station_id,
                        timestamp=timestamp,
                        sensor_type=sensor_type,
                        adjustment_key=adjustment_key,
                        adjustment_project_id=project_id,
                        adjustment_cluster_index=cluster_index,
                        data=compact,
                    )
                )
                if rows:
                    db.add_all(rows)
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.warning(
                    "Adjustment snapshot with key %s already exists (concurrent insert)",
                    adjustment_key,
                )
    return compact


async def write_adjustment_failure_report(
    project_id: int,
    error: Exception | str,
    *,
    source: str,
    context: dict[str, Any] | None = None,
    project_code: str | None = None,
    cluster_name: str | None = None,
) -> dict[str, Any] | None:
    """Persist a compact failed result; workbook rendering stays in data_export."""
    timestamp = int(time.time())
    filename_timestamp = int(time.time_ns() // 1_000_000)
    error_type = error.__class__.__name__ if isinstance(error, Exception) else "AdjustmentError"
    error_message = str(error).strip()[:4000] or error_type
    cluster_idx = (context or {}).get("cluster_index")
    cluster_token = f"c{cluster_idx}" if cluster_idx is not None else "c0"
    unique_suffix = uuid.uuid4().hex[:6]
    payload: dict[str, Any] = {
        "status": "failed",
        "phase": "ERROR",
        "source": str(source),
        "project_id": int(project_id),
        "project_code": str(project_code or "") or None,
        "cluster_name": str(cluster_name or "") or None,
        "cluster_index": cluster_idx,
        "timestamp": timestamp,
        "error": {"type": error_type, "message": error_message},
        "context": dict(context or {}),
        "adjustment_key": f"failure:{int(project_id)}:{cluster_token}:{filename_timestamp}_{unique_suffix}",
    }
    payload.update(
        adjustment_report_links(
            int(project_id),
            timestamp,
            project_code=project_code,
            cluster_name=cluster_name,
            run_id=(context or {}).get("run_id"),
            filename_token=filename_timestamp,
        )
    )
    try:
        compact, _evidence = compact_adjustment_payload(payload)
        await persist_adjustment_snapshot(
            payload,
            sensor_type="gnss_adjustment_failed",
        )
        return compact
    except Exception:
        logger.exception(
            "Could not persist GNSS adjustment failure snapshot for project %s",
            project_id,
        )
        return None
