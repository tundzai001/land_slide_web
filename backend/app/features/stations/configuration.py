"""Station configuration routes."""

from __future__ import annotations

import copy
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from ...shared.project_location import refresh_project_map_position
from ...shared.station_policy import check_operator_station_access
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config
from .topics import duplicate_mqtt_topics, find_mqtt_topic_conflicts, normalize_mqtt_topic
from .defaults import get_default_station_config
from app.shared.sensor_catalog import SENSOR_CATALOG
from app.shared.custom_sensors import validate_custom_sensor_selection

router = APIRouter(prefix="/api/admin", tags=["Admin Console"])
logger = logging.getLogger(__name__)

def _merge_station_config(station, config_data: dict, current_user):
    import copy

    current_config = copy.deepcopy(station.config) if station.config else get_default_station_config()
    new_config = config_data['config']

    # The monitoring reference is immutable. A station edit may update all
    # other settings, but it cannot blank or replace a locked origin.
    locked_origin = copy.deepcopy(current_config.get('gnss_origin'))
    if locked_origin and locked_origin.get('lat') is not None and locked_origin.get('lon') is not None:
        new_config = copy.deepcopy(new_config)
        new_config['gnss_origin'] = locked_origin

    # Backward compatibility for VN2000 config key:
    # normalize legacy `vn2000_params` into canonical `vn2000`.
    if isinstance(new_config, dict) and 'vn2000_params' in new_config and 'vn2000' not in new_config:
        new_config['vn2000'] = new_config.get('vn2000_params') or {}

    logger.info(f"📋 [CONFIG] Before merge, offline_thresholds: {current_config.get('offline_thresholds')}")
    logger.info(f"📋 [CONFIG] Incoming config keys: {list(new_config.keys())}")

    for key, value in new_config.items():
        if key == 'custom_sensors':
            current_config[key] = value
        elif isinstance(value, dict) and key in current_config and isinstance(current_config[key], dict):
            current_config[key].update(value)
        else:
            current_config[key] = value

    logger.info(f"📋 [CONFIG] After merge, offline_thresholds: {current_config.get('offline_thresholds')}")

    station.config = current_config  # Assign NEW dict object
    from ..operations.forwarding import authorize
    forwarding = current_config.get('gnss_rtk_forwarding')
    if isinstance(forwarding, dict):
        current_config['gnss_rtk_forwarding'] = authorize(
            station.id, forwarding, current_user, config_data.get('owner_authorization', '')
        )
    flag_modified(station, 'config')  # Force SQLAlchemy to detect change


async def _sync_sensor_device(db: AsyncSession, station, s_type: str, info: dict, existing_devices: dict):
    topic = info.get('topic', '').strip() if isinstance(info, dict) else ''
    if not topic:
        return None

    import copy
    mqtt_payload = info.get('mqtt') if isinstance(info, dict) else None

    if s_type in existing_devices:
        existing_devices[s_type].mqtt_topic = topic
        existing_devices[s_type].is_active = True
        existing_devices[s_type].updated_at = int(time.time())

        dev_config = copy.deepcopy(existing_devices[s_type].config) if existing_devices[s_type].config else {}
        dev_config['mqtt'] = mqtt_payload
        existing_devices[s_type].config = dev_config
        flag_modified(existing_devices[s_type], "config")
        logger.info(f"  ✅ Updated {s_type}: topic={topic}")
    else:
        dev_code = f"{station.station_code}_{s_type.upper()}"
        existing_by_code = await db.execute(
            select(model_config.Device).where(model_config.Device.device_code == dev_code)
        )
        found_dev = existing_by_code.scalar_one_or_none()

        if found_dev:
            found_dev.station_id = station.id
            found_dev.device_type = s_type
            found_dev.mqtt_topic = topic
            found_dev.is_active = True
            found_dev.updated_at = int(time.time())

            dev_config = copy.deepcopy(found_dev.config) if found_dev.config else {}
            dev_config['mqtt'] = mqtt_payload
            found_dev.config = dev_config
            flag_modified(found_dev, "config")
            logger.info(f"  🔄 Reassigned existing device {dev_code}: topic={topic}")
        else:
            db.add(model_config.Device(
                device_code=dev_code,
                name=f"{station.name} - {s_type.upper()}",
                station_id=station.id,
                device_type=s_type,
                mqtt_topic=topic,
                is_active=True,
                config={"mqtt": mqtt_payload},
                created_at=int(time.time()),
                updated_at=int(time.time())
            ))
            logger.info(f"  🆕 Created {s_type}: topic={topic}")
    return s_type


async def _sync_station_devices(db: AsyncSession, station, sensors: dict):
    if any(not isinstance(info, dict) for info in sensors.values()):
        raise HTTPException(status_code=422, detail='Loại cảm biến hoặc cấu hình cảm biến không hợp lệ')
    await validate_custom_sensor_selection(db, sensors, station.config or {})
    requested_topics = [
        normalize_mqtt_topic(info.get('topic'))
        for info in sensors.values()
        if isinstance(info, dict) and normalize_mqtt_topic(info.get('topic'))
    ]
    duplicates = duplicate_mqtt_topics(requested_topics)
    if duplicates:
        raise HTTPException(status_code=409, detail=f"MQTT topic bị trùng trong form: {', '.join(duplicates)}")
    conflicts = await find_mqtt_topic_conflicts(db, requested_topics, station.id)
    if conflicts:
        conflict = conflicts[0]
        raise HTTPException(
            status_code=409,
            detail=f"MQTT topic '{conflict.mqtt_topic}' đã được dùng bởi thiết bị {conflict.device_code}",
        )
    logger.info(f"📋 [UPDATE] Station {station.id}: syncing sensors={list(sensors.keys())}")

    existing_res = await db.execute(
        select(model_config.Device).where(model_config.Device.station_id == station.id)
    )
    existing_devices = {d.device_type: d for d in existing_res.scalars().all()}
    logger.info(f"📋 [UPDATE] Existing devices: {list(existing_devices.keys())}")

    active_types = set()
    for s_type, info in sensors.items():
        synced = await _sync_sensor_device(db, station, s_type, info, existing_devices)
        if synced:
            active_types.add(synced)

    for d_type, dev in existing_devices.items():
        if d_type not in active_types:
            dev.is_active = False
            dev.updated_at = int(time.time())
            logger.info(f"  ❌ Deactivated {d_type}")

    logger.info(f"📋 [UPDATE] Active types: {active_types}")


def _auto_compute_station_location(station):
    final_config = station.config or {}
    origin_keys = [f'{sensor_type}_origin' for sensor_type in SENSOR_CATALOG]
    origin_keys.extend(f'{sensor_type}_origin' for sensor_type in (station.config or {}).get('custom_sensors', {}))
    lats, lons = [], []
    for key in origin_keys:
        origin = final_config.get(key, {})
        try:
            lat_val = float(origin.get('lat', 0))
            lon_val = float(origin.get('lon', 0))
            if lat_val != 0 and lon_val != 0:
                lats.append(lat_val)
                lons.append(lon_val)
        except (ValueError, TypeError, AttributeError):
            continue

    if lats and lons and not (
        isinstance(station.location, dict)
        and station.location.get("source") == "project-dem-grid"
    ):
        avg_lat = sum(lats) / len(lats)
        avg_lon = sum(lons) / len(lons)
        station.location = {"lat": round(avg_lat, 8), "lon": round(avg_lon, 8)}
        logger.info(f"📍 [LOCATION] Auto-set station {station.id} location to ({avg_lat:.6f}, {avg_lon:.6f}) from {len(lats)} origins")


@router.put("/stations/{station_id}/config", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 409: {"description": "Conflict"}, 422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
async def update_station_config(
    station_id: int,
    config_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        await check_operator_station_access(current_user, station_id, db)
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()

        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        if not config_data:
            raise HTTPException(status_code=400, detail="Config data is empty")

        # Update basic info
        if 'station_code' in config_data: station.station_code = config_data['station_code']
        if 'name' in config_data: station.name = config_data['name']

        if 'config' in config_data:
            _merge_station_config(station, config_data, current_user)

        # ✅ SYNC DEVICES từ sensors payload
        if 'sensors' in config_data and isinstance(config_data['sensors'], dict):
            await _sync_station_devices(db, station, config_data['sensors'])
        elif 'custom_sensors' in (config_data.get('config') or {}):
            active = (await db.execute(select(model_config.Device.device_type).where(
                model_config.Device.station_id == station_id,
                model_config.Device.is_active.is_(True),
            ))).scalars().all()
            await validate_custom_sensor_selection(db, {sensor_type: {} for sensor_type in active}, station.config or {})

        # ✅ AUTO-COMPUTE station location from average of sensor coordinate origins
        _auto_compute_station_location(station)

        station.updated_at = int(time.time())
        await refresh_project_map_position(db, station.project_id)
        await db.commit()

        return {"status": "success", "message": f"Updated station {station_id}"}

        station.updated_at = int(time.time())
        await refresh_project_map_position(db, station.project_id)
        await db.commit()

        return {"status": "success", "message": f"Updated station {station_id}"}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"❌ Error updating station config: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi cập nhật cấu hình: {str(e)}")


@router.post("/stations/{station_id}/reset-config", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def reset_station_config(
    station_id: int,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    _current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()

        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        new_default_config = get_default_station_config()
        station.config = new_default_config

        await db.commit()
        return {
            "status": "success",
            "message": "Config reset to default",
            "config": new_default_config
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stations/{station_id}/config", responses={404: {"description": "Not Found"}})
async def get_station_config(
    station_id: int,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    _current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_STATIONS))
):
    result = await db.execute(
        select(model_config.Station).where(model_config.Station.id == station_id)
    )
    station = result.scalar_one_or_none()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # Deep-merge: defaults ← station config (station wins)
    import copy
    merged = copy.deepcopy(get_default_station_config())
    raw = station.config or {}
    for key, value in raw.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key].update(value)
        else:
            merged[key] = value

    return {
        "station_id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "config": merged
    }
