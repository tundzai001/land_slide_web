"""Frontend document, health-check, and WebSocket routes."""
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse

from ..websocket import manager as ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

# ============================================================================
# WEBSOCKET & HEALTH CHECK
# ============================================================================
@router.websocket("/ws/updates")
@router.websocket("/ws/admin")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong"})
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
async def redirect_legacy_frontend_routes_to_landing():
    return RedirectResponse(url="/", status_code=307)
