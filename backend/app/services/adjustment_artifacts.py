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
