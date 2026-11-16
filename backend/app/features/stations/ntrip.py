"""Station NTRIP command routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth, schemas
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

@router.post("/stations/{station_code}/ntrip_route/stop")
async def stop_ntrip_route(
    station_code: str,
    _admin: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
    db: AsyncSession = Depends(get_config_db)
):
    from ...mqtt.ntrip_pusher import ntrip_manager

    # Check if station exists
    stmt = select(model_config.Station).where(model_config.Station.station_code == station_code)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    if station_code:
        await ntrip_manager.stop_pusher(station_code)

    return {"status": "ok", "message": f"NTRIP route stopped for {station_code}"}


@router.post("/stations/{station_code}/ntrip_route/start")
async def start_ntrip_route(
    station_code: str,
    payload: schemas.NtripRouteStart,
    _admin: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
    db: AsyncSession = Depends(get_config_db)
):
    from ...mqtt.ntrip_pusher import ntrip_manager

    # Check if station exists
    stmt = select(model_config.Station).where(model_config.Station.station_code == station_code)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    if station_code and payload.mountpoint:
        await ntrip_manager.start_pusher(
            station_code,
            payload.host,
            payload.port,
            payload.mountpoint,
            payload.password
        )

    return {"status": "ok", "message": f"NTRIP route started for {station_code}"}
