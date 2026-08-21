"""Admin-only deterministic landslide simulations and report exports."""
from __future__ import annotations

import asyncio
from io import BytesIO
import logging
import math
import os
import re
import secrets
import time
from typing import Any, Literal, Optional
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..database import ConfigSessionLocal, DataSessionLocal, get_config_db, get_data_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data
from ..services.simulation_engine import ENGINE_VERSION, SCHEMA_VERSION, calculate_fos, normalize_parameters, run_simulation
from ..services.simulation_reports import build_json, build_pdf, build_xlsx, run_payload

router = APIRouter(prefix="/api/simulations", tags=["Landslide simulations"])
logger = logging.getLogger(__name__)
_workers: set[asyncio.Task] = set()
_worker_limit = asyncio.Semaphore(max(1, min(4, (os.cpu_count() or 2) // 2)))


class SimulationCreate(BaseModel):
    mode: Literal["manual", "station_snapshot"] = "manual"
    project_id: Optional[int] = None
    station_id: Optional[int] = None
    display_name: Optional[str] = Field(default=None, max_length=240)
    duration_hours: int = Field(default=24, ge=1, le=168)
    seed: Optional[int] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


def _safe_name(value: Any, fallback: str) -> str:
    text = re.sub(r'[^\w\-. ]+', "_", str(value or "").strip(), flags=re.UNICODE)
    return re.sub(r"\s+", "_", text).strip("._")[:100] or fallback


def _download_header(filename: str, fallback: str) -> str:
    """Return an ASCII-safe header plus the UTF-8 name understood by browsers."""
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'


def _run_view(run: model_data.SimulationRun, detail: bool = True) -> dict[str, Any]:
    payload = run_payload(run)
    payload["progress"] = run.progress
    if not detail:
        for key in ("parameters", "parameter_sources", "sensor_snapshot", "time_series", "events", "terrain_profile"):
            payload.pop(key, None)
    return payload


async def _station_inputs(station_id: int, config_db: AsyncSession, data_db: AsyncSession) -> dict[str, Any]:
    station = (await config_db.execute(select(model_config.Station).where(model_config.Station.id == station_id))).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm")
    project = (await config_db.execute(select(model_config.Project).where(model_config.Project.id == station.project_id))).scalar_one_or_none()
    rows = (await data_db.execute(select(model_data.LatestSensorCache).where(model_data.LatestSensorCache.station_id == station_id))).scalars().all()
    now = int(time.time())
    config = station.config or {}
    profile = config.get("simulation_profile") or {}
    mapping = {
        "cohesion_kpa": "cohesion", "friction_angle_deg": "friction_angle",
        "unit_weight_kn_m3": "unit_weight", "slip_depth_m": "slip_depth",
        "slope_angle_deg": "slope_angle", "saturated_conductivity_m_s": "ks",
        "porosity": "porosity", "base_pore_pressure_ratio": "pore_pressure_ratio",
        "base_seismic_coeff": "seismic_coeff", "house_count": "house_count", "tree_count": "tree_count",
    }
    parameters: dict[str, Any] = {}
    sources: dict[str, str] = {}
    warnings: list[str] = []
    for profile_key, parameter_key in mapping.items():
        if profile_key in profile:
            parameters[parameter_key] = profile[profile_key]
            sources[parameter_key] = "Hồ sơ trạm"
        else:
            sources[parameter_key] = "Mặc định hệ thống"
            warnings.append(f"Thiếu {profile_key}; dùng giá trị mặc định")

    snapshot: dict[str, Any] = {}
    valid_data: dict[str, dict[str, Any]] = {}
    thresholds = config.get("offline_thresholds") or {}
    for row in rows:
        sensor_type = str(row.sensor_type).lower()
        data = row.data if isinstance(row.data, dict) else {}
        threshold = int(thresholds.get(sensor_type, 300))
        fresh = now - int(row.timestamp or 0) <= threshold
        fallback = bool(data.get("is_fallback"))
        snapshot[sensor_type] = {"timestamp": row.timestamp, "is_online": fresh, "is_fallback": fallback, "data": data}
        if fresh and not fallback:
            valid_data[sensor_type] = data
        else:
            warnings.append(f"Sensor {sensor_type} {'đã cũ/offline' if not fresh else 'đang dùng fallback'}; không áp dụng vào phép tính")

    rain = valid_data.get("rain") or valid_data.get("rainfall")
    if rain:
        value = rain.get("intensity_mm_h", rain.get("rainfall_mm"))
        if value is not None:
            parameters["rainfall"], sources["rainfall"] = value, "Cảm biến mưa"
    water = valid_data.get("water")
    if water:
        level = water.get("water_level", water.get("water_level_m"))
        dry, saturated = profile.get("water_level_dry_m"), profile.get("water_level_saturated_m")
        if level is not None and dry is not None and saturated is not None and float(saturated) > float(dry):
            ratio = min(1.0, max(0.0, (float(level) - float(dry)) / (float(saturated) - float(dry))))
            base_ru = float(parameters.get("pore_pressure_ratio", 0.0))
            parameters["pore_pressure_ratio"] = min(0.6, base_ru + ratio * (0.6 - base_ru))
            sources["pore_pressure_ratio"] = "Cảm biến mực nước + calibration trạm"
        else:
            warnings.append("Có mực nước nhưng thiếu calibration khô/bão hòa; không quy đổi sang ru")
    imu = valid_data.get("imu")
    if imu and imu.get("ax") is not None and imu.get("ay") is not None:
        parameters["seismic_coeff"] = min(0.5, math.hypot(float(imu["ax"]), float(imu["ay"])) / 9.81)
        sources["seismic_coeff"] = "Gia tốc ngang IMU"

    normalized = normalize_parameters(parameters)
    return {
        "station": station, "project": project, "parameters": normalized, "parameter_sources": sources,
        "sensor_snapshot": snapshot, "warnings": list(dict.fromkeys(warnings)),
    }


async def _execute_run(run_id: int) -> None:
    async with _worker_limit:
        now = int(time.time())
        async with DataSessionLocal() as db:
            run = await db.get(model_data.SimulationRun, run_id)
            if not run or run.status != "queued":
                return
            run.status, run.progress, run.started_at, run.updated_at = "running", 10, now, now
            await db.commit()
            parameters, duration, seed = dict(run.parameters), int(run.sim_duration_seconds), int(run.seed)
        try:
            result = await asyncio.to_thread(run_simulation, parameters, duration, seed)
            async with DataSessionLocal() as db:
                run = await db.get(model_data.SimulationRun, run_id)
                if not run or run.status == "stopped":
                    return
                run.parameters = result["parameters"]
                run.time_series = result["time_series"]
                run.events = result["events"]
                run.summary = result["summary"]
                run.terrain_profile = result["terrain_profile"]
                run.status, run.progress = "completed", 100
                run.finished_at = run.updated_at = int(time.time())
                await db.commit()
        except Exception as exc:
            async with DataSessionLocal() as db:
                run = await db.get(model_data.SimulationRun, run_id)
                if run and run.status != "stopped":
                    run.status, run.error_detail = "failed", str(exc)[:4000]
                    run.finished_at = run.updated_at = int(time.time())
                    await db.commit()


def _start_worker(run_id: int) -> None:
    task = asyncio.create_task(_execute_run(run_id), name=f"simulation-{run_id}")
    _workers.add(task)
    task.add_done_callback(_workers.discard)


async def recover_interrupted_runs() -> int:
    try:
        async with DataSessionLocal() as db:
            result = await db.execute(update(model_data.SimulationRun).where(model_data.SimulationRun.status.in_(["queued", "running"])).values(status="interrupted", finished_at=int(time.time()), updated_at=int(time.time()), error_detail="Server khởi động lại trước khi tác vụ hoàn tất"))
            await db.commit()
            return int(result.rowcount or 0)
    except SQLAlchemyError as exc:
        # Deployments may start once before the Alembic/pgAdmin migration is
        # applied. Keep unrelated monitoring services available and make the
        # missing simulation schema explicit in the server log.
        logger.warning("Simulation recovery skipped; apply the simulation_runs migration: %s", exc)
        return 0


@router.post("/runs", status_code=202)
async def create_run(payload: SimulationCreate, data_db: AsyncSession = Depends(get_data_db), config_db: AsyncSession = Depends(get_config_db), current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    now, warnings = int(time.time()), []
    sources = {key: "Nhập thủ công" for key in payload.parameters}
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
    subject = station.name if station else (project.name if project else "Kịch bản thủ công")
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
async def list_runs(response: Response, project_id: Optional[int] = None, station_id: Optional[int] = None, status: Optional[str] = None, mode: Optional[str] = None, start_ts: Optional[int] = None, end_ts: Optional[int] = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
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
    return {"station_id": station_id, "evaluated_at": int(time.time()), "fos": round(fos, 4), "classification": "Ổn định" if fos >= 1.5 else "Cảnh báo" if fos >= 1.0 else "Nguy hiểm", "parameters": context["parameters"], "parameter_sources": context["parameter_sources"], "sensor_snapshot": context["sensor_snapshot"], "warnings": context["warnings"]}


@router.get("/runs/{run_id}/export")
async def export_run(run_id: int, format: Literal["pdf", "xlsx", "json"] = "pdf", db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    builders = {"pdf": (build_pdf, "application/pdf"), "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), "json": (build_json, "application/json; charset=utf-8")}
    body = await asyncio.to_thread(builders[format][0], run)
    filename = f"{_safe_name(run.display_name, f'simulation_{run.id}')}.{format}"
    return StreamingResponse(BytesIO(body), media_type=builders[format][1], headers={"Content-Disposition": _download_header(filename, f"simulation_{run.id}.{format}"), "Cache-Control": "no-store"})


@router.get("/runs/{run_id}/bundle")
async def export_bundle(run_id: int, db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    files = await asyncio.gather(asyncio.to_thread(build_pdf, run), asyncio.to_thread(build_xlsx, run), asyncio.to_thread(build_json, run))
    folder = "/".join(["simulations", _safe_name(run.project_code, "MANUAL"), _safe_name(run.station_code, "manual"), f"{time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(run.created_at))}_{_safe_name(run.display_name, str(run.id))}"])
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, body in zip(("report.pdf", "results.xlsx", "data.json"), files):
            archive.writestr(f"{folder}/{name}", body)
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="simulation_{run.id}.zip"', "Cache-Control": "no-store"})
