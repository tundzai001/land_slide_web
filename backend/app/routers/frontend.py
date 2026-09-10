"""Frontend document, health-check, and WebSocket routes."""
import asyncio
import hashlib
import logging
import re
import time
from pathlib import Path

import jwt
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
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

_ws_ticket_lock = asyncio.Lock()
_consumed_ws_tickets: dict[str, float] = {}


async def _consume_ws_ticket(jti: str, *, ttl_seconds: int = 60) -> bool:
    """Consume a ticket once and keep the registry bounded for one worker."""
    now = time.time()
    async with _ws_ticket_lock:
        for key, expires_at in list(_consumed_ws_tickets.items()):
            if expires_at <= now:
                _consumed_ws_tickets.pop(key, None)
        if not jti or jti in _consumed_ws_tickets:
            return False
        _consumed_ws_tickets[jti] = now + ttl_seconds
        return True


def _frontend_document(file_name: str, *, private: bool = False):
    file_path = FRONTEND_DIR / file_name
    if not file_path.exists():
        return JSONResponse(status_code=503, content={"error": "Frontend not found"})
    noindex = private or settings.ENVIRONMENT.lower() != "production"
    headers = {"X-Robots-Tag": "noindex, noarchive"} if noindex else {}
    return FileResponse(file_path, media_type="text/html; charset=utf-8", headers=headers)

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

    if websocket.url.path not in {"/ws/admin", "/ws/operations"}:
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
        channel = str(payload.get("channel") or "legacy_admin").lower()
        required_channel = "operations" if websocket.url.path == "/ws/operations" else None
        if required_channel and channel != required_channel:
            raise ValueError("Wrong WebSocket channel")
        if websocket.url.path == "/ws/admin" and channel not in {"legacy_admin", "admin"}:
            raise ValueError("Wrong WebSocket channel")
        jti = str(payload.get("jti") or "")
        if (
            not username
            or payload.get("purpose") != "websocket"
            or payload.get("boot_epoch") != auth.WS_BOOT_EPOCH
            or not await _consume_ws_ticket(jti)
        ):
            raise ValueError("Token has no subject")

        async with AuthSessionLocal() as db:
            user = await auth.get_user_by_username_cached(username, db)
        if user is None or not user.is_active:
            raise ValueError("Inactive user")
        if channel == "admin" and str(user.role or "") != auth.Role.ADMIN:
            raise ValueError("Admin channel requires admin role")
        assigned_projects = sorted({
            int(project_id)
            for project_id in (getattr(user, "assigned_projects", []) or [])
            if str(project_id).strip().lstrip("-").isdigit()
        })
        scope_material = ":".join([
            str(user.id), str(bool(user.is_active)).lower(), str(user.role or ""),
            ",".join(map(str, assigned_projects)),
        ])
        scope_hash = hashlib.sha256(scope_material.encode("utf-8")).hexdigest()
        if payload.get("authz_scope_hash") and payload.get("authz_scope_hash") != scope_hash:
            raise ValueError("Authorization scope changed")
        websocket.state.user_role = str(user.role or "")
        websocket.state.user_id = int(user.id)
        websocket.state.user_project_ids = assigned_projects
        websocket.state.authz_scope_hash = scope_hash
        websocket.state.ws_channel = channel
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
@router.websocket("/ws/operations")
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
        return RedirectResponse(url=f"/{legacy_view}", status_code=307)
    return _frontend_document("index.html")

@router.get("/management")
@router.get("/management.html")
@router.get("/admin")
@router.get("/admin.html")
async def read_app():
    return _frontend_document("app.html", private=True)

@router.get("/map")
async def read_map():
    return _frontend_document("map.html")


@router.get("/login")
async def read_login():
    return _frontend_document("app.html", private=True)


@router.get("/robots.txt")
async def robots_txt():
    site_url = settings.PUBLIC_SITE_URL.rstrip("/")
    if settings.ENVIRONMENT.lower() != "production":
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse(
        f"User-agent: *\nDisallow: /api/\nDisallow: /ws/\nSitemap: {site_url}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
async def sitemap_xml():
    if settings.ENVIRONMENT.lower() != "production":
        return Response(status_code=404)
    site_url = settings.PUBLIC_SITE_URL.rstrip("/")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<url><loc>{site_url}/</loc></url>'
        f'<url><loc>{site_url}/map</loc></url>'
        '</urlset>'
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    file_path = FRONTEND_DIR / "aitogy.png"
    if file_path.exists():
        return FileResponse(file_path, media_type="image/png")
    return Response(status_code=404)


@router.get("/img/aitogy.png", include_in_schema=False)
async def aitogy_logo():
    file_path = FRONTEND_DIR / "aitogy.png"
    if file_path.exists():
        return FileResponse(file_path, media_type="image/png")
    return Response(status_code=404)
