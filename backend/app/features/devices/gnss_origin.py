"""GNSS device origin calibration route."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

@router.post("/gnss/reset-origin/{station_id}")
async def reset_gnss_origin(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    """Calibrate device tracking offsets; survey origins remain immutable."""
    from ...runtime import mqtt_service

    result = await db.execute(
        select(model_config.Device).where(
            model_config.Device.station_id == station_id,
            model_config.Device.device_type == "gnss",
            model_config.Device.is_active.is_(True),
        )
    )
    devices = result.scalars().all()
    if not devices:
        raise HTTPException(status_code=404, detail="No active GNSS device found")

    calibrations = []
    try:
        results = await asyncio.gather(*(
            mqtt_service.reset_gnss_origin(device.id, station_id=station_id) for device in devices
        ))
        calibrations = [result for result in results if result is not None]
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not calibrations:
        raise HTTPException(
            status_code=409,
            detail="GNSS processor is not ready; wait for live RTK FIXED data",
        )

    return {
        "status": "tracking_offset_calibrated",
        "station_id": station_id,
        "calibrated_count": len(calibrations),
        "reset_count": len(calibrations),
        "origin_unchanged": True,
        "calibrations": calibrations,
    }
