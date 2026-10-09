"""Database administration read routes."""

from __future__ import annotations

import logging
import json
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db, get_data_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...models import data as model_data
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows
from ...shared.station_policy import get_offline_threshold
from ...shared.sensor_catalog import SENSOR_CATALOG

logger = logging.getLogger(__name__)
router = APIRouter()

PUBLIC_SENSOR_TYPES = tuple(SENSOR_CATALOG)
PUBLIC_SENSOR_FILTER = or_(model_data.SensorData.sensor_type.in_(PUBLIC_SENSOR_TYPES),
                           model_data.SensorData.sensor_type.like("custom\\_%", escape="\\"))
INTERNAL_SENSOR_TYPES = (
    "gnss_audit",
    "gnss_adjusted",
    "gnss_adjustment_failed",
)
_STATS_CACHE_TTL_SECONDS = 5
_stats_cache = None
_stats_cache_expires_at = 0.0

def _sensor_data_preview(value):
    """Return a compact, bounded preview without database-specific JSON casts."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text[:240]


def _coerce_int(value, fallback=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _device_runtime_state(device, station, now_ts: int) -> dict:
    threshold = get_offline_threshold(station.config or {}, device.device_type)
    last_data_time = int(device.last_data_time or 0)
    age_seconds = max(0, now_ts - last_data_time) if last_data_time else None
    is_online = bool(device.is_active and last_data_time and age_seconds < threshold)
    return {
        "effective_status": "online" if is_online else "offline",
        "age_seconds": age_seconds,
        "offline_threshold_seconds": threshold,
    }


@router.get("/api/admin/db/stats")  #
async def get_database_stats(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    global _stats_cache, _stats_cache_expires_at
    now = time.monotonic()
    if _stats_cache is not None and now < _stats_cache_expires_at:
        return _stats_cache
    try:
        # Đếm Stations
        count_stations = await config_db.execute(select(func.count()).select_from(model_config.Station))
        num_stations = count_stations.scalar()

        # Đếm Devices
        count_devices = await config_db.execute(select(func.count()).select_from(model_config.Device))
        num_devices = count_devices.scalar()

        # Match the general sensor explorer: internal GNSS adjustment streams
        # are counted separately below.
        count_sensor_data = await data_db.execute(
            select(func.count()).select_from(model_data.SensorData).where(
                PUBLIC_SENSOR_FILTER
            )
        )
        num_data = int(count_sensor_data.scalar() or 0)
        count_adjustments = await data_db.execute(
            select(func.count()).select_from(model_data.SensorData).where(
                model_data.SensorData.adjustment_key.is_not(None)
            )
        )
        num_adjustments = int(count_adjustments.scalar() or 0)

        # Đếm Active Alerts (Chưa xử lý)
        count_alerts = await data_db.execute(
            select(func.count()).select_from(model_data.Alert).where(model_data.Alert.is_resolved == False)
        )
        num_alerts = count_alerts.scalar()
        _stats_cache = {
            "stations": num_stations,
            "devices": num_devices,
            "sensor_data": num_data,
            "gnss_adjustments": num_adjustments,
            "alerts": num_alerts,
        }
        _stats_cache_expires_at = now + _STATS_CACHE_TTL_SECONDS
        return _stats_cache
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"stations": 0, "devices": 0, "sensor_data": 0, "gnss_adjustments": 0, "alerts": 0}


@router.get("/api/admin/db/stations")
async def admin_get_all_stations(
    response: Response,
    q: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    summary_only: bool = False,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Lấy tất cả stations từ DB"""
    try:
        query = select(model_config.Station)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            query = query.where(or_(model_config.Station.name.ilike(pattern), model_config.Station.station_code.ilike(pattern)))
        if project_id is not None:
            query = query.where(model_config.Station.project_id == project_id)
        sort_fields = {"id": model_config.Station.id, "name": model_config.Station.name, "station_code": model_config.Station.station_code, "created_at": model_config.Station.created_at}
        if sort:
            field = sort.lstrip("-")
            if field not in sort_fields:
                raise HTTPException(status_code=422, detail="Unsupported sort field")
            column = sort_fields[field]
            query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
        result = await db.execute(query)
        stations = result.scalars().all()
        if summary_only:
            rows = [
                {
                    "id": station.id,
                    "station_code": station.station_code,
                    "name": station.name,
                    "project_id": station.project_id,
                }
                for station in stations
            ]
            page_offset, page_limit = normalize_page(offset, limit)
            set_pagination_headers(response, total=len(rows), offset=page_offset, limit=page_limit)
            return slice_rows(rows, page_offset, page_limit)
        devices = list((await db.execute(select(model_config.Device))).scalars().all())
        devices_by_station = {}
        for device in devices:
            devices_by_station.setdefault(device.station_id, []).append(device)
        now_ts = int(time.time())
        rows = []
        for s in stations:
            active_devices = [device for device in devices_by_station.get(s.id, []) if device.is_active]
            runtime_states = [_device_runtime_state(device, s, now_ts) for device in active_devices]
            latest_data_time = max([int(device.last_data_time or 0) for device in active_devices] + [int(s.last_update or 0)])
            effective_status = "online" if any(state["effective_status"] == "online" for state in runtime_states) else "offline"
            row = {
                "id": s.id,
                "station_code": s.station_code,
                "name": s.name,
                "project_id": s.project_id,
                "location": s.location,
                "status": effective_status,
                "stored_status": s.status,
                "last_update": latest_data_time,
                "age_seconds": max(0, now_ts - latest_data_time) if latest_data_time else None,
                "online_device_count": sum(state["effective_status"] == "online" for state in runtime_states),
                "active_device_count": len(active_devices),
                "config": s.config,
                "created_at": s.created_at,
                "updated_at": s.updated_at
            }
            if not status or effective_status == status.lower():
                rows.append(row)
        page_offset, page_limit = normalize_page(offset, limit)
        set_pagination_headers(response, total=len(rows), offset=page_offset, limit=page_limit)
        return slice_rows(rows, page_offset, page_limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/devices")
async def admin_get_all_devices(
    response: Response,
    q: Optional[str] = None,
    station_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    connection_status: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Lấy tất cả devices từ DB"""
    try:
        query = select(model_config.Device)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            query = query.where(or_(model_config.Device.name.ilike(pattern), model_config.Device.device_code.ilike(pattern)))
        if station_id is not None:
            query = query.where(model_config.Device.station_id == station_id)
        if is_active is not None:
            query = query.where(model_config.Device.is_active.is_(is_active))
        sort_fields = {"id": model_config.Device.id, "name": model_config.Device.name, "device_code": model_config.Device.device_code, "created_at": model_config.Device.created_at}
        if sort:
            field = sort.lstrip("-")
            if field not in sort_fields:
                raise HTTPException(status_code=422, detail="Unsupported sort field")
            column = sort_fields[field]
            query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
        result = await db.execute(query)
        devices = result.scalars().all()
        station_rows = list((await db.execute(select(model_config.Station))).scalars().all())
        stations_by_id = {station.id: station for station in station_rows}
        now_ts = int(time.time())
        rows = []
        for d in devices:
            station = stations_by_id.get(d.station_id)
            runtime = _device_runtime_state(d, station, now_ts) if station else {
                "effective_status": "offline",
                "age_seconds": None,
                "offline_threshold_seconds": 300,
            }
            row = {
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "station_id": d.station_id,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "position": d.position,
                "is_active": d.is_active,
                "last_data_time": d.last_data_time,
                "config": d.config,
                "created_at": d.created_at,
                "updated_at": d.updated_at
            }
            row.update(runtime)
            if not connection_status or runtime["effective_status"] == connection_status.lower():
                rows.append(row)
        page_offset, page_limit = normalize_page(offset, limit)
        set_pagination_headers(response, total=len(rows), offset=page_offset, limit=page_limit)
        return slice_rows(rows, page_offset, page_limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/sensor-data")
async def admin_get_sensor_data(
    response: Response,
    offset: int = 0,
    limit: int = 500,
    station_id: Optional[int] = None,
    sensor_type: Optional[str] = None,
    cluster_key: Optional[str] = None,
    sort: str = "-timestamp",
    include_total: bool = True,
    include_data: bool = True,
    include_internal: bool = False,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Lấy sensor data gần nhất"""
    try:
        requested_sensor_type = sensor_type.strip().lower() if sensor_type and sensor_type.strip() else None
        if requested_sensor_type in INTERNAL_SENSOR_TYPES and not include_internal:
            raise HTTPException(
                status_code=422,
                detail="Internal GNSS streams belong to the dedicated adjustment dataset",
            )

        grouped_adjustments = requested_sensor_type == "gnss_adjusted" and not include_data
        cluster_project_id = cluster_index = None
        if cluster_key:
            if requested_sensor_type != "gnss_adjusted":
                raise HTTPException(status_code=422, detail="GNSS cluster filter requires gnss_adjusted")
            try:
                cluster_project_id, cluster_index = (int(value) for value in cluster_key.split(":", 1))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Invalid GNSS cluster filter")

        sensor_filters = []
        if station_id is not None:
            sensor_filters.append(model_data.SensorData.station_id == station_id)
        if requested_sensor_type:
            sensor_filters.append(model_data.SensorData.sensor_type == requested_sensor_type)
        elif not include_internal:
            sensor_filters.append(PUBLIC_SENSOR_FILTER)
        if grouped_adjustments:
            sensor_filters.append(model_data.SensorData.adjustment_key.is_not(None))
            if cluster_project_id is not None:
                sensor_filters.extend([
                    model_data.SensorData.adjustment_project_id == cluster_project_id,
                    model_data.SensorData.adjustment_cluster_index == cluster_index,
                ])
        query = select(model_data.SensorData).where(*sensor_filters)
        sort_fields = {"id": model_data.SensorData.id, "timestamp": model_data.SensorData.timestamp, "station_id": model_data.SensorData.station_id, "sensor_type": model_data.SensorData.sensor_type}
        field = sort.lstrip("-")
        if field not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")

        if grouped_adjustments:
            summary_query = select(
                model_data.SensorData.id,
                model_data.SensorData.station_id,
                model_data.SensorData.timestamp,
                model_data.SensorData.sensor_type,
                model_data.SensorData.value_1,
                model_data.SensorData.value_2,
                model_data.SensorData.value_3,
                model_data.SensorData.value_4,
                model_data.SensorData.value_5,
                model_data.SensorData.adjustment_project_id.label("project_id"),
                model_data.SensorData.adjustment_cluster_index.label("cluster_index"),
            ).where(*sensor_filters)

        page_offset, page_limit = normalize_page(offset, limit, max_limit=2000)
        total = None
        if include_total:
            count_query = (
                summary_query
                if grouped_adjustments
                else query
            )
            total = int((await db.execute(select(func.count()).select_from(count_query.subquery()))).scalar() or 0)
        if include_data:
            page_query = query
            column = sort_fields[field]
        elif grouped_adjustments:
            page_query = summary_query
            column = sort_fields[field]
        else:
            page_query = select(
                model_data.SensorData.id,
                model_data.SensorData.station_id,
                model_data.SensorData.timestamp,
                model_data.SensorData.sensor_type,
                model_data.SensorData.value_1,
                model_data.SensorData.value_2,
                model_data.SensorData.value_3,
                model_data.SensorData.value_4,
                model_data.SensorData.value_5,
            )
            page_query = page_query.where(*sensor_filters)
            column = sort_fields[field]

        fetch_limit = page_limit + 1 if not include_total else page_limit
        result = await db.execute(
            page_query.order_by(column.desc() if sort.startswith("-") else column.asc())
            .offset(page_offset)
            .limit(fetch_limit)
        )
        data = result.scalars().all() if include_data else result.all()
        has_more = not include_total and len(data) > page_limit
        if has_more:
            data = data[:page_limit]
        if total is not None:
            set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
        else:
            response.headers["X-Offset"] = str(page_offset)
            response.headers["X-Limit"] = str(page_limit)
            response.headers["X-Has-More"] = "true" if has_more else "false"

        rows = []
        for d in data:
            row = {
                "id": d.id,
                "station_id": d.station_id,
                "timestamp": d.timestamp,
                "sensor_type": d.sensor_type,
                "value_1": d.value_1,
                "value_2": d.value_2,
                "value_3": d.value_3,
                "value_4": d.value_4,
                "value_5": d.value_5,
            }
            if grouped_adjustments:
                row.update({
                    "project_id": _coerce_int(getattr(d, "project_id", None)),
                    "project_code": getattr(d, "project_code", None),
                    "cluster_index": _coerce_int(getattr(d, "cluster_index", None)),
                    "cluster_name": getattr(d, "cluster_name", None),
                    "computed_at": _coerce_int(
                        getattr(d, "computed_at", None),
                        getattr(d, "timestamp", None),
                    ),
                })
            if include_data:
                row["data"] = d.data
            else:
                # Do not fetch the JSON payload for list pages. GNSS adjustment
                # rows contain the complete network result; the detail endpoint
                # loads that payload only when a row is opened.
                source = getattr(d, "data_preview", None)
                if source is None and not grouped_adjustments:
                    source = getattr(d, "data", None)
                row["data_preview"] = _sensor_data_preview(source)
            rows.append(row)
        return rows
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sensor data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/sensor-data/{record_id}")
async def admin_get_sensor_data_record(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE)),
):
    record = (
        await db.execute(
            select(model_data.SensorData).where(model_data.SensorData.id == record_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Sensor data not found")
    return {
        "id": record.id,
        "station_id": record.station_id,
        "timestamp": record.timestamp,
        "sensor_type": record.sensor_type,
        "data": record.data,
        "value_1": record.value_1,
        "value_2": record.value_2,
        "value_3": record.value_3,
        "value_4": record.value_4,
        "value_5": record.value_5,
    }


@router.get("/api/admin/db/alerts")
async def admin_get_alerts(
    response: Response,
    offset: int = 0,
    limit: int = 200,
    station_id: Optional[int] = None,
    level: Optional[str] = None,
    is_resolved: Optional[bool] = None,
    sort: str = "-timestamp",
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_DATABASE))
):
    """Lấy alerts gần nhất"""
    try:
        query = select(model_data.Alert)
        if station_id is not None:
            query = query.where(model_data.Alert.station_id == station_id)
        if level:
            query = query.where(model_data.Alert.level == level.upper())
        if is_resolved is not None:
            query = query.where(model_data.Alert.is_resolved.is_(is_resolved))
        sort_fields = {"id": model_data.Alert.id, "timestamp": model_data.Alert.timestamp, "station_id": model_data.Alert.station_id, "level": model_data.Alert.level}
        field = sort.lstrip("-")
        if field not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        page_offset, page_limit = normalize_page(offset, limit, max_limit=1000)
        total = int((await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0)
        column = sort_fields[field]
        result = await db.execute(query.order_by(column.desc() if sort.startswith("-") else column.asc()).offset(page_offset).limit(page_limit))
        alerts = result.scalars().all()
        set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
        return [
            {
                "id": a.id,
                "station_id": a.station_id,
                "timestamp": a.timestamp,
                "level": a.level,
                "category": a.category,
                "message": a.message,
                "is_resolved": a.is_resolved
            }
            for a in alerts
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/db/simulations")
async def admin_get_simulations(
    response: Response,
    offset: int = 0,
    limit: int = 100,
    project_id: Optional[int] = None,
    station_id: Optional[int] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
    sort: str = "-id",
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS)),
):
    query = select(model_data.SimulationRun)
    if project_id is not None:
        query = query.where(model_data.SimulationRun.project_id == project_id)
    if station_id is not None:
        query = query.where(model_data.SimulationRun.station_id == station_id)
    if status:
        query = query.where(model_data.SimulationRun.status == status)
    if mode:
        query = query.where(model_data.SimulationRun.mode == mode)
    fields = {"id": model_data.SimulationRun.id, "created_at": model_data.SimulationRun.created_at}
    field = sort.lstrip("-")
    if field not in fields:
        raise HTTPException(status_code=422, detail="Unsupported sort field")
    page_offset, page_limit = normalize_page(offset, limit, max_limit=500)
    total = int((await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0)
    column = fields[field]
    rows = (await db.execute(query.order_by(column.desc() if sort.startswith("-") else column.asc()).offset(page_offset).limit(page_limit))).scalars().all()
    set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
    return [{"id": row.id, "display_name": row.display_name, "project_id": row.project_id, "project_code": row.project_code, "station_id": row.station_id, "station_code": row.station_code, "mode": row.mode, "status": row.status, "progress": row.progress, "summary": row.summary, "warnings": row.warnings, "engine_version": row.engine_version, "created_by_username": row.created_by_username, "created_at": row.created_at, "finished_at": row.finished_at} for row in rows]
