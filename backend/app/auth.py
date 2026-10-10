# backend/app/auth.py
from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncio
import secrets
import jwt
from jwt import InvalidTokenError as JWTError
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# SỬA IMPORT Ở ĐÂY:
from .database import get_auth_db
from .models import auth as model_auth # Import từ thư mục models/auth.py
from .config import settings

_bearer_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


async def oauth2_scheme(request: Request, bearer_token: Optional[str] = Depends(_bearer_scheme)):
    from .browser_session import request_token
    return request_token(request)

def invalidate_user_cache(username: Optional[str] = None) -> None:
    """Compatibility hook; user authorization now reads directly from the database."""
    return None


async def get_user_by_username_cached(username: str, db: AsyncSession):
    result = await db.execute(select(model_auth.User).where(model_auth.User.username == username))
    return result.scalar_one_or_none()


class Role:
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

class Permission:
    MANAGE_USERS = "manage_users"
    EDIT_STATIONS = "edit_stations"
    VIEW_STATIONS = "view_stations"
    MANAGE_SIMULATIONS = "manage_simulations"
    CONTROL_SIREN = "control_siren"
    RUN_ADJUSTMENT = "run_adjustment"
    VIEW_INCIDENTS = "view_incidents"
    MANAGE_INCIDENTS = "manage_incidents"
    VIEW_FIELD_DEVICES = "view_field_devices"
    ASSIGN_FIELD_DEVICES = "assign_field_devices"
    MANAGE_FIELD_DEVICES = "manage_field_devices"
    MANAGE_DATABASE = "manage_database"
    MANAGE_RESCUE = "manage_rescue"

# --- Password Hashing ---
async def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = await asyncio.to_thread(bcrypt.gensalt)
    hashed = await asyncio.to_thread(bcrypt.hashpw, pwd_bytes, salt)
    return hashed.decode('utf-8')

async def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return await asyncio.to_thread(bcrypt.checkpw, plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except (ValueError, TypeError):
        return False

# --- JWT Token ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.setdefault("purpose", "access")
    to_encode.setdefault("jti", secrets.token_urlsafe(24))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token):
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                         options={"require": ["exp", "iat", "sub", "jti", "purpose"]})
    if payload["purpose"] != "access" or not isinstance(payload["sub"], str) or not payload["sub"]:
        raise JWTError("Invalid access token purpose or subject")
    if not isinstance(payload["jti"], str) or not 16 <= len(payload["jti"]) <= 128:
        raise JWTError("Invalid session identifier")
    return payload


# --- Dependency lấy User hiện tại ---
async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_auth_db) # Sử dụng Auth DB
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Query từ bảng User trong Auth DB
    user = await get_user_by_username_cached(username, db)

    if user is None or not user.is_active:
        raise credentials_exception
    from .features.authentication import sessions
    try:
        session_valid = await asyncio.to_thread(sessions.valid, payload["jti"], user,
                                                touch=request.url.path != "/api/auth/me")
    except Exception:
        raise HTTPException(503, "Authentication unavailable") from None
    if not session_valid:
        raise credentials_exception
    from .features.operations.store import actor
    actor(user)
    return user

# --- Phân quyền ---
def get_user_permissions(user):
    if user.role == Role.ADMIN:
        return [
            Permission.MANAGE_USERS,
            Permission.EDIT_STATIONS,
            Permission.VIEW_STATIONS,
            Permission.CONTROL_SIREN,
            Permission.RUN_ADJUSTMENT,
            Permission.VIEW_INCIDENTS,
            Permission.MANAGE_INCIDENTS,
            Permission.VIEW_FIELD_DEVICES,
            Permission.ASSIGN_FIELD_DEVICES,
            Permission.MANAGE_FIELD_DEVICES,
            Permission.MANAGE_DATABASE,
            Permission.MANAGE_RESCUE,
            Permission.MANAGE_SIMULATIONS,
        ]
    if user.role == Role.OPERATOR:
        return [
            Permission.EDIT_STATIONS,
            Permission.VIEW_STATIONS,
            Permission.CONTROL_SIREN,
            Permission.RUN_ADJUSTMENT,
            Permission.VIEW_INCIDENTS,
            Permission.MANAGE_INCIDENTS,
            Permission.VIEW_FIELD_DEVICES,
            Permission.ASSIGN_FIELD_DEVICES,
        ]
    if user.role == Role.VIEWER:
        return [Permission.VIEW_STATIONS, Permission.VIEW_INCIDENTS, Permission.VIEW_FIELD_DEVICES]
    return []

def require_permission(permission: str):
    async def permission_checker(current_user: model_auth.User = Depends(get_current_user)):
        perms = get_user_permissions(current_user)
        if permission not in perms:
             raise HTTPException(status_code=403, detail="Not enough permissions")
        return current_user
    return permission_checker
