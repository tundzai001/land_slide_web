"""Shared optional-auth and project visibility helpers for public APIs."""
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth, config


async def get_optional_current_user_from_request(
    request: Request,
    db: AsyncSession,
) -> Optional[Any]:
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = auth.jwt.decode(
            token,
            config.settings.SECRET_KEY,
            algorithms=[config.settings.ALGORITHM],
        )
        username = payload.get("sub")
        if not username:
            return None
        user = await auth.get_user_by_username_cached(username, db)
        if user is None or not user.is_active:
            return None
        return user
    except Exception:
        return None


def user_project_filter_ids(user: Optional[Any]) -> Optional[set[int]]:
    if user is None or user.role == "admin":
        return None
    assigned = getattr(user, "assigned_projects", None) or []
    if user.role == "viewer" and not assigned:
        return None
    return {int(project_id) for project_id in assigned}
