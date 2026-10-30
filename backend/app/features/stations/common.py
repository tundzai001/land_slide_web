"""Shared station query and alert-summary helpers."""

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import config as model_config
from ...models import data as model_data
from ...runtime import mqtt_service
from ...shared.station_policy import get_offline_threshold


def _device_activity_timestamp(device) -> int:
    """Include received packets that have not reached the periodic DB flush."""
    pending = getattr(mqtt_service, "_device_update_buffer", {})
    return max(int(device.last_data_time or 0), int(pending.get(int(device.id), 0)))


def _station_detail_adjustment_latest(
    payload: Optional[Dict[str, Any]], include_observations: bool
) -> Dict[str, Any]:
    """Keep raw adjustment observations out of the normal station-detail response."""
    latest = dict(payload or {})
    if not include_observations:
        latest.pop("baseline_observations", None)
    return latest


def is_offline_display_enabled(station_config: Optional[Dict[str, Any]]) -> bool:
    cfg = station_config or {}
    return bool(
        cfg.get("offline_display_enabled") is True
        or cfg.get("offline_display", {}).get("enabled") is True
    )


def calculate_station_location(sensors: dict, manual_location: dict = None):
    # A DEM grid pick is the station's chosen map position; sensor reference
    # coordinates are separate origins and must not override it.
    if isinstance(manual_location, dict) and manual_location.get("source") == "project-dem-grid":
        return manual_location
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
    """Load activity timestamps and alerts in bulk for station online status."""
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
        select(model_data.LatestSensorCache.station_id, model_data.LatestSensorCache.sensor_type,
               model_data.LatestSensorCache.timestamp).where(
            model_data.LatestSensorCache.station_id.in_(station_ids)
        )
    )
    latest_by_key = {
        (int(row.station_id), str(row.sensor_type)): int(row.timestamp or 0)
        for row in cache_result.all()
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

    # Online means the device is sending packets, including AGRICA/RTCM and
    # rejected measurements. Do not require a new accepted position sample.
    for station_devices in devices_by_station.values():
        for device in station_devices:
            key = (int(device.station_id), str(device.device_type))
            latest_by_key[key] = max(latest_by_key.get(key, 0), _device_activity_timestamp(device))

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
    # TTL only describes freshness; it must never erase an unresolved durable
    # alert from the API.  A restart can happen after the last sensor packet,
    # so silently dropping the row would make a real warning look SAFE.
    alert_rows = []
    for alert in alerts:
        ttl = int(ttl_cfg.get(alert.category, default_ttl.get(alert.category, 180)))
        age_seconds = max(0, now_ts - int(alert.timestamp or 0))
        alert_rows.append((alert, age_seconds > ttl, age_seconds))

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
    for alert, _is_stale, _age_seconds in alert_rows:
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
                "stale": is_stale,
                "age_seconds": age_seconds,
            }
            for alert, is_stale, age_seconds in alert_rows
        ],
        "stale_alerts": [
            {
                "level": alert.level,
                "category": alert.category,
                "message": alert.message,
                "timestamp": alert.timestamp,
                "stale": True,
                "age_seconds": age_seconds,
            }
            for alert, is_stale, age_seconds in alert_rows
            if is_stale
        ],
        "fresh_alerts": [
            {
                "level": alert.level,
                "category": alert.category,
                "message": alert.message,
                "timestamp": alert.timestamp,
                "stale": False,
                "age_seconds": age_seconds,
            }
            for alert, is_stale, age_seconds in alert_rows
            if not is_stale
        ],
    }


