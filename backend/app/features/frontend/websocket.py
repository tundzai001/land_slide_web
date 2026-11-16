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

router = APIRouter()
AUTHORIZATION_REFRESH_SECONDS = 30
AUTHORIZATION_TIMEOUT_SECONDS = max(10, int(getattr(settings, "DB_POOL_TIMEOUT_SECONDS", 10)))
MAX_CLIENT_MESSAGE_BYTES = 16 * 1024
WS_ADMIN_PATH = "/ws/admin"


def _user_scope(user):
    assigned = sorted({
        int(project_id) for project_id in (getattr(user, "assigned_projects", []) or [])
        if str(project_id).strip().lstrip("-").isdigit()
    })
    material = ":".join([
        str(user.id), str(bool(user.is_active)).lower(), str(user.role or ""),
        ",".join(map(str, assigned)),
    ])
    return assigned, hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _session_user(username, session_id):
    from ..authentication import sessions

    async with AuthSessionLocal() as db:
        user = await auth.get_user_by_username_cached(username, db)
    if user is None or not user.is_active or not await asyncio.to_thread(
        sessions.valid, session_id, user, touch=False
    ):
        raise ValueError("Session expired")
    return user


async def _await_session_user(username: str, session_id: str):
    try:
        return await asyncio.wait_for(
            _session_user(username, session_id),
            timeout=AUTHORIZATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await asyncio.sleep(0)
        return await asyncio.wait_for(
            _session_user(username, session_id),
            timeout=AUTHORIZATION_TIMEOUT_SECONDS,
        )

async def _consume_ws_ticket(jti: str) -> bool:
    from ..authentication import sessions
    return bool(jti and await asyncio.to_thread(sessions.consume_ws_ticket, jti))


async def _validate_ws_preconditions(websocket: WebSocket) -> str | None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_cors_origins:
        await websocket.close(code=1008, reason="Origin not allowed")
        return None

    if websocket.url.path not in {WS_ADMIN_PATH, "/ws/operations", "/ws/updates"}:
        await websocket.close(code=1008, reason="Unknown channel")
        return None

    token = websocket.query_params.get("ticket")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return None
    return token


def _validate_ws_payload(payload: dict, ws_path: str) -> tuple[str, str, str, str]:
    username = payload.get("sub")
    channel = str(payload.get("channel") or "legacy_admin").lower()
    required_channel = {"/ws/operations": "operations", "/ws/updates": "updates"}.get(ws_path)
    if required_channel and channel != required_channel:
        raise ValueError("Wrong WebSocket channel")
    if ws_path == WS_ADMIN_PATH and channel not in {"legacy_admin", "admin"}:
        raise ValueError("Wrong WebSocket channel")
    jti = payload.get("jti")
    if (
        not username
        or payload.get("purpose") != "websocket"
        or not isinstance(jti, str)
        or not jti
    ):
        raise ValueError("Token has no subject")
    parent_session = str(payload.get("session_id") or "")
    return username, channel, jti, parent_session


async def _authorize_websocket(websocket: WebSocket) -> bool:
    token = await _validate_ws_preconditions(websocket)
    if not token:
        return False

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti", "purpose", "channel", "session_id", "authz_scope_hash"]},
        )
        username, channel, jti, parent_session = _validate_ws_payload(payload, websocket.url.path)
        user = await _await_session_user(username, parent_session)
        if websocket.url.path == WS_ADMIN_PATH and str(user.role or "") != auth.Role.ADMIN:
            raise ValueError("Admin channel requires admin role")
        assigned_projects, scope_hash = _user_scope(user)
        if payload.get("authz_scope_hash") != scope_hash:
            raise ValueError("Authorization scope changed")
        if not await _consume_ws_ticket(jti):
            raise ValueError("WebSocket ticket expired or already used")
        websocket.state.user_role = str(user.role or "")
        websocket.state.user_id = int(user.id)
        websocket.state.user_project_ids = assigned_projects
        websocket.state.authz_scope_hash = scope_hash
        websocket.state.ws_channel = channel
        websocket.state.session_id = parent_session
        websocket.state.username = username
        websocket.state.authorization_deadline = time.monotonic() + AUTHORIZATION_REFRESH_SECONDS
        websocket.state.authorization_lock = asyncio.Lock()
        websocket.state.authorization_failed = False
        # Both outbound delivery and the independent monitor use this gate.
        websocket.state.ensure_authorized = lambda: _refresh_authorization(websocket)
    except (jwt.InvalidTokenError, ValueError):
        await websocket.close(code=1008, reason="Invalid authentication")
        return False
    except Exception:
        logger.exception("WebSocket authentication service failed")
        await websocket.close(code=1013, reason="Authentication unavailable")
        return False

    return True


async def _refresh_authorization(websocket: WebSocket) -> bool:
    async with websocket.state.authorization_lock:
        if websocket.state.authorization_failed:
            return False
        if time.monotonic() < websocket.state.authorization_deadline:
            return True
        try:
            user = await _await_session_user(
                websocket.state.username, websocket.state.session_id
            )
            if _user_scope(user)[1] != websocket.state.authz_scope_hash:
                raise ValueError("Authorization changed")
        except ValueError:
            code, reason = 1008, "Session or authorization expired"
        except Exception:
            logger.exception("WebSocket authorization refresh failed")
            code, reason = 1013, "Authentication unavailable"
        else:
            websocket.state.authorization_deadline = time.monotonic() + AUTHORIZATION_REFRESH_SECONDS
            return True
        websocket.state.authorization_failed = True
        ws_manager.disconnect(websocket)
        await websocket.close(code=code, reason=reason)
        return False


async def _monitor_authorization(websocket: WebSocket):
    while websocket in ws_manager.active_connections:
        await asyncio.sleep(max(0, websocket.state.authorization_deadline - time.monotonic()))
        if not await _refresh_authorization(websocket):
            return


async def _receive_messages(websocket: WebSocket):
    while True:
        data = await websocket.receive_text()
        if len(data.encode("utf-8")) > MAX_CLIENT_MESSAGE_BYTES:
            await websocket.close(code=1009, reason="Message too large")
            return
        if not await _refresh_authorization(websocket):
            return
        if data == "ping":
            await ws_manager.send_personal(websocket, {"type": "pong"})
        else:
            await ws_manager.handle_client_message(websocket, data)


@router.websocket("/ws/updates")
@router.websocket(WS_ADMIN_PATH)
@router.websocket("/ws/operations")
async def websocket_endpoint(websocket: WebSocket):
    if not await _authorize_websocket(websocket):
        return
    tasks = []
    try:
        await ws_manager.connect(websocket)
        tasks = [
            asyncio.create_task(_receive_messages(websocket)),
            asyncio.create_task(_monitor_authorization(websocket)),
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        logger.info("WebSocket receive loop ended: %s", detail)
    finally:
        ws_manager.disconnect(websocket)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
