"""Frontend document, health-check, and WebSocket routes."""
import asyncio
import logging
import re
import time
from pathlib import Path

import jwt
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import auth
from ..config import settings
from ..database import AuthSessionLocal, auth_engine, config_engine, data_engine
from ..runtime import mqtt_service
from ..websocket import manager as ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
PUBLIC_SOUND_DIR = Path(__file__).resolve().parents[2] / "static" / "sounds"
PUBLIC_SOUND_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}\.mp3$")

# ============================================================================
# WEBSOCKET & HEALTH CHECK
# ============================================================================


@router.get("/static/sounds/{file_name}")
async def get_public_sound(file_name: str):
    """Serve only known-safe MP3 filenames from the public sound directory."""
    if PUBLIC_SOUND_NAME.fullmatch(file_name) is None:
        return JSONResponse(status_code=404, content={"detail": "Sound not found"})
    sound_path = (PUBLIC_SOUND_DIR / file_name).resolve()
    if sound_path.parent != PUBLIC_SOUND_DIR.resolve() or not sound_path.is_file():
        return JSONResponse(status_code=404, content={"detail": "Sound not found"})
    return FileResponse(
        sound_path,
        media_type="audio/mpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )


async def _authorize_websocket(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=1008, reason="Origin not allowed")
        return False

    if websocket.url.path != "/ws/admin":
        return True

    token = websocket.query_params.get("ticket")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return False

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        username = payload.get("sub")
        if not username or payload.get("purpose") != "websocket":
            raise ValueError("Token has no subject")

        async with AuthSessionLocal() as db:
            user = await auth.get_user_by_username_cached(username, db)
        if user is None or not user.is_active:
            raise ValueError("Inactive user")
        websocket.state.user_role = str(user.role or "")
    except (jwt.InvalidTokenError, ValueError):
        await websocket.close(code=1008, reason="Invalid authentication")
        return False
    except Exception:
        logger.exception("WebSocket authentication service failed")
        await websocket.close(code=1013, reason="Authentication unavailable")
        return False

    return True


@router.websocket("/ws/updates")
@router.websocket("/ws/admin")
async def websocket_endpoint(websocket: WebSocket):
    if not await _authorize_websocket(websocket):
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong"})
            else:
                await ws_manager.handle_client_message(websocket, data)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        logger.info("WebSocket receive loop ended: %s", detail)
    finally:
        ws_manager.disconnect(websocket)

@router.get("/api/health")
async def health_check():
    return {"status": "ok", "time": time.time(), "db_status": "3-DB-Active"}


@router.get("/api/health/live")
async def liveness_check():
    return {"status": "ok", "time": time.time()}


@router.get("/api/health/ready")
async def readiness_check():
    async def check_database(name, engine):
        try:
            async with engine.connect() as connection:
                await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=3)
            return name, True
        except Exception as exc:
            logger.warning("Readiness check failed for %s: %s", name, exc)
            return name, False

    database_checks = await asyncio.gather(
        check_database("auth_db", auth_engine),
        check_database("config_db", config_engine),
        check_database("data_db", data_engine),
    )
    checks = dict(database_checks)
    try:
        checks["mqtt"] = bool(mqtt_service.client.is_connected())
    except Exception:
        checks["mqtt"] = False

    ready = all(checks.values())
    payload = {"status": "ready" if ready else "degraded", "checks": checks, "time": time.time()}
    return JSONResponse(status_code=200 if ready else 503, content=payload)

@router.get("/")
async def read_root(request: Request):
    legacy_view = (request.query_params.get("view") or "").lower()
    if legacy_view in {"admin", "management"}:
        return RedirectResponse(url="/management", status_code=307)
    if legacy_view in {"map", "login"}:
        return RedirectResponse(url="/", status_code=307)

    file_path = FRONTEND_DIR / "index.html"
    if file_path.exists():
        return FileResponse(file_path, media_type="text/html; charset=utf-8")
    return {"error": "Frontend not found"}

@router.get("/management")
@router.get("/management.html")
@router.get("/admin")
@router.get("/admin.html")
async def read_app():
    file_path = FRONTEND_DIR / "app.html"
    if file_path.exists():
        return FileResponse(file_path, media_type="text/html; charset=utf-8")
    return {"error": "Frontend not found"}

@router.get("/map")
@router.get("/login")
async def read_map_or_login():
    """Serve the route-aware application shell for stable deep links."""
    file_path = FRONTEND_DIR / "app.html"
    if file_path.exists():
        return FileResponse(file_path, media_type="text/html; charset=utf-8")
    return {"error": "Frontend not found"}
