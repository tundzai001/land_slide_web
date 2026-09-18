"""Stable, readable paths for GNSS adjustment artifacts."""

from datetime import datetime, timedelta, timezone
import re
import unicodedata
from pathlib import Path


VIETNAM_TIMEZONE = timezone(timedelta(hours=7))


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
    timestamp: int | None = None,
) -> tuple[Path, str, str, bool]:
    project_slug = artifact_slug(project_code, f"project-{int(project_id)}")
    cluster_slug = artifact_slug(cluster_name, "project-run")
    scoped = bool(str(project_code or "").strip() and str(cluster_name or "").strip())
    report_dir = root / project_slug / cluster_slug if scoped else root
    if run_id is not None:
        run_date = (
            datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE)
            if timestamp is not None else datetime.now(VIETNAM_TIMEZONE)
        )
        report_dir = report_dir / run_date.strftime("%Y-%m-%d")
    return (
        report_dir,
        project_slug,
        cluster_slug,
        scoped,
    )


def adjustment_report_links(
    project_id: int,
    timestamp: int,
    *,
    project_code: str | None = None,
    cluster_name: str | None = None,
    run_id: int | None = None,
    filename_token: int | None = None,
) -> dict[str, str]:
    """Build virtual download links without creating files on the server."""
    _report_dir, project_slug, cluster_slug, scoped = adjustment_scope(
        Path("."),
        project_id,
        project_code,
        cluster_name,
        run_id=run_id,
        timestamp=timestamp,
    )
    if scoped:
        prefix_parts = [project_slug, cluster_slug]
        if run_id is not None:
            prefix_parts.append(
                datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).strftime("%Y-%m-%d")
            )
        prefix = "/api/admin/gnss/adjustment/reports/" + "/".join(prefix_parts)
        stem = (
            f"gnss_adjustment_{project_slug}_{cluster_slug}_"
            f"{datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE):%Y-%m-%d_%H-%M-%S}"
        )
        if filename_token is not None:
            stem += f"_{int(filename_token) % 1000:03d}"
    else:
        prefix = f"/api/admin/gnss/adjustment/reports/{int(project_id)}"
        stem = f"gnss_adjustment_{int(project_id)}_{int(filename_token or timestamp)}"

    json_url = f"{prefix}/{stem}.json"
    xlsx_url = f"{prefix}/{stem}.xlsx"
    return {
        "audit_json_url": json_url,
        "excel_report_url": xlsx_url,
        "report_file_url": xlsx_url,
    }
