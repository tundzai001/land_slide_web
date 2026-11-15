"""Station listing, detail, history, and project query routes."""

import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.shared.sensor_catalog import SENSOR_CATALOG
from app.shared.sensor_catalog import is_custom_sensor
from app.shared.custom_sensors import validate_custom_sensor_selection
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth, schemas
from ...database import get_auth_db, get_config_db, get_data_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...models import data as model_data
from ...models.pi_device import PiDevice
from ...runtime import mqtt_service
from ...shared.access import get_optional_current_user_from_request, user_project_filter_ids
from ...shared.pagination import normalize_page, set_pagination_headers, slice_rows
from ...shared.project_location import refresh_project_map_position
from ...shared.station_policy import check_operator_project_access, get_offline_threshold
from .analysis_router import _calculate_station_risk_assessment
from .common import (
    _device_activity_timestamp,
    _load_station_runtime_maps,
    _station_detail_adjustment_latest,
    _summarize_station_alerts,
    calculate_station_location,
    is_offline_display_enabled,
)
from .history_query import build_sensor_history_query, history_payload
from .topics import duplicate_mqtt_topics, find_mqtt_topic_conflicts, normalize_mqtt_topic

router = APIRouter(tags=["Stations"])
logger = logging.getLogger(__name__)

STATION_REQUEST_FAILED_DETAIL = "Unable to complete station request"

@router.get("/api/admin/projects/{project_id}/stations")
async def get_stations_by_project(
    project_id: int,
    response: Response,
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    include_runtime: bool = Query(True),
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_STATIONS))
):
    # Enforce operator project access
    check_operator_project_access(current_user, project_id)
    stmt = select(model_config.Station).where(model_config.Station.project_id == project_id)
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(model_config.Station.name.icontains(term, autoescape=True)
                          | model_config.Station.station_code.icontains(term, autoescape=True))
    sort_fields = {"name": model_config.Station.name, "station_code": model_config.Station.station_code, "created_at": model_config.Station.created_at}
    if sort:
        field_name = sort.lstrip("-")
        if field_name not in sort_fields:
            raise HTTPException(status_code=422, detail="Unsupported sort field")
        column = sort_fields[field_name]
        stmt = stmt.order_by(column.desc() if sort.startswith("-") else column.asc())
    result = await db_config.execute(stmt)
    stations = result.scalars().all()
    if include_runtime:
        devices_by_station, latest_by_key, _alerts_by_station = await _load_station_runtime_maps(
            stations, db_config, db_data
        )
    else:
        station_ids = [int(station.id) for station in stations]
        devices_by_station = defaultdict(list)
        if station_ids:
            device_result = await db_config.execute(
                select(model_config.Device).where(model_config.Device.station_id.in_(station_ids))
            )
            for device in device_result.scalars().all():
                devices_by_station[int(device.station_id)].append(device)
        latest_by_key = {}

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
        computed_status = (
            "online" if station_online else ("stale" if offline_display_enabled else "offline")
        ) if include_runtime else str(station.status or "offline")

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


@router.get("/api/admin/devices/topic-availability")
async def get_mqtt_topic_availability(
    topic: str = Query(..., min_length=1, max_length=255),
    exclude_station_id: Optional[int] = None,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
):
    normalized = normalize_mqtt_topic(topic)
    conflicts = await find_mqtt_topic_conflicts(db, [normalized], exclude_station_id)
    conflict = conflicts[0] if conflicts else None
    return {
        "topic": normalized,
        "available": conflict is None,
        "conflict": None if conflict is None else {
            "device_code": conflict.device_code,
            "station_id": conflict.station_id,
        },
    }


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

        if any(not isinstance(info, dict) for info in (station_data.sensors or {}).values()):
            raise HTTPException(status_code=422, detail='Loại cảm biến hoặc cấu hình cảm biến không hợp lệ')
        await validate_custom_sensor_selection(db, station_data.sensors or {}, station_data.config or {})
        requested_topics = [
            normalize_mqtt_topic(info.get("topic"))
            for info in (station_data.sensors or {}).values()
            if isinstance(info, dict) and normalize_mqtt_topic(info.get("topic"))
        ]
        duplicates = duplicate_mqtt_topics(requested_topics)
        if duplicates:
            raise HTTPException(status_code=409, detail=f"MQTT topic bị trùng trong form: {', '.join(duplicates)}")
        conflicts = await find_mqtt_topic_conflicts(db, requested_topics)
        if conflicts:
            conflict = conflicts[0]
            raise HTTPException(
                status_code=409,
                detail=f"MQTT topic '{conflict.mqtt_topic}' đã được dùng bởi thiết bị {conflict.device_code}",
            )

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

        await refresh_project_map_position(db, project_id)
        await db.commit()
        await db.refresh(new_station)
        return new_station
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating station: {e}")
        raise HTTPException(status_code=500, detail=STATION_REQUEST_FAILED_DETAIL)


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


def parse_station_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(part.strip()) for part in value.split(","))
        if (not all(map(math.isfinite, (west, south, east, north)))
                or not (-180 <= west <= east <= 180)
                or not (-90 <= south <= north <= 90)):
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="bbox must be finite west,south,east,north") from None
    return west, south, east, north


@router.get("/api/stations")
async def get_stations(
    request: Request,
    response: Response,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    risk: Optional[str] = None,
    bbox: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=100),
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
        bbox_bounds = parse_station_bbox(bbox) if bbox else None
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
        term = (q or "").strip()
        if term:
            stmt = stmt.where(
                model_config.Station.name.icontains(term, autoescape=True)
                | model_config.Station.station_code.icontains(term, autoescape=True)
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
                "project_id": station.project_id,
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
        if bbox_bounds:
            west, south, east, north = bbox_bounds
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
        raise HTTPException(status_code=500, detail=STATION_REQUEST_FAILED_DETAIL)


@router.get("/api/stations/{station_id}/history")
async def get_station_history(
    station_id: int,
    request: Request,
    sensor_types: str = Query("gnss,rain,water,imu"),
    hours: int = Query(24, ge=1, le=8760),
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

    allowed_types = set(SENSOR_CATALOG) | {"gnss_adjusted"}
    requested_types = {
        value.strip().lower()
        for value in sensor_types.split(",")
        if value.strip().lower() in allowed_types or is_custom_sensor(value.strip().lower())
    }
    if not requested_types:
        raise HTTPException(status_code=400, detail="No valid sensor types requested")

    cutoff = int(time.time()) - int(hours * 3600)
    dialect = db_data.bind.dialect.name
    history_result = await db_data.execute(build_sensor_history_query(
        model_data.SensorData.__table__, station_id, requested_types, cutoff, limit, dialect
    ))
    sensors = {sensor_type: {"history": []} for sensor_type in requested_types}
    for sensor_type, timestamp, data in history_result.all():
        sensors[str(sensor_type)]["history"].append(
            {"timestamp": int(timestamp), "data": data}
        )
    return {
        "station_id": station_id,
        "hours": hours,
        "limit_per_sensor": limit,
        "sampled_across_interval": True,
        "sensors": sensors,
    }


@router.get("/api/stations/{station_id}/detail")
async def get_station_detail(
    station_id: int,
    request: Request,
    include_history: bool = True,
    include_adjustment_observations: bool = False,
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

            received_ts = max(int(latest_ts or 0), _device_activity_timestamp(device))
            sensor_is_online = bool(received_ts and current_time - received_ts < threshold)
            station_online = station_online or sensor_is_online

            # Measurement freshness is separate from device activity.
            if latest_ts and (current_time - latest_ts) < threshold:
                has_recent_data = True
                if latest_ts > latest_data_timestamp:
                    latest_data_timestamp = latest_ts

            # Lấy lịch sử 24h
            history = []
            if include_history:
                history_result = await db_data.execute(
                    select(model_data.SensorData.timestamp,
                           history_payload(model_data.SensorData.data, db_data.bind.dialect.name).label("data"))
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
                history = history_result.all()
                if sensor_type == 'gnss':
                    history = [
                        h for h in history
                        if isinstance(h.data, dict)
                        and (
                            h.data.get('speed_2d_mm_s') is not None
                            or (h.data.get('vel_e') is not None and h.data.get('vel_n') is not None)
                        )
                    ]

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
                "last_received_timestamp": received_ts or None,
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
                    "latest": _station_detail_adjustment_latest(
                        adj_cached.data, include_adjustment_observations
                    ),
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
        raise HTTPException(status_code=500, detail=STATION_REQUEST_FAILED_DETAIL)

