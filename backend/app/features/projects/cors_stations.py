"""Public CORS base-station discovery and cache."""
import asyncio
import copy
import logging
import math
import threading
import time
from typing import Any, Dict, List

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import config
from ...database import get_auth_db, get_config_db
from ...models import config as model_config
from ...runtime import cors_failover_status
from ...shared.access import get_optional_current_user_from_request, user_project_filter_ids

router = APIRouter(tags=["CORS Stations"])
logger = logging.getLogger(__name__)

CORS_BASE_STATIONS_URL = config.settings.CORS_BASE_STATIONS_URL
CORS_BASE_STATIONS_TOKEN = config.settings.CORS_BASE_STATIONS_TOKEN
CORS_BASE_STATIONS_CACHE_TTL_SECONDS = config.settings.CORS_BASE_STATIONS_CACHE_TTL_SECONDS
CORS_BASE_STATIONS_STALE_TTL_SECONDS = config.settings.CORS_BASE_STATIONS_STALE_TTL_SECONDS
CORS_BASE_STATIONS_RETRY_SECONDS = config.settings.CORS_BASE_STATIONS_RETRY_SECONDS
_cors_base_stations_cache_lock = threading.Lock()
_cors_base_stations_cache: List[Dict[str, Any]] = []
_cors_base_stations_cache_has_value = False
_cors_base_stations_cache_updated_monotonic = 0.0
_cors_base_stations_last_attempt_monotonic = 0.0
_cors_base_stations_last_error = None
_SERVICE_DISPLAY_FIELDS = {
    "server1_enabled", "server2_enabled", "serverhost1", "serverhost2",
    "port1", "port2", "mountpoint1", "mountpoint2", "active_mountpoint",
    "stream_active", "stream_on_demand", "server1_stream_active",
    "server2_stream_active", "server1_stream_on_demand", "server2_stream_on_demand",
}

def _resolve_cors_online_status(item: dict, status_text: str) -> bool:
    if isinstance(item.get("is_online"), bool):
        return bool(item.get("is_online"))
    if status_text:
        return status_text in {"online", "active", "connected", "streaming"}
    return bool(item.get("ntrip_connected"))


def _extract_cors_streams(item: dict, service_config: dict) -> list:
    streams = []
    raw_streams = item.get("streams") if isinstance(item.get("streams"), list) else []
    for position, raw_stream in enumerate(raw_streams, start=1):
        if not isinstance(raw_stream, dict):
            continue
        stream = {key: raw_stream[key] for key in (
            "server_id", "stream_id", "host", "port", "mountpoint", "enabled"
        ) if key in raw_stream}
        raw_server_id = stream.get("server_id")
        if raw_server_id in (None, ""):
            stream_token = str(stream.get("stream_id") or "")
            digits = "".join(char for char in stream_token if char.isdigit())
            raw_server_id = digits or position
        try:
            stream["server_id"] = int(raw_server_id)
        except (TypeError, ValueError):
            continue
        streams.append(stream)

    if not streams:
        for server_id in (1, 2):
            host = str(
                service_config.get(f"serverhost{server_id}")
                or service_config.get(f"server{server_id}_host")
                or ""
            ).strip()
            mountpoint = str(
                service_config.get(f"mountpoint{server_id}") or ""
            ).strip()
            if not host or not mountpoint:
                continue
            port = (
                service_config.get(f"serverport{server_id}")
                or service_config.get(f"server{server_id}_port")
                or 2101
            )
            streams.append({
                "server_id": server_id,
                "stream_id": f"s{server_id}",
                "host": host,
                "port": port,
                "mountpoint": mountpoint,
                "enabled": bool(
                    service_config.get(f"server{server_id}_enabled", True)
                ),
            })
    return streams


def _parse_cors_station_item(item: dict) -> Optional[dict]:
    if not isinstance(item, dict):
        return None

    name = str(item.get("name") or "").strip()
    try:
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        alt = float(item.get("alt")) if item.get("alt") is not None else 0.0
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt)
            and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    service_config = (
        item.get("service_config")
        if isinstance(item.get("service_config"), dict)
        else {}
    )
    status_text = str(item.get("status") or "").strip().casefold()
    is_online = _resolve_cors_online_status(item, status_text)
    streams = _extract_cors_streams(item, service_config)

    return {
        "serial": item.get("serial"),
        "name": name,
        "status": item.get("status"),
        "is_online": is_online,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "mountpoint": (
            service_config.get("mountpoint1")
            or item.get("mountpoint")
            or name
        ),
        "streams": streams,
        "service_config": {key: value for key, value in service_config.items()
                           if key in _SERVICE_DISPLAY_FIELDS},
        "is_provisioned": bool(item.get("is_provisioned")),
        "server_host": service_config.get("serverhost1"),
        "stream_active": bool(service_config.get("stream_active")),
        "ntrip_connected": bool(item.get("ntrip_connected")),
        "bps": item.get("bps"),
    }


def _normalize_cors_base_stations(raw_stations: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_stations, list):
        return []

    stations: List[Dict[str, Any]] = []
    for item in raw_stations:
        parsed = _parse_cors_station_item(item)
        if parsed is not None:
            stations.append(parsed)

    return sorted(stations, key=lambda station: station["name"])


def _should_return_cached_cors(managed_key_url: bool, cache_age: float) -> bool:
    return (
        not managed_key_url
        and _cors_base_stations_cache_has_value
        and cache_age <= CORS_BASE_STATIONS_CACHE_TTL_SECONDS
    )


def _check_cors_retry_cooldown(managed_key_url: bool, since_last_attempt: float, cache_age: float) -> bool:
    if managed_key_url or since_last_attempt >= CORS_BASE_STATIONS_RETRY_SECONDS:
        return False
    if _cors_base_stations_cache_has_value and cache_age <= CORS_BASE_STATIONS_STALE_TTL_SECONDS:
        return True
    if _cors_base_stations_last_error is not None:
        raise requests.ConnectionError("CORS refresh retry cooldown is active") from _cors_base_stations_last_error
    return False


def _handle_cors_fetch_exception(exc: requests.RequestException, managed_key_url: bool, cache_age: float):
    global _cors_base_stations_cache, _cors_base_stations_cache_has_value, _cors_base_stations_last_error
    _cors_base_stations_last_error = exc
    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (401, 403):
        _cors_base_stations_cache = []
        _cors_base_stations_cache_has_value = False
        raise exc
    if not managed_key_url and _cors_base_stations_cache_has_value and cache_age <= CORS_BASE_STATIONS_STALE_TTL_SECONDS:
        logger.warning("CORS base station refresh failed; serving %.1fs stale cache: %s", cache_age, exc)
        return copy.deepcopy(_cors_base_stations_cache)
    raise exc


def _fetch_cors_base_stations_sync() -> List[Dict[str, Any]]:
    global _cors_base_stations_cache
    global _cors_base_stations_cache_has_value
    global _cors_base_stations_cache_updated_monotonic
    global _cors_base_stations_last_attempt_monotonic
    global _cors_base_stations_last_error

    if not CORS_BASE_STATIONS_URL:
        raise requests.ConnectionError(
            "CORS_BASE_STATIONS_URL is not configured"
        )

    with _cors_base_stations_cache_lock:
        now = time.monotonic()
        cache_age = now - _cors_base_stations_cache_updated_monotonic
        managed_key_url = "/api/integrations/stations" in CORS_BASE_STATIONS_URL
        if _should_return_cached_cors(managed_key_url, cache_age):
            return copy.deepcopy(_cors_base_stations_cache)

        since_last_attempt = now - _cors_base_stations_last_attempt_monotonic
        if _check_cors_retry_cooldown(managed_key_url, since_last_attempt, cache_age):
            return copy.deepcopy(_cors_base_stations_cache)

        _cors_base_stations_last_attempt_monotonic = now
        try:
            headers = (
                {"Authorization": f"Bearer {CORS_BASE_STATIONS_TOKEN}"}
                if CORS_BASE_STATIONS_TOKEN else {}
            )
            response = requests.get(CORS_BASE_STATIONS_URL, headers=headers, timeout=8)
            response.raise_for_status()
            payload = response.json()
            raw_stations = payload.get("value") if isinstance(payload, dict) else payload
            stations = _normalize_cors_base_stations(raw_stations)
        except requests.RequestException as exc:
            return _handle_cors_fetch_exception(exc, managed_key_url, cache_age)

        _cors_base_stations_cache = copy.deepcopy(stations)
        _cors_base_stations_cache_has_value = True
        _cors_base_stations_cache_updated_monotonic = time.monotonic()
        _cors_base_stations_last_error = None
        return copy.deepcopy(stations)


@router.get("/api/public/cors-base-stations")
async def get_cors_base_stations(
    request: Request,
    db_config: AsyncSession = Depends(get_config_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    try:
        all_cors = await asyncio.to_thread(_fetch_cors_base_stations_sync)
        if not all_cors:
            return []

        # Find which CORS stations are used by projects the user can see
        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)

        stmt = select(model_config.Project).where(model_config.Project.is_active == True)
        if project_filter_ids is not None:
            if not project_filter_ids:
                return []
            stmt = stmt.where(model_config.Project.id.in_(project_filter_ids))

        result = await db_config.execute(stmt)
        projects = result.scalars().all()

        used_bases = set()
        for p in projects:
            clusters = p.gnss_clusters or []
            if isinstance(clusters, list):
                for c in clusters:
                    if isinstance(c, dict):
                        used_bases.update(str(c[key]) for key in (
                            "base_station", "backup_base_station", "base_serial", "backup_base_serial"
                        ) if c.get(key))

        filtered_cors = [
            st for st in all_cors
            if st["name"] in used_bases or st.get("mountpoint") in used_bases
            or st.get("code") in used_bases or str(st.get("serial") or "") in used_bases
        ]

        # Physical receiver state and mountpoint availability are different.
        # A primary receiver may be offline while another station's S2 keeps
        # its mountpoint connected.  Never let that backup source make the
        # offline physical station appear online on the public map.
        failover_pairs = copy.deepcopy(cors_failover_status)
        for station in filtered_cors:
            station["station_online"] = bool(station.get("is_online"))
            station["mountpoint_connected"] = bool(
                station.get("ntrip_connected")
            )
            station["failover_active"] = bool(
                not station["station_online"]
                and station["mountpoint_connected"]
            )
            station["correction_source"] = (
                "Nguồn dự phòng khác"
                if station["failover_active"]
                else f"{station.get('name')}/S1"
            )
            station_name = str(station.get("name") or "").strip().casefold()
            station_mountpoint = str(
                station.get("mountpoint") or ""
            ).strip().casefold()
            pair = next(
                (
                    item
                    for item in failover_pairs
                    if str(item.get("primary_station") or "").strip().casefold()
                    == station_name
                    or (
                        station_mountpoint
                        and str(item.get("mountpoint") or "").strip().casefold()
                        == station_mountpoint
                    )
                ),
                None,
            )
            if pair:
                station["failover_state"] = pair.get("state")
                station["failover_active"] = pair.get("state") == "BACKUP_ACTIVE"
                if station["failover_active"]:
                    station["correction_source"] = (
                        f"{pair.get('backup_station')}/S"
                        f"{pair.get('backup_server_id')}"
                    )
                else:
                    station["correction_source"] = (
                        f"{pair.get('primary_station')}/S"
                        f"{pair.get('primary_server_id')}"
                    )

        for station in filtered_cors:
            station.pop("service_config", None)
        return filtered_cors
    except requests.RequestException as e:
        logger.warning(f"CORS base station fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch CORS base stations")
