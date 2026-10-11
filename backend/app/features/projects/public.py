"""Public project routes."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ...database import get_auth_db, get_config_db
from ...models import config as model_config
from ...shared.access import get_optional_current_user_from_request, user_project_filter_ids
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows
from ...shared.project_dem import project_dem_path
from ...shared.project_dem_db import get_project_dem_models, get_project_dem_summaries

router = APIRouter(tags=["Projects"])
logger = logging.getLogger(__name__)


def public_clusters(clusters):
    # The map only needs geometry. Base connection settings can contain credentials.
    return [
        {key: cluster[key] for key in ('name', 'cluster_type', 'stations') if key in cluster}
        for cluster in (clusters or []) if isinstance(cluster, dict)
    ]

@router.get("/api/projects")
async def get_public_projects(
    request: Request,
    response: Response,
    q: Optional[str] = Query(None, max_length=100),
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
            term = q.strip()
            stmt = stmt.where(
                model_config.Project.name.icontains(term, autoescape=True)
                | model_config.Project.project_code.icontains(term, autoescape=True)
            )
        if is_active is not None:
            stmt = stmt.where(model_config.Project.is_active.is_(is_active))
        page_offset, page_limit = normalize_page(offset, limit)
        result = await db.execute(stmt)
        project_rows = result.all()
        dem_summaries = await get_project_dem_summaries(db, [project.id for project, _ in project_rows])

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
                **dem_summaries[p.id],
                "gnss_clusters": public_clusters(p.gnss_clusters),
            }
            for p, count in project_rows
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


async def _project_dem_access(project_id: int, request: Request, db: AsyncSession, db_auth: AsyncSession):
    current_user = await get_optional_current_user_from_request(request, db_auth)
    allowed_project_ids = user_project_filter_ids(current_user)
    if allowed_project_ids is not None and project_id not in allowed_project_ids:
        raise HTTPException(status_code=404, detail="Không tìm thấy mô hình địa hình.")
    project = await db.get(model_config.Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy mô hình địa hình.")
    return project


@router.get("/api/projects/{project_id}/dems")
async def get_project_dems(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_config_db),
    db_auth: AsyncSession = Depends(get_auth_db),
):
    await _project_dem_access(project_id, request, db, db_auth)
    return {"project_id": project_id, "models": await get_project_dem_models(db, project_id)}


@router.get("/api/projects/{project_id}/dems/{dem_id}")
async def get_project_dem_file(
    project_id: int,
    dem_id: str,
    request: Request,
    db: AsyncSession = Depends(get_config_db),
    db_auth: AsyncSession = Depends(get_auth_db),
):
    await _project_dem_access(project_id, request, db, db_auth)
    models = await get_project_dem_models(db, project_id)
    model = next((item for item in models if item.get("id") == dem_id), None)
    if not model:
        raise HTTPException(status_code=404, detail="Dự án chưa có mô hình địa hình.")
    dem_path = project_dem_path(project_id, dem_id)
    return FileResponse(
        dem_path,
        media_type="text/plain; charset=utf-8",
        filename=f"model-{dem_id}.asc",
        headers={"Cache-Control": "private, no-store"},
    )
