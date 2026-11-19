"""Station GNSS origin routes."""

from __future__ import annotations

import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException

from ... import auth, config
from ...models import auth as model_auth
from .origin_fetcher import GNSSLiveFetcher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

@router.post("/gnss/fetch-live-origin", responses={400: {"description": "Bad Request"}, 408: {"description": "Request Timeout"}, 500: {"description": "Internal Server Error"}})
async def fetch_live_gnss_origin(
    request_data: dict,
    _user: Annotated[model_auth.User, Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))]
):
    try:
        topic = request_data.get('topic')
        if not topic:
            raise HTTPException(status_code=400, detail="MQTT topic is required")

        mqtt_cfg = request_data.get('mqtt', {}) or {}
        broker = (mqtt_cfg.get('host') or '').strip() or config.settings.MQTT_BROKER
        port = mqtt_cfg.get('port')
        if port is not None:
            try:
                port = int(port)
            except (ValueError, TypeError):
                port = None
        if not port:
            port = config.settings.MQTT_PORT
        username = (mqtt_cfg.get('username') or '').strip() or config.settings.MQTT_USER or ""
        password = mqtt_cfg.get('password') or config.settings.MQTT_PASSWORD or ""
        use_tls = bool(mqtt_cfg.get('use_tls', False))

        fetcher = GNSSLiveFetcher(
            broker=broker,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls
        )

        result = await fetcher.fetch_origin(topic)

        if not result:
            raise HTTPException(status_code=408, detail="Timeout: Không nhận được dữ liệu GNSS")

        return {
            "status": "success",
            "lat": result['lat'],
            "lon": result['lon'],
            "h": result['h'],
            "fix_quality": result['fix_quality'],
            "num_sats": result['num_sats'],
            "message": f"Success! Fix: {result['fix_quality']}, Sats: {result['num_sats']}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching live GNSS: {e}")
        raise HTTPException(status_code=500, detail=str(e))
