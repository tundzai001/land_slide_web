"""Administrative GNSS network-adjustment workflow API."""
import asyncio
import copy
import json
import logging
import math
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..database import get_config_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..runtime import mqtt_service
from ..services.station_policy import check_operator_project_access, get_offline_threshold
from ..websocket import manager as ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class GnssAdjustmentStartRequest(BaseModel):
    project_id: int
    base_mountpoint: Optional[str] = None
    caster_address: Optional[str] = None
    new_base_station_id: Optional[int] = None
    selected_clusters: Optional[list[list[int]]] = None


def _normalize_active_adjustment_clusters(
    raw_clusters: Any,
    stations: list[Any],
    selected_clusters: Optional[list[list[int]]],
) -> list[dict]:
    """Resolve persisted station codes to IDs without losing base metadata."""

    stations_by_id = {int(station.id): station for station in stations}
    stations_by_code = {
        str(station.station_code).strip(): station
        for station in stations
        if getattr(station, "station_code", None)
    }

    def resolve_station_ids(tokens: Any) -> list[int]:
        resolved = []
        for token in tokens if isinstance(tokens, list) else []:
            station = None
            try:
                station = stations_by_id.get(int(token))
            except (TypeError, ValueError):
                station = stations_by_code.get(str(token).strip())
            if station and station.id not in resolved:
                resolved.append(int(station.id))
        return resolved

    configured = []
    for index, raw_cluster in enumerate(raw_clusters or []):
        cluster = dict(raw_cluster) if isinstance(raw_cluster, dict) else {"stations": raw_cluster}
        station_ids = resolve_station_ids(cluster.get("stations", []))
        if len(station_ids) < 2:
            continue
        def normalize_candidate(source: dict, role: str) -> dict:
            prefix = "" if role == "primary" else "backup_"
            try:
                latitude = float(source.get(f"{prefix}base_lat"))
                longitude = float(source.get(f"{prefix}base_lon"))
                altitude = float(source.get(f"{prefix}base_alt") or 0.0)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"GNSS cluster #{index + 1} {role} base is missing a valid coordinate"
                ) from exc
            if (
                not all(math.isfinite(value) for value in (latitude, longitude, altitude))
                or not -90.0 <= latitude <= 90.0
                or not -180.0 <= longitude <= 180.0
                or (
                    abs(latitude) < 1e-12
                    and abs(longitude) < 1e-12
                    and abs(altitude) < 1e-12
                )
            ):
                raise ValueError(
                    f"GNSS cluster #{index + 1} has an invalid {role} fixed-base coordinate"
                )
            return {
                "role": role,
                "base_station": str(source.get(f"{prefix}base_station") or "").strip(),
                "base_lat": latitude,
                "base_lon": longitude,
                "base_alt": altitude,
                "base_stream": str(source.get(f"{prefix}base_stream") or "").strip(),
                "base_stream_host": str(
                    source.get(f"{prefix}base_stream_host") or ""
                ).strip(),
                "base_stream_port": source.get(f"{prefix}base_stream_port"),
                "base_stream_mp": str(
                    source.get(f"{prefix}base_stream_mp") or ""
                ).strip(),
                "base_service_config": copy.deepcopy(
                    source.get(f"{prefix}base_service_config") or {}
                ),
                "base_serial": str(
                    source.get(f"{prefix}base_serial") or ""
                ).strip(),
                "base_server_id": source.get(f"{prefix}base_server_id"),
            }

        primary = normalize_candidate(cluster, "primary")
        candidates = [primary]
        if str(cluster.get("backup_base_station") or "").strip():
            backup = normalize_candidate(cluster, "backup")
            if backup["base_station"].casefold() == primary["base_station"].casefold():
                raise ValueError(
                    f"GNSS cluster #{index + 1} backup base must differ from its primary base"
                )
            if not backup["base_stream_host"] or not backup["base_stream_mp"]:
                raise ValueError(
                    f"GNSS cluster #{index + 1} backup base requires an explicit "
                    "CORS stream host and mountpoint"
                )
            if (
                backup["base_stream_mp"].casefold()
                != primary["base_stream_mp"].casefold()
            ):
                raise ValueError(
                    f"GNSS cluster #{index + 1} backup S2 must publish the same "
                    "mountpoint as primary S1"
                )
            candidates.append(backup)

        cluster["stations"] = station_ids
        cluster["rovers"] = [stations_by_id[station_id].station_code for station_id in station_ids]
        cluster["aicaster_users"] = {}
        for station_id in station_ids:
            station = stations_by_id[station_id]
            station_config = station.config if isinstance(station.config, dict) else {}
            binding = (
                station_config.get("gnss_aicaster_user")
                or station_config.get("gnss_aicaster_client")
                or {}
            )
            username = str(binding.get("username") or "").strip()
            if not username:
                continue
            cluster["aicaster_users"][station.station_code] = {
                "username": username,
                "caster_host": str(binding.get("caster_host") or "").strip(),
            }
        cluster["fixed_base_candidates"] = candidates
        cluster["selected_fixed_base_candidate"] = (
            copy.deepcopy(primary) if len(candidates) == 1 else None
        )
        cluster.update({
            key: copy.deepcopy(value)
            for key, value in primary.items()
            if key != "role"
        })
        configured.append(cluster)

    if not configured:
        raise ValueError("project has no valid GNSS cluster with two rovers and a fixed base")
    if selected_clusters is None:
        return configured

    selected = [resolve_station_ids(cluster) for cluster in selected_clusters]
    if not selected or any(len(cluster) < 2 for cluster in selected):
        raise ValueError("the selected GNSS cluster must contain at least two project stations")

    active = []
    for selected_station_ids in selected:
        target = set(selected_station_ids)
        match = next((cluster for cluster in configured if set(cluster["stations"]) == target), None)
        if match is None:
            raise ValueError(
                "the selected stations do not match a configured GNSS cluster; select the cluster connection on the map"
            )
        active.append(match)
    return active


def _restrict_adjustment_clusters_to_online_stations(
    clusters: list[dict],
    online_station_ids: set[int],
) -> tuple[list[dict], list[int]]:
    """Remove offline rovers while preserving station/code ordering per cluster."""

    active_clusters = []
    excluded_station_ids = []
    for source in clusters:
        station_rover_pairs = list(zip(source["stations"], source["rovers"], strict=True))
        included = [
            (station_id, rover)
            for station_id, rover in station_rover_pairs
            if int(station_id) in online_station_ids
        ]
        excluded_station_ids.extend(
            int(station_id)
            for station_id, _ in station_rover_pairs
            if int(station_id) not in online_station_ids
        )
        if len(included) < 2:
            continue
        cluster = dict(source)
        cluster["stations"] = [int(station_id) for station_id, _ in included]
        cluster["rovers"] = [str(rover) for _, rover in included]
        active_clusters.append(cluster)

    if not active_clusters:
        raise ValueError("fewer than two online GNSS rovers are available in the selected cluster")
    return active_clusters, sorted(set(excluded_station_ids))


@router.get("/api/admin/gnss/aicaster-users")
async def list_aicaster_users(
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.EDIT_STATIONS)
    ),
):
    """List configured accounts reported by AICaster GET /usertable."""

    try:
        users = await mqtt_service.round_robin_manager.list_aicaster_users()
    except Exception as exc:
        logger.error("Could not load AICaster user table: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "users": [
            {
                "username": item.get("Username") or "",
                "mountpoints": item.get("Mountpoints") or [],
                "status": item.get("Status") or "",
                "identifier": item.get("Identifier") or "",
                "active_client_count": item.get("ActiveClientCount") or "",
                "caster_host": item.get("CasterHost") or "",
                "caster_port": item.get("CasterPort"),
            }
            for item in users
        ]
    }

@router.post("/api/admin/gnss/adjustment/start")
async def start_gnss_adjustment(
    req: GnssAdjustmentStartRequest,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        if not hasattr(mqtt_service, "active_adjustment_clusters"):
            mqtt_service.active_adjustment_clusters = {}

        project_result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == req.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        check_operator_project_access(current_user, project.id)

        existing_phase = str(mqtt_service.adjustment_phase.get(req.project_id) or "").upper()
        if existing_phase in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
            existing_clusters = mqtt_service.active_adjustment_clusters.get(req.project_id) or []
            expected_station_ids = sorted({
                int(station_id)
                for cluster in existing_clusters
                for station_id in cluster.get("stations", [])
            })
            seed_status = mqtt_service.round_robin_manager.get_seed_collection_status(req.project_id)
            return {
                "status": "success",
                "existing": True,
                "phase": existing_phase,
                "expected_station_ids": expected_station_ids,
                "seed_status": seed_status,
                "message": "Adjustment is already running; reopened the existing session.",
            }

        stale_session = mqtt_service.round_robin_manager._sessions.get(req.project_id)
        if stale_session and stale_session.get("seed_topology_snapshots"):
            await mqtt_service.round_robin_manager.restore_common_fixed_base_topology(
                req.project_id
            )
            mqtt_service.round_robin_manager.clear_project(req.project_id)

        stations_result = await db.execute(
            select(model_config.Station).where(model_config.Station.project_id == project.id)
        )
        stations = stations_result.scalars().all()
        try:
            active_clusters = _normalize_active_adjustment_clusters(
                project.gnss_clusters,
                stations,
                req.selected_clusters,
            )
            selected_station_ids = {
                int(station_id)
                for cluster in active_clusters
                for station_id in cluster["stations"]
            }
            devices_result = await db.execute(
                select(model_config.Device).where(
                    and_(
                        model_config.Device.station_id.in_(selected_station_ids),
                        func.lower(model_config.Device.device_type) == "gnss",
                        model_config.Device.is_active == True,
                    )
                )
            )
            gnss_devices = devices_result.scalars().all()
            stations_by_id = {int(station.id): station for station in stations}
            pending_device_updates = getattr(mqtt_service, "_device_update_buffer", {})
            now_ts = int(time.time())
            online_station_ids = set()
            for device in gnss_devices:
                station = stations_by_id.get(int(device.station_id))
                if station is None:
                    continue
                last_seen = max(
                    int(device.last_data_time or 0),
                    int(pending_device_updates.get(int(device.id), 0) or 0),
                )
                threshold = get_offline_threshold(station.config, "gnss")
                if last_seen and now_ts - last_seen < threshold:
                    online_station_ids.add(int(device.station_id))
            active_clusters, skipped_offline_station_ids = (
                _restrict_adjustment_clusters_to_online_stations(
                    active_clusters,
                    online_station_ids,
                )
            )
            mqtt_service.round_robin_manager.configure_project(req.project_id, active_clusters)
            try:
                seed_topology = (
                    await mqtt_service.round_robin_manager.prepare_common_fixed_base_seed(
                        req.project_id
                    )
                )
            except Exception:
                failed_session = mqtt_service.round_robin_manager._sessions.get(
                    req.project_id
                )
                # Keep a failed restore snapshot reachable so a stop/retry can
                # restore the exact pre-adjustment service configuration.
                if not failed_session or not failed_session.get(
                    "seed_topology_snapshots"
                ):
                    mqtt_service.round_robin_manager.clear_project(req.project_id)
                raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Preserve coordinates and stream settings from project configuration.
        mqtt_service.active_adjustment_clusters[req.project_id] = active_clusters
        logger.info(
            "Configured GNSS adjustment project=%s clusters=%s",
            req.project_id,
            [cluster.get("name") or cluster["stations"] for cluster in active_clusters],
        )

        # 1. Bật chế độ chờ thu thập Baseline (COLLECTING_BASELINE)
        mqtt_service.adjustment_phase[req.project_id] = "COLLECTING_BASELINE"
        mqtt_service.adjustment_message[req.project_id] = (
            "Common fixed-base route is ready; waiting for source-verified #AGRICA "
            "baselines from every selected rover."
        )
        mqtt_service.adjustment_results.pop(req.project_id, None)
        logger.info(f"🎯 Started GNSS Adjustment for project {req.project_id}. Phase: COLLECTING_BASELINE.")

        expected_station_ids = sorted({
            station_id
            for cluster in active_clusters
            for station_id in cluster["stations"]
        })
        await ws_manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": req.project_id,
            "phase": "COLLECTING_BASELINE",
            "message": "Common fixed-base route is ready; waiting for source-verified #AGRICA baselines from every selected rover.",
            "expected_station_ids": expected_station_ids,
            "skipped_offline_station_ids": skipped_offline_station_ids,
            "seed_topology": seed_topology,
        })

        return {
            "status": "success",
            "phase": "COLLECTING_BASELINE",
            "expected_station_ids": expected_station_ids,
            "skipped_offline_station_ids": skipped_offline_station_ids,
            "seed_topology": seed_topology,
            "message": "Both rover streams now use the selected physical base; waiting for verified baseline collection.",
        }
    except Exception as e:
        logger.error(f"Failed to start GNSS adjustment cycle: {e}")
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/gnss/adjustment/status")
async def get_gnss_adjustment_status(
    project_id: int,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
):
    """Return the authoritative terminal state when a WebSocket event is missed."""

    phase = str(mqtt_service.adjustment_phase.get(project_id) or "IDLE").upper()
    message = str(mqtt_service.adjustment_message.get(project_id) or "")
    result = (
        mqtt_service.adjustment_results.get(project_id)
        if phase in {"COMPLETED", "FAILED_QUALITY_GATE"}
        else None
    )
    seed_status = None
    if phase in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
        try:
            seed_status = mqtt_service.round_robin_manager.get_seed_collection_status(project_id)
        except (KeyError, ValueError):
            seed_status = None
    return {
        "project_id": project_id,
        "phase": phase,
        "message": message,
        "running": phase in {"COLLECTING_BASELINE", "FREE_NETWORK"},
        "seed_status": seed_status,
        "data": result,
    }


@router.post("/api/admin/gnss/adjustment/stop")
async def stop_gnss_adjustment(
    req: GnssAdjustmentStartRequest,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        if not hasattr(mqtt_service, "active_adjustment_clusters"):
            mqtt_service.active_adjustment_clusters = {}

        # Cancel first so the cycle's finally block can restore both the
        # temporary-base stream and the pre-seed S1/S2 topology.
        running_task = mqtt_service.round_robin_manager.running_tasks.get(req.project_id)
        if running_task and not running_task.done():
            running_task.cancel()
            try:
                await running_task
            except asyncio.CancelledError:
                pass
        await mqtt_service.round_robin_manager.restore_common_fixed_base_topology(
            req.project_id
        )

        # Clear dynamic active adjustment clusters and phase
        mqtt_service.active_adjustment_clusters.pop(req.project_id, None)
        mqtt_service.adjustment_phase.pop(req.project_id, None)
        mqtt_service.adjustment_message.pop(req.project_id, None)
        mqtt_service.adjustment_results.pop(req.project_id, None)
        mqtt_service.round_robin_manager.clear_project(req.project_id)
        logger.info(f"Cleared active adjustment clusters and phase for project {req.project_id}")

        # 1. Gửi lệnh mở lại (wake) luồng RTCM của Base gốc qua MQTT tới CORS Dashboard
        topic = "ntrip/rtcm/start"
        payload = {
            "mountpoint": req.base_mountpoint,
            "client_instance_id": "landslide_system",
            "ttl_seconds": 300 # Đánh thức duy trì trong 5 phút hoặc lâu hơn
        }
        if req.caster_address:
            payload["caster_address"] = req.caster_address

        if mqtt_service.client and mqtt_service.client.is_connected():
            mqtt_service.client.publish(topic, json.dumps(payload), qos=1)
            logger.info(f"Published adjustment stop command (wake Base RTCM): {payload}")
        else:
            logger.warning(f"MQTT client not connected, failed to publish wake base command")
            raise HTTPException(status_code=503, detail="MQTT broker connection unavailable")

        return {"status": "success", "message": "Adjustment cycle stopped, Base stream woken up"}
    except Exception as e:
        logger.error(f"Failed to stop GNSS adjustment cycle: {e}")
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================


