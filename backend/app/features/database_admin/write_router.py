"""Database administration write routes."""

from __future__ import annotations

import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db, get_data_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...models import data as model_data

logger = logging.getLogger(__name__)
router = APIRouter()


@router.put("/api/admin/db/stations/{record_id}")
async def admin_update_station(
    record_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Cập nhật station record"""
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == record_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Update allowed fields
        for key, value in update_data.items():
            if key not in ['id', '_table'] and hasattr(station, key):
                setattr(station, key, value)
        
        station.updated_at = int(time.time())
        
        await db.commit()
        return {"status": "success", "message": "Station updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating station: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/db/stations/{record_id}")
async def admin_delete_station(
    record_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Xóa station"""
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == record_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Not found")
        
        await db.delete(station)
        await db.commit()
        
        return {"status": "success", "message": f"Deleted station {record_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/admin/db/devices/{record_id}")
async def admin_update_device(
    record_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    try:
        result = await db.execute(
            select(model_config.Device).where(model_config.Device.id == record_id)
        )
        device = result.scalar_one_or_none()
        
        if not device:
            raise HTTPException(status_code=404)
        
        for key, value in update_data.items():
            if key not in ['id', '_table'] and hasattr(device, key):
                setattr(device, key, value)
        
        device.updated_at = int(time.time())
        await db.commit()
        
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/db/devices/{record_id}")
async def admin_delete_device(
    record_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    try:
        await db.execute(
            delete(model_config.Device).where(model_config.Device.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/db/sensor-data/{record_id}")
async def admin_delete_sensor_data(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    try:
        from sqlalchemy import delete as sql_delete
        await db.execute(
            sql_delete(model_data.SensorData).where(model_data.SensorData.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/db/alerts/{record_id}")
async def admin_delete_alert(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    try:
        from sqlalchemy import delete as sql_delete
        await db.execute(
            sql_delete(model_data.Alert).where(model_data.Alert.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/db/simulations/{record_id}")
async def admin_delete_simulation(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE)),
):
    try:
        result = await db.execute(
            delete(model_data.SimulationRun).where(model_data.SimulationRun.id == record_id)
        )
        if not result.rowcount:
            raise HTTPException(status_code=404, detail="Simulation not found")
        await db.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
