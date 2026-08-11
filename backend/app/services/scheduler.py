import logging
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.future import select

from app.database import ConfigSessionLocal
from app.models.config import Project

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


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

            if not selected_indices:
                logger.info(f"No clusters selected for auto-adjustment in project {project_id}.")
                return

            try:
                normalized_indices = {int(index) for index in selected_indices}
            except (TypeError, ValueError):
                logger.error(
                    "Invalid selected cluster indices for project %s: %r",
                    project_id,
                    selected_indices,
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

            # Reuse the public workflow entry point. It prepares the fixed-base
            # topology and waits for verified AGRICA seeds before round-robin starts.
            from app.routers.gnss_adjustment import (
                GnssAdjustmentStartRequest,
                start_gnss_adjustment,
            )

            selected_clusters = []
            for cluster in filtered_clusters:
                stations = (
                    cluster.get("stations", [])
                    if isinstance(cluster, dict)
                    else cluster
                )
                selected_clusters.append(list(stations or []))

            response = await start_gnss_adjustment(
                GnssAdjustmentStartRequest(
                    project_id=project_id,
                    selected_clusters=selected_clusters,
                ),
                db=db_config,
                current_user=SimpleNamespace(role="system", assigned_projects=[]),
            )
            logger.info(
                "Scheduled auto-adjustment accepted for project %s "
                "(phase=%s, existing=%s)",
                project_id,
                response.get("phase"),
                response.get("existing", False),
            )

    except Exception as e:
        logger.error(f"Error in scheduled auto-adjustment for project {project_id}: {e}", exc_info=True)

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
                                CronTrigger(hour=hour, minute=minute),
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
                            logger.error(
                                "Invalid scheduled_hour %r for project %s: %s",
                                hour_str,
                                project.id,
                                e,
                            )
    except Exception as e:
        logger.error(f"Failed to reload schedules: {e}")


async def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Auto-adjustment scheduler started.")
    await reload_scheduler()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Auto-adjustment scheduler stopped.")
