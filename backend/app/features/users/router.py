"""Admin API routes owned by this feature."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth, schemas
from ...database import get_auth_db
from ...models import auth as model_auth
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])



@router.put("/users/{user_id}/status")
async def toggle_user_status(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot change status of the admin user")

    is_active = payload.get("is_active", True)
    user.is_active = is_active
    await db.commit()
    auth.invalidate_user_cache(user.username)
    return {"status": "success", "is_active": user.is_active}


@router.get("/users", response_model=List[schemas.UserResponse])
async def get_users(
    response: Response,
    q: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    users = list((await db.execute(select(model_auth.User))).scalars().all())
    normalized_q = (q or "").strip().lower()
    if normalized_q:
        users = [user for user in users if normalized_q in (user.username or "").lower() or normalized_q in (user.full_name or "").lower()]
    if role:
        users = [user for user in users if user.role == role]
    if is_active is not None:
        users = [user for user in users if user.is_active is is_active]
    allowed_sort = {"id", "username", "full_name", "role", "is_active"}
    if sort:
        field = sort.lstrip("-")
        if field not in allowed_sort:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        users.sort(key=lambda user: getattr(user, field, None) or "", reverse=sort.startswith("-"))
    page_offset, page_limit = normalize_page(offset, limit)
    set_pagination_headers(response, total=len(users), offset=page_offset, limit=page_limit)
    return slice_rows(users, page_offset, page_limit)


@router.put("/users/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS)),
):
    user = (
        await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role = payload.role or user.role
    if role not in {"admin", "operator", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if user.username == "admin" and role != "admin":
        raise HTTPException(status_code=400, detail="Cannot change the primary admin role")
    if user.id == current_user.id and role != current_user.role:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip() or None
    user.role = role
    user.assigned_projects = (
        list(dict.fromkeys(payload.assigned_projects or []))
        if role in {"operator", "viewer"}
        else []
    )
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must contain at least 6 characters")
        user.hashed_password = await auth.get_password_hash(payload.password)

    await db.commit()
    await db.refresh(user)
    auth.invalidate_user_cache(user.username)
    return user


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot delete the admin user")

    username = user.username
    await db.execute(delete(model_auth.User).where(model_auth.User.id == user_id))
    await db.commit()
    auth.invalidate_user_cache(username)
    return {"status": "success"}


@router.put("/users/{user_id}/projects")
async def update_user_projects(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Update project assignments for a user (typically operator)."""
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.assigned_projects = payload.get("assigned_projects", [])
    await db.commit()
    auth.invalidate_user_cache(user.username)
    return {"status": "success", "assigned_projects": user.assigned_projects}


@router.post("/users", response_model=schemas.UserResponse)
async def create_user(
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    exists = await db.execute(select(model_auth.User).where(model_auth.User.username == user_in.username))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_pw = await auth.get_password_hash(user_in.password)
    new_user = model_auth.User(
        username=user_in.username,
        hashed_password=hashed_pw,
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=True,
        assigned_projects=user_in.assigned_projects or []
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user
