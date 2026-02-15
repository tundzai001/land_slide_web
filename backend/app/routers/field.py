
import logging
import time
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .. import schemas, config
from ..database import get_config_db
from ..models import config as model_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/field",
    tags=["Field Unit API"]
)

class DeviceRegisterRequest(BaseModel):
    device_code: str
    name: str
    device_type: str = "pi"
    mqtt_topic: Optional[str] = None

class DeviceRegisterResponse(BaseModel):
    device_id: int
    enroll_token: str
    status: str
    station_id: int

@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    payload: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_config_db)
):
    """
    Auto-register a field device (e.g. Raspberry Pi).
    If device exists, return existing info.
    If not, create pending device (station_id=0).
    """
    try:
        # Check if device exists
        res = await db.execute(
            select(model_config.Device).where(model_config.Device.device_code == payload.device_code)
        )
        device = res.scalar_one_or_none()
        
        current_time = int(time.time())
        enroll_token = str(uuid.uuid4()) # In real app, store this or use simpler auth

        if device:
            # Device already exists -> Update info if needed
            logger.info(f"🔄 Device reconnect: {payload.device_code} (ID: {device.id})")
            # Return current station_id (might be 0 if still pending)
            return {
                "device_id": device.id,
                "enroll_token": "existing-token", # Simplification
                "status": "registered",
                "station_id": device.station_id
            }
        else:
            # Create new pending device
            logger.info(f"✨ New device registration: {payload.device_code}")
            new_device = model_config.Device(
                device_code=payload.device_code,
                name=payload.name,
                station_id=0, # 0 means pending/unassigned
                device_type=payload.device_type,
                mqtt_topic=payload.mqtt_topic or "",
                is_active=True,
                last_data_time=0,
                config={"enroll_token": enroll_token},
                created_at=current_time,
                updated_at=current_time
            )
            db.add(new_device)
            await db.commit()
            await db.refresh(new_device)
            
            return {
                "device_id": new_device.id,
                "enroll_token": enroll_token,
                "status": "pending",
                "station_id": 0
            }

    except Exception as e:
        logger.error(f"❌ Device registration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
