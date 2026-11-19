# ==============================================================================
# == backend/app/main.py   ==
# ==============================================================================

import logging
import asyncio
import copy
import time
import sys
import os
import mimetypes
from pathlib import Path

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/javascript', '.jsx')
mimetypes.add_type('text/css', '.css')
# Force utf-8 for text files to fix mojibake on Windows
mimetypes.init()
mimetypes.types_map['.js'] = 'application/javascript; charset=utf-8'
mimetypes.types_map['.jsx'] = 'application/javascript; charset=utf-8'
mimetypes.types_map['.css'] = 'text/css; charset=utf-8'
mimetypes.types_map['.html'] = 'text/html; charset=utf-8'

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent

from contextlib import asynccontextmanager, suppress
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from .logging_config import (
    configure_system_logging,
    disable_windows_quick_edit_mode,
    install_heartbeat_filter,
)
from .middleware import CharsetMiddleware, VersionedAssetCacheMiddleware
from .errors import install_error_handlers, operation_phase_label

configure_system_logging()
disable_windows_quick_edit_mode()
install_heartbeat_filter()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import các module nội bộ
from . import auth, config
from .database import (
    auth_engine, config_engine, data_engine,
    AuthSessionLocal, ConfigSessionLocal, DataSessionLocal
)
from .features.authentication import router as authentication_router
from .features.database_admin import router as database_admin_router
from .features.devices import router as devices_router
from .features.projects import cors_stations as cors_stations_router
from .features.field import router as field_router
from .features.field import provisioning_router as field_provisioning_router
from .features.frontend import router as frontend_router
from .features.data_export import router as data_export_router
from .features.database_admin import maintenance_router as database_maintenance_router
from .features.devices import admin_router as device_admin_router
from .features.gnss_adjustment import router as gnss_adjustment_router
from .features.projects import router as projects_router
from .features.rescue import router as rescue_router
from .features.stations import admin_router as station_admin_router
from .features.users import router as users_router
from .features.stations import router as stations_router
from .features.simulation import router as simulations_router
from .features.incidents import router as incidents_router
from .features.health import router as health_router
from .features.operations import router as operations_router
from .features.operations.audit import AuditMiddleware
from .features.operations.backups import daemon as run_backup_daemon
from .features.operations.backups import recover_interrupted_jobs
from .features.operations import store as operations_store
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data
from .models.pi_device import PiDevice  # noqa: F401 – ensures table is registered
from .runtime import analyzer, cors_failover_status, mqtt_service
from .features.gnss_monitoring.rollup import run_gnss_daily_rollup_daemon
from .infrastructure.file_cleanup import run_file_cleanup_daemon

# Import security core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from security_core import AdvancedSecurityMiddleware

logger = logging.getLogger(__name__)

# Tắt log spam cho /api/field/heartbeat của Uvicorn
# ============================================================================
# GLOBAL INSTANCES
# ============================================================================
gnss_rollup_task: Optional[asyncio.Task] = None
cors_failover_task: Optional[asyncio.Task] = None
file_cleanup_task: Optional[asyncio.Task] = None
backup_task: Optional[asyncio.Task] = None


async def run_cors_fixed_base_failover_daemon():
    """Continuously enforce configured cross-station S1/S2 failover pairs."""

    poll_seconds = max(
        2.0,
        float(config.settings.GNSS_CORS_FAILOVER_POLL_SECONDS),
    )
    retry_seconds = poll_seconds
    last_error_kind = None
    last_error_log_at = 0.0
    while True:
        try:
            async with ConfigSessionLocal() as db_config:
                result = await db_config.execute(
                    select(model_config.Project).where(
                        model_config.Project.is_active.is_(True)
                    )
                )
                clusters = []
                for project in result.scalars().all():
                    for raw_cluster in project.gnss_clusters or []:
                        if isinstance(raw_cluster, dict) and raw_cluster.get(
                            "backup_base_station"
                        ):
                            cluster = copy.deepcopy(raw_cluster)
                            cluster["project_id"] = int(project.id)
                            clusters.append(cluster)
            cors_failover_status[:] = await (
                mqtt_service.round_robin_manager.reconcile_cors_failover_pairs(clusters)
            )
            if last_error_kind is not None:
                logger.info("CORS fixed-base failover connection recovered")
            retry_seconds = poll_seconds
            last_error_kind = None
            await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            logger.info("CORS fixed-base failover daemon cancelled")
            raise
        except Exception as exc:
            retry_seconds = min(max(60.0, poll_seconds), retry_seconds * 2.0)
            now = time.monotonic()
            detail = str(exc).strip() or type(exc).__name__
            error_kind = detail.split(':', 1)[0]
            if error_kind != last_error_kind or now - last_error_log_at >= 300.0:
                logger.warning("CORS fixed-base failover unavailable; retry in %.0fs: %s",
                               retry_seconds, detail.splitlines()[0][:240])
                last_error_log_at = now
            last_error_kind = error_kind
            await asyncio.sleep(retry_seconds)


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================
@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.settings.validate_security()
    if config.settings.MQTT_BROKER and not config.settings.MQTT_PASSWORD:
        logger.warning("MQTT_PASSWORD is unset; broker connection will attempt anonymous authentication")
    logger.info("🚀 Landslide Monitoring System starting...")
    if not config.settings.BACKUP_SIGNING_KEY:
        logger.warning("BACKUP_SIGNING_KEY is unset; backup manifests use SECRET_KEY")

    global gnss_rollup_task, cors_failover_task, file_cleanup_task, backup_task

    try:
        try:
            await asyncio.to_thread(recover_interrupted_jobs)
            await asyncio.to_thread(operations_store.append, 'operation_log', 'service.starting')
        except Exception:
            logger.critical('Operations PostgreSQL store unavailable at startup', exc_info=True)
        # Production startup must not acquire DDL locks. Fresh development
        # environments can opt in; production schema changes use Alembic.
        if config.settings.RUN_SCHEMA_BOOTSTRAP:
            for engine, metadata, label in (
                (auth_engine, model_auth.BaseAuth.metadata, "auth"),
                (config_engine, model_config.BaseConfig.metadata, "config"),
                (data_engine, model_data.BaseData.metadata, "data"),
            ):
                async with engine.begin() as conn:
                    await conn.run_sync(metadata.create_all)
                logger.info("Database schema bootstrap complete: %s", label)

        try:
            from .shared.project_location import backfill_project_map_positions
            async with asyncio.timeout(30):
                async with ConfigSessionLocal() as db_config:
                    await backfill_project_map_positions(db_config)

            interrupted = await simulations_router.recover_interrupted_runs()
            if interrupted:
                logger.warning("Marked %s unfinished simulation run(s) as interrupted", interrupted)

            # 4. Tạo Admin mặc định
            async with asyncio.timeout(10):
                async with AuthSessionLocal() as db_auth:
                    result = await db_auth.execute(
                        select(model_auth.User).where(model_auth.User.username == "admin")
                    )
                    admin_user = result.scalar_one_or_none()

                    if not admin_user and config.settings.BOOTSTRAP_ADMIN_PASSWORD:
                        hashed_password = await auth.get_password_hash(
                            config.settings.BOOTSTRAP_ADMIN_PASSWORD
                        )
                        new_admin = model_auth.User(
                            username="admin",
                            hashed_password=hashed_password,
                            role="admin",
                            full_name="Administrator",
                            is_active=True
                        )
                        db_auth.add(new_admin)
                        await db_auth.commit()
                        logger.info("Bootstrap admin user created")
                    elif not admin_user:
                        logger.warning(
                            "No admin user exists; set BOOTSTRAP_ADMIN_PASSWORD once to create it"
                        )

            # System Access was retired: purge browser-managed credentials and
            # global runtime overrides left by older deployments. Server settings
            # are now sourced only from the deployment environment.
            async with asyncio.timeout(10):
                async with ConfigSessionLocal() as db_config:
                    legacy_keys = {
                        "system_password",
                        "main_config",
                        "confirmation_config",
                        "save_intervals_config",
                    }
                    result = await db_config.execute(
                        delete(model_config.GlobalConfig).where(
                            model_config.GlobalConfig.key.in_(legacy_keys)
                        )
                    )
                    await db_config.commit()
                    if result.rowcount:
                        logger.warning(
                            "Removed %s retired System Access configuration record(s)",
                            result.rowcount,
                        )
        except Exception as exc:
            # Keep liveness available while /api/health/ready reports the
            # unavailable databases as degraded. A transient DB outage must not
            # make the whole HTTP process exit during startup.
            logger.warning(
                "Database startup tasks skipped; service is degraded until DB recovers: %s",
                exc,
            )

        mqtt_service.start()
        logger.info("MQTT background workers scheduled; broker status is reported by connection callbacks")

        from .infrastructure.scheduler import start_scheduler
        await start_scheduler()

        gnss_rollup_task = asyncio.create_task(run_gnss_daily_rollup_daemon())
        cors_failover_task = asyncio.create_task(
            run_cors_fixed_base_failover_daemon()
        )
        file_cleanup_task = asyncio.create_task(run_file_cleanup_daemon())
        backup_task = asyncio.create_task(run_backup_daemon())
        logger.info("✓ GNSS rollup daemon started")

        logger.info("=" * 60)
        logger.info("🎉 System ready to serve!")
        logger.info("=" * 60)

        yield

    finally:
        logger.info("🛑 Shutting down...")
        from .infrastructure.scheduler import stop_scheduler
        stop_scheduler()
        if backup_task and not backup_task.done():
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task
        if gnss_rollup_task and not gnss_rollup_task.done():
            gnss_rollup_task.cancel()
            with suppress(asyncio.CancelledError):
                await gnss_rollup_task
        if cors_failover_task and not cors_failover_task.done():
            cors_failover_task.cancel()
            with suppress(asyncio.CancelledError):
                await cors_failover_task
        if file_cleanup_task and not file_cleanup_task.done():
            file_cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await file_cleanup_task
        # Stop MQTT producers and await their DB work before disposing pools.
        # Otherwise Paho callbacks can enqueue writes into closing asyncpg
        # connections and leave unobserved Future exceptions behind.
        await mqtt_service.stop()
        await auth_engine.dispose()
        await config_engine.dispose()
        await data_engine.dispose()
        logger.info("✅ Shutdown complete")
        try:
            await asyncio.to_thread(operations_store.append, 'operation_log', 'service.stopped')
        except Exception:
            logger.critical('Operations PostgreSQL store unavailable at shutdown', exc_info=True)
        operations_store.dispose()

# ============================================================================
# FASTAPI APPLICATION SETUP
# ============================================================================
app = FastAPI(title="Landslide System API", lifespan=lifespan)
install_error_handlers(app)


@app.exception_handler(TimeoutError)
@app.exception_handler(SQLAlchemyTimeoutError)
async def timeout_exception_handler(request: Request, exc: Exception):
    """Return a bounded outage response instead of an ASGI traceback storm."""

    phase = getattr(request.state, "operation_phase", "dependencies")
    request_id = getattr(request.state, "request_id", "unknown")
    phase_label = operation_phase_label(phase)
    logger.warning(
        "Request timed out request_id=%s method=%s path=%s phase=%s (%s) error=%s",
        request_id,
        request.method,
        request.url.path,
        phase,
        phase_label,
        exc.__class__.__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "A required backend service timed out; retry shortly.",
            "retryable": True,
            "phase": phase,
            "phase_label": phase_label,
            "request_id": request_id,
        },
        headers={"Retry-After": "5", "X-Operation-Phase": phase},
    )

# Add Security and Performance Middlewares
app.add_middleware(AdvancedSecurityMiddleware)
app.add_middleware(CharsetMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(VersionedAssetCacheMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
# CORSMiddleware must be added last so it is the outermost middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "ETag", "Server-Timing", "X-Request-ID", "X-Operation-Phase",
        "X-Total-Count", "X-Offset", "X-Limit", "X-Has-More",
    ],
)
app.include_router(authentication_router.router)
app.include_router(users_router.router)
app.include_router(device_admin_router.router)
app.include_router(station_admin_router.router)
app.include_router(database_maintenance_router.router)
app.include_router(data_export_router.router)
app.include_router(database_admin_router.router)
app.include_router(devices_router.router)
app.include_router(cors_stations_router.router)
app.include_router(field_router.router)
app.include_router(field_provisioning_router.router)
app.include_router(frontend_router.router)
app.include_router(gnss_adjustment_router.router)
app.include_router(projects_router.router)
app.include_router(rescue_router.router)
app.include_router(stations_router.router)
app.include_router(simulations_router.router)
app.include_router(incidents_router.router)
app.include_router(health_router.router)
app.include_router(operations_router.router)

# ADMIN - PROJECTS API
# ============================================================================
# ============================================================================
# ADMIN - STATIONS API
# ============================================================================

# =====================
# Field Unit Provisioning API
# =====================
# Only compiled/minified browser assets are public. Source JSX, templates and
# feature modules remain outside the HTTP surface and are used only at build time.
app.mount(
    "/assets",
    StaticFiles(directory=PROJECT_ROOT / "frontend" / "dist"),
    name="frontend-assets",
)
