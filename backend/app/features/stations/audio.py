"""Station audio command routes."""

from __future__ import annotations

import json
import time
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

class PlayAudioRequest(BaseModel):
    audio_code: str


@router.post("/stations/{station_id}/command/play", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def send_audio_command(
    station_id: int,
    payload: PlayAudioRequest,
    db: Annotated[AsyncSession, Depends(get_config_db)],
    _user: Annotated[model_auth.User, Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))]
):
    """
    Send a 'play audio' command to the station via MQTT.
    """
    try:
        # Import mqtt_service here to avoid circular imports
        from ...runtime import mqtt_service

        # 1. Verify station exists
        res = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        station = res.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        audio_code = payload.audio_code
        if not audio_code:
             raise HTTPException(status_code=400, detail="audio_code required")

        # 2. Publish to MQTT
        topic = f"landslide/{station_id}/command"
        message = json.dumps({
            "cmd": "play_audio",
            "audio_code": audio_code,
            "ts": int(time.time())
        })

        mqtt_service.client.publish(topic, message, retain=False)
        logger.info(f"📢 Command sent to {topic}: {message}")

        return {"status": "success", "message": f"Command sent: {audio_code}"}

    except Exception as e:
        logger.error(f"❌ Error sending command: {e}")
        raise HTTPException(status_code=500, detail=str(e))
