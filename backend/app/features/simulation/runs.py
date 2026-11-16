"""Simulation run routes."""

from __future__ import annotations

import secrets
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db, get_data_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...models import data as model_data
from .engine import ENGINE_VERSION, SCHEMA_VERSION, calculate_fos, normalize_parameters
from .schemas import SimulationCreate
from .service import _run_view, _start_worker, _station_inputs

router = APIRouter(prefix="/api/simulations", tags=["Landslide simulations"])

@router.post("/runs", status_code=202)
async def create_run(payload: SimulationCreate, data_db: AsyncSession = Depends(get_data_db), config_db: AsyncSession = Depends(get_config_db), current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    now, warnings = int(time.time()), []
    sources = dict.fromkeys(payload.parameters, "Nhập thủ công")
    sensor_snapshot: dict[str, Any] = {}
    project = station = None
    if payload.mode == "station_snapshot":
        if not payload.station_id:
            raise HTTPException(status_code=422, detail="Chế độ dữ liệu trạm cần station_id")
        context = await _station_inputs(payload.station_id, config_db, data_db)
        station, project = context["station"], context["project"]
        parameters = {**context["parameters"], **payload.parameters}
        sources, sensor_snapshot, warnings = context["parameter_sources"], context["sensor_snapshot"], context["warnings"]
        for key in payload.parameters:
            sources[key] = "Điều chỉnh thủ công"
    else:
        parameters = normalize_parameters(payload.parameters)
        if payload.project_id:
            project = (await config_db.execute(select(model_config.Project).where(model_config.Project.id == payload.project_id))).scalar_one_or_none()
    parameters = normalize_parameters(parameters)
    seed = int(payload.seed if payload.seed is not None else secrets.randbelow(2_000_000_000))
    if station:
        subject = station.name
    elif project:
        subject = project.name
    else:
        subject = "Kịch bản thủ công"
    display_name = payload.display_name or f"{subject} · {'Dữ liệu trạm' if station else 'Nhập thông số'} · {time.strftime('%d/%m/%Y %H:%M', time.localtime(now))}"
    run = model_data.SimulationRun(
        display_name=display_name, created_by_user_id=current_user.id, created_by_username=current_user.username,
        project_id=project.id if project else payload.project_id, project_code=project.project_code if project else None, project_name=project.name if project else None,
        station_id=station.id if station else None, station_code=station.station_code if station else None, station_name=station.name if station else None,
        mode=payload.mode, status="queued", progress=0, engine_version=ENGINE_VERSION, schema_version=SCHEMA_VERSION,
        seed=seed, sim_duration_seconds=payload.duration_hours * 3600, parameters=parameters, parameter_sources=sources,
        sensor_snapshot=sensor_snapshot, warnings=warnings, created_at=now, updated_at=now,
    )
    data_db.add(run)
    await data_db.commit()
    await data_db.refresh(run)
    _start_worker(run.id)
    return _run_view(run, detail=False)


@router.get("/runs")
async def list_runs(_response: Response, project_id: Optional[int] = None, station_id: Optional[int] = None, status: Optional[str] = None, mode: Optional[str] = None, start_ts: Optional[int] = None, end_ts: Optional[int] = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    query = select(model_data.SimulationRun)
    for condition in [model_data.SimulationRun.project_id == project_id if project_id is not None else None, model_data.SimulationRun.station_id == station_id if station_id is not None else None, model_data.SimulationRun.status == status if status else None, model_data.SimulationRun.mode == mode if mode else None, model_data.SimulationRun.created_at >= start_ts if start_ts else None, model_data.SimulationRun.created_at <= end_ts if end_ts else None]:
        if condition is not None:
            query = query.where(condition)
    rows = (await db.execute(query.order_by(desc(model_data.SimulationRun.created_at)).offset(offset).limit(limit))).scalars().all()
    return [_run_view(row, detail=False) for row in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: int, db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    return _run_view(run)


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: int, db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    if run.status in {"queued", "running"}:
        run.status, run.finished_at, run.updated_at = "stopped", int(time.time()), int(time.time())
        await db.commit()
    return _run_view(run, detail=False)


@router.post("/runs/{run_id}/rerun", status_code=202)
async def rerun(run_id: int, db: AsyncSession = Depends(get_data_db), current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    original = await db.get(model_data.SimulationRun, run_id)
    if not original:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    now = int(time.time())
    clone = model_data.SimulationRun(display_name=f"{original.display_name} · Chạy lại", created_by_user_id=current_user.id, created_by_username=current_user.username, project_id=original.project_id, project_code=original.project_code, project_name=original.project_name, station_id=original.station_id, station_code=original.station_code, station_name=original.station_name, mode=original.mode, status="queued", progress=0, engine_version=ENGINE_VERSION, schema_version=SCHEMA_VERSION, seed=original.seed, sim_duration_seconds=original.sim_duration_seconds, parameters=original.parameters, parameter_sources=original.parameter_sources, sensor_snapshot=original.sensor_snapshot, warnings=original.warnings, created_at=now, updated_at=now)
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    _start_worker(clone.id)
    return _run_view(clone, detail=False)


@router.get("/stations/{station_id}/evaluation")
async def evaluate_station(station_id: int, data_db: AsyncSession = Depends(get_data_db), config_db: AsyncSession = Depends(get_config_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    context = await _station_inputs(station_id, config_db, data_db)
    fos = calculate_fos(context["parameters"])
    if fos >= 1.5:
        classification = "Ổn định"
    elif fos >= 1.0:
        classification = "Cảnh báo"
    else:
        classification = "Nguy hiểm"
    return {"station_id": station_id, "evaluated_at": int(time.time()), "fos": round(fos, 4), "classification": classification, "parameters": context["parameters"], "parameter_sources": context["parameter_sources"], "sensor_snapshot": context["sensor_snapshot"], "warnings": context["warnings"]}
