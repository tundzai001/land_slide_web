"""Project administration and CRUD routes."""

from __future__ import annotations

import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows

router = APIRouter(tags=["Projects"])

@router.get("/api/admin/projects")
async def get_projects(
    response: Response,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_STATIONS))
):
    try:
        result = await db.execute(
            select(
                model_config.Project,
                func.count(model_config.Station.id).label('station_count')
            )
            .outerjoin(model_config.Station, model_config.Station.project_id == model_config.Project.id)
            .group_by(model_config.Project.id)
            .order_by(model_config.Project.created_at.desc())
        )

        projects_with_counts = result.all()

        # Filter projects for operator role
        assigned = getattr(current_user, 'assigned_projects', None) or []
        if current_user.role == 'operator' and assigned:
            projects_with_counts = [(p, c) for p, c in projects_with_counts if p.id in assigned]

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
                "gnss_clusters": getattr(p, "gnss_clusters", None),
                "auto_adjustment_config": getattr(p, "auto_adjustment_config", None)
            }
            for p, count in projects_with_counts
        ]
        normalized_q = (q or "").strip().lower()
        if normalized_q:
            rows = [row for row in rows if normalized_q in row["name"].lower() or normalized_q in row["project_code"].lower()]
        if is_active is not None:
            rows = [row for row in rows if row["is_active"] is is_active]
        allowed_sort = {"name", "project_code", "created_at", "station_count"}
        if sort:
            field = sort.lstrip("-")
            if field not in allowed_sort:
                raise HTTPException(status_code=422, detail="Unsupported sort field")
            rows.sort(key=lambda row: row.get(field) if row.get(field) is not None else "", reverse=sort.startswith("-"))
        page_offset, page_limit = normalize_page(offset, limit)
        set_pagination_headers(response, total=len(rows), offset=page_offset, limit=page_limit)
        return slice_rows(rows, page_offset, page_limit)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/admin/projects")
async def create_project(
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        new_project = model_config.Project(
            project_code=project_data['project_code'],
            name=project_data['name'],
            description=project_data.get('description'),
            location=project_data.get('location'),
            created_at=int(time.time()),
            updated_at=int(time.time()),
            is_active=True
        )

        db.add(new_project)
        await db.commit()
        await db.refresh(new_project)

        return {
            "id": new_project.id,
            "project_code": new_project.project_code,
            "name": new_project.name,
            "description": new_project.description,
            "location": new_project.location
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/admin/projects/{project_id}")
async def update_project(
    project_id: int,
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if 'project_code' in project_data:
            project_code = str(project_data['project_code'] or '').strip()
            if not project_code:
                raise HTTPException(status_code=422, detail="Mã dự án không được để trống")
            duplicate = await db.execute(
                select(model_config.Project).where(
                    model_config.Project.project_code == project_code,
                    model_config.Project.id != project_id,
                )
            )
            if duplicate.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Mã dự án đã được sử dụng")
            project.project_code = project_code

        if 'name' in project_data:
            name = str(project_data['name'] or '').strip()
            if not name:
                raise HTTPException(status_code=422, detail="Tên dự án không được để trống")
            project.name = name
        if 'description' in project_data:
            project.description = project_data['description']
        if 'location' in project_data:
            project.location = project_data['location']
        if 'is_active' in project_data:
            project.is_active = project_data['is_active']
        if 'gnss_clusters' in project_data:
            project.gnss_clusters = project_data['gnss_clusters']
        if 'auto_adjustment_config' in project_data:
            project.auto_adjustment_config = project_data['auto_adjustment_config']

        project.updated_at = int(time.time())

        await db.commit()
        await db.refresh(project)

        if 'auto_adjustment_config' in project_data:
            try:
                from ...infrastructure.scheduler import reload_scheduler
                await reload_scheduler()
            except Exception as e:
                logger.warning(f"Could not reload scheduler: {e}")


        return {
            "id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "description": project.description,
            "location": project.location,
            "gnss_clusters": project.gnss_clusters,
            "auto_adjustment_config": project.auto_adjustment_config
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/projects/{project_id}")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "description": project.description,
            "location": project.location,
            "gnss_clusters": project.gnss_clusters,
            "auto_adjustment_config": project.auto_adjustment_config
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/admin/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        await db.delete(project)
        await db.commit()

        return {"status": "success", "message": f"Deleted project {project_id}"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))
