"""Administrative GNSS network-adjustment workflow API."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import auth
from ...database import get_config_db
from ...models import auth as model_auth
from ...models import config as model_config
from ...runtime import mqtt_service
from .store import write_adjustment_failure_report
from .clusters import (
    normalize_active_clusters,
    restrict_clusters_to_online_stations,
    streaming_gnss_station_ids,
)
from .schemas import GnssAdjustmentControlRequest, GnssAdjustmentStartRequest
from ...shared.station_policy import check_operator_project_access, get_offline_threshold
from ...websocket import manager as ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


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
        if not hasattr(mqtt_service, "adjustment_run_rosters"):
            mqtt_service.adjustment_run_rosters = {}

        project_result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == req.project_id)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        check_operator_project_access(current_user, project.id)
        if req.run_id is not None and getattr(current_user, "role", None) != "system":
            raise HTTPException(status_code=403, detail="Internal adjustment run ID is scheduler-only")

        session_id = int(req.run_id if req.run_id is not None else req.project_id)
        existing_phase = str(mqtt_service.adjustment_phase.get(session_id) or "").upper()
        if existing_phase in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}:
            existing_clusters = mqtt_service.active_adjustment_clusters.get(session_id) or []
            expected_station_ids = sorted({
                int(station_id)
                for cluster in existing_clusters
                for station_id in cluster.get("stations", [])
            })
            seed_status = mqtt_service.round_robin_manager.get_seed_collection_status(session_id)
            return {
                "status": "success",
                "existing": True,
                "phase": existing_phase,
                "expected_station_ids": expected_station_ids,
                "run_id": session_id,
                "roster": mqtt_service.adjustment_run_rosters.get(session_id) or {},
                "seed_status": seed_status,
                "message": "Adjustment is already running; reopened the existing session.",
            }

        stale_session = mqtt_service.round_robin_manager._sessions.get(session_id)
        if stale_session and stale_session.get("seed_topology_snapshots"):
            await mqtt_service.round_robin_manager.restore_common_fixed_base_topology(
                session_id
            )
            mqtt_service.round_robin_manager.clear_project(session_id)

        stations_result = await db.execute(
            select(model_config.Station).where(model_config.Station.project_id == project.id)
        )
        stations = stations_result.scalars().all()
        try:
            active_clusters = normalize_active_clusters(
                project.gnss_clusters,
                stations,
                req.selected_clusters,
            )
            for cluster in active_clusters:
                cluster["project_code"] = str(project.project_code or f"project-{project.id}")
                cluster["parent_project_id"] = int(project.id)
                cluster["run_id"] = session_id
            selected_station_ids = {
                int(station_id)
                for cluster in active_clusters
                for station_id in cluster["stations"]
            }
            selected_station_ids_snapshot = sorted(selected_station_ids)
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
            live_mqtt_station_ids = streaming_gnss_station_ids(
                active_clusters,
                stations_by_id,
            )
            db_stale_but_streaming = live_mqtt_station_ids - online_station_ids
            if db_stale_but_streaming:
                logger.info(
                    "GNSS adjustment online check recovered live MQTT station IDs absent from DB/buffer: %s",
                    sorted(db_stale_but_streaming),
                )
            online_station_ids.update(live_mqtt_station_ids)
            active_clusters, skipped_offline_station_ids = (
                restrict_clusters_to_online_stations(
                    active_clusters,
                    online_station_ids,
                )
            )
            # Wait for an idle repair already in flight, then reserve the
            # selected rovers before any startup/preflight await can race it.
            async with mqtt_service.round_robin_manager._idle_rover_recovery_lock:
                mqtt_service.round_robin_manager.configure_project(session_id, active_clusters)
                mqtt_service.round_robin_manager._sessions[session_id]["idle_recovery_reserved"] = True
            try:
                rover_preflight = (
                    await mqtt_service.round_robin_manager.ensure_rover_streams_ready(
                        session_id,
                        allow_unavailable=True,
                    )
                )
                excluded_codes = {
                    str(item.get("station_code") or "").casefold()
                    for item in rover_preflight
                    if str(item.get("status") or "").startswith("excluded_")
                }
                station_id_by_code = {
                    str(code).casefold(): int(station_id)
                    for cluster in active_clusters
                    for station_id, code in zip(
                        cluster.get("stations", []), cluster.get("rovers", []), strict=True
                    )
                }
                skipped_uncontrollable_station_ids = sorted({
                    station_id_by_code[code]
                    for code in excluded_codes
                    if code in station_id_by_code
                })
                if skipped_uncontrollable_station_ids:
                    active_clusters, _ = restrict_clusters_to_online_stations(
                        active_clusters,
                        {
                            int(station_id)
                            for cluster in active_clusters
                            for station_id in cluster.get("stations", [])
                        } - set(skipped_uncontrollable_station_ids),
                    )
                    # Rebuild only the in-memory session. Any verified receiver
                    # repair above is physical and remains in effect.
                    mqtt_service.round_robin_manager.configure_project(
                        session_id, active_clusters
                    )
                    mqtt_service.round_robin_manager._sessions[session_id]["idle_recovery_reserved"] = True
                # Scope monitoring isolation before the seed handover starts,
                # including scheduler runs whose session ID is not a project ID.
                mqtt_service.round_robin_manager._sessions[session_id]["monitoring_project_id"] = int(project.id)
                seed_topology = (
                    await mqtt_service.round_robin_manager.prepare_common_fixed_base_seed(
                        session_id
                    )
                )
            except Exception:
                failed_session = mqtt_service.round_robin_manager._sessions.get(
                    session_id
                )
                # Keep a failed restore snapshot reachable so a stop/retry can
                # restore the exact pre-adjustment service configuration.
                if not failed_session or not failed_session.get(
                    "seed_topology_snapshots"
                ):
                    mqtt_service.round_robin_manager.clear_project(session_id)
                raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Preserve coordinates and stream settings from project configuration.
        mqtt_service.active_adjustment_clusters[session_id] = active_clusters
        if not hasattr(mqtt_service, "adjustment_run_contexts"):
            mqtt_service.adjustment_run_contexts = {}
        if req.cluster_index is not None:
            cluster_index = req.cluster_index
        elif len(active_clusters) == 1 and isinstance(active_clusters[0], dict):
            cluster_index = next(
                (
                    index for index, configured in enumerate(project.gnss_clusters or [])
                    if str(configured.get("name") or "") == str(active_clusters[0].get("name") or "")
                ),
                None,
            )
        else:
            cluster_index = None

        mqtt_service.adjustment_run_contexts[session_id] = {
            "run_id": session_id,
            "started_at_ns": time.time_ns(),
            "project_id": int(project.id),
            "project_code": str(project.project_code or f"project-{project.id}"),
            "cluster_index": cluster_index,
            "cluster_name": (
                str(active_clusters[0].get("name") or "Cụm")
                if len(active_clusters) == 1 else "Nhiều cụm"
            ),
            "source": str(req.source or "manual"),
            "status": "COLLECTING_BASELINE",
        }
        logger.info(
            "Configured GNSS adjustment project=%s clusters=%s",
            req.project_id,
            [cluster.get("name") or cluster["stations"] for cluster in active_clusters],
        )

        # 1. Bật chế độ chờ thu thập Baseline (COLLECTING_BASELINE)
        mqtt_service.adjustment_phase[session_id] = "COLLECTING_BASELINE"
        mqtt_service.adjustment_phase[req.project_id] = "COLLECTING_BASELINE"
        mqtt_service.round_robin_manager._sessions[session_id].pop("idle_recovery_reserved", None)
        mqtt_service.adjustment_message[session_id] = (
            "Common fixed-base route is ready; waiting for source-verified #AGRICA "
            "baselines from every selected rover."
        )
        mqtt_service.adjustment_message[req.project_id] = mqtt_service.adjustment_message[session_id]
        mqtt_service.adjustment_results.pop(session_id, None)
        logger.info("Started GNSS adjustment project=%s run=%s cluster=%s", project.project_code, session_id, mqtt_service.adjustment_run_contexts[session_id]["cluster_name"])

        expected_station_ids = sorted({
            station_id
            for cluster in active_clusters
            for station_id in cluster["stations"]
        })
        skipped_uncontrollable_station_ids = locals().get(
            "skipped_uncontrollable_station_ids", []
        )
        roster = {
            "selected_station_ids": selected_station_ids_snapshot,
            "participating_station_ids": expected_station_ids,
            "skipped_offline_station_ids": skipped_offline_station_ids,
            "skipped_uncontrollable_station_ids": skipped_uncontrollable_station_ids,
        }
        mqtt_service.adjustment_run_rosters[session_id] = roster
        await ws_manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": req.project_id,
            "run_id": session_id,
            "cluster_name": mqtt_service.adjustment_run_contexts[session_id]["cluster_name"],
            "phase": "COLLECTING_BASELINE",
            "message": "Common fixed-base route is ready; waiting for source-verified #AGRICA baselines from every selected rover.",
            "expected_station_ids": expected_station_ids,
            "roster": roster,
            "skipped_offline_station_ids": skipped_offline_station_ids,
            "rover_preflight": rover_preflight,
            "seed_topology": seed_topology,
        })

        return {
            "status": "success",
            "run_id": session_id,
            "phase": "COLLECTING_BASELINE",
            "expected_station_ids": expected_station_ids,
            "roster": roster,
            "skipped_offline_station_ids": skipped_offline_station_ids,
            "rover_preflight": rover_preflight,
            "seed_topology": seed_topology,
            "message": "Both rover streams now use the selected physical base; waiting for verified baseline collection.",
        }
    except Exception as e:
        logger.error(f"Failed to start GNSS adjustment cycle: {e}")
        if (
            str(req.source or "manual") != "automatic_scheduler"
            and "project" in locals()
            and project is not None
            and not (isinstance(e, HTTPException) and e.status_code in {401, 403, 404})
        ):
            session_id = int(locals().get("session_id") or req.project_id)
            diagnostics = mqtt_service.round_robin_manager.get_adjustment_diagnostics(
                session_id
            )
            await write_adjustment_failure_report(
                int(project.id),
                e.detail if isinstance(e, HTTPException) else e,
                source=str(req.source or "manual"),
                project_code=str(project.project_code or f"project-{project.id}"),
                cluster_name=(
                    str(active_clusters[0].get("name") or "Cụm")
                    if "active_clusters" in locals() and len(active_clusters) == 1
                    else "Nhiều cụm"
                ),
                context={
                    "stage": "start_adjustment",
                    "run_id": session_id,
                    "cluster_index": req.cluster_index,
                    "stations": locals().get("selected_station_ids_snapshot", []),
                    "skipped_offline_station_ids": locals().get(
                        "skipped_offline_station_ids", []
                    ),
                    "skipped_uncontrollable_station_ids": locals().get(
                        "skipped_uncontrollable_station_ids", []
                    ),
                    "diagnostics": diagnostics,
                },
            )
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
        if phase in {"COMPLETED", "FAILED_QUALITY_GATE", "PARTIAL_FAILED", "ERROR"}
        else None
    )
    seed_status = None
    run_contexts = [
        dict(context)
        for context in getattr(mqtt_service, "adjustment_run_contexts", {}).values()
        if int(context.get("project_id") or 0) == int(project_id)
    ]
    if phase in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}:
        seed_status = {"runs": []}
        for context in run_contexts:
            run_id = int(context["run_id"])
            try:
                status = mqtt_service.round_robin_manager.get_seed_collection_status(run_id)
            except (KeyError, ValueError):
                status = None
            seed_status["runs"].append({**context, "seed_status": status})
    roster_by_run = getattr(mqtt_service, "adjustment_run_rosters", {})
    return {
        "project_id": project_id,
        "phase": phase,
        "message": message,
        "running": phase in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"},
        "paused": phase == "PAUSED",
        "runs": run_contexts,
        "roster": {
            "runs": [
                {**context, "roster": roster_by_run.get(int(context["run_id"])) or {}}
                for context in run_contexts
            ]
        },
        "seed_status": seed_status,
        "data": result,
    }


@router.post("/api/admin/gnss/adjustment/pause")
async def pause_gnss_adjustment(
    req: GnssAdjustmentControlRequest,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
):
    phase = str(mqtt_service.adjustment_phase.get(req.project_id) or "IDLE").upper()
    if phase not in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
        raise HTTPException(
            status_code=409,
            detail="Phiên bình sai chưa ở trạng thái có thể tạm dừng.",
        )
    run_ids = [
        int(context["run_id"])
        for context in getattr(mqtt_service, "adjustment_run_contexts", {}).values()
        if int(context.get("project_id") or 0) == int(req.project_id)
        and context.get("status") in {"COLLECTING_BASELINE", "FREE_NETWORK"}
    ] or [int(req.project_id)]
    paused_run_ids = [
        run_id for run_id in run_ids
        if mqtt_service.round_robin_manager.pause_project(run_id)
    ]
    if not paused_run_ids:
        raise HTTPException(status_code=409, detail="Phiên bình sai không còn chạy.")
    for run_id in paused_run_ids:
        session = mqtt_service.round_robin_manager._sessions.get(run_id) or {}
        session["phase_before_pause"] = str(mqtt_service.adjustment_phase.get(run_id) or phase)
        mqtt_service.adjustment_phase[run_id] = "PAUSED"
        if run_id in getattr(mqtt_service, "adjustment_run_contexts", {}):
            mqtt_service.adjustment_run_contexts[run_id]["status"] = "PAUSED"
    mqtt_service.adjustment_phase[req.project_id] = "PAUSED"
    mqtt_service.adjustment_message[req.project_id] = (
        "Đã yêu cầu tạm dừng; hệ thống sẽ dừng tại checkpoint an toàn kế tiếp."
    )
    await ws_manager.broadcast({
        "type": "gnss_adjustment_progress",
        "project_id": req.project_id,
        "phase": "PAUSED",
        "message": mqtt_service.adjustment_message[req.project_id],
        "roster": getattr(mqtt_service, "adjustment_run_rosters", {}).get(req.project_id) or {},
    })
    return {"status": "success", "phase": "PAUSED", "run_ids": paused_run_ids}


@router.post("/api/admin/gnss/adjustment/resume")
async def resume_gnss_adjustment(
    req: GnssAdjustmentControlRequest,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
):
    if str(mqtt_service.adjustment_phase.get(req.project_id) or "").upper() != "PAUSED":
        raise HTTPException(status_code=409, detail="Phiên bình sai không ở trạng thái tạm dừng.")
    run_ids = [
        int(context["run_id"])
        for context in getattr(mqtt_service, "adjustment_run_contexts", {}).values()
        if int(context.get("project_id") or 0) == int(req.project_id)
        and context.get("status") == "PAUSED"
    ] or [int(req.project_id)]
    resumed_run_ids = [
        run_id for run_id in run_ids
        if mqtt_service.round_robin_manager.resume_project(run_id)
    ]
    if not resumed_run_ids:
        raise HTTPException(status_code=409, detail="Phiên bình sai không còn chạy.")
    resumed_phases = []
    for run_id in resumed_run_ids:
        session = mqtt_service.round_robin_manager._sessions.get(run_id) or {}
        run_phase = str(session.pop("phase_before_pause", "FREE_NETWORK")).upper()
        if run_phase not in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
            run_phase = "FREE_NETWORK"
        resumed_phases.append(run_phase)
        mqtt_service.adjustment_phase[run_id] = run_phase
        if run_id in getattr(mqtt_service, "adjustment_run_contexts", {}):
            mqtt_service.adjustment_run_contexts[run_id]["status"] = run_phase
    resumed_phase = "FREE_NETWORK" if "FREE_NETWORK" in resumed_phases else "COLLECTING_BASELINE"
    mqtt_service.adjustment_phase[req.project_id] = resumed_phase
    mqtt_service.adjustment_message[req.project_id] = "Đã tiếp tục phiên bình sai từ checkpoint đã giữ."
    await ws_manager.broadcast({
        "type": "gnss_adjustment_progress",
        "project_id": req.project_id,
        "phase": resumed_phase,
        "message": mqtt_service.adjustment_message[req.project_id],
        "roster": getattr(mqtt_service, "adjustment_run_rosters", {}).get(req.project_id) or {},
    })
    return {"status": "success", "phase": resumed_phase, "run_ids": resumed_run_ids}


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
        run_ids = [
            int(context["run_id"])
            for context in getattr(mqtt_service, "adjustment_run_contexts", {}).values()
            if int(context.get("project_id") or 0) == int(req.project_id)
            and context.get("status") in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
        ] or [int(req.project_id)]
        for run_id in run_ids:
            running_task = mqtt_service.round_robin_manager.running_tasks.get(run_id)
            if running_task and not running_task.done():
                running_task.cancel()
                try:
                    await running_task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
        for run_id in run_ids:
            await mqtt_service.round_robin_manager.restore_common_fixed_base_topology(run_id)

        # Clear dynamic active adjustment clusters and phase
        for run_id in run_ids:
            mqtt_service.active_adjustment_clusters.pop(run_id, None)
            mqtt_service.adjustment_phase[run_id] = "STOPPED"
            getattr(mqtt_service, "adjustment_run_rosters", {}).pop(run_id, None)
            if run_id in getattr(mqtt_service, "adjustment_run_contexts", {}):
                mqtt_service.adjustment_run_contexts[run_id]["status"] = "STOPPED"
            mqtt_service.round_robin_manager.clear_project(run_id)
        mqtt_service.adjustment_phase[req.project_id] = "STOPPED"
        mqtt_service.adjustment_message[req.project_id] = "Phiên bình sai đã được dừng hẳn; cấu hình Base đã khôi phục."
        mqtt_service.adjustment_results.pop(req.project_id, None)
        logger.info("Cleared adjustment runs %s for project %s", run_ids, req.project_id)

        # 1. Gửi lệnh mở lại (wake) luồng RTCM của Base gốc qua MQTT tới CORS Dashboard
        topic = "ntrip/rtcm/start"
        payload = {
            "mountpoint": req.base_mountpoint,
            "client_instance_id": "landslide_system",
            "ttl_seconds": 300 # Đánh thức duy trì trong 5 phút hoặc lâu hơn
        }
        if req.caster_address:
            payload["caster_address"] = req.caster_address

        if not str(req.base_mountpoint or "").strip():
            logger.info(
                "Adjustment stop for project %s restored topology; no legacy wake mountpoint supplied",
                req.project_id,
            )
        elif mqtt_service.client and mqtt_service.client.is_connected():
            mqtt_service.client.publish(topic, json.dumps(payload), qos=1)
            logger.info(f"Published adjustment stop command (wake Base RTCM): {payload}")
        else:
            # The authoritative topology restore above already completed. A
            # missing legacy MQTT wake path must not turn a successful stop
            # into an apparent failure for the operator.
            logger.warning("MQTT unavailable; skipped optional legacy Base wake command")

        await ws_manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": req.project_id,
            "phase": "STOPPED",
            "message": mqtt_service.adjustment_message[req.project_id],
        })
        return {"status": "success", "phase": "STOPPED", "message": "Adjustment cycle stopped; fixed Base topology restored"}
    except Exception as e:
        logger.error(f"Failed to stop GNSS adjustment cycle: {e}")
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
