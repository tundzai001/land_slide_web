"""Shared optional-auth and project visibility helpers for public APIs."""
from typing import Any, Optional

from fastapi import Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth, config


async def get_optional_current_user_from_request(
    request: Request,
    db: AsyncSession,
) -> Optional[Any]:
    from ..browser_session import request_token
    token = request_token(request, required=not config.settings.PUBLIC_MONITORING_ENABLED)
    if token is None:
        return None
    return await auth.get_current_user(request, token, db)


def user_project_filter_ids(user: Optional[Any]) -> Optional[set[int]]:
    if user is None or user.role == "admin":
        return None
    assigned = getattr(user, "assigned_projects", None) or []
    return {int(project_id) for project_id in assigned}
