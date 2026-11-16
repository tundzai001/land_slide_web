import asyncio
import logging
from datetime import timedelta, timezone
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.future import select

from app.database import ConfigSessionLocal
from app.models.config import Project
from app.features.gnss_adjustment.store import write_adjustment_failure_report

logger = logging.getLogger(__name__)

VIETNAM_TIMEZONE = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")
scheduler = AsyncIOScheduler(timezone=VIETNAM_TIMEZONE)
ACTIVE_ADJUSTMENT_STATUSES = {
    "STARTING",
    "COLLECTING_BASELINE",
    "FREE_NETWORK",
    "PAUSED",
}


async def _start_normal_adjustment(
    project_id: int,
    selected_clusters: list,
    db,
    *,
    run_id: int | None = None,
    cluster_index: int | None = None,
):
    """Enter the same validated workflow used by the manual admin action."""

    from app.features.gnss_adjustment.router import (
        GnssAdjustmentStartRequest,
        start_gnss_adjustment,
    )

    return await start_gnss_adjustment(
        GnssAdjustmentStartRequest(
            project_id=project_id,
            selected_clusters=selected_clusters,
            run_id=run_id,
            cluster_index=cluster_index,
            source="automatic_scheduler" if run_id is not None else "manual",
        ),
        db=db,
        current_user=SimpleNamespace(role="system", assigned_projects=[]),
    )


async def run_scheduled_adjustment(project_id: int):
    logger.info(f"Starting scheduled auto-adjustment for project {project_id}")
    try:
        # Load the project to get the configured clusters
        async with ConfigSessionLocal() as db_config:
            result = await db_config.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            if not project:
                logger.error(f"Project {project_id} not found during scheduled adjustment.")
                return

            config = project.auto_adjustment_config
            if not config or not config.get("enabled"):
                logger.info(f"Auto-adjustment for project {project_id} is disabled. Skipping.")
                return

            selected_indices = config.get("selected_clusters", [])
            all_clusters = project.gnss_clusters or []
            project_code = str(
                getattr(project, "project_code", None) or f"project-{project_id}"
            )

            if not selected_indices:
                logger.info(f"No clusters selected for auto-adjustment in project {project_id}.")
                return

            try:
                normalized_indices = {int(index) for index in selected_indices}
            except (TypeError, ValueError) as exc:
                logger.error(
                    "Invalid selected cluster indices for project %s: %r",
                    project_id,
                    selected_indices,
                )
                await write_adjustment_failure_report(
                    project_id,
                    exc,
                    source="automatic_scheduler",
                    context={
                        "selected_clusters": selected_indices,
                        "stage": "validate_configuration",
                    },
                )
                return

            filtered_clusters = [
                cluster
                for index, cluster in enumerate(all_clusters)
                if index in normalized_indices
            ]

            if not filtered_clusters:
                logger.warning(
                    "No matching clusters found for indices %s in project %s.",
                    selected_indices,
                    project_id,
                )
                return

            cluster_runs = []
            for cluster_index, cluster in enumerate(all_clusters):
                if cluster_index not in normalized_indices:
                    continue
                stations = (
                    cluster.get("stations", [])
                    if isinstance(cluster, dict)
                    else cluster
                )
                cluster_name = (
                    str(cluster.get("name") or f"Cụm {cluster_index + 1}")
                    if isinstance(cluster, dict)
                    else f"Cụm {cluster_index + 1}"
                )
                cluster_runs.append({
                    "cluster_index": cluster_index,
                    "cluster_name": cluster_name,
                    "stations": list(stations or []),
                    # Negative IDs cannot collide with persisted positive project IDs.
                    "run_id": -(int(project_id) * 1000 + cluster_index + 1),
                })

            station_owner: dict[str, str] = {}
            overlap_messages = []
            for cluster_run in cluster_runs:
                for station in cluster_run["stations"]:
                    station_key = str(station).strip().casefold()
                    previous = station_owner.get(station_key)
                    if previous and previous != cluster_run["cluster_name"]:
                        overlap_messages.append(
                            f"{station}: {previous} / {cluster_run['cluster_name']}"
                        )
                    else:
                        station_owner[station_key] = cluster_run["cluster_name"]
            if overlap_messages:
                error = ValueError(
                    "selected automatic clusters overlap and cannot safely control "
                    "the same rover in parallel; " + "; ".join(overlap_messages)
                )
                await write_adjustment_failure_report(
                    project_id,
                    error,
                    source="automatic_scheduler",
                    project_code=project_code,
                    cluster_name="configuration",
                    context={
                        "stage": "validate_parallel_clusters",
                        "selected_clusters": sorted(normalized_indices),
                    },
                )
                logger.error("Project %s: %s", project_code, error)
                return

            # Stable run IDs are reused by each schedule. Remove only finished
            # automatic contexts from the previous batch before starting this one.
            from app.runtime import mqtt_service
            active_existing = [
                context
                for context in getattr(mqtt_service, "adjustment_run_contexts", {}).values()
                if int(context.get("project_id") or 0) == int(project_id)
                and context.get("status") in ACTIVE_ADJUSTMENT_STATUSES
            ]
            if active_existing:
                logger.warning(
                    "⚠ Scheduled project %s SKIPPED — adjustment runs remain active: %s (statuses: %s)",
                    project_code,
                    [context.get("cluster_name") for context in active_existing],
                    [context.get("status") for context in active_existing],
                )
                return
            for old_run_id, old_context in list(
                getattr(mqtt_service, "adjustment_run_contexts", {}).items()
            ):
                if (
                    int(old_context.get("project_id") or 0) == int(project_id)
                    and old_context.get("status")
                        not in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
                ):
                    mqtt_service.adjustment_run_contexts.pop(old_run_id, None)
                    mqtt_service.active_adjustment_clusters.pop(old_run_id, None)
                    mqtt_service.adjustment_phase.pop(old_run_id, None)
            getattr(mqtt_service, "adjustment_cluster_results", {}).pop(
                int(project_id), None
            )
            for cluster_run in cluster_runs:
                mqtt_service.adjustment_run_contexts[cluster_run["run_id"]] = {
                    **cluster_run,
                    "project_id": int(project_id),
                    "project_code": project_code,
                    "source": "automatic_scheduler",
                    "status": "STARTING",
                }

            async def start_cluster(cluster_run: dict):
                try:
                    async with ConfigSessionLocal() as cluster_db:
                        response = await _start_normal_adjustment(
                            project_id,
                            [cluster_run["stations"]],
                            cluster_db,
                            run_id=cluster_run["run_id"],
                            cluster_index=cluster_run["cluster_index"],
                        )
                    logger.info(
                        "Scheduled cluster accepted project=%s cluster=%s run=%s phase=%s",
                        project_code,
                        cluster_run["cluster_name"],
                        cluster_run["run_id"],
                        response.get("phase"),
                    )
                    return response
                except Exception as exc:
                    logger.error(
                        "Scheduled cluster failed to start project=%s cluster=%s: %s",
                        project_code,
                        cluster_run["cluster_name"],
                        exc,
                        exc_info=True,
                    )
                    failure_result = await write_adjustment_failure_report(
                        project_id,
                        exc,
                        source="automatic_scheduler",
                        project_code=project_code,
                        cluster_name=cluster_run["cluster_name"],
                        context={
                            "stage": "start_adjustment",
                            "cluster_index": cluster_run["cluster_index"],
                            "run_id": cluster_run["run_id"],
                            "stations": cluster_run["stations"],
                        },
                    )
                    mqtt_service.adjustment_run_contexts[
                        cluster_run["run_id"]
                    ]["status"] = "ERROR"
                    if failure_result is not None:
                        failure_result["run_id"] = cluster_run["run_id"]
                        mqtt_service.adjustment_cluster_results[int(project_id)][
                            cluster_run["run_id"]
                        ] = failure_result
                    return None

            # Disjoint clusters own different receivers/mountpoints, so start
            # every selected cluster at the scheduled instant. The topology
            # manager keeps its short hardware reconfiguration section locked.
            await asyncio.gather(*(start_cluster(item) for item in cluster_runs))
            refresh = getattr(mqtt_service, "_refresh_project_adjustment_state", None)
            if callable(refresh):
                refresh(int(project_id))

    except Exception as e:
        logger.error(f"Error in scheduled auto-adjustment for project {project_id}: {e}", exc_info=True)
        # Clean up any STARTING contexts that were registered before the failure
        if 'cluster_runs' in locals() and 'mqtt_service' in locals():
            for cluster_run in cluster_runs:
                run_id = cluster_run["run_id"]
                context = getattr(mqtt_service, "adjustment_run_contexts", {}).get(run_id)
                if context and context.get("status") == "STARTING":
                    getattr(mqtt_service, "adjustment_run_contexts", {}).pop(run_id, None)
                    getattr(mqtt_service, "active_adjustment_clusters", {}).pop(run_id, None)
                    getattr(mqtt_service, "adjustment_phase", {}).pop(run_id, None)
        await write_adjustment_failure_report(
            project_id,
            e,
            source="automatic_scheduler",
            context={"stage": "start_adjustment"},
        )

async def reload_scheduler():
    logger.info("Reloading auto-adjustment schedules")
    scheduler.remove_all_jobs()

    try:
        async with ConfigSessionLocal() as db_config:
            result = await db_config.execute(select(Project).where(Project.is_active == True))
            projects = result.scalars().all()

            for project in projects:
                config = project.auto_adjustment_config
                if config and config.get("enabled"):
                    scheduled_hours = config.get("scheduled_hours", [])
                    for hour_str in scheduled_hours:
                        try:
                            # Parse "HH:MM"
                            parts = hour_str.split(":")
                            hour = int(parts[0])
                            minute = int(parts[1]) if len(parts) > 1 else 0
                            if (
                                len(parts) > 2
                                or not 0 <= hour <= 23
                                or not 0 <= minute <= 59
                            ):
                                raise ValueError(
                                    "time must use HH:MM within a 24-hour day"
                                )

                            job_id = f"auto_adj_{project.id}_{hour}_{minute}"
                            scheduler.add_job(
                                run_scheduled_adjustment,
                                CronTrigger(
                                    hour=hour,
                                    minute=minute,
                                    timezone=VIETNAM_TIMEZONE,
                                ),
                                id=job_id,
                                args=[project.id],
                                replace_existing=True,
                                coalesce=True,
                                max_instances=1,
                            )
                            logger.info(
                                "Scheduled project %s auto-adjustment for %02d:%02d",
                                project.id,
                                hour,
                                minute,
                            )
                        except Exception as e:
                            logger.exception(
                                "Invalid scheduled_hour %r for project %s: %s",
                                hour_str,
                                project.id,
                                e,
                            )
    except Exception as e:
        logger.exception(f"Failed to reload schedules: {e}")


async def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Auto-adjustment scheduler started.")
    await reload_scheduler()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Auto-adjustment scheduler stopped.")
