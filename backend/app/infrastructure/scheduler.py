import asyncio
import logging
from datetime import timedelta, timezone
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.future import select

from app.database import ConfigSessionLocal
from app.models.config import Project
from app.models import auth as model_auth
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
        current_user=model_auth.User(id=0, username="system", role="system", assigned_projects=[]),
    )


def _extract_cluster_runs(all_clusters: list, normalized_indices: set[int], project_id: int) -> list[dict]:
    cluster_runs = []
    for cluster_index, cluster in enumerate(all_clusters):
        if cluster_index not in normalized_indices:
            continue
        stations = cluster.get("stations", []) if isinstance(cluster, dict) else cluster
        cluster_name = (
            str(cluster.get("name") or f"Cụm {cluster_index + 1}")
            if isinstance(cluster, dict)
            else f"Cụm {cluster_index + 1}"
        )
        cluster_runs.append({
            "cluster_index": cluster_index,
            "cluster_name": cluster_name,
            "stations": list(stations or []),
            "run_id": -(int(project_id) * 1000 + cluster_index + 1),
        })
    return cluster_runs


async def _resolve_project_cluster_runs(project, project_id: int) -> tuple[str, list[dict], set[int]] | None:
    if not project:
        logger.error(f"Project {project_id} not found during scheduled adjustment.")
        return None

    config = project.auto_adjustment_config
    if not config or not config.get("enabled"):
        logger.info(f"Auto-adjustment for project {project_id} is disabled. Skipping.")
        return None

    selected_indices = config.get("selected_clusters", [])
    if not selected_indices:
        logger.info(f"No clusters selected for auto-adjustment in project {project_id}.")
        return None

    project_code = str(getattr(project, "project_code", None) or f"project-{project_id}")
    try:
        normalized_indices = {int(index) for index in selected_indices}
    except (TypeError, ValueError) as exc:
        logger.error("Invalid selected cluster indices for project %s: %r", project_id, selected_indices)
        await write_adjustment_failure_report(
            project_id, exc, source="automatic_scheduler",
            context={"selected_clusters": selected_indices, "stage": "validate_configuration"},
        )
        return None

    all_clusters = project.gnss_clusters or []
    cluster_runs = _extract_cluster_runs(all_clusters, normalized_indices, project_id)
    if not cluster_runs:
        logger.warning("No matching clusters found for indices %s in project %s.", selected_indices, project_id)
        return None

    return project_code, cluster_runs, normalized_indices


async def _check_cluster_overlaps(project_id: int, project_code: str, cluster_runs: list[dict], normalized_indices: set[int]) -> bool:
    station_owner: dict[str, str] = {}
    overlap_messages = []
    for cluster_run in cluster_runs:
        for station in cluster_run["stations"]:
            station_key = str(station).strip().casefold()
            previous = station_owner.get(station_key)
            if previous and previous != cluster_run["cluster_name"]:
                overlap_messages.append(f"{station}: {previous} / {cluster_run['cluster_name']}")
            else:
                station_owner[station_key] = cluster_run["cluster_name"]

    if overlap_messages:
        error = ValueError(
            "selected automatic clusters overlap and cannot safely control the same rover in parallel; "
            + "; ".join(overlap_messages)
        )
        await write_adjustment_failure_report(
            project_id, error, source="automatic_scheduler",
            project_code=project_code, cluster_name="configuration",
            context={"stage": "validate_parallel_clusters", "selected_clusters": sorted(normalized_indices)},
        )
        logger.error("Project %s: %s", project_code, error)
        return False
    return True


def _prepare_mqtt_contexts(mqtt_service, project_id: int, project_code: str, cluster_runs: list[dict]) -> bool:
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
        return False

    stale_items = list(getattr(mqtt_service, "adjustment_run_contexts", {}).items())
    for old_run_id, old_context in stale_items:
        if (
            int(old_context.get("project_id") or 0) == int(project_id)
            and old_context.get("status") not in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
        ):
            mqtt_service.adjustment_run_contexts.pop(old_run_id, None)
            mqtt_service.active_adjustment_clusters.pop(old_run_id, None)
            mqtt_service.adjustment_phase.pop(old_run_id, None)

    getattr(mqtt_service, "adjustment_cluster_results", {}).pop(int(project_id), None)
    for cluster_run in cluster_runs:
        mqtt_service.adjustment_run_contexts[cluster_run["run_id"]] = {
            **cluster_run,
            "project_id": int(project_id),
            "project_code": project_code,
            "source": "automatic_scheduler",
            "status": "STARTING",
        }
    return True


async def _start_single_cluster(cluster_run: dict, project_id: int, project_code: str, mqtt_service) -> dict | None:
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
        logger.exception(
            "Scheduled cluster failed to start project=%s cluster=%s: %s",
            project_code,
            cluster_run["cluster_name"],
            exc,
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
        mqtt_service.adjustment_run_contexts[cluster_run["run_id"]]["status"] = "ERROR"
        if failure_result is not None:
            failure_result["run_id"] = cluster_run["run_id"]
            mqtt_service.adjustment_cluster_results[int(project_id)][cluster_run["run_id"]] = failure_result
        return None


def _cleanup_failed_contexts(mqtt_service, cluster_runs) -> None:
    if not mqtt_service or not cluster_runs:
        return
    for cluster_run in cluster_runs:
        run_id = cluster_run["run_id"]
        context = getattr(mqtt_service, "adjustment_run_contexts", {}).get(run_id)
        if context and context.get("status") == "STARTING":
            getattr(mqtt_service, "adjustment_run_contexts", {}).pop(run_id, None)
            getattr(mqtt_service, "active_adjustment_clusters", {}).pop(run_id, None)
            getattr(mqtt_service, "adjustment_phase", {}).pop(run_id, None)


async def run_scheduled_adjustment(project_id: int):
    logger.info(f"Starting scheduled auto-adjustment for project {project_id}")
    cluster_runs = None
    mqtt_svc = None
    try:
        async with ConfigSessionLocal() as db_config:
            result = await db_config.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            resolved = await _resolve_project_cluster_runs(project, project_id)
            if not resolved:
                return
            project_code, cluster_runs, normalized_indices = resolved

            if not await _check_cluster_overlaps(project_id, project_code, cluster_runs, normalized_indices):
                return

            from app.runtime import mqtt_service
            mqtt_svc = mqtt_service
            if not _prepare_mqtt_contexts(mqtt_service, project_id, project_code, cluster_runs):
                return

            await asyncio.gather(*(_start_single_cluster(item, project_id, project_code, mqtt_service) for item in cluster_runs))
            refresh = getattr(mqtt_service, "_refresh_project_adjustment_state", None)
            if callable(refresh):
                refresh(int(project_id))

    except Exception as e:
        logger.exception(f"Error in scheduled auto-adjustment for project {project_id}: {e}")
        _cleanup_failed_contexts(mqtt_svc, cluster_runs)
        await write_adjustment_failure_report(
            project_id,
            e,
            source="automatic_scheduler",
            context={"stage": "start_adjustment"},
        )

def _schedule_single_hour(project_id: int, hour_str: str) -> None:
    try:
        parts = hour_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if len(parts) > 2 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("time must use HH:MM within a 24-hour day")

        job_id = f"auto_adj_{project_id}_{hour}_{minute}"
        scheduler.add_job(
            run_scheduled_adjustment,
            CronTrigger(hour=hour, minute=minute, timezone=VIETNAM_TIMEZONE),
            id=job_id,
            args=[project_id],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduled project %s auto-adjustment for %02d:%02d", project_id, hour, minute)
    except Exception as e:
        logger.exception("Invalid scheduled_hour %r for project %s: %s", hour_str, project_id, e)


def _schedule_project_jobs(project) -> None:
    config = project.auto_adjustment_config
    if not config or not config.get("enabled"):
        return
    for hour_str in config.get("scheduled_hours", []):
        _schedule_single_hour(project.id, hour_str)


async def reload_scheduler():
    logger.info("Reloading auto-adjustment schedules")
    scheduler.remove_all_jobs()

    try:
        async with ConfigSessionLocal() as db_config:
            result = await db_config.execute(select(Project).where(Project.is_active == True))
            projects = result.scalars().all()
            for project in projects:
                _schedule_project_jobs(project)
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
