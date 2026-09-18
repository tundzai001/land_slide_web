"""Legacy field-unit provisioning endpoints."""
import hmac
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_config_db
from ...models import config as model_config

router = APIRouter(tags=["Field Provisioning"])


def _device_token(request: Request, payload: Optional[Dict[str, Any]] = None, query_token: Optional[str] = None) -> str:
    """Read the device credential without logging or echoing it."""
    authorization = request.headers.get("Authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    return (
        request.headers.get("X-Device-Token")
        or bearer
        or (payload or {}).get("device_token")
        or (payload or {}).get("enroll_token")
        or query_token
        or ""
    )


def _require_device_token(request: Request, cfg: Dict[str, Any], payload: Optional[Dict[str, Any]] = None, query_token: Optional[str] = None) -> None:
    expected = str(cfg.get("device_token") or cfg.get("enroll_token") or "")
    # Existing deployments may not have issued a token yet. Keep those devices
    # on the legacy path until an admin provisions one, but never bypass a
    # configured credential merely because the row is marked provisioned.
    if expected and not hmac.compare_digest(_device_token(request, payload, query_token), expected):
        raise HTTPException(status_code=403, detail="invalid device token")

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
    if not cfg.get('enroll_token') or not hmac.compare_digest(str(cfg.get('enroll_token')), str(token)):
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
async def field_get_config(device_code: str, request: Request, token: Optional[str] = None, db: AsyncSession = Depends(get_config_db)):
    """Device fetches its config. Provide enroll_token or provision token as query param 'token'"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    cfg = device.config or {}
    _require_device_token(request, cfg, query_token=token)
    return {"device_code": device.device_code, "device_id": device.id, "station_id": device.station_id, "mqtt_topic": device.mqtt_topic, "config": cfg}


@router.post("/api/field/{device_code}/status")
async def field_status(device_code: str, payload: Dict[str, Any], request: Request, db: AsyncSession = Depends(get_config_db)):
    """Device posts health/status. payload example: {"status":"ok","uptime":1234, "audio_files": [...] }"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    _require_device_token(request, device.config or {}, payload)

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
