"""Project administration and CRUD routes."""

from __future__ import annotations

import logging
import time
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config
from pydantic import BaseModel
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows
from ...shared.access import user_project_filter_ids
from ...shared.project_location import refresh_project_map_position, save_project_map_position, update_location_address, validate_map_position
from ...shared.project_dem import delete_project_dems, save_project_dem, update_project_dem_metadata
from ...shared.project_dem_db import delete_project_dem_catalog, get_project_dem_models, get_project_dem_summaries, save_project_dem_catalog
from .public import public_clusters

router = APIRouter(tags=["Projects"])
logger = logging.getLogger(__name__)


def validate_project_fields(data, creating=False):
    for key, limit in (("project_code", 50), ("name", 255), ("description", 1000)):
        if key not in data and not (creating and key in ("project_code", "name")):
            continue
        value = data.get(key)
        if key == 'description' and value is None:
            continue
        if not isinstance(value, str) or len(value) > limit or (key != 'description' and not value.strip()):
            raise HTTPException(422, f"Trường {key} không hợp lệ (tối đa {limit} ký tự).")
        data[key] = value.strip()

@router.get("/api/admin/projects", responses={422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
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
        dem_summaries = await get_project_dem_summaries(db, [project.id for project, _ in projects_with_counts])

        # Filter projects for operator role
        assigned = user_project_filter_ids(current_user)
        if assigned is not None:
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
                **dem_summaries[p.id],
                "gnss_clusters": p.gnss_clusters if current_user.role == 'admin' else public_clusters(p.gnss_clusters),
                **({"auto_adjustment_config": p.auto_adjustment_config} if current_user.role == 'admin' else {}),
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
        logger.exception(f"Error loading projects: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải danh sách dự án.")


@router.post("/api/admin/projects/{project_id}/dems", responses={404: {"description": "Not Found"}, 415: {"description": "Unsupported Media Type"}})
async def upload_project_dem(
    project_id: int,
    dem_name: str = Form(..., max_length=100),
    dem_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS)),
):
    safe_filename = (dem_file.filename or "").replace("\r", "").replace("\n", "")
    logger.info("Project DEM upload received project_id=%s filename=%r bytes=%s", project_id, safe_filename, getattr(dem_file, "size", None))
    project = await db.get(model_config.Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án.")
    if not (dem_file.filename or "").lower().endswith(".asc"):
        raise HTTPException(status_code=415, detail="Chỉ hỗ trợ file DEM ESRI ASCII Grid (.asc).")
    existing_models = await get_project_dem_models(db, project_id)
    result = await run_in_threadpool(save_project_dem, project_id, dem_name, dem_file.file, existing_models)
    await save_project_dem_catalog(db, project_id, result["models"], current_user.username)
    await refresh_project_map_position(db, project_id)
    await db.commit()
    logger.info("Saved project DEM project_id=%s dem_id=%s filename=%r bytes=%s", project_id, result["dem_id"], safe_filename, dem_file.size)
    return {"project_id": project_id, **result}


class UpdateProjectDemRequest(BaseModel):
    xllcorner: float
    yllcorner: float
    name: Optional[str] = None


@router.put("/api/admin/projects/{project_id}/dems/{dem_id}", responses={404: {"description": "Not Found"}})
async def update_project_dem(
    project_id: int,
    dem_id: str,
    payload: UpdateProjectDemRequest,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS)),
):
    project = await db.get(model_config.Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án.")
    existing_models = await get_project_dem_models(db, project_id)
    result = await run_in_threadpool(
        update_project_dem_metadata,
        project_id,
        dem_id,
        payload.xllcorner,
        payload.yllcorner,
        payload.name,
        existing_models,
    )
    await save_project_dem_catalog(db, project_id, result["models"], current_user.username)
    await refresh_project_map_position(db, project_id)
    await db.commit()
    safe_dem_id = dem_id.replace("\r", "").replace("\n", "")
    logger.info("Updated project DEM project_id=%s dem_id=%r xllcorner=%s yllcorner=%s", project_id, safe_dem_id, payload.xllcorner, payload.yllcorner)
    return {"project_id": project_id, **result}


@router.post("/api/admin/projects", responses={422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
async def create_project(
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        validate_project_fields(project_data, creating=True)
        position = validate_map_position(project_data.get('map_position', {"mode": "auto"}))
        new_project = model_config.Project(
            project_code=project_data['project_code'],
            name=project_data['name'],
            description=project_data.get('description'),
            location=update_location_address(None, project_data.get('location')),
            created_at=int(time.time()),
            updated_at=int(time.time()),
            is_active=True
        )

        db.add(new_project)
        await db.flush()
        await save_project_map_position(db, new_project, position)
        await db.commit()
        await db.refresh(new_project)

        return {
            "id": new_project.id,
            "project_code": new_project.project_code,
            "name": new_project.name,
            "description": new_project.description,
            "location": new_project.location
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail="Không thể tạo dự án.")


@router.put("/api/admin/projects/{project_id}", responses={404: {"description": "Not Found"}, 409: {"description": "Conflict"}, 422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
async def update_project(
    project_id: int,
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id).with_for_update()
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        validate_project_fields(project_data)
        position = validate_map_position(project_data['map_position']) if 'map_position' in project_data else None

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
            project.location = update_location_address(project.location, project_data['location'])
        if 'is_active' in project_data:
            project.is_active = project_data['is_active']
        if 'gnss_clusters' in project_data:
            project.gnss_clusters = project_data['gnss_clusters']
        if 'auto_adjustment_config' in project_data:
            project.auto_adjustment_config = project_data['auto_adjustment_config']

        project.updated_at = int(time.time())
        await save_project_map_position(db, project, position)

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
        logger.exception(f"Error updating project: {e}")
        raise HTTPException(status_code=500, detail="Không thể cập nhật dự án.")


@router.get("/api/admin/projects/{project_id}", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
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
        logger.exception(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải dự án.")


@router.delete("/api/admin/projects/{project_id}", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        await db.delete(project)
        await delete_project_dem_catalog(db, project_id)
        await db.commit()
        try:
            delete_project_dems(project_id)
        except OSError:
            logger.warning("Could not remove DEM for deleted project id=%s", project_id)

        return {"status": "success", "message": f"Deleted project {project_id}"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error deleting project: {e}")
        raise HTTPException(status_code=500, detail="Không thể xóa dự án.")
