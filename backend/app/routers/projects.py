"""Project CRUD and project-level CORS configuration endpoints."""
import asyncio
import copy
import logging
import time

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..database import get_auth_db, get_config_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..runtime import cors_failover_status
from ..services.access import get_optional_current_user_from_request, user_project_filter_ids
from .cors_stations import _fetch_cors_base_stations_sync

router = APIRouter(tags=["Projects"])
logger = logging.getLogger(__name__)

@router.get("/api/projects")
async def get_public_projects(
    request: Request,
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
                return []
            stmt = stmt.where(model_config.Project.id.in_(project_filter_ids))

        result = await db.execute(stmt)

        return [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count,
                "gnss_clusters": getattr(p, "gnss_clusters", None)
            }
            for p, count in result.all()
        ]

    except Exception as e:
        logger.error(f"Error loading public projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/admin/projects")
async def get_projects(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
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

        return [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count,
                "gnss_clusters": getattr(p, "gnss_clusters", None)
            }
            for p, count in projects_with_counts
        ]

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

@router.get("/api/admin/projects/cors-stations")
async def get_admin_cors_stations(
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        return await asyncio.to_thread(_fetch_cors_base_stations_sync)
    except requests.RequestException as e:
        logger.warning(f"CORS base station fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch CORS base stations")


@router.get("/api/admin/projects/cors-failover-status")
async def get_admin_cors_failover_status(
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.MANAGE_USERS)
    ),
):
    return {"pairs": copy.deepcopy(cors_failover_status)}

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

        if 'name' in project_data:
            project.name = project_data['name']
        if 'description' in project_data:
            project.description = project_data['description']
        if 'location' in project_data:
            project.location = project_data['location']
        if 'is_active' in project_data:
            project.is_active = project_data['is_active']
        if 'gnss_clusters' in project_data:
            project.gnss_clusters = project_data['gnss_clusters']

        project.updated_at = int(time.time())

        await db.commit()
        await db.refresh(project)

        return {
            "id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "description": project.description,
            "location": project.location,
            "gnss_clusters": project.gnss_clusters
        }

    except HTTPException:
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
            "gnss_clusters": project.gnss_clusters
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


