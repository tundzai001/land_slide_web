"""Stable, readable paths and lifecycle records for GNSS adjustment artifacts."""

import json
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
ADJUSTMENT_REPORT_DIR = Path(__file__).resolve().parents[2] / "static" / "adjustments"


def artifact_slug(value: object, fallback: str) -> str:
    text = str(value or "").strip().replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text[:80] or fallback).strip("-")


def adjustment_scope(
    root: Path,
    project_id: int,
    project_code: str | None = None,
    cluster_name: str | None = None,
    run_id: int | None = None,
) -> tuple[Path, str, str, bool]:
    project_slug = artifact_slug(project_code, f"project-{int(project_id)}")
    cluster_slug = artifact_slug(cluster_name, "project-run")
    scoped = bool(str(project_code or "").strip() and str(cluster_name or "").strip())
    report_dir = root / project_slug / cluster_slug if scoped else root
    if run_id is not None:
        report_dir = report_dir / f"run-{int(run_id)}"
    return (
        report_dir,
        project_slug,
        cluster_slug,
        scoped,
    )


def write_adjustment_run_status(
    project_id: int,
    *,
    run_id: int,
    phase: str,
    source: str,
    project_code: str,
    cluster_name: str,
    cluster_index: int | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist one atomic, human-readable status file for every scheduled run.

    The status file is created before the parallel starts are awaited. This
    makes every selected cluster independently observable even while it is
    still collecting its seed window and before a final JSON/XLSX exists.
    """

    report_dir, project_slug, cluster_slug, _ = adjustment_scope(
        ADJUSTMENT_REPORT_DIR,
        project_id,
        project_code,
        cluster_name,
        run_id=run_id,
    )
    payload: dict[str, Any] = {
        "status": str(phase).upper(),
        "phase": str(phase).upper(),
        "source": str(source),
        "project_id": int(project_id),
        "project_code": str(project_code),
        "cluster_name": str(cluster_name),
        "cluster_index": cluster_index,
        "run_id": int(run_id),
        "updated_at": int(time.time()),
        "context": dict(context or {}),
        "status_url": (
            f"/api/admin/gnss/adjustment/reports/{project_slug}/{cluster_slug}/run-{int(run_id)}/run_status.json"
        ),
    }
    report_path = report_dir / "run_status.json"
    temporary_path = report_dir / "run_status.json.tmp"
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(report_path)
        return payload
    except Exception:
        logger.exception(
            "Could not persist GNSS adjustment run status for project %s run %s",
            project_id,
            run_id,
        )
        return None
