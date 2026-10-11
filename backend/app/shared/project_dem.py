"""Storage and validation for project digital elevation models."""

from __future__ import annotations

import math
import os
import json
import re
import threading
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException

PROJECT_DEM_DIR = Path(__file__).resolve().parents[2] / "static" / "uploads" / "dems"
MAX_DEM_BYTES = 20 * 1024 * 1024
MAX_DEM_CELLS = 10_000_000
DEM_ID_PATTERN = re.compile(r"^[a-f0-9]{16}$")
_manifest_lock = threading.RLock()


def project_dem_manifest_path(project_id: int) -> Path:
    return PROJECT_DEM_DIR / f"project-{int(project_id)}.json"


def project_dem_path(project_id: int, dem_id: str) -> Path:
    if not DEM_ID_PATTERN.fullmatch(str(dem_id)):
        raise HTTPException(status_code=404, detail="Không tìm thấy mô hình địa hình.")
    return PROJECT_DEM_DIR / f"project-{int(project_id)}-{dem_id}.asc"


def list_project_dems(project_id: int) -> list[dict]:
    manifest_path = project_dem_manifest_path(project_id)
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        models = manifest.get("models", []) if isinstance(manifest, dict) else []
        return [
            model for model in models
            if isinstance(model, dict)
            and DEM_ID_PATTERN.fullmatch(str(model.get("id", "")))
            and project_dem_path(project_id, model["id"]).is_file()
        ]
    except (OSError, ValueError, TypeError):
        return []


def project_dem_summary(project_id: int) -> dict:
    models = list_project_dems(project_id)
    return {"dems": models, "has_dem": bool(models)}


def inspect_ascii_grid(content: bytes) -> dict:
    if not content or len(content) > MAX_DEM_BYTES:
        raise HTTPException(status_code=413 if content else 400, detail="File DEM trống hoặc vượt quá 20 MB.")
    try:
        lines = content.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="DEM phải là file ESRI ASCII Grid dạng văn bản.") from exc

    if len(lines) < 7:
        raise HTTPException(status_code=400, detail="File DEM thiếu phần tiêu đề hoặc dữ liệu độ cao.")
    header = {}
    for line in lines[:6]:
        fields = line.split()
        if len(fields) != 2:
            raise HTTPException(status_code=400, detail="Tiêu đề DEM không đúng định dạng ESRI ASCII Grid.")
        header[fields[0].lower()] = fields[1]

    try:
        columns = int(header["ncols"])
        rows = int(header["nrows"])
        cellsize = float(header["cellsize"])
        nodata = float(header["nodata_value"])
        x_key = "xllcorner" if "xllcorner" in header else "xllcenter"
        y_key = "yllcorner" if "yllcorner" in header else "yllcenter"
        x_origin = float(header[x_key])
        y_origin = float(header[y_key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Tiêu đề DEM thiếu hoặc sai thông số lưới.") from exc

    if columns <= 0 or rows <= 0 or columns * rows > MAX_DEM_CELLS:
        raise HTTPException(status_code=400, detail="Kích thước lưới DEM không hợp lệ hoặc quá lớn.")
    if not all(math.isfinite(value) for value in (cellsize, nodata, x_origin, y_origin)) or cellsize <= 0:
        raise HTTPException(status_code=400, detail="Tọa độ hoặc kích thước ô DEM không hợp lệ.")
    # The project DEM workflow uses WGS84 / UTM zone 48N, whose projected
    # coordinates fall within these broad bounds.
    xll = x_origin - (cellsize / 2 if x_key.endswith("center") else 0)
    yll = y_origin - (cellsize / 2 if y_key.endswith("center") else 0)
    if not (0 <= xll <= 1_000_000 and 0 <= yll <= 10_000_000):
        raise HTTPException(status_code=400, detail="DEM không có tọa độ UTM hợp lệ cho vùng 48N.")

    expected_values = columns * rows
    value_count = 0
    elevation_min = math.inf
    elevation_max = -math.inf
    try:
        for line in lines[6:]:
            for raw_value in line.split():
                value_count += 1
                if value_count > expected_values:
                    raise HTTPException(status_code=400, detail="Số ô dữ liệu không khớp kích thước lưới DEM.")
                value = float(raw_value)
                if not math.isfinite(value):
                    raise ValueError
                if value != nodata:
                    elevation_min = min(elevation_min, value)
                    elevation_max = max(elevation_max, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="DEM chứa giá trị độ cao không hợp lệ.") from exc
    if value_count != expected_values:
        raise HTTPException(status_code=400, detail="Số ô dữ liệu không khớp kích thước lưới DEM.")
    if math.isinf(elevation_min):
        raise HTTPException(status_code=400, detail="DEM không có ô độ cao hợp lệ.")

    return {
        "ncols": columns,
        "nrows": rows,
        "cellsize": cellsize,
        "nodata_value": nodata,
        "xllcorner": xll,
        "yllcorner": yll,
        "crs": "EPSG:32648",
        "elevation_min": elevation_min,
        "elevation_max": elevation_max,
    }


def save_project_dem(project_id: int, name: str, content: bytes) -> dict:
    metadata = inspect_ascii_grid(content)
    clean_name = (name or "").strip()
    if not clean_name or len(clean_name) > 100:
        raise HTTPException(status_code=422, detail="Tên khu địa hình phải có từ 1 đến 100 ký tự.")
    PROJECT_DEM_DIR.mkdir(parents=True, exist_ok=True)
    with _manifest_lock:
        models = list_project_dems(project_id)
        existing = next((model for model in models if model.get("name", "").casefold() == clean_name.casefold()), None)
        dem_id = existing["id"] if existing else uuid.uuid4().hex[:16]
        destination = project_dem_path(project_id, dem_id)
        descriptor, temporary_path = tempfile.mkstemp(prefix=f"project-{project_id}-", suffix=".tmp", dir=PROJECT_DEM_DIR)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, destination)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

        model = {"id": dem_id, "name": clean_name, **metadata}
        if existing:
            models = [model if item["id"] == dem_id else item for item in models]
        else:
            models.append(model)
        _write_manifest(project_id, models)
        return {"dem_id": dem_id, "dem": model, "models": models}


def _write_manifest(project_id: int, models: list[dict]) -> None:
    manifest_path = project_dem_manifest_path(project_id)
    descriptor, temporary_path = tempfile.mkstemp(prefix=f"project-{project_id}-", suffix=".json.tmp", dir=PROJECT_DEM_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "models": models}, file, ensure_ascii=False, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, manifest_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def delete_project_dems(project_id: int) -> None:
    with _manifest_lock:
        project_dem_manifest_path(project_id).unlink(missing_ok=True)
        for path in PROJECT_DEM_DIR.glob(f"project-{int(project_id)}-*.asc"):
            path.unlink(missing_ok=True)
