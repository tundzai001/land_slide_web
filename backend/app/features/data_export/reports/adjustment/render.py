"""On-demand GNSS adjustment exports backed by the data database."""

from __future__ import annotations

import json
import logging
import time
from io import BytesIO
from typing import Callable, Iterable
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import data as model_data

logger = logging.getLogger(__name__)
ADJUSTMENT_SENSOR_TYPES = ("gnss_adjusted", "gnss_adjustment_failed")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render_adjustment_xlsx(
    payload: dict,
    evidence: Iterable[object],
    *,
    project_id: int,
) -> bytes:
    """Render the adjustment workbook owned by this feature."""
    from ....gnss_adjustment.store import hydrate_adjustment_payload

    render_payload = hydrate_adjustment_payload(payload, evidence)
    output = BytesIO()
    if str(render_payload.get("status") or "").lower() == "failed":
        from .failure_workbook import _write_failure_workbook

        _write_failure_workbook(output, render_payload)
    else:
        from .workbook import AdjustmentReportMixin

        class _Writer(AdjustmentReportMixin):
            pass

        timestamp = int(
            render_payload.get("timestamp")
            or render_payload.get("computed_at")
            or 1
        )
        _Writer()._append_adjustment_to_excel(
            int(render_payload.get("project_id") or project_id),
            timestamp,
            render_payload,
            "",
            output_stream=output,
        )
    return output.getvalue()


def _url_path(value: object) -> str:
    return str(value or "").split("?", 1)[0].rstrip("/")


def matches_payload(
    payload: dict,
    record: object,
    requested_url: str,
    project_id: int,
) -> bool:
    requested = _url_path(requested_url)
    urls = {
        _url_path(payload.get(key))
        for key in ("audit_json_url", "excel_report_url", "report_file_url")
        if payload.get(key)
    }
    if requested not in urls:
        return False
    project_ids = {
        int(value)
        for value in (
            payload.get("project_id"),
            getattr(record, "adjustment_project_id", None),
        )
        if str(value or "").strip().lstrip("-").isdigit()
    }
    return int(project_id) in project_ids


def _report_url_filter(requested_url: str):
    requested = _url_path(requested_url)
    url_filters = []
    for key in ("audit_json_url", "excel_report_url", "report_file_url"):
        value = model_data.SensorData.data[key].as_string()
        url_filters.append(
            or_(
                value == requested,
                value.startswith(f"{requested}?", autoescape=True),
                value.startswith(f"{requested}/", autoescape=True),
            )
        )
    return or_(*url_filters)


async def find_adjustment(
    data_db: AsyncSession,
    *,
    project_id: int,
    requested_url: str,
    request_id: str = "unknown",
    mark_phase: Callable[[str], None] | None = None,
) -> tuple[object, dict, list[object]] | None:
    def mark(phase: str) -> None:
        if mark_phase:
            mark_phase(phase)

    async def execute(phase: str, statement):
        mark(phase)
        started = time.perf_counter()
        logger.info(
            "GNSS export phase started request_id=%s phase=%s project_id=%s",
            request_id,
            phase,
            project_id,
        )
        try:
            result = await data_db.execute(statement)
            rows = result.scalars().all()
        except Exception:
            logger.exception(
                "GNSS export phase failed request_id=%s phase=%s project_id=%s elapsed_ms=%.1f",
                request_id,
                phase,
                project_id,
                (time.perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "GNSS export phase completed request_id=%s phase=%s project_id=%s rows=%d elapsed_ms=%.1f",
            request_id,
            phase,
            project_id,
            len(rows),
            (time.perf_counter() - started) * 1000,
        )
        return rows

    # Keep the hot path on the project/adjustment indexes. Filtering the JSON
    # report URLs in SQL makes PostgreSQL scan the large sensor_data table;
    # the indexed adjustment rows are small enough to match in Python.
    query = select(model_data.SensorData).where(
        model_data.SensorData.sensor_type.in_(ADJUSTMENT_SENSOR_TYPES),
    )
    records = await execute(
        "lookup_indexed_adjustment",
        query.where(
            model_data.SensorData.adjustment_project_id == project_id,
            model_data.SensorData.adjustment_key.is_not(None),
        ),
    )
    if not records:
        # Keep compatibility with pre-indexed rows whose project id lives only
        # in the JSON payload. Keep the expensive JSON predicate off the hot path.
        legacy_query = (
            query.where(
                model_data.SensorData.adjustment_project_id.is_(None),
                _report_url_filter(requested_url),
            )
            .order_by(model_data.SensorData.timestamp.desc())
            .limit(1)
        )
        records = await execute(
            "lookup_legacy_adjustment",
            legacy_query,
        )
    for record in records:
        payload = record.data if isinstance(record.data, dict) else None
        if not payload or not matches_payload(payload, record, requested_url, project_id):
            continue
        evidence = []
        key = str(getattr(record, "adjustment_key", None) or payload.get("adjustment_key") or "")
        if key:
            try:
                evidence = await execute(
                    "load_adjustment_evidence",
                    select(model_data.GnssAdjustmentEvidence)
                    .where(model_data.GnssAdjustmentEvidence.adjustment_key == key)
                    .order_by(model_data.GnssAdjustmentEvidence.source_index.asc()),
                )
            except (TimeoutError, SQLAlchemyTimeoutError):
                raise
            except Exception:
                # Old deployments have no evidence table yet; old rows still
                # contain baseline_observations and remain downloadable.
                mark("load_adjustment_evidence")
                logger.warning(
                    "GNSS export evidence unavailable; using stored payload request_id=%s project_id=%s adjustment_key=%s",
                    request_id,
                    project_id,
                    key,
                    exc_info=True,
                )
        return record, payload, evidence
    logger.info(
        "GNSS export record not found request_id=%s project_id=%s requested_url=%s",
        request_id,
        project_id,
        _url_path(requested_url),
    )
    return None


def _response_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store, max-age=0",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }


def json_response(payload: dict, filename: str) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={
            **_response_headers(),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def xlsx_response(
    payload: dict,
    evidence: list[object],
    *,
    project_id: int,
    filename: str,
) -> Response:
    """Build the workbook in memory; no XLSX is written to the filesystem."""
    output = render_adjustment_xlsx(payload, evidence, project_id=project_id)
    return Response(
        content=output,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            **_response_headers(),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def missing_export(extension: str) -> HTTPException:
    detail = (
        "File XLSX không tồn tại và không thể tạo lại từ dữ liệu DB"
        if extension == ".xlsx"
        else "Adjustment report not found"
    )
    return HTTPException(status_code=404, detail=detail)
