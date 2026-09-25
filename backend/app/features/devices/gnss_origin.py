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


@router.post("/gnss/relock-origin/{station_id}")
async def relock_gnss_origin(
    station_id: int,
    request_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
):
    """Replace a station's locked GNSS origin after stable RTK FIXED capture."""
    from ...runtime import mqtt_service

    topic = str(request_data.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="GNSS MQTT topic is required")

    result = await db.execute(
        select(model_config.Device).where(
            model_config.Device.station_id == station_id,
            model_config.Device.device_type == "gnss",
            model_config.Device.is_active.is_(True),
            model_config.Device.mqtt_topic == topic,
        )
    )
    devices = result.scalars().all()
    if not devices:
        raise HTTPException(status_code=404, detail="No active GNSS device matches this topic")
    if len(devices) != 1:
        raise HTTPException(status_code=409, detail="The GNSS topic maps to multiple active devices")

    device_id = devices[0].id
    await db.close()
    try:
        relock = await mqtt_service.relock_gnss_origin(
            device_id,
            station_id=station_id,
            actor=current_user.username,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "status": "origin_relocked",
        "station_id": station_id,
        "relock": relock,
    }
