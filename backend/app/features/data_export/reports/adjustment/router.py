"""Protected, on-demand GNSS adjustment download routes."""

from pathlib import Path
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..... import auth
from .....database import get_config_db, get_data_db
from .....models import auth as model_auth
from .....models import config as model_config
from .....shared.station_policy import check_operator_project_access
from .artifacts import artifact_slug
from .render import find_adjustment, json_response, missing_export, xlsx_response

router = APIRouter()
ADJUSTMENT_REPORT_NAME = re.compile(
    r"^gnss_(?:binh_sai|adjustment)_(?P<project_id>[1-9][0-9]*)_"
    r"(?P<timestamp>[1-9][0-9]*)\.(?P<extension>xlsx|json)$"
)


async def _project_or_404(
    db: AsyncSession,
    project_id: int,
    current_user: model_auth.User,
):
    project = (
        await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    check_operator_project_access(current_user, project_id)
    return project


async def _download(
    *,
    project_id: int,
    filename: str,
    requested_url: str,
    data_db: AsyncSession,
):
    match = re.search(r"\.(xlsx|json)$", filename, re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    found = await find_adjustment(
        data_db,
        project_id=project_id,
        requested_url=requested_url,
    )
    if found is None:
        raise missing_export(f".{match.group(1).lower()}")
    _record, payload, evidence = found
    if match.group(1).lower() == "json":
        return json_response(payload, filename)
    return xlsx_response(
        payload,
        evidence,
        project_id=project_id,
        filename=filename,
    )


@router.get("/api/admin/gnss/adjustment/reports/{project_id}/{filename}")
async def download_gnss_adjustment_report(
    project_id: int,
    filename: str,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.EDIT_STATIONS)
    ),
    data_db: AsyncSession = Depends(get_data_db),
):
    """Download a project-scoped result rendered from the data database."""
    match = ADJUSTMENT_REPORT_NAME.fullmatch(filename)
    if not match or int(match.group("project_id")) != project_id:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    await _project_or_404(db, project_id, current_user)
    return await _download(
        project_id=project_id,
        filename=filename,
        requested_url=f"/api/admin/gnss/adjustment/reports/{project_id}/{filename}",
        data_db=data_db,
    )


@router.get("/api/admin/gnss/adjustment/reports/{project_code}/{cluster_name}/{path:path}")
async def download_scoped_gnss_adjustment_report(
    project_code: str,
    cluster_name: str,
    path: str,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.EDIT_STATIONS)
    ),
    data_db: AsyncSession = Depends(get_data_db),
):
    """Download a project/cluster result rendered from the data database."""
    path_object = Path(path)
    filename = path_object.name
    if (
        not filename
        or path_object.is_absolute()
        or ".." in path_object.parts
        or path_object.suffix.lower() not in {".json", ".xlsx"}
        or artifact_slug(project_code, "") != project_code
        or artifact_slug(cluster_name, "") != cluster_name
    ):
        raise HTTPException(status_code=404, detail="Adjustment report not found")

    projects = (await db.execute(select(model_config.Project))).scalars().all()
    project = next(
        (
            item
            for item in projects
            if artifact_slug(item.project_code, f"project-{item.id}") == project_code
        ),
        None,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    check_operator_project_access(current_user, int(project.id))
    return await _download(
        project_id=int(project.id),
        filename=filename,
        requested_url=(
            f"/api/admin/gnss/adjustment/reports/"
            f"{project_code}/{cluster_name}/{path}"
        ),
        data_db=data_db,
    )
