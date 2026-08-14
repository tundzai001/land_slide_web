"""Durable failure artifacts for automatic and in-progress GNSS adjustments."""

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.services.adjustment_artifacts import adjustment_scope

logger = logging.getLogger(__name__)
ADJUSTMENT_REPORT_DIR = Path(__file__).resolve().parents[2] / "static" / "adjustments"


def write_adjustment_failure_report(
    project_id: int,
    error: Exception | str,
    *,
    source: str,
    context: dict[str, Any] | None = None,
    project_code: str | None = None,
    cluster_name: str | None = None,
) -> dict[str, Any] | None:
    """Atomically write a project-scoped JSON result and return its API payload."""

    timestamp = int(time.time())
    filename_timestamp = int(time.time_ns() // 1_000_000)
    error_type = error.__class__.__name__ if isinstance(error, Exception) else "AdjustmentError"
    error_message = str(error).strip()[:4000] or error_type
    report_dir, project_slug, cluster_slug, scoped = adjustment_scope(
        ADJUSTMENT_REPORT_DIR,
        project_id,
        project_code,
        cluster_name,
    )
    report_name = (
        f"gnss_adjustment_{project_slug}_{cluster_slug}_{filename_timestamp}.json"
        if scoped else f"gnss_adjustment_{int(project_id)}_{filename_timestamp}.json"
    )
    report_path = report_dir / report_name
    temporary_path = report_path.with_suffix(".json.tmp")
    payload: dict[str, Any] = {
        "status": "failed",
        "phase": "ERROR",
        "source": str(source),
        "project_id": int(project_id),
        "project_code": str(project_code or "") or None,
        "cluster_name": str(cluster_name or "") or None,
        "cluster_index": (context or {}).get("cluster_index"),
        "timestamp": timestamp,
        "error": {"type": error_type, "message": error_message},
        "context": dict(context or {}),
        "audit_json_url": (
            f"/api/admin/gnss/adjustment/reports/{project_slug}/{cluster_slug}/{report_name}"
            if scoped else
            f"/api/admin/gnss/adjustment/reports/{int(project_id)}/{report_name}"
        ),
    }
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(report_path)
        logger.error("GNSS adjustment failure report written: %s", report_path)
        return payload
    except Exception:
        logger.exception(
            "Could not persist GNSS adjustment failure report for project %s",
            project_id,
        )
        return None
