"""Field siren-control HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...database import get_config_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field", tags=["Field Unit API"])

@router.post("/stations/{station_id}/stop-siren", responses={500: {"description": "Internal Server Error"}})
async def stop_siren_command(
    station_id: int,
    db: Annotated[AsyncSession, Depends(get_config_db)],
    target: Optional[str] = 'all',
):
    """
    Publish an MQTT command to stop any continuous siren (e.g., from IMU tilt)
    at the specified station without resetting the entire device state.
    """
    try:
        import json
        import paho.mqtt.publish as publish
        
        # Gửi lệnh stop_siren (tắt còi, và có thể mute tùy thuộc vào Pi logic)
        cmd_topic = f"landslide/{station_id}/command"
        payload_data = json.dumps({
            "cmd": "stop_siren",
            "target": target
        })
        
        # Lấy thông tin broker từ cấu hình trạm
        from app.models.config import Station
        from sqlalchemy import select
        res = await db.execute(select(Station).where(Station.id == station_id))
        station = res.scalar_one_or_none()
        
        from app.config import settings
        broker = settings.MQTT_BROKER
        port = settings.MQTT_PORT
        username = settings.MQTT_USER
        password = settings.MQTT_PASSWORD
        use_tls = False
        
        if station and station.config:
            st_cfg = station.config
            mqtt_cfg = st_cfg.get("mqtt", {}) or {}
            if mqtt_cfg.get("host"):
                broker = mqtt_cfg["host"].strip()
                port = int(mqtt_cfg.get("port") or 1883)
                username = mqtt_cfg.get("username", "").strip() or None
                password = mqtt_cfg.get("password") or None
                use_tls = bool(mqtt_cfg.get("use_tls", False))
                
        auth_info = None
        if username:
            auth_info = {'username': username, 'password': password}
            
        tls_info = None
        if use_tls:
            import ssl
            tls_info = {} # Sử dụng mặc định TLS
            
        safe_topic = str(cmd_topic).replace("\r", "").replace("\n", "")
        safe_target = str(target).replace("\r", "").replace("\n", "")
        safe_broker = str(broker).replace("\r", "").replace("\n", "")
        logger.info("📡 Sending stop_siren command to %s (target: %s) via broker %s:%s", safe_topic, safe_target, safe_broker, port)
        publish.single(
            topic=cmd_topic,
            payload=payload_data,
            hostname=broker,
            port=port,
            auth=auth_info,
            tls=tls_info,
            qos=1
        )
        return {"status": "success", "message": "Stop siren command sent"}
    except Exception as e:
        logger.exception(f"Failed to send MQTT stop_siren: {e}")
        raise HTTPException(status_code=500, detail="Failed to send command to device")


@router.post("/stations/{station_id}/enable-siren", responses={500: {"description": "Internal Server Error"}})
async def enable_siren_command(
    station_id: int,
    db: Annotated[AsyncSession, Depends(get_config_db)],
    target: Optional[str] = 'all',
):
    """
    Re-enable the siren at the specified station (undo a previous stop-siren).
    Sends an MQTT 'enable_siren' command.
    """
    try:
        import json
        import paho.mqtt.publish as publish
        
        cmd_topic = f"landslide/{station_id}/command"
        payload_data = json.dumps({
            "cmd": "enable_siren",
            "target": target
        })
        
        # Lấy thông tin broker từ cấu hình trạm
        from app.models.config import Station
        from sqlalchemy import select
        res = await db.execute(select(Station).where(Station.id == station_id))
        station = res.scalar_one_or_none()
        
        from app.config import settings
        broker = settings.MQTT_BROKER
        port = settings.MQTT_PORT
        username = settings.MQTT_USER
        password = settings.MQTT_PASSWORD
        use_tls = False
        
        if station and station.config:
            st_cfg = station.config
            mqtt_cfg = st_cfg.get("mqtt", {}) or {}
            if mqtt_cfg.get("host"):
                broker = mqtt_cfg["host"].strip()
                port = int(mqtt_cfg.get("port") or 1883)
                username = mqtt_cfg.get("username", "").strip() or None
                password = mqtt_cfg.get("password") or None
                use_tls = bool(mqtt_cfg.get("use_tls", False))
                
        auth_info = None
        if username:
            auth_info = {'username': username, 'password': password}
            
        tls_info = None
        if use_tls:
            import ssl
            tls_info = {} # Sử dụng mặc định TLS
            
        logger.info(f"📡 Sending enable_siren command to {cmd_topic} via broker {broker}:{port}")
        publish.single(
            topic=cmd_topic,
            payload=payload_data,
            hostname=broker,
            port=port,
            auth=auth_info,
            tls=tls_info,
            qos=1
        )
        return {"status": "success", "message": "Enable siren command sent"}
    except Exception as e:
        logger.exception(f"Failed to send MQTT enable_siren: {e}")
        raise HTTPException(status_code=500, detail="Failed to send command to device")
