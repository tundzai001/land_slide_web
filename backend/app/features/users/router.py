"""Admin API routes owned by this feature."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth, schemas
from ...database import get_auth_db
from ...models import auth as model_auth
from ...shared.pagination import normalize_page, set_pagination_headers


USER_NOT_FOUND = "User not found"
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])



@router.put("/users/{user_id}/status", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}})
async def toggle_user_status(
    user_id: int,
    payload: schemas.UserStatusUpdate,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND)

    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot change status of the admin user")

    if user.id == current_user.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    user.is_active = payload.is_active
    await db.commit()
    auth.invalidate_user_cache(user.username)
    return {"status": "success", "is_active": user.is_active}


@router.get("/users", response_model=List[schemas.UserResponse], responses={422: {"description": "Unprocessable Entity"}})
async def get_users(
    response: Response,
    q: Optional[str] = Query(None, max_length=150),
    role: Optional[schemas.UserRole] = None,
    is_active: Optional[bool] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    page_offset, page_limit = normalize_page(offset, limit)
    query = select(model_auth.User)
    normalized_q = (q or "").strip().lower()
    if normalized_q:
        query = query.where(or_(
            model_auth.User.username.icontains(normalized_q, autoescape=True),
            model_auth.User.full_name.icontains(normalized_q, autoescape=True),
        ))
    if role:
        query = query.where(model_auth.User.role == role)
    if is_active is not None:
        query = query.where(model_auth.User.is_active == is_active)
    allowed_sort = {"id", "username", "full_name", "role", "is_active"}
    if sort:
        field = sort.lstrip("-")
        if field not in allowed_sort:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        column = getattr(model_auth.User, field)
        query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
    total = (await db.execute(select(func.count()).select_from(query.order_by(None).subquery()))).scalar_one()
    query = query.order_by(model_auth.User.id.asc()).offset(page_offset)
    if page_limit is not None:
        query = query.limit(page_limit)
    users = list((await db.execute(query)).scalars().all())
    set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
    return users


@router.put("/users/{user_id}", response_model=schemas.UserResponse, responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}})
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
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND)

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
    if role == "admin":
        user.assigned_projects = []
    elif payload.assigned_projects is not None:
        user.assigned_projects = payload.assigned_projects
    if payload.password:
        user.hashed_password = await auth.get_password_hash(payload.password)

    await db.commit()
    await db.refresh(user)
    auth.invalidate_user_cache(user.username)
    return user


@router.delete("/users/{user_id}", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}})
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
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND)

    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot delete the admin user")

    username = user.username
    await db.execute(delete(model_auth.User).where(model_auth.User.id == user_id))
    await db.commit()
    auth.invalidate_user_cache(username)
    return {"status": "success"}


@router.put("/users/{user_id}/projects", responses={404: {"description": "Not Found"}})
async def update_user_projects(
    user_id: int,
    payload: schemas.UserProjectsUpdate,
    db: AsyncSession = Depends(get_auth_db),
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Update project assignments for a user (typically operator)."""
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND)

    user.assigned_projects = payload.assigned_projects if user.role != "admin" else []
    await db.commit()
    auth.invalidate_user_cache(user.username)
    return {"status": "success", "assigned_projects": user.assigned_projects}


@router.post("/users", response_model=schemas.UserResponse, responses={400: {"description": "Bad Request"}, 409: {"description": "Conflict"}})
async def create_user(
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
        assigned_projects=user_in.assigned_projects if user_in.role != "admin" else []
    )
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from None
    await db.refresh(new_user)
    return new_user
