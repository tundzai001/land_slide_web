"""Administrative database inspection and record-management routes."""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..database import get_config_db, get_data_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS (cho Admin Panel)
# ============================================================================

# ============================================================================
# STATS API (Đếm tổng số lượng bản ghi thực tế)
# ============================================================================
@router.get("/api/admin/db/stats")  #
async def get_database_stats(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        # Đếm Stations
        count_stations = await config_db.execute(select(func.count()).select_from(model_config.Station))
        num_stations = count_stations.scalar()

        # Đếm Devices
        count_devices = await config_db.execute(select(func.count()).select_from(model_config.Device))
        num_devices = count_devices.scalar()

        # Đếm Sensor Data (Total)
        count_data = await data_db.execute(select(func.count()).select_from(model_data.SensorData))
        num_data = count_data.scalar()

        # Đếm Active Alerts (Chưa xử lý)
        count_alerts = await data_db.execute(
            select(func.count()).select_from(model_data.Alert).where(model_data.Alert.is_resolved == False)
        )
        num_alerts = count_alerts.scalar()

        return {
            "stations": num_stations,
            "devices": num_devices,
            "sensor_data": num_data,
            "alerts": num_alerts
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"stations": 0, "devices": 0, "sensor_data": 0, "alerts": 0}

@router.get("/api/admin/db/stations")
async def admin_get_all_stations(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tất cả stations từ DB"""
    try:
        result = await db.execute(select(model_config.Station))
        stations = result.scalars().all()
        
        return [
            {
                "id": s.id,
                "station_code": s.station_code,
                "name": s.name,
                "project_id": s.project_id,
                "location": s.location,
                "status": s.status,
                "last_update": s.last_update,
                "config": s.config,
                "created_at": s.created_at,
                "updated_at": s.updated_at
            }
            for s in stations
        ]
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/devices")
async def admin_get_all_devices(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tất cả devices từ DB"""
    try:
        result = await db.execute(select(model_config.Device))
        devices = result.scalars().all()
        
        return [
            {
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "station_id": d.station_id,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "position": d.position,
                "is_active": d.is_active,
                "last_data_time": d.last_data_time,
                "config": d.config,
                "created_at": d.created_at,
                "updated_at": d.updated_at
            }
            for d in devices
        ]
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/sensor-data")
async def admin_get_sensor_data(
    limit: int = 500,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy sensor data gần nhất"""
    try:
        result = await db.execute(
            select(model_data.SensorData)
            .order_by(desc(model_data.SensorData.timestamp))
            .limit(limit)
        )
        data = result.scalars().all()
        
        return [
            {
                "id": d.id,
                "station_id": d.station_id,
                "timestamp": d.timestamp,
                "sensor_type": d.sensor_type,
                "data": d.data,
                "value_1": d.value_1,
                "value_2": d.value_2,
                "value_3": d.value_3,
                "value_4": d.value_4,
                "value_5": d.value_5
            }
            for d in data
        ]
    except Exception as e:
        logger.error(f"Error fetching sensor data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/alerts")
async def admin_get_alerts(
    limit: int = 200,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy alerts gần nhất"""
    try:
        result = await db.execute(
            select(model_data.Alert)
            .order_by(desc(model_data.Alert.timestamp))
            .limit(limit)
        )
        alerts = result.scalars().all()
        
        return [
            {
                "id": a.id,
                "station_id": a.station_id,
                "timestamp": a.timestamp,
                "level": a.level,
                "category": a.category,
                "message": a.message,
                "is_resolved": a.is_resolved
            }
            for a in alerts
        ]
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# UPDATE/DELETE ENDPOINTS
# ============================================================================

@router.put("/api/admin/db/stations/{record_id}")
async def admin_update_station(
    record_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
    
