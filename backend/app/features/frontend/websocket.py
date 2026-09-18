"""Frontend WebSocket routes."""

from __future__ import annotations

import logging
import asyncio
import hashlib
import time
import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ... import auth
from ...config import settings
from ...database import AuthSessionLocal
from ...websocket import manager as ws_manager

logger = logging.getLogger(__name__)

_ws_ticket_lock = asyncio.Lock()
_consumed_ws_tickets: dict[str, float] = {}

router = APIRouter()

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
