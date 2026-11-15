"""Storage and validation for project digital elevation models."""

from __future__ import annotations

import math
import io
import os
import json
import re
import threading
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException
from ..config import settings

PROJECT_DEM_DIR = (
    Path(settings.PROJECT_DEM_DIR)
    if settings.PROJECT_DEM_DIR
    else Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Aitogy" / "Landslide" / "project_dems"
    if os.name == "nt"
    else Path(__file__).resolve().parents[3] / "runtime" / "project_dems"
)
LEGACY_PROJECT_DEM_DIR = Path(__file__).resolve().parents[2] / "static" / "uploads" / "dems"
MAX_DEM_CELLS = 10_000_000
DEM_ID_PATTERN = re.compile(r"^[a-f0-9]{16}$")
_manifest_lock = threading.RLock()
INVALID_ELEVATION_DETAIL = "DEM chứa giá trị độ cao không hợp lệ."
GRID_SIZE_MISMATCH_DETAIL = "Số ô dữ liệu không khớp kích thước lưới DEM."


def project_dem_manifest_path(project_id: int) -> Path:
    return PROJECT_DEM_DIR / f"project-{int(project_id)}.json"


def project_dem_path(project_id: int, dem_id: str) -> Path:
    if not DEM_ID_PATTERN.fullmatch(str(dem_id)):
        raise HTTPException(status_code=404, detail="Không tìm thấy mô hình địa hình.")
    filename = f"project-{int(project_id)}-{dem_id}.asc"
    primary = PROJECT_DEM_DIR / filename
    return primary if primary.is_file() else LEGACY_PROJECT_DEM_DIR / filename


def list_project_dems(project_id: int, models=None) -> list[dict]:
    if models is not None:
        return [
            model for model in models
            if isinstance(model, dict)
            and DEM_ID_PATTERN.fullmatch(str(model.get("id", "")))
            and project_dem_path(project_id, model["id"]).is_file()
        ]
    manifest_path = project_dem_manifest_path(project_id)
    if not manifest_path.is_file():
        manifest_path = LEGACY_PROJECT_DEM_DIR / manifest_path.name
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


def project_dem_summary(project_id: int, models=None) -> dict:
    models = list_project_dems(project_id, models)
    return {"dems": models, "has_dem": bool(models)}


def inspect_ascii_grid(content) -> dict:
    stream = io.BytesIO(content) if isinstance(content, bytes) else content
    if not hasattr(stream, "read"):
        raise HTTPException(status_code=400, detail="DEM không phải file ESRI ASCII Grid hợp lệ.")
    try:
        stream.seek(0)
        header_lines = [stream.readline(257) for _ in range(6)]
        if any(not line or len(line) > 256 for line in header_lines):
            raise HTTPException(status_code=400, detail="File DEM thiếu phần tiêu đề hoặc dữ liệu độ cao.")
        header_lines[0] = header_lines[0].removeprefix(b"\xef\xbb\xbf")
        lines = [line.decode("ascii").strip() for line in header_lines]
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="DEM phải là file ESRI ASCII Grid dạng văn bản.") from exc
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
    token = b""

    def consume_value(raw_value: bytes) -> None:
        nonlocal value_count, elevation_min, elevation_max
        value_count += 1
        if value_count > expected_values:
            raise HTTPException(status_code=400, detail=GRID_SIZE_MISMATCH_DETAIL)
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=INVALID_ELEVATION_DETAIL) from exc
        if not math.isfinite(value):
            raise HTTPException(status_code=400, detail=INVALID_ELEVATION_DETAIL)
        if value != nodata:
            elevation_min = min(elevation_min, value)
            elevation_max = max(elevation_max, value)

    for chunk in iter(lambda: stream.read(64 * 1024), b""):
        parts = re.split(rb"[ \t\r\n\v\f]+", chunk)
        if chunk[:1] not in (b" ", b"\t", b"\r", b"\n", b"\v", b"\f") and token:
            parts[0] = token + parts[0]
        elif token:
            consume_value(token)
        token = b""
        if chunk[-1:] not in (b" ", b"\t", b"\r", b"\n", b"\v", b"\f"):
            token = parts.pop()
        for raw_value in parts:
            if raw_value:
                consume_value(raw_value)
        if len(token) > 64:
            raise HTTPException(status_code=400, detail=INVALID_ELEVATION_DETAIL)
    if token:
        consume_value(bytes(token))
    if value_count != expected_values:
        raise HTTPException(status_code=400, detail=GRID_SIZE_MISMATCH_DETAIL)
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


def save_project_dem(project_id: int, name: str, content, existing_models=None) -> dict:
    metadata = inspect_ascii_grid(content)
    clean_name = (name or "").strip()
    if not clean_name or len(clean_name) > 100:
        raise HTTPException(status_code=422, detail="Tên khu địa hình phải có từ 1 đến 100 ký tự.")
    PROJECT_DEM_DIR.mkdir(parents=True, exist_ok=True)
    with _manifest_lock:
        models = list_project_dems(project_id, existing_models)
        existing = next((model for model in models if model.get("name", "").casefold() == clean_name.casefold()), None)
        dem_id = existing["id"] if existing else uuid.uuid4().hex[:16]
        destination = PROJECT_DEM_DIR / f"project-{int(project_id)}-{dem_id}.asc"
        descriptor, temporary_path = tempfile.mkstemp(prefix=f"project-{project_id}-", suffix=".tmp", dir=PROJECT_DEM_DIR)
        try:
            with os.fdopen(descriptor, "wb") as file:
                source = io.BytesIO(content) if isinstance(content, bytes) else content
                source.seek(0)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    file.write(chunk)
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
        return {"dem_id": dem_id, "dem": model, "models": models}


def update_project_dem_metadata(
    project_id: int,
    dem_id: str,
    xllcorner: float,
    yllcorner: float,
    name: str | None = None,
    existing_models: list[dict] | None = None,
) -> dict:
    if not (math.isfinite(xllcorner) and math.isfinite(yllcorner)):
        raise HTTPException(status_code=400, detail="Tọa độ không hợp lệ.")
    if not (0 <= xllcorner <= 1_000_000 and 0 <= yllcorner <= 10_000_000):
        raise HTTPException(status_code=400, detail="DEM không có tọa độ UTM hợp lệ cho vùng 48N.")
    path = project_dem_path(project_id, dem_id)
    with _manifest_lock:
        models = list_project_dems(project_id, existing_models)
        target = next((m for m in models if m.get("id") == dem_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Không tìm thấy mô hình địa hình.")

        clean_name = (name or "").strip()
        if clean_name:
            if len(clean_name) > 100:
                raise HTTPException(status_code=422, detail="Tên khu địa hình phải từ 1 đến 100 ký tự.")
            target["name"] = clean_name

        target["xllcorner"] = float(xllcorner)
        target["yllcorner"] = float(yllcorner)

        # Update the header lines in the .asc file
        descriptor, temp_path = tempfile.mkstemp(prefix=f"project-{project_id}-", suffix=".tmp", dir=PROJECT_DEM_DIR)
        try:
            with open(path, "rb") as src, os.fdopen(descriptor, "wb") as dst:
                header_count = 0
                for line in src:
                    if header_count < 6:
                        header_count += 1
                        parts = line.strip().split()
                        if parts and parts[0].lower() in (b"xllcorner", b"xllcenter"):
                            dst.write(f"xllcorner     {float(xllcorner):.4f}\n".encode("ascii"))
                            continue
                        elif parts and parts[0].lower() in (b"yllcorner", b"yllcenter"):
                            dst.write(f"yllcorner     {float(yllcorner):.4f}\n".encode("ascii"))
                            continue
                    dst.write(line)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        updated_models = [target if m.get("id") == dem_id else m for m in models]
        _write_manifest(project_id, updated_models)
        return {"dem_id": dem_id, "dem": target, "models": updated_models}


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
        (LEGACY_PROJECT_DEM_DIR / f"project-{int(project_id)}.json").unlink(missing_ok=True)
        for directory in {PROJECT_DEM_DIR, LEGACY_PROJECT_DEM_DIR}:
            for path in directory.glob(f"project-{int(project_id)}-*.asc"):
                path.unlink(missing_ok=True)
