"""Public project routes."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ...database import get_auth_db, get_config_db
from ...models import config as model_config
from ...shared.access import get_optional_current_user_from_request, user_project_filter_ids
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows

router = APIRouter(tags=["Projects"])
logger = logging.getLogger(__name__)


def public_clusters(clusters):
    # The map only needs geometry. Base connection settings can contain credentials.
    return [
        {key: cluster[key] for key in ('name', 'cluster_type', 'stations') if key in cluster}
        if isinstance(cluster, dict) else cluster
        for cluster in (clusters or []) if isinstance(cluster, (dict, list))
    ]

@router.get("/api/projects")
async def get_public_projects(
    request: Request,
    response: Response,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_config_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    try:
        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)

        stmt = (
            select(
                model_config.Project,
                func.count(model_config.Station.id).label('station_count')
            )
            .outerjoin(model_config.Station, model_config.Station.project_id == model_config.Project.id)
            .group_by(model_config.Project.id)
            .order_by(model_config.Project.created_at.desc())
        )

        if project_filter_ids is not None:
            if not project_filter_ids:
                page_offset, page_limit = normalize_page(offset, limit)
                set_pagination_headers(response, total=0, offset=page_offset, limit=page_limit)
                return []
            stmt = stmt.where(model_config.Project.id.in_(project_filter_ids))

        if q and q.strip():
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                model_config.Project.name.ilike(pattern)
                | model_config.Project.project_code.ilike(pattern)
            )
        if is_active is not None:
            stmt = stmt.where(model_config.Project.is_active.is_(is_active))
        page_offset, page_limit = normalize_page(offset, limit)
        result = await db.execute(stmt)

        rows = [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count,
                "gnss_clusters": public_clusters(p.gnss_clusters),
            }
            for p, count in result.all()
        ]
        allowed_sort = {"name", "project_code", "created_at", "station_count"}
        if sort:
            field = sort.lstrip("-")
            if field not in allowed_sort:
                raise HTTPException(status_code=422, detail="Unsupported sort field")
            rows.sort(key=lambda row: row.get(field) if row.get(field) is not None else "", reverse=sort.startswith("-"))
        set_pagination_headers(response, total=len(rows), offset=page_offset, limit=page_limit)
        return slice_rows(rows, page_offset, page_limit)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading public projects: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải danh sách dự án.")
