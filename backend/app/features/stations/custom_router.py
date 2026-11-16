"""Admin catalog for reusable custom sensor names."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.database import get_config_db
from app.models.auth import User
from app.shared.custom_sensors import create_custom_sensor, get_custom_sensors

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])


class CustomSensorCreate(BaseModel):
    name: str
    description: str
    unit: str = ""


@router.get("/sensor-presets")
async def list_sensor_presets(
    db: AsyncSession = Depends(get_config_db),
    _user: User = Depends(auth.require_permission(auth.Permission.VIEW_STATIONS)),
):
    return await get_custom_sensors(db)


@router.post("/sensor-presets")
async def add_sensor_preset(
    payload: CustomSensorCreate,
    db: AsyncSession = Depends(get_config_db),
    _user: User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS)),
):
    return await create_custom_sensor(db, payload.name, payload.description, payload.unit)
