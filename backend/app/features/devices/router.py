"""Administrative station-device CRUD routes."""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config

router = APIRouter()
logger = logging.getLogger(__name__)


def _check_private_device_scope(user: model_auth.User, project_id: int) -> None:
    """Field-device data is private even though station metadata is public."""
    if user.role == auth.Role.ADMIN:
        return
    assigned = {
        int(value)
        for value in (getattr(user, "assigned_projects", None) or [])
        if str(value).strip().lstrip("-").isdigit()
    }
    if project_id not in assigned:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập thiết bị của dự án này")


@router.get("/api/admin/stations/{station_id}/devices")
async def get_station_devices(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_FIELD_DEVICES))
):
    try:
        station_result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        _check_private_device_scope(current_user, station.project_id)
        result = await db.execute(
            select(model_config.Device)
            .where(model_config.Device.station_id == station_id)
            .order_by(model_config.Device.created_at.desc())
        )

        devices = result.scalars().all()

        device_ids = [device.id for device in devices]
        tracking_offsets = {}
        if device_ids:
            origin_result = await db.execute(
                select(model_config.GNSSOrigin.device_id, model_config.GNSSOrigin.tracking_offset)
                .where(model_config.GNSSOrigin.device_id.in_(device_ids))
            )
            tracking_offsets = {
                device_id: tracking_offset
                for device_id, tracking_offset in origin_result.all()
            }

        return [
            {
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "position": d.position,
                "is_active": d.is_active,
                "last_data_time": d.last_data_time,
                "config": d.config or {},
                "tracking_offset": tracking_offsets.get(d.id) if d.device_type == "gnss" else None,
            }
            for d in devices
        ]

    except Exception as e:
        logger.error(f"Error loading devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/admin/stations/{station_id}/devices")
async def create_device_in_station(
    station_id: int,
    device_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    try:
        # Verify station exists
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        _check_private_device_scope(current_user, station.project_id)

        new_device = model_config.Device(
            device_code=device_data['device_code'],
            name=device_data['name'],
            station_id=station_id,
            device_type=device_data['device_type'],
            mqtt_topic=device_data.get('mqtt_topic'),
            position=device_data.get('position'),
            is_active=True,
            last_data_time=0,
            config={},
            created_at=int(time.time()),
            updated_at=int(time.time())
        )

        db.add(new_device)
        await db.commit()
        await db.refresh(new_device)

        return {
            "id": new_device.id,
            "device_code": new_device.device_code,
            "name": new_device.name,
            "device_type": new_device.device_type
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/admin/devices/{device_id}")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_FIELD_DEVICES))
):
    try:
        result = await db.execute(
            select(model_config.Device).where(model_config.Device.id == device_id)
        )
        device = result.scalar_one_or_none()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        station_result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == device.station_id)
        )
        station = station_result.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        _check_private_device_scope(current_user, station.project_id)

        await db.delete(device)
        await db.commit()

        return {"status": "success", "message": f"Deleted device {device_id}"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
