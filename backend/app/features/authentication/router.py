"""Login and current-session API routes."""
from datetime import timedelta
import hashlib
import logging
import secrets
import time

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth, schemas
from ...config import settings
from ...database import get_auth_db
from ...models import auth as model_auth

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@router.post("/api/auth/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_auth_db)
):
    result = await db.execute(
        select(model_auth.User).where(model_auth.User.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not await auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Check remember_me from form scopes (OAuth2 extra fields)
    remember_me = 'remember_me' in (form_data.scopes or [])
    
    # If remember_me, issue a 30-day token; otherwise use default
    if remember_me:
        expires = timedelta(days=30)
    else:
        expires = None  # Uses default from settings
    
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=expires
    )
    
    logger.info(f"✅ Login successful: {user.username} (remember_me={remember_me})")
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user: model_auth.User = Depends(auth.get_current_user)
):
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


@router.post("/api/auth/ws-ticket")
async def create_websocket_ticket(
    current_user: model_auth.User = Depends(auth.get_current_user),
    body: dict | None = Body(default=None),
):
    """Return a short-lived credential so access tokens never enter proxy URLs."""
    body_payload = body if isinstance(body, dict) else {}
    channel = str(body_payload.get("channel") or "legacy_admin").strip().lower()
    if channel not in {"legacy_admin", "admin", "operations"}:
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
            "channel": channel,
            "assigned_projects": assigned_projects,
            "authz_scope_hash": hashlib.sha256(scope_material.encode("utf-8")).hexdigest(),
            "jti": secrets.token_urlsafe(12),
            "boot_epoch": auth.WS_BOOT_EPOCH,
        },
        expires_delta=timedelta(seconds=30),
    )
    return {"ticket": ticket, "expires_in": 30}
