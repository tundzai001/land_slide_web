# backend/app/auth.py
from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncio
import secrets
import time
import jwt
from jwt import InvalidTokenError as JWTError
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# SỬA IMPORT Ở ĐÂY:
from .database import get_auth_db
from .models import auth as model_auth # Import từ thư mục models/auth.py
from .config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

_AUTH_USER_CACHE_TTL_SECONDS = 15.0
_auth_user_cache = {}
_auth_user_locks = {}
# Short-lived WebSocket tickets are single-process credentials.  A fresh
# random epoch invalidates every outstanding ticket after a process restart,
# even when the JWT signing secret remains stable.
WS_BOOT_EPOCH = secrets.token_urlsafe(16)


def invalidate_user_cache(username: Optional[str] = None) -> None:
    """Drop cached auth records immediately after an admin RBAC mutation."""
    if username:
        _auth_user_cache.pop(str(username), None)
        return
    _auth_user_cache.clear()


async def get_user_by_username_cached(username: str, db: AsyncSession):
    now = time.monotonic()
    cached = _auth_user_cache.get(username)
    if cached and cached[0] > now:
        return cached[1]

    lock = _auth_user_locks.setdefault(username, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _auth_user_cache.get(username)
        if cached and cached[0] > now:
            return cached[1]

        result = await db.execute(select(model_auth.User).where(model_auth.User.username == username))
        user = result.scalar_one_or_none()
        if user is not None and user.is_active:
            _auth_user_cache[username] = (time.monotonic() + _AUTH_USER_CACHE_TTL_SECONDS, user)
        else:
            _auth_user_cache.pop(username, None)
        return user

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
    return await asyncio.to_thread(
        bcrypt.checkpw,
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8'),
    )

# --- JWT Token ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# --- Dependency lấy User hiện tại ---
async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_auth_db) # Sử dụng Auth DB
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # Query từ bảng User trong Auth DB
    user = await get_user_by_username_cached(username, db)
    
    if user is None or not user.is_active:
        raise credentials_exception
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
