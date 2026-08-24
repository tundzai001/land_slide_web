"""Operational liveness/readiness and non-secret runtime diagnostics."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from .. import auth
from ..database import auth_engine, config_engine, data_engine
from ..models import auth as model_auth
from ..runtime import mqtt_service
from ..websocket import manager as websocket_manager

router = APIRouter(tags=["Health"])


async def _probe_engine(engine, timeout: float = 2.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return {"ok": True, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return {
            "ok": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": type(exc).__name__,
        }


@router.get("/api/health/live")
async def health_live() -> dict[str, Any]:
    """Process/event-loop liveness only; dependencies are intentionally omitted."""
    return {"status": "live", "ts": int(time.time())}


@router.get("/api/health/ready")
async def health_ready(response: Response) -> dict[str, Any]:
    probes = await asyncio.gather(
        _probe_engine(auth_engine),
        _probe_engine(config_engine),
        _probe_engine(data_engine),
    )
    names = ("auth_db", "config_db", "data_db")
    checks = dict(zip(names, probes))
    try:
        ingest = await mqtt_service.ingest_diagnostics()
    except Exception as exc:
        ingest = {"error": type(exc).__name__}
    checks["ingest"] = ingest
    ready = all(item.get("ok") for item in probes)
    # A non-empty spool is healthy during a transient outage, but a rejected
    # append means the bounded handoff has reached its hard safety limit.
    if int((ingest.get("metrics") or {}).get("spool_rejected", 0) or 0) > 0:
        ready = False
    response.status_code = 200 if ready else 503
    return {
        "status": "ready" if ready else "degraded",
        "ts": int(time.time()),
        "checks": checks,
        "draining": bool(getattr(mqtt_service, "_stopping", False)),
    }


@router.get("/api/admin/system/runtime")
async def runtime_diagnostics(
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE)),
) -> dict[str, Any]:
    del current_user
    try:
        ingest = await mqtt_service.ingest_diagnostics()
    except Exception as exc:
        ingest = {"error": type(exc).__name__}
    client = getattr(mqtt_service, "client", None)
    connected = False
    try:
        connected = bool(client and client.is_connected())
    except Exception:
        connected = False
    return {
        "ts": int(time.time()),
        "mqtt": {"connected": connected, "topic_count": len(getattr(mqtt_service, "topic_map", {}) or {})},
        "ingest": ingest,
        "background_tasks": len(getattr(mqtt_service, "_background_tasks", set()) or set()),
        "threadsafe_futures": len(getattr(mqtt_service, "_threadsafe_futures", set()) or set()),
        "websocket": websocket_manager.diagnostics(),
        "draining": bool(getattr(mqtt_service, "_stopping", False)),
    }
