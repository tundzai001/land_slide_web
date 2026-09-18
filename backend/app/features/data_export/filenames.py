"""Safe names used inside exported archives."""

from __future__ import annotations

import re
from typing import Any


def zip_component(value: Any, fallback: str) -> str:
    """Return a safe, readable folder/file component for exported ZIP paths."""
    component = str(value or "").strip()
    component = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", component)
    component = re.sub(r"\s+", "_", component).strip(" ._")
    if not component or component in {".", ".."}:
        return fallback
    return component[:120]


def station_export_path(
    project_code: Any, station_code: Any, station_id: Any, filename: str
) -> str:
    project_folder = zip_component(project_code, "UNKNOWN_PROJECT")
    station_folder = zip_component(station_code, f"station_{station_id}")
    safe_filename = zip_component(filename, "DATA.csv")
    return f"{project_folder}/{station_folder}/{safe_filename}"
