"""Shared station access and offline-threshold policies."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import config as model_config


def check_operator_project_access(user, project_id: int) -> None:
    if user.role == "operator":
        assigned = getattr(user, "assigned_projects", None) or []
        if project_id not in assigned:
            raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập dự án này")


async def check_operator_station_access(user, station_id: int, db: AsyncSession) -> None:
    if user.role != "operator":
        return
    assigned = getattr(user, "assigned_projects", None) or []
    station = (
        await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
    ).scalar_one_or_none()
    if not station or station.project_id not in assigned:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập trạm này")


def get_offline_threshold(station_config: dict, sensor_type: str) -> int:
    defaults = {"gnss": 30, "rain": 60, "water": 60, "imu": 2400}
    default = defaults.get(sensor_type, 300)
    offline_config = (station_config or {}).get("offline_thresholds", {}) or {}
    try:
        return max(int(offline_config.get(sensor_type, default)), 15)
    except (TypeError, ValueError):
        return default
