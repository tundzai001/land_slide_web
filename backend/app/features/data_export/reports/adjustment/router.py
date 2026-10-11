"""Protected, on-demand GNSS adjustment download routes."""

from pathlib import Path
import re
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
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
logger = logging.getLogger(__name__)
ADJUSTMENT_REPORT_NAME = re.compile(
    r"^gnss_(?:binh_sai|adjustment)_(?P<project_id>[1-9][0-9]*)_"
    r"(?P<timestamp>[1-9][0-9]*)\.(?P<extension>xlsx|json)$"
)


async def _project_or_404(
    db: AsyncSession,
    project_id: int,
):
    project = (
        await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    return project


async def _observe_phase(
    request: Request,
    phase: str,
    operation: Callable[[], Awaitable[object]],
    **context,
):
    request.state.operation_phase = phase
    request_id = getattr(request.state, "request_id", "unknown")
    started = time.perf_counter()
    logger.info(
        "GNSS export phase started request_id=%s phase=%s context=%s",
        request_id,
        phase,
        context,
    )
    try:
        result = await operation()
    except Exception:
        logger.exception(
            "GNSS export phase failed request_id=%s phase=%s context=%s elapsed_ms=%.1f",
            request_id,
            phase,
            context,
            (time.perf_counter() - started) * 1000,
        )
        raise
    logger.info(
        "GNSS export phase completed request_id=%s phase=%s context=%s bytes=%s elapsed_ms=%.1f",
        request_id,
        phase,
        context,
        len(result.body) if isinstance(getattr(result, "body", None), bytes) else "n/a",
        (time.perf_counter() - started) * 1000,
    )
    return result


async def _download(
    *,
    project_id: int,
    filename: str,
    requested_url: str,
    data_db: AsyncSession,
    request: Request,
):
    match = re.search(r"\.(xlsx|json)$", filename, re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=404, detail="Adjustment report not found")
    found = await find_adjustment(
        data_db,
        project_id=project_id,
        requested_url=requested_url,
        request_id=getattr(request.state, "request_id", "unknown"),
        mark_phase=lambda phase: setattr(request.state, "operation_phase", phase),
    )
    if found is None:
        raise missing_export(f".{match.group(1).lower()}")
    _record, payload, evidence = found
    if match.group(1).lower() == "json":
        request.state.operation_phase = "serialize_json"
        return json_response(payload, filename)
    baseline_observations = payload.get("baseline_observations") or []
    points = payload.get("points") or {}
    return await _observe_phase(
        request,
        "render_xlsx",
        lambda: run_in_threadpool(
            xlsx_response,
            payload,
            evidence,
            project_id=project_id,
            filename=filename,
        ),
        project_id=project_id,
        filename=filename,
        status=payload.get("status", "unknown"),
        evidence_count=len(evidence),
        baseline_observation_count=len(baseline_observations),
        point_count=len(points),
    )


@router.get("/api/admin/gnss/adjustment/reports/{project_id}/{filename}")
async def download_gnss_adjustment_report(
    request: Request,
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
    request.state.operation_phase = "validate_report"
    await _observe_phase(
        request,
        "resolve_project",
        lambda: _project_or_404(db, project_id),
        project_id=project_id,
    )
    request.state.operation_phase = "authorize_project"
    check_operator_project_access(current_user, project_id)
    return await _download(
        project_id=project_id,
        filename=filename,
        requested_url=f"/api/admin/gnss/adjustment/reports/{project_id}/{filename}",
        data_db=data_db,
        request=request,
    )


@router.get("/api/admin/gnss/adjustment/reports/{project_code}/{cluster_name}/{path:path}")
async def download_scoped_gnss_adjustment_report(
    request: Request,
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

    projects = await _observe_phase(
        request,
        "list_projects",
        lambda: _list_projects(db),
        project_code=project_code,
    )
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
    request.state.operation_phase = "authorize_project"
    check_operator_project_access(current_user, int(project.id))
    return await _download(
        project_id=int(project.id),
        filename=filename,
        requested_url=(
            f"/api/admin/gnss/adjustment/reports/"
            f"{project_code}/{cluster_name}/{path}"
        ),
        data_db=data_db,
        request=request,
    )


async def _list_projects(db: AsyncSession):
    return (await db.execute(select(model_config.Project))).scalars().all()
