"""Project-level CORS administration routes."""

from __future__ import annotations

import asyncio
import copy
import logging
import requests
from fastapi import APIRouter, Depends, HTTPException
from ... import auth
from ...models import auth as model_auth
from ...runtime import cors_failover_status
from .cors_stations import _fetch_cors_base_stations_sync

router = APIRouter(tags=["Projects"])
logger = logging.getLogger(__name__)

@router.get("/api/admin/projects/cors-stations")
async def get_admin_cors_stations(
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        return await asyncio.to_thread(_fetch_cors_base_stations_sync)
    except requests.RequestException as e:
        logger.warning(f"CORS base station fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch CORS base stations")


@router.get("/api/admin/projects/cors-failover-status")
async def get_admin_cors_failover_status(
    _user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.MANAGE_USERS)
    ),
):
    return {"pairs": copy.deepcopy(cors_failover_status)}
