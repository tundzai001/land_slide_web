"""Simulation run lifecycle and input preparation."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any
from urllib.parse import quote
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from ...database import DataSessionLocal
from ...models import config as model_config
from ...models import data as model_data
from .engine import normalize_parameters, run_simulation
from ..data_export.reports.simulation import run_payload

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
