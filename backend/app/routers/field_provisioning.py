"""Legacy field-unit provisioning endpoints."""
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_config_db
from ..models import config as model_config

router = APIRouter(tags=["Field Provisioning"])

@router.post("/api/field/provision")
async def field_provision(payload: Dict[str, Any], db: AsyncSession = Depends(get_config_db)):
    """Provision device with station assignment and configs.
    Payload: {"device_code":"hw123","enroll_token":"...","station_id":1,"mqtt":{...},"audio_files":[...],"license":"..."}
    """
    device_code = payload.get('device_code')
    token = payload.get('enroll_token')
    if not device_code or not token:
        raise HTTPException(status_code=400, detail="device_code and enroll_token required")

    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    cfg = device.config or {}
    if cfg.get('enroll_token') != token:
        raise HTTPException(status_code=403, detail="invalid enroll token")

    # apply provisioning
    station_id = int(payload.get('station_id', 0))
    mqtt_conf = payload.get('mqtt') or {}
    audio_files = payload.get('audio_files') or []
    license_blob = payload.get('license')

    # set mqtt topic for alerts/commands
    mqtt_topic = f"landslide/{station_id}"

    cfg.update({
        "provisioned": True,
        "provisioned_at": int(time.time()),
        "mqtt": mqtt_conf,
        "audio_files": audio_files,
        "license": license_blob
    })

    device.station_id = station_id
    device.mqtt_topic = mqtt_topic
    device.config = cfg
    device.updated_at = int(time.time())

    db.add(device)
    await db.commit()
    await db.refresh(device)

    return {"status": "ok", "device_id": device.id, "station_id": station_id, "mqtt_topic": mqtt_topic}


@router.get("/api/field/{device_code}/config")
async def field_get_config(device_code: str, token: Optional[str] = None, db: AsyncSession = Depends(get_config_db)):
    """Device fetches its config. Provide enroll_token or provision token as query param 'token'"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    cfg = device.config or {}
    # Accept either enroll_token or provisioned state
    if (cfg.get('enroll_token') and token == cfg.get('enroll_token')) or cfg.get('provisioned'):
        return {"device_code": device.device_code, "device_id": device.id, "station_id": device.station_id, "mqtt_topic": device.mqtt_topic, "config": cfg}
    raise HTTPException(status_code=403, detail="unauthorized")


@router.post("/api/field/{device_code}/status")
async def field_status(device_code: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_config_db)):
    """Device posts health/status. payload example: {"status":"ok","uptime":1234, "audio_files": [...] }"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    # update last_data_time and config audio list if provided
    now_ts = int(time.time())
    device.last_data_time = now_ts
    cfg = device.config or {}
    if 'audio_files' in payload:
        cfg['audio_files_local'] = payload.get('audio_files')
    if 'status' in payload:
        cfg['last_status'] = payload.get('status')

    device.config = cfg
    device.updated_at = now_ts
    db.add(device)
    await db.commit()
    return {"status": "ok", "updated_at": now_ts}


