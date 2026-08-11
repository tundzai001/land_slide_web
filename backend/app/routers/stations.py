"""Station discovery, details, risk analysis and GNSS summaries."""
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth, schemas
from ..database import get_auth_db, get_config_db, get_data_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data
from ..models.pi_device import PiDevice
from ..runtime import analyzer, mqtt_service
from ..services.gnss_rollup import _utc_day_start
from ..services.access import get_optional_current_user_from_request, user_project_filter_ids
from ..services.station_policy import check_operator_project_access, get_offline_threshold
from ..services.pagination import normalize_page, set_pagination_headers, slice_rows

router = APIRouter(tags=["Stations"])
logger = logging.getLogger(__name__)


def is_offline_display_enabled(station_config: Optional[Dict[str, Any]]) -> bool:
    cfg = station_config or {}
    return bool(
        cfg.get("offline_display_enabled") is True
        or cfg.get("offline_display", {}).get("enabled") is True
    )

def calculate_station_location(sensors: dict, manual_location: dict = None):
    coords = []
    if sensors:
        for s_type, info in sensors.items():
            # Kiểm tra nếu sensor info có chứa lat/lon
            if isinstance(info, dict) and info.get('lat') is not None and info.get('lon') is not None:
                try:
                    coords.append({
                        "lat": float(info['lat']),
                        "lon": float(info['lon']),
                        "h": float(info.get('h', 0))
                    })
                except (ValueError, TypeError):
                    continue

    if not coords:
        return manual_location

    if len(coords) == 1:
        return {
            "lat": coords[0]['lat'],
            "lon": coords[0]['lon'],
            "h": coords[0]['h'],
            "source": "Single Sensor (Auto)"
        }
    else:
        avg_lat = sum(c['lat'] for c in coords) / len(coords)
        avg_lon = sum(c['lon'] for c in coords) / len(coords)
        avg_h = sum(c['h'] for c in coords) / len(coords)
        return {
            "lat": round(avg_lat, 8),
            "lon": round(avg_lon, 8),
            "h": round(avg_h, 3),
            "source": f"Average of {len(coords)} sensors"
        }


async def _load_station_runtime_maps(
    stations: List[model_config.Station],
    db_config: AsyncSession,
    db_data: AsyncSession,
):
    """Load station runtime state in bulk instead of querying per station/device."""
    station_ids = [int(station.id) for station in stations]
    if not station_ids:
        return defaultdict(list), {}, defaultdict(list)

    devices_result = await db_config.execute(
        select(model_config.Device).where(
            and_(
                model_config.Device.station_id.in_(station_ids),
                model_config.Device.is_active.is_(True),
            )
        )
    )
    devices_by_station = defaultdict(list)
    active_keys = set()
    for device in devices_result.scalars().all():
        devices_by_station[int(device.station_id)].append(device)
        active_keys.add((int(device.station_id), str(device.device_type)))

    cache_result = await db_data.execute(
        select(model_data.LatestSensorCache).where(
            model_data.LatestSensorCache.station_id.in_(station_ids)
        )
    )
    latest_by_key = {
        (int(row.station_id), str(row.sensor_type)): int(row.timestamp or 0)
        for row in cache_result.scalars().all()
    }

    # A cache miss is expected only during migration/recovery. Resolve every
    # missing station/sensor pair with one window query rather than N queries.
    missing_keys = active_keys.difference(latest_by_key)
    if missing_keys:
        missing_station_ids = sorted({key[0] for key in missing_keys})
        missing_sensor_types = sorted({key[1] for key in missing_keys})
        ranked = (
            select(
                model_data.SensorData.station_id.label("station_id"),
                model_data.SensorData.sensor_type.label("sensor_type"),
                model_data.SensorData.timestamp.label("timestamp"),
                func.row_number().over(
                    partition_by=(
                        model_data.SensorData.station_id,
                        model_data.SensorData.sensor_type,
                    ),
                    order_by=model_data.SensorData.timestamp.desc(),
                ).label("row_number"),
            )
            .where(
                and_(
                    model_data.SensorData.station_id.in_(missing_station_ids),
                    model_data.SensorData.sensor_type.in_(missing_sensor_types),
                )
            )
            .subquery()
        )
        fallback_result = await db_data.execute(
            select(ranked.c.station_id, ranked.c.sensor_type, ranked.c.timestamp).where(
                ranked.c.row_number == 1
            )
        )
        for station_id, sensor_type, timestamp in fallback_result.all():
            key = (int(station_id), str(sensor_type))
            if key in missing_keys:
                latest_by_key[key] = int(timestamp or 0)

    alerts_result = await db_data.execute(
        select(model_data.Alert).where(
            and_(
                model_data.Alert.station_id.in_(station_ids),
                model_data.Alert.is_resolved.is_(False),
            )
        )
    )
    alerts_by_station = defaultdict(list)
    for alert in alerts_result.scalars().all():
        alerts_by_station[int(alert.station_id)].append(alert)

    return devices_by_station, latest_by_key, alerts_by_station


def _summarize_station_alerts(
    alerts: List[model_data.Alert],
    station_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = station_config or {}
    alerting_cfg = config.get("alerting", {})
    if alerting_cfg.get("enabled", config.get("alerting_enabled", True)) is False:
        return {"overall_risk": "LOW", "active_alerts": []}

    default_ttl = {
        "gnss_velocity": max(90, get_offline_threshold(config, "gnss") * 2),
        "rainfall": max(120, get_offline_threshold(config, "rain") * 2),
        "water_level": max(120, get_offline_threshold(config, "water") * 2),
        "tilt": max(300, get_offline_threshold(config, "imu")),
        "tilt_warning": max(300, get_offline_threshold(config, "imu")),
        "tilt_critical": max(300, get_offline_threshold(config, "imu")),
        "shock": max(300, get_offline_threshold(config, "imu")),
    }
    ttl_cfg = config.get("alert_ttl_seconds", {}) or {}
    now_ts = int(time.time())
    fresh_alerts = [
        alert
        for alert in alerts
        if now_ts - int(alert.timestamp or 0)
        <= int(ttl_cfg.get(alert.category, default_ttl.get(alert.category, 180)))
    ]

    priority = {
        "EXTREME": 5,
        "CRITICAL": 4,
        "HIGH": 3,
        "WARNING": 2,
        "MEDIUM": 1,
        "LOW": 0,
    }
    overall_risk = "LOW"
    highest_score = -1
    for alert in fresh_alerts:
        level = str(alert.level or "").upper()
        if alert.category in {"tilt_warning", "tilt_critical", "shock", "tilt"} and level == "WARNING":
            level = "CRITICAL"
        score = priority.get(level, 0)
        if score > highest_score:
            overall_risk = level
            highest_score = score

    if overall_risk not in priority:
        overall_risk = "LOW"
    return {
        "overall_risk": overall_risk,
        "active_alerts": [
            {
                "level": alert.level,
                "category": alert.category,
                "message": alert.message,
                "timestamp": alert.timestamp,
            }
            for alert in fresh_alerts
        ],
    }

# ============================================================================
# RBAC HELPER: Check operator project access
# ============================================================================
@router.get("/api/admin/projects/{project_id}/stations")
async def get_stations_by_project(
    project_id: int,
    response: Response,
    q: Optional[str] = None,
    status: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    # Enforce operator project access
    check_operator_project_access(current_user, project_id)
    stmt = select(model_config.Station).where(model_config.Station.project_id == project_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(model_config.Station.name.ilike(pattern) | model_config.Station.station_code.ilike(pattern))
    sort_fields = {"name": model_config.Station.name, "station_code": model_config.Station.station_code, "created_at": model_config.Station.created_at}
    if sort:
        field_name = sort.lstrip("-")
        if field_name not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        column = sort_fields[field_name]
        stmt = stmt.order_by(column.desc() if sort.startswith("-") else column.asc())
    result = await db_config.execute(stmt)
    stations = result.scalars().all()
    devices_by_station, latest_by_key, _alerts_by_station = await _load_station_runtime_maps(
        stations, db_config, db_data
    )

    # Tính status động cho từng trạm
    current_time = int(time.time())

    stations_with_status = []
    for station in stations:
        devices = devices_by_station[int(station.id)]
        # Lấy danh sách devices của trạm
        # Kiểm tra status cho từng sensor type
        station_online = False

        for device in devices:
            sensor_type = device.device_type
            threshold = get_offline_threshold(station.config, sensor_type)

            # ✅ Ưu tiên lấy từ latest_sensor_cache
            latest_ts = latest_by_key.get((int(station.id), str(sensor_type)), 0)

            # Nếu có ít nhất 1 sensor online -> station online
            if latest_ts and (current_time - latest_ts) < threshold:
                station_online = True
                break

        offline_display_enabled = is_offline_display_enabled(station.config)
        computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")

        devices_list = []
        for d in devices:
            devices_list.append({
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic
            })

        stations_with_status.append({
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status,
            "config": station.config,
            "devices": devices_list
        })

    if status:
        normalized_status = status.strip().lower()
        if normalized_status not in {"online", "offline", "stale"}:
            raise HTTPException(status_code=422, detail="Unsupported status filter")
        stations_with_status = [row for row in stations_with_status if row["status"] == normalized_status]
    page_offset, page_limit = normalize_page(offset, limit)
    set_pagination_headers(response, total=len(stations_with_status), offset=page_offset, limit=page_limit)
    return slice_rows(stations_with_status, page_offset, page_limit)

@router.post("/api/admin/projects/{project_id}/stations", response_model=schemas.StationResponse)
async def create_station_in_project(
    project_id: int,
    station_data: schemas.StationCreate,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    # Enforce operator project access
    check_operator_project_access(current_user, project_id)
    try:
        # 1. Kiểm tra mã trạm
        exist = await db.execute(select(model_config.Station).where(model_config.Station.station_code == station_data.station_code))
        if exist.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Mã trạm đã tồn tại")

        # 2. TỰ ĐỘNG TÍNH TOẠ ĐỘ TRẠM
        final_location = calculate_station_location(station_data.sensors, station_data.location)

        # 3. Tạo trạm
        new_station = model_config.Station(
            station_code=station_data.station_code,
            name=station_data.name,
            project_id=project_id,
            location=final_location, # Dùng tọa độ đã tính toán
            status="offline",
            config=station_data.config or {},
            created_at=int(time.time()),
            updated_at=int(time.time())
        )
        db.add(new_station)
        await db.flush()

        # 4. Tạo thiết bị
        if station_data.sensors:
            for s_type, info in station_data.sensors.items():
                topic = info.get('topic', '').strip()
                if topic:
                    db.add(model_config.Device(
                        device_code=f"{new_station.station_code}_{s_type.upper()}",
                        name=f"{new_station.name} - {s_type.upper()}",
                        station_id=new_station.id,
                        device_type=s_type,
                        mqtt_topic=topic,
                        is_active=True,
                        config={"mqtt": info.get('mqtt')} if info.get('mqtt') else {},
                        created_at=int(time.time()),
                        updated_at=int(time.time())
                    ))

        await db.commit()
        await db.refresh(new_station)
        return new_station
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating station: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ADMIN - DEVICES API
# ============================================================================

# STATION DATA ENDPOINTS
# ============================================================================
@router.get("/api/public/dashboard-summary")
async def get_public_dashboard_summary(
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
):
    """Return small landing metrics without transferring every station."""
    stations = (await db_config.execute(select(model_config.Station))).scalars().all()
    devices_by_station, latest_by_key, _alerts = await _load_station_runtime_maps(
        stations, db_config, db_data
    )
    now = int(time.time())
    counts = {"total": len(stations), "online": 0, "offline": 0, "stale": 0}
    for station in stations:
        online = any(
            latest_by_key.get((int(station.id), str(device.device_type)), 0)
            and now - latest_by_key[(int(station.id), str(device.device_type))]
            < get_offline_threshold(station.config, device.device_type)
            for device in devices_by_station[int(station.id)]
        )
        if online:
            counts["online"] += 1
        elif is_offline_display_enabled(station.config):
            counts["stale"] += 1
        else:
            counts["offline"] += 1
    return {
        "stations": counts,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.get("/api/stations")
async def get_stations(
    request: Request,
    response: Response,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    risk: Optional[str] = None,
    bbox: Optional[str] = None,
    q: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    """
    ✅ Trả về danh sách tất cả các trạm với offline threshold tùy chỉnh
    """
    try:
        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)

        page_offset, page_limit = normalize_page(offset, limit)
        stmt = select(model_config.Station)
        if project_filter_ids is not None:
            if not project_filter_ids:
                set_pagination_headers(response, total=0, offset=page_offset, limit=page_limit)
                return []
            stmt = stmt.where(model_config.Station.project_id.in_(project_filter_ids))
        if project_id is not None:
            stmt = stmt.where(model_config.Station.project_id == project_id)
        normalized_q = (q or "").strip().lower()
        if normalized_q:
            pattern = f"%{normalized_q}%"
            stmt = stmt.where(
                model_config.Station.name.ilike(pattern)
                | model_config.Station.station_code.ilike(pattern)
            )

        sort_fields = {
            "name": model_config.Station.name,
            "station_code": model_config.Station.station_code,
            "created_at": model_config.Station.created_at,
            "updated_at": model_config.Station.updated_at,
        }
        sort_value = (sort or "").strip()
        descending = sort_value.startswith("-")
        sort_name = sort_value.lstrip("-")
        if sort_value and sort_name not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        if sort_name:
            column = sort_fields[sort_name]
            stmt = stmt.order_by(column.desc() if descending else column.asc())

        result = await db_config.execute(stmt)
        stations = result.scalars().all()
        devices_by_station, latest_by_key, alerts_by_station = await _load_station_runtime_maps(
            stations, db_config, db_data
        )

        current_time = int(time.time())

        stations_with_status = []
        for station in stations:
            devices = devices_by_station[int(station.id)]
            # ✅ Chỉ lấy devices ACTIVE
            # Kiểm tra status cho từng sensor type
            station_online = False

            for device in devices:
                sensor_type = device.device_type
                threshold = get_offline_threshold(station.config, sensor_type)

                # ✅ Ưu tiên lấy từ latest_sensor_cache (luôn cập nhật mỗi lần MQTT nhận data)
                latest_ts = latest_by_key.get((int(station.id), str(sensor_type)), 0)

                # Nếu có ít nhất 1 sensor online -> station online
                if latest_ts and (current_time - latest_ts) < threshold:
                    station_online = True
                    break

            # ✅ Tính risk_level thực tế từ alerts (không hardcode LOW nữa)
            risk_assessment = _summarize_station_alerts(
                alerts_by_station[int(station.id)], station.config
            )
            computed_risk = risk_assessment.get("overall_risk", "LOW")
            offline_display_enabled = is_offline_display_enabled(station.config)
            computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")

            stations_with_status.append({
                "id": station.id,
                "station_code": station.station_code,
                "name": station.name,
                "location": station.location,
                "status": computed_status,
                "offline_display_enabled": offline_display_enabled,
                "last_update": station.last_update,
                "risk_level": computed_risk
            })
        normalized_status = (status or "").strip().lower()
        if normalized_status:
            if normalized_status not in {"online", "offline", "stale"}:
                raise HTTPException(status_code=422, detail="Unsupported status filter")
            stations_with_status = [row for row in stations_with_status if row["status"] == normalized_status]
        normalized_risk = (risk or "").strip().upper()
        if normalized_risk:
            if normalized_risk not in {"LOW", "MEDIUM", "WARNING", "HIGH", "CRITICAL", "EXTREME"}:
                raise HTTPException(status_code=422, detail="Unsupported risk filter")
            stations_with_status = [row for row in stations_with_status if row["risk_level"] == normalized_risk]
        if bbox:
            try:
                west, south, east, north = (float(value.strip()) for value in bbox.split(","))
                if west > east or south > north:
                    raise ValueError
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="bbox must be west,south,east,north")
            def in_bbox(row):
                location = row.get("location") or {}
                try:
                    lat, lon = float(location["lat"]), float(location.get("lon", location.get("lng")))
                    return west <= lon <= east and south <= lat <= north
                except (KeyError, TypeError, ValueError):
                    return False
            stations_with_status = [row for row in stations_with_status if in_bbox(row)]

        total = len(stations_with_status)
        set_pagination_headers(response, total=total, offset=page_offset, limit=page_limit)
        return slice_rows(stations_with_status, page_offset, page_limit)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading stations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stations/{station_id}/history")
async def get_station_history(
    station_id: int,
    request: Request,
    sensor_types: str = Query("gnss,rain,water,imu"),
    hours: int = Query(24, ge=1, le=2160),
    limit: int = Query(500, ge=1, le=2000),
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    db_auth: AsyncSession = Depends(get_auth_db),
):
    station_result = await db_config.execute(
        select(model_config.Station).where(model_config.Station.id == station_id)
    )
    station = station_result.scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    current_user = await get_optional_current_user_from_request(request, db_auth)
    project_filter_ids = user_project_filter_ids(current_user)
    if project_filter_ids is not None and station.project_id not in project_filter_ids:
        raise HTTPException(status_code=403, detail="Station not allowed")

    allowed_types = {"gnss", "rain", "water", "imu", "gnss_adjusted"}
    requested_types = {
        value.strip().lower()
        for value in sensor_types.split(",")
        if value.strip().lower() in allowed_types
    }
    if not requested_types:
        raise HTTPException(status_code=400, detail="No valid sensor types requested")

    cutoff = int(time.time()) - int(hours * 3600)
    ranked = (
        select(
            model_data.SensorData.sensor_type.label("sensor_type"),
            model_data.SensorData.timestamp.label("timestamp"),
            model_data.SensorData.data.label("data"),
            func.row_number().over(
                partition_by=model_data.SensorData.sensor_type,
                order_by=model_data.SensorData.timestamp.desc(),
            ).label("row_number"),
        )
        .where(
            and_(
                model_data.SensorData.station_id == station_id,
                model_data.SensorData.sensor_type.in_(sorted(requested_types)),
                model_data.SensorData.timestamp >= cutoff,
            )
        )
        .subquery()
    )
    history_result = await db_data.execute(
        select(ranked.c.sensor_type, ranked.c.timestamp, ranked.c.data)
        .where(ranked.c.row_number <= limit)
        .order_by(ranked.c.sensor_type.asc(), ranked.c.timestamp.asc())
    )
    sensors = {sensor_type: {"history": []} for sensor_type in requested_types}
    for sensor_type, timestamp, data in history_result.all():
        sensors[str(sensor_type)]["history"].append(
            {"timestamp": int(timestamp), "data": data}
        )
    return {
        "station_id": station_id,
        "hours": hours,
        "limit_per_sensor": limit,
        "sensors": sensors,
    }


@router.get("/api/stations/{station_id}/detail")
async def get_station_detail(
    station_id: int,
    request: Request,
    include_history: bool = True,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    try:
        # 1. Lấy thông tin trạm từ Config DB
        result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()

        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)
        if project_filter_ids is not None and station.project_id not in project_filter_ids:
            raise HTTPException(status_code=403, detail="Station not allowed")

        # 2. Lấy devices của trạm
        devices_result = await db_config.execute(
            select(model_config.Device).where(
                and_(
                    model_config.Device.station_id == station_id,
                    model_config.Device.is_active == True
                )
            )
        )
        devices = devices_result.scalars().all()

        # 3. Lấy dữ liệu mới nhất từ Data DB (24h gần nhất)
        cutoff_time = int(time.time()) - 86400  # 24h ago

        sensor_data = {}
        device_sensor_types = list({device.device_type for device in devices})
        latest_cache_by_type = {}
        if device_sensor_types:
            cache_rows_result = await db_data.execute(
                select(model_data.LatestSensorCache).where(
                    and_(
                        model_data.LatestSensorCache.station_id == station_id,
                        model_data.LatestSensorCache.sensor_type.in_(device_sensor_types),
                    )
                )
            )
            latest_cache_by_type = {
                row.sensor_type: row for row in cache_rows_result.scalars().all()
            }
        has_recent_data = False
        latest_data_timestamp = 0
        station_online = False  # Flag để kiểm tra trạm có online không

        for device in devices:
            sensor_type = device.device_type

            # ✅ Ưu tiên lấy từ latest_sensor_cache (luôn cập nhật mỗi lần MQTT nhận data)
            cached = latest_cache_by_type.get(sensor_type)

            # Fallback: nếu cache chưa có (server mới khởi động) thì lấy từ sensor_data
            if not cached:
                latest_result = await db_data.execute(
                    select(model_data.SensorData)
                    .where(
                        and_(
                            model_data.SensorData.station_id == station_id,
                            model_data.SensorData.sensor_type == sensor_type
                        )
                    )
                    .order_by(desc(model_data.SensorData.timestamp))
                    .limit(1)
                )
                latest_row = latest_result.scalar_one_or_none()
                latest_data = latest_row.data if latest_row else None
                latest_ts = latest_row.timestamp if latest_row else None
            else:
                latest_data = cached.data
                latest_ts = cached.timestamp

            # ✅ Lấy offline threshold riêng cho sensor này
            threshold = get_offline_threshold(station.config, sensor_type)
            current_time = int(time.time())

            # Check xem sensor này có online không (dựa trên ts mới nhất thực sự)
            if latest_ts and (current_time - latest_ts) < threshold:
                station_online = True  # Chỉ cần 1 sensor online là trạm online
                has_recent_data = True
                if latest_ts > latest_data_timestamp:
                    latest_data_timestamp = latest_ts

            # Lấy lịch sử 24h
            history = []
            if include_history:
                history_result = await db_data.execute(
                    select(model_data.SensorData)
                    .where(
                        and_(
                            model_data.SensorData.station_id == station_id,
                            model_data.SensorData.sensor_type == sensor_type,
                            model_data.SensorData.timestamp >= cutoff_time
                        )
                    )
                    .order_by(desc(model_data.SensorData.timestamp))
                    .limit(500)
                )
                history = history_result.scalars().all()
                if sensor_type == 'gnss':
                    history = [
                        h for h in history
                        if isinstance(h.data, dict)
                        and (
                            h.data.get('speed_2d_mm_s') is not None
                            or (h.data.get('vel_e') is not None and h.data.get('vel_n') is not None)
                        )
                    ]

            # ✅ Per-sensor online check (dựa trên cache timestamp)
            sensor_is_online = bool(latest_ts and (current_time - latest_ts) < threshold)

            # ✅ Sửa lỗi "ảo": Tự động bù đắp dữ liệu Advanced cho trạm Offline/Dữ liệu cũ
            if sensor_type == 'gnss' and latest_data and 'adv_x' not in latest_data:
                latest_data = dict(latest_data) # Clone to modify
                latest_data['adv_x'] = latest_data.get('pos_e', latest_data.get('lon', 0.0))
                latest_data['adv_y'] = latest_data.get('pos_n', latest_data.get('lat', 0.0))
                latest_data['adv_h'] = latest_data.get('pos_u', latest_data.get('h', 0.0))
                latest_data['adv_dx'] = 0.0
                latest_data['adv_dy'] = 0.0
                latest_data['adv_dh'] = 0.0
                latest_data['adv_vdx'] = 0.0
                latest_data['adv_vdy'] = 0.0
                latest_data['adv_vdh'] = 0.0

            sensor_data[sensor_type] = {
                "is_online": sensor_is_online,
                "latest": latest_data,
                "latest_timestamp": latest_ts,
                "history": [
                    {
                        "timestamp": h.timestamp,
                        "data": h.data
                    }
                    for h in reversed(history)
                ]
            }

        # 3.5. Fetch latest gnss_adjusted data from LatestSensorCache
        try:
            adj_cache_res = await db_data.execute(
                select(model_data.LatestSensorCache)
                .where(
                    and_(
                        model_data.LatestSensorCache.station_id == station_id,
                        model_data.LatestSensorCache.sensor_type == 'gnss_adjusted'
                    )
                )
            )
            adj_cached = adj_cache_res.scalar_one_or_none()
            if adj_cached:
                sensor_data["gnss_adjusted"] = {
                    "is_online": True,
                    "latest": adj_cached.data,
                    "latest_timestamp": adj_cached.timestamp,
                    "history": []
                }
        except Exception as adj_load_e:
            logger.error(f"Error loading cached gnss_adjusted for station {station_id}: {adj_load_e}")

        # ✅ Tính status dựa trên offline threshold tùy chỉnh
        offline_display_enabled = is_offline_display_enabled(station.config)
        computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")

        # 4. Tính risk assessment
        risk_assessment = await _calculate_station_risk_assessment(
            db_data,
            station_id,
            station.config
        )

        # 4.5 Lấy Pi devices gắn với trạm (pi_point, pi_center)
        pi_devices_status = []
        try:
            pi_result = await db_config.execute(
                select(PiDevice).where(PiDevice.station_id == station_id)
            )
            pi_devs = pi_result.scalars().all()
            PI_ONLINE_THRESHOLD = 300  # 5 phút
            for pd in pi_devs:
                is_online = (current_time - (pd.last_seen or 0)) < PI_ONLINE_THRESHOLD
                pi_devices_status.append({
                    "id": pd.id,
                    "serial": pd.serial,
                    "name": pd.name,
                    "device_type": pd.device_type,
                    "is_online": is_online,
                    "last_seen": pd.last_seen,
                    "is_locked": pd.is_locked
                })
        except Exception as e:
            logger.error(f"Error fetching Pi devices for station {station_id}: {e}")

        # 5. Trả về response
        mqtt_connected = False
        try:
            mqtt_connected = bool(mqtt_service.client.is_connected())
        except Exception:
            mqtt_connected = False

        return {
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "project_id": station.project_id,
            "status": computed_status,
            "offline_display_enabled": offline_display_enabled,
            "offline_display": {"enabled": offline_display_enabled},
            "mqtt_connected": mqtt_connected,
            "last_update": latest_data_timestamp if has_recent_data else station.last_update,
            "config": station.config,
            "sensors": sensor_data,
            "risk_assessment": risk_assessment,
            "pi_devices": pi_devices_status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading station detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def _calculate_station_risk_assessment(
    db_data: AsyncSession,
    station_id: int,
    station_config: Optional[Dict[str, Any]] = None
) -> Dict:
    """Helper: Tính toán risk assessment từ unresolved alerts còn hiệu lực thời gian."""
    try:
        now_ts = int(time.time())
        alerting_cfg = (station_config or {}).get("alerting", {}) if station_config else {}
        if alerting_cfg.get("enabled", (station_config or {}).get("alerting_enabled", True)) is False:
            return {"overall_risk": "LOW", "active_alerts": []}

        gnss_offline = get_offline_threshold(station_config or {}, 'gnss')
        rain_offline = get_offline_threshold(station_config or {}, 'rain')
        water_offline = get_offline_threshold(station_config or {}, 'water')
        imu_offline = get_offline_threshold(station_config or {}, 'imu')

        # Chỉ tính alert còn "tươi" để tránh kẹt WARNING/CRITICAL khi sensor đã ngừng gửi.
        default_ttl = {
            'gnss_velocity': max(90, gnss_offline * 2),
            'rainfall': max(120, rain_offline * 2),
            'water_level': max(120, water_offline * 2),
            'tilt': max(300, imu_offline),
            'tilt_warning': max(300, imu_offline),
            'tilt_critical': max(300, imu_offline),
            'shock': max(300, imu_offline),
        }
        ttl_cfg = (station_config or {}).get('alert_ttl_seconds', {}) if station_config else {}
        alert_ttl = {
            'gnss_velocity': int(ttl_cfg.get('gnss_velocity', default_ttl['gnss_velocity'])),
            'rainfall': int(ttl_cfg.get('rainfall', default_ttl['rainfall'])),
            'water_level': int(ttl_cfg.get('water_level', default_ttl['water_level'])),
            'tilt': int(ttl_cfg.get('tilt', default_ttl['tilt'])),
            'tilt_warning': int(ttl_cfg.get('tilt_warning', default_ttl['tilt_warning'])),
            'tilt_critical': int(ttl_cfg.get('tilt_critical', default_ttl['tilt_critical'])),
            'shock': int(ttl_cfg.get('shock', default_ttl['shock'])),
        }

        result = await db_data.execute(
            select(model_data.Alert).where(
                and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.is_resolved == False
                )
            )
        )
        alerts = result.scalars().all()

        # Lọc alert hết hạn theo category-specific TTL.
        fresh_alerts = []
        for a in alerts:
            ttl = alert_ttl.get(a.category, 180)
            if (now_ts - int(a.timestamp or 0)) <= ttl:
                fresh_alerts.append(a)

        # Dùng logic max-level giống mqtt_bridge._get_station_active_alert_summary()
        # để WebSocket và REST API trả về cùng giá trị risk_level.
        priority = {
            "EXTREME": 5,
            "CRITICAL": 4,
            "HIGH": 3,
            "WARNING": 2,
            "MEDIUM": 1,
            "LOW": 0,
        }
        overall_risk = "LOW"
        highest_score = -1
        for a in fresh_alerts:
            level = str(a.level or "").upper()
            if a.category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and level == 'WARNING':
                level = 'CRITICAL'
            score = priority.get(level, 0)
            if score > highest_score:
                overall_risk = level
                highest_score = score

        if overall_risk not in priority:
            overall_risk = "LOW"

        return {
            "overall_risk": overall_risk,
            "active_alerts": [
                {
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "timestamp": a.timestamp
                }
                for a in fresh_alerts
            ]
        }
    except Exception as e:
        logger.error(f"Error calculating risk: {e}")
        return {"overall_risk": "UNKNOWN", "active_alerts": []}

# ============================================================================
# LONG-TERM ANALYSIS ENDPOINT
# ============================================================================
@router.get("/api/stations/{station_id}/long-term-analysis")
async def get_long_term_analysis(
    station_id: int,
    days: float = 30.0,
    include_correlation: bool = False,
    correlation_model: str = "slide_model",
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    """
    Phân tích dài hạn cho GNSS displacement + IMU tilt.
    Rainfall correlation chỉ chạy khi include_correlation=True.
    correlation_model hiện hỗ trợ: slide_model.
    + Multi-window analysis + Inverse Velocity (Fukuzono)
    """
    try:
        def is_gnss_analysis_point(data: dict) -> bool:
            if not isinstance(data, dict):
                return False
            return all(key in data for key in ("pos_e", "pos_n", "pos_u"))

        def _trend_from_velocity_series(values: List[float]) -> str:
            clean = [float(v or 0.0) for v in values]
            if len(clean) < 2:
                return "stable"
            first_v = clean[0]
            last_v = clean[-1]
            if abs(first_v) < 1e-6 and abs(last_v) < 1e-6:
                return "stable"
            if abs(first_v) < 1e-6:
                return "accelerating" if last_v > 0 else "stable"
            ratio = (last_v - first_v) / (abs(first_v) + 1e-6)
            if ratio > 0.1:
                return "accelerating"
            if ratio < -0.1:
                return "decelerating"
            return "stable"

        def _severity(level: str) -> int:
            order = {
                "INFO": 0,
                "LOW": 1,
                "MEDIUM": 2,
                "HIGH": 3,
                "CRITICAL": 4,
                "EXTREME": 5,
            }
            return order.get(str(level or "").upper(), 0)

        def _build_gnss_analysis_from_daily_summaries(
            daily_rows: List[model_data.GnssDailySummary],
            station_cfg: Dict[str, Any]
        ) -> Dict[str, Any]:
            if not daily_rows:
                return {
                    "status": "insufficient_data",
                    "message": "Không có GNSS daily summary trong khoảng thời gian yêu cầu."
                }

            rows = sorted(daily_rows, key=lambda r: int(r.day_start_ts or 0))
            total_displacement_mm = float(sum(float(r.net_displacement_mm or 0.0) for r in rows))
            duration_seconds = int(sum(int(r.duration_seconds or 0) for r in rows))
            duration_days = duration_seconds / 86400.0 if duration_seconds > 0 else float(len(rows))
            if duration_days <= 0:
                duration_days = float(len(rows))

            velocity_mm_per_day = total_displacement_mm / duration_days if duration_days > 0 else 0.0
            velocity_mm_per_second = velocity_mm_per_day / 86400.0
            velocity_mm_per_year = velocity_mm_per_day * 365.0

            classification = analyzer._classify_velocity_extended(
                velocity_mm_per_second,
                velocity_mm_per_day,
                velocity_mm_per_year,
                station_cfg or {}
            )

            min_reliable_duration_days = analyzer._get_gnss_min_reliable_window_days(station_cfg or {})
            data_points_used = int(sum(int(r.sample_count or 0) for r in rows))
            reliability_points = data_points_used if data_points_used > 0 else len(rows)
            velocity_reliable = analyzer._is_reliable_observation_window(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )
            reliability_message = analyzer._build_gnss_preliminary_message(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )

            trend = _trend_from_velocity_series([float(r.velocity_mm_day or 0.0) for r in rows])
            derived_risk = _map_gnss_daily_risk(classification)
            max_row_risk = "LOW"
            for r in rows:
                row_risk = str(r.risk_level or "LOW").upper()
                if _severity(row_risk) > _severity(max_row_risk):
                    max_row_risk = row_risk
            risk_level = max_row_risk if _severity(max_row_risk) >= _severity(derived_risk) else derived_risk

            if risk_level in ("CRITICAL", "EXTREME"):
                warning_message = f"🚨 Cảnh báo cao từ GNSS daily summary ({classification})."
            elif risk_level == "HIGH":
                warning_message = f"⚠️ Cảnh báo: vận tốc có xu hướng tăng ({classification})."
            elif risk_level == "MEDIUM":
                warning_message = f"Cần theo dõi: GNSS có chuyển dịch mức trung bình ({classification})."
            else:
                warning_message = f"An toàn tương đối theo GNSS daily summary ({classification})."

            if not velocity_reliable:
                warning_message = reliability_message
                risk_level = "INFO"

            labels = []
            displacement_series = []
            cumulative_disp = 0.0
            for row in rows:
                labels.append(datetime.fromtimestamp(int(row.day_start_ts)).strftime('%d/%m'))
                cumulative_disp += float(row.net_displacement_mm or 0.0)
                displacement_series.append(round(cumulative_disp, 2))

            return {
                "status": "success",
                "source": "daily_summary_rollup",
                "analysis": {
                    "total_displacement_mm": round(total_displacement_mm, 2),
                    "net_displacement_mm": round(total_displacement_mm, 2),
                    "regression_displacement_mm": round(total_displacement_mm, 2),
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_ci_95": 0.0,
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "regression_velocity_mm_year": round(velocity_mm_per_year, 2),
                    "regression_velocity_mm_day": round(velocity_mm_per_day, 4),
                    "regression_velocity_mm_second": round(velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "cusum_change": False,
                    "cusum_message": "Daily summary mode: không chạy CUSUM trên raw sample.",
                    "displacement_basis": "daily_rollup_sum",
                    "velocity_reliable": velocity_reliable,
                    "reliability_message": reliability_message,
                    "min_reliable_duration_days": round(min_reliable_duration_days, 4),
                    "min_reliable_points": 3,
                    "duration_days": round(duration_days, 4),
                    "data_points_used": data_points_used,
                    "summary_days_used": len(rows),
                    "start_date": datetime.fromtimestamp(int(rows[0].day_start_ts)).isoformat(),
                    "end_date": datetime.fromtimestamp(int(rows[-1].day_end_ts)).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning_message,
                "inverse_velocity": {
                    "available": False,
                    "message": "Daily summary mode: inverse velocity cần raw GNSS chi tiết."
                },
                "time_series": {
                    "labels": labels,
                    "displacement": displacement_series,
                    "e": [],
                    "n": [],
                    "u": []
                }
            }

        # 1. Lấy config trạm
        station_result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()

        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        # Lấy window lớn nhất cho multi-window (tối thiểu = days, mở rộng 90 ngày)
        max_window = max(days, 90)
        cutoff_time = int(time.time() - (max_window * 86400))
        cutoff_requested = int(time.time() - (days * 86400))
        raw_gnss_cutoff = max(cutoff_time, int(time.time() - 86400))

        # 2. Lấy dữ liệu GNSS (mở rộng window cho multi-window)
        gnss_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "gnss",
                    model_data.SensorData.timestamp >= raw_gnss_cutoff
                )
            )
            .order_by(model_data.SensorData.timestamp.desc())
            .limit(10000)
        )
        gnss_data = list(reversed(gnss_result.scalars().all()))

        # 2b. Lấy GNSS daily summary để fallback khi raw đã purge
        daily_summary_result = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_start_ts >= _utc_day_start(cutoff_time),
                    model_data.GnssDailySummary.status == "success"
                )
            )
            .order_by(model_data.GnssDailySummary.day_start_ts.asc())
        )
        daily_gnss_full = daily_summary_result.scalars().all()
        daily_gnss_requested = [
            d for d in daily_gnss_full
            if int(d.day_start_ts or 0) >= _utc_day_start(cutoff_requested)
        ]

        # 3. Lấy dữ liệu IMU
        imu_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "imu",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        imu_data = imu_result.scalars().all()

        # 4. Lấy dữ liệu mưa (cho rainfall-displacement correlation)
        rain_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "rain",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        rain_data = rain_result.scalars().all()

        model_key = str(correlation_model or "slide_model").strip().lower()
        result = {
            "station_id": station_id,
            "days": days,
            "correlation_model": model_key
        }

        # Chuyển sang list dict chung
        historical_gnss_full = [
            {"timestamp": d.timestamp, "data": d.data}
            for d in gnss_data
            if is_gnss_analysis_point(d.data)
        ]
        historical_gnss_requested = [p for p in historical_gnss_full if p['timestamp'] >= cutoff_requested]
        if days > 1 and daily_gnss_requested:
            historical_gnss_requested = []
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_gnss_requested) < 2 and len(historical_gnss_full) >= 2 and days <= 1:
            historical_gnss_requested = historical_gnss_full[-20:]

        # 5. Phân tích GNSS (trên window requested)
        if len(historical_gnss_requested) >= 2:
            gnss_analysis = analyzer.analyze_long_term_velocity(
                station_id=station_id,
                historical_data=historical_gnss_requested,
                config=station.config or {},
                window_days=days
            )

            # Tạo time-series GNSS (trung bình theo ngày/giờ) cho chart & 3D
            if gnss_analysis.get("status") == "success":
                from collections import OrderedDict
                from datetime import datetime as dt
                daily_gnss = OrderedDict()

                if days < 1/24:    fmt = '%H:%M:%S'
                elif days <= 1:    fmt = '%H:%M'
                elif days <= 7:    fmt = '%d/%m %H:00'
                else:              fmt = '%d/%m'

                first_e, first_n, first_u = None, None, None

                for point in historical_gnss_requested:
                    day_key = dt.fromtimestamp(point['timestamp']).strftime(fmt)
                    data = point['data']

                    disp = data.get('total_displacement_mm', data.get('displacement_mm', 0))
                    e = data.get('pos_e', 0)
                    n = data.get('pos_n', 0)
                    u = data.get('pos_u', 0)

                    if first_e is None:
                        first_e, first_n, first_u = e, n, u

                    if day_key not in daily_gnss:
                        daily_gnss[day_key] = {'disp': [], 'e': [], 'n': [], 'u': []}

                    daily_gnss[day_key]['disp'].append(float(disp))
                    delta_e_mm = (e - first_e) * 1000
                    delta_n_mm = (n - first_n) * 1000
                    delta_u_mm = (u - first_u) * 1000

                    daily_gnss[day_key]['e'].append(delta_e_mm)
                    daily_gnss[day_key]['n'].append(delta_n_mm)
                    daily_gnss[day_key]['u'].append(delta_u_mm)

                gnss_analysis["time_series"] = {
                    "labels": list(daily_gnss.keys()),
                    "displacement": [round(sum(v['disp']) / len(v['disp']), 2) for v in daily_gnss.values()],
                    "e": [round(sum(v['e']) / len(v['e']), 2) for v in daily_gnss.values()],
                    "n": [round(sum(v['n']) / len(v['n']), 2) for v in daily_gnss.values()],
                    "u": [round(sum(v['u']) / len(v['u']), 2) for v in daily_gnss.values()]
                }

            result["gnss"] = gnss_analysis
        elif len(daily_gnss_requested) >= 1:
            result["gnss"] = _build_gnss_analysis_from_daily_summaries(
                daily_rows=daily_gnss_requested,
                station_cfg=station.config or {}
            )
        else:
            result["gnss"] = {
                "status": "insufficient_data",
                "message": f"Không đủ dữ liệu GNSS raw ({len(historical_gnss_requested)} điểm) và chưa có daily summary trong cửa sổ {days} ngày."
            }

        # 6. Phân tích IMU
        historical_imu_full = [{"timestamp": d.timestamp, "data": d.data} for d in imu_data]
        historical_imu_requested = [p for p in historical_imu_full if p['timestamp'] >= cutoff_requested]
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_imu_requested) < 2 and len(historical_imu_full) >= 2 and days <= 1:
            historical_imu_requested = historical_imu_full[-60:]

        if len(historical_imu_requested) >= 2:
            imu_analysis = analyzer.analyze_long_term_tilt(
                station_id=station_id,
                historical_data=historical_imu_requested,
                window_days=days
            )

            # Format X-axis for IMU exactly like GNSS
            if imu_analysis.get("status") == "success" and "time_series" in imu_analysis:
                from collections import OrderedDict
                from datetime import datetime as dt
                fmt = '%H:%M:%S' if days < 1/24 else '%H:%M' if days <= 1 else '%d/%m %H:00' if days <= 7 else '%d/%m'

                daily_imu = OrderedDict()
                for ts, r, p in zip(imu_analysis["time_series"]["raw_timestamps"], imu_analysis["time_series"]["rolls"], imu_analysis["time_series"]["pitches"]):
                    day_key = dt.fromtimestamp(ts).strftime(fmt)
                    if day_key not in daily_imu:
                        daily_imu[day_key] = {'rolls': [], 'pitches': []}
                    daily_imu[day_key]['rolls'].append(r)
                    daily_imu[day_key]['pitches'].append(p)

                imu_analysis["time_series"]["labels"] = list(daily_imu.keys())
                imu_analysis["time_series"]["rolls"] = [round(sum(v['rolls']) / len(v['rolls']), 2) for v in daily_imu.values()]
                imu_analysis["time_series"]["pitches"] = [round(sum(v['pitches']) / len(v['pitches']), 2) for v in daily_imu.values()]

            result["imu"] = imu_analysis
        else:
            result["imu"] = {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu IMU. Hiện có: {len(historical_imu_requested)}"
            }

        # 7. Phân tích tương quan Mưa - Dịch chuyển (chạy theo yêu cầu)
        if include_correlation:
            if model_key != "slide_model":
                raise HTTPException(status_code=400, detail="Unsupported correlation_model. Use slide_model.")

            # Nếu raw GNSS đã bị purge, dựng pseudo-GNSS từ daily summary
            gnss_for_correlation = historical_gnss_requested
            if len(gnss_for_correlation) < 2 and len(daily_gnss_requested) >= 2:
                logger.info(f"[Slide model] Raw GNSS insufficient ({len(historical_gnss_requested)} pts). "
                            f"Synthesizing from {len(daily_gnss_requested)} daily summaries.")
                cumulative_mm = 0.0
                gnss_for_correlation = []
                for row in sorted(daily_gnss_requested, key=lambda r: int(r.day_start_ts or 0)):
                    ts = int(row.day_start_ts or 0) + 43200  # giữa ngày (12h)
                    cumulative_mm += float(row.net_displacement_mm or 0.0)
                    # Dựng pseudo pos_e = cumulative (m), pos_n=0, pos_u=0
                    gnss_for_correlation.append({
                        "timestamp": ts,
                        "data": {
                            "pos_e": cumulative_mm / 1000.0,
                            "pos_n": 0.0,
                            "pos_u": 0.0
                        }
                    })

            if len(gnss_for_correlation) >= 2 and len(rain_data) >= 2:
                historical_rain = [{"timestamp": d.timestamp, "data": d.data} for d in rain_data]
                rain_correlation = analyzer.analyze_rainfall_displacement_correlation(
                    gnss_data=gnss_for_correlation,
                    rain_data=historical_rain,
                    window_days=days,
                    config=station.config or {}
                )
                rain_correlation["model"] = "slide_model"
                result["rainfall_correlation"] = rain_correlation
            else:
                gnss_count = len(gnss_for_correlation)
                rain_count = len(rain_data)
                result["rainfall_correlation"] = {
                    "available": False,
                    "model": "slide_model",
                    "message": f"Cần cả dữ liệu GNSS và mưa để phân tích tương quan. "
                               f"Hiện có: {gnss_count} điểm GNSS, {rain_count} bản ghi mưa."
                }
        else:
            result["rainfall_correlation"] = {
                "available": False,
                "model": "slide_model",
                "message": "Chưa chạy phân tích tương quan Slide model. Nhấn 'Chạy AI Slide model' để thực hiện."
            }

        # 8. Phân tích đa cửa sổ (Multi-Window) - dùng full GNSS data
        if len(historical_gnss_full) >= 2:
            multi_window = analyzer.analyze_multi_window(
                station_id=station_id,
                historical_data=historical_gnss_full,
                config=station.config or {},
                windows=[7, 30, 90]
            )
            result["multi_window"] = multi_window
        else:
            result["multi_window"] = {"available": False, "message": "Không đủ dữ liệu."}

        # 9. Overall status
        gnss_ok = result["gnss"].get("status") == "success"
        imu_ok = result["imu"].get("status") == "success"
        multi_window_ok = result.get("multi_window", {}).get("available") is True
        rainfall_ok = result.get("rainfall_correlation", {}).get("available") is True

        if gnss_ok or imu_ok or multi_window_ok or rainfall_ok:
            result["status"] = "success"
        else:
            result["status"] = "insufficient_data"
            result["message"] = "Không đủ dữ liệu GNSS và IMU để phân tích."

        # 10. Cross-sensor consensus — đánh giá đồng thuận giữa các model
        result["cross_sensor_consensus"] = analyzer.analyze_cross_sensor_consensus(
            gnss_result=result.get("gnss", {}),
            imu_result=result.get("imu", {}),
            rain_corr_result=result.get("rainfall_correlation", {})
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in long-term analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stations/{station_id}/gnss-daily-summary")
async def get_gnss_daily_summary(
    station_id: int,
    limit: int = 30,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo ngày (đã rollup)."""
    try:
        n = max(1, min(int(limit), 365))
        res = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(model_data.GnssDailySummary.station_id == station_id)
            .order_by(model_data.GnssDailySummary.day_start_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "day_start_ts": r.day_start_ts,
                    "day_end_ts": r.day_end_ts,
                    "sample_count": r.sample_count,
                    "duration_seconds": r.duration_seconds,
                    "net_displacement_mm": r.net_displacement_mm,
                    "velocity_mm_day": r.velocity_mm_day,
                    "velocity_mm_second": r.velocity_mm_second,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching GNSS daily summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stations/{station_id}/gnss-weekly-summary")
async def get_gnss_weekly_summary(
    station_id: int,
    limit: int = 12,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo tuần (từ 7 daily summaries liên tiếp)."""
    try:
        n = max(1, min(int(limit), 104))
        res = await db_data.execute(
            select(model_data.GnssWeeklySummary)
            .where(model_data.GnssWeeklySummary.station_id == station_id)
            .order_by(model_data.GnssWeeklySummary.week_end_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "week_start_ts": r.week_start_ts,
                    "week_end_ts": r.week_end_ts,
                    "day_count": r.day_count,
                    "total_displacement_mm": r.total_displacement_mm,
                    "avg_velocity_mm_day": r.avg_velocity_mm_day,
                    "max_velocity_mm_day": r.max_velocity_mm_day,
                    "min_velocity_mm_day": r.min_velocity_mm_day,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching GNSS weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
