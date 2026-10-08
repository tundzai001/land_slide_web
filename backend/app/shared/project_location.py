"""Persist map positions in the existing project location JSON, preserving addresses."""
import math
from fastapi import HTTPException
from sqlalchemy import select

from ..models.config import Project, Station


def coordinates(value):
    if not isinstance(value, dict):
        return None
    lat, lon = value.get("lat"), value.get("lon")
    if isinstance(lat, bool) or isinstance(lon, bool) or lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    # Existing stations use (0, 0) for an unknown location.
    return None if lat == lon == 0 else (lat, lon)


def location_object(location):
    return dict(location) if isinstance(location, dict) else {"address": location or ""}


def map_mode(location):
    location = location_object(location)
    return location["map_mode"] if location.get("map_mode") in ("auto", "manual") else ("manual" if coordinates(location) else "auto")


def validate_map_position(position):
    if not isinstance(position, dict) or position.get("mode") not in ("auto", "manual"):
        raise HTTPException(422, "Chọn cách đặt điểm dự án: tự động hoặc nhập tọa độ.")
    mode = position["mode"]
    allowed = {"mode", "lat", "lon"} if mode == "manual" else {"mode"}
    if set(position) - allowed:
        raise HTTPException(422, "Dữ liệu điểm dự án không hợp lệ.")
    if mode == "manual" and (
        any(type(position.get(key)) not in (int, float) for key in ("lat", "lon"))
        or coordinates(position) is None
    ):
        raise HTTPException(422, "Vĩ độ phải từ -90 đến 90, kinh độ từ -180 đến 180; không dùng điểm (0, 0).")
    return position


def update_location_address(current, incoming):
    # Old admin clients send only an address. They must not erase a saved point.
    location = location_object(current)
    address = incoming.get("address", incoming.get("source", "")) if isinstance(incoming, dict) else incoming
    if address is not None and (not isinstance(address, str) or len(address) > 500):
        raise HTTPException(422, "Địa điểm không được dài quá 500 ký tự.")
    location["address"] = (address or "").strip()
    return location


async def save_project_map_position(db, project, position=None):
    if position is not None:
        validate_map_position(position)
    location = location_object(project.location)
    mode = position["mode"] if position is not None else map_mode(location)
    if mode == "manual":
        point = coordinates(position if position is not None else location)
    else:
        await db.flush()
        rows = (await db.execute(select(Station.location).where(Station.project_id == project.id))).scalars().all()
        points = [point for row in rows if (point := coordinates(row)) is not None]
        point = tuple(round(sum(values) / len(points), 8) for values in zip(*points)) if points else None
    location.update(map_mode=mode, lat=point[0] if point else None, lon=point[1] if point else None)
    project.location = location


async def refresh_project_map_position(db, project_id):
    # Serialize concurrent station edits with manual project-position updates.
    await db.flush()
    project = (await db.execute(
        select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if project is not None and map_mode(project.location) == "auto":
        await save_project_map_position(db, project)


async def backfill_project_map_positions(db):
    # Idempotent upgrade of legacy JSON; no schema change or deleted fields.
    ids = (await db.execute(select(Project.id).order_by(Project.id))).scalars().all()
    for project_id in ids:
        project = (await db.execute(
            select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if project is not None:
            await save_project_map_position(db, project)
    await db.commit()
