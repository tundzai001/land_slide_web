"""Login and current-session API routes."""
from datetime import timedelta
import asyncio
import bcrypt
import hashlib
import logging
import secrets
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth, schemas
from ...config import settings
from ...database import get_auth_db
from ...models import auth as model_auth
from ... import browser_session
from ...websocket import manager as websocket_manager

router = APIRouter()
logger = logging.getLogger(__name__)
from . import sessions

AUTH_UNAVAILABLE_DETAIL = "Authentication unavailable"
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(secrets.token_urlsafe(24).encode(), bcrypt.gensalt()).decode()

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@router.post("/api/auth/login", response_model=schemas.Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_auth_db)
):
    if len(form_data.username) > 254 or len(form_data.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    try:
        await asyncio.to_thread(sessions.check_login, request.client.host if request.client else "unknown", form_data.username)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    result = await db.execute(
        select(model_auth.User).where(model_auth.User.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    password_valid = await auth.verify_password(
        form_data.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH)
    if not user or not password_valid or not user.is_active:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    remember_me = 'remember_me' in (form_data.scopes or [])
    expires = timedelta(hours=12) if remember_me else None

    browser = request.headers.get("x-session-mode") == "cookie"
    if browser:
        browser_session.require_origin(request)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, **({"transport": "cookie"} if browser else {})},
        expires_delta=expires
    )
    claims = auth.decode_access_token(access_token)
    try:
        await asyncio.to_thread(sessions.prune)
        await asyncio.to_thread(sessions.create, claims["jti"], user, claims["exp"],
                                client=request.headers.get("user-agent", ""))
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    from ..operations.store import actor
    actor(user)
    
    logger.info(f"✅ Login successful: {user.username} (remember_me={remember_me})")
    if browser:
        response = JSONResponse({"token_type": "cookie"})
        browser_session.set_cookies(response, request, access_token, claims["jti"],
                                    max_age=claims["exp"] - int(time.time()) if remember_me else None)
        return response
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/api/auth/logout")
async def logout(response: Response,
                 current_user: model_auth.User = Depends(auth.get_current_user),
                 token: str = Depends(auth.oauth2_scheme)):
    jti = auth.decode_access_token(token)["jti"]
    try:
        await asyncio.to_thread(sessions.revoke, jti)
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    await websocket_manager.close_session(jti)
    browser_session.clear_cookies(response)
    return {"status": "success"}

@router.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    request: Request,
    response: Response,
    token: str = Depends(auth.oauth2_scheme),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    await asyncio.sleep(0)
    claims = auth.decode_access_token(token)
    if claims.get("transport") == "cookie":
        csrf_name = browser_session.cookie_names()[1]
        if request.cookies.get(csrf_name) != browser_session.csrf_token(claims["jti"]):
            response.set_cookie(csrf_name, browser_session.csrf_token(claims["jti"]),
                                httponly=False, secure=settings.ENVIRONMENT.lower() == "production"
                                or request.url.scheme == "https", samesite="lax", path="/")
    permissions = auth.get_user_permissions(current_user)
    user_response = schemas.UserResponse.from_orm(current_user)
    user_response.permissions = permissions
    assigned_projects = sorted({
        int(project_id)
        for project_id in (getattr(current_user, 'assigned_projects', []) or [])
        if str(project_id).strip().lstrip('-').isdigit()
    })
    user_response.assigned_projects = assigned_projects
    scope_material = ':'.join([
        str(current_user.id),
        str(bool(current_user.is_active)).lower(),
        str(current_user.role or ''),
        ','.join(str(project_id) for project_id in assigned_projects),
    ])
    user_response.authz_scope_hash = hashlib.sha256(scope_material.encode('utf-8')).hexdigest()
    user_response.private_authz_grace_seconds = max(
        60,
        min(int(getattr(settings, 'PRIVATE_AUTHZ_GRACE_SECONDS', 300)), 900),
    )
    user_response.server_time = int(time.time())
    return user_response


@router.get("/api/auth/sessions")
async def list_sessions(current_user: model_auth.User = Depends(auth.get_current_user),
                        token: str = Depends(auth.oauth2_scheme)):
    try:
        return await asyncio.to_thread(sessions.list_for, current_user,
                                       auth.decode_access_token(token)["jti"])
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None


@router.delete("/api/auth/sessions/{session_id}")
async def revoke_session(session_id: str,
                         current_user: model_auth.User = Depends(auth.get_current_user),
                         token: str = Depends(auth.oauth2_scheme)):
    if not 16 <= len(session_id) <= 128:
        raise HTTPException(422, "Invalid session identifier")
    current_id = auth.decode_access_token(token)["jti"]
    try:
        revoked = await asyncio.to_thread(sessions.revoke_for, current_user, session_id,
                                          current_jti=current_id)
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    if not revoked:
        raise HTTPException(404, "Session not found")
    await websocket_manager.close_session(session_id)
    return {"status": "revoked"}


@router.post("/api/auth/sessions/revoke-others")
async def revoke_other_sessions(current_user: model_auth.User = Depends(auth.get_current_user),
                                token: str = Depends(auth.oauth2_scheme)):
    current_id = auth.decode_access_token(token)["jti"]
    try:
        rows = await asyncio.to_thread(sessions.list_for, current_user, current_id)
        for row in rows:
            if not row["current"]:
                await asyncio.to_thread(sessions.revoke_for, current_user, row["id"],
                                        current_jti=current_id)
                await websocket_manager.close_session(row["id"])
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    return {"revoked": sum(not row["current"] for row in rows)}


@router.post("/api/auth/ws-ticket")
async def create_websocket_ticket(
    current_user: model_auth.User = Depends(auth.get_current_user),
    body: dict | None = Body(default=None),
    token: str = Depends(auth.oauth2_scheme),
):
    """Return a short-lived credential so access tokens never enter proxy URLs."""
    body_payload = body if isinstance(body, dict) else {}
    channel = str(body_payload.get("channel") or "legacy_admin").strip().lower()
    if channel not in {"legacy_admin", "admin", "operations", "updates"}:
        raise HTTPException(status_code=422, detail="Unsupported WebSocket channel")
    assigned_projects = sorted({
        int(project_id)
        for project_id in (getattr(current_user, "assigned_projects", []) or [])
        if str(project_id).strip().lstrip("-").isdigit()
    })
    scope_material = ":".join([
        str(getattr(current_user, "id", 0)), str(bool(getattr(current_user, "is_active", True))).lower(),
        str(current_user.role or ""), ",".join(map(str, assigned_projects)),
    ])
    ticket = auth.create_access_token(
        data={
            "sub": current_user.username,
            "role": current_user.role,
            "purpose": "websocket",
            "session_id": auth.decode_access_token(token)["jti"],
            "channel": channel,
            "assigned_projects": assigned_projects,
            "authz_scope_hash": hashlib.sha256(scope_material.encode("utf-8")).hexdigest(),
            "jti": secrets.token_urlsafe(12),
        },
        expires_delta=timedelta(seconds=30),
    )
    claims = auth.jwt.decode(ticket, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    try:
        await asyncio.to_thread(sessions.create_ws_ticket, claims["jti"], claims["exp"])
    except Exception:
        raise HTTPException(503, AUTH_UNAVAILABLE_DETAIL) from None
    return {"ticket": ticket, "expires_in": 30}
