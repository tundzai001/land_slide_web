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
from .routers import admin as admin_router
from .routers import authentication as authentication_router
from .routers import database_admin as database_admin_router
from .routers import devices as devices_router
from .routers import cors_stations as cors_stations_router
from .routers import field as field_router
from .routers import field_provisioning as field_provisioning_router
from .routers import frontend as frontend_router
from .routers import gnss_adjustment as gnss_adjustment_router
from .routers import projects as projects_router
from .routers import rescue as rescue_router
from .routers import stations as stations_router
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data
from .models.pi_device import PiDevice  # noqa: F401 – ensures table is registered
from .runtime import analyzer, cors_failover_status, mqtt_service
from .services.gnss_rollup import run_gnss_daily_rollup_daemon

# Import security core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from security_core import AdvancedSecurityMiddleware, start_ipc_server

logger = logging.getLogger(__name__)

# Tắt log spam cho /api/field/heartbeat của Uvicorn
# ============================================================================
# GLOBAL INSTANCES
# ============================================================================
gnss_rollup_task: Optional[asyncio.Task] = None
cors_failover_task: Optional[asyncio.Task] = None


async def run_cors_fixed_base_failover_daemon():
    """Continuously enforce configured cross-station S1/S2 failover pairs."""

    poll_seconds = max(
        2.0,
        float(config.settings.GNSS_CORS_FAILOVER_POLL_SECONDS),
    )
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
            await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            logger.info("CORS fixed-base failover daemon cancelled")
            raise
        except Exception as exc:
            logger.error(
                "CORS fixed-base failover reconciliation failed: %s",
                exc,
                exc_info=True,
            )
            await asyncio.sleep(poll_seconds)


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Landslide Monitoring System starting...")

    # Start the Security IPC Server as a background task
    asyncio.create_task(start_ipc_server())
    global gnss_rollup_task, cors_failover_task

    try:
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

        async with asyncio.timeout(10):
            async with ConfigSessionLocal() as db_config:
                result = await db_config.execute(
                    select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "system_password")
                )
                sys_pass_config = result.scalar_one_or_none()

                if not sys_pass_config and config.settings.BOOTSTRAP_SYSTEM_PASSWORD:
                    new_config = model_config.GlobalConfig(
                        key="system_password",
                        value=config.settings.BOOTSTRAP_SYSTEM_PASSWORD,
                        updated_at=int(time.time()),
                        updated_by="system_init"
                    )
                    db_config.add(new_config)
                    await db_config.commit()
                    logger.info("Bootstrap system password created")
                elif not sys_pass_config:
                    logger.warning(
                        "No system password exists; set BOOTSTRAP_SYSTEM_PASSWORD once to create it"
                    )

        mqtt_service.start()
        logger.info("✓ Background MQTT Service started")

        from .services.scheduler import start_scheduler
        await start_scheduler()

        gnss_rollup_task = asyncio.create_task(run_gnss_daily_rollup_daemon())
        cors_failover_task = asyncio.create_task(
            run_cors_fixed_base_failover_daemon()
        )
        logger.info("✓ GNSS rollup daemon started")

        logger.info("=" * 60)
        logger.info("🎉 System ready to serve!")
        logger.info("=" * 60)

        yield

    finally:
        logger.info("🛑 Shutting down...")
        from .services.scheduler import stop_scheduler
        stop_scheduler()
        if gnss_rollup_task and not gnss_rollup_task.done():
            gnss_rollup_task.cancel()
            with suppress(asyncio.CancelledError):
                await gnss_rollup_task
        if cors_failover_task and not cors_failover_task.done():
            cors_failover_task.cancel()
            with suppress(asyncio.CancelledError):
                await cors_failover_task
        await auth_engine.dispose()
        await config_engine.dispose()
        await data_engine.dispose()
        mqtt_service.stop()
        logger.info("✅ Shutdown complete")

# ============================================================================
# FASTAPI APPLICATION SETUP
# ============================================================================
app = FastAPI(title="Landslide System API", lifespan=lifespan)


@app.exception_handler(TimeoutError)
@app.exception_handler(SQLAlchemyTimeoutError)
async def timeout_exception_handler(_request: Request, exc: Exception):
    """Return a bounded outage response instead of an ASGI traceback storm."""

    logger.warning("Request dependency timed out: %s", exc.__class__.__name__)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "A required backend service timed out; retry shortly.",
            "retryable": True,
        },
        headers={"Retry-After": "5"},
    )

# Add Security Middleware FIRST (Before CORS or Routing)
app.add_middleware(AdvancedSecurityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "ETag", "Server-Timing", "X-Request-ID",
        "X-Total-Count", "X-Offset", "X-Limit",
    ],
)
app.add_middleware(CharsetMiddleware)
app.include_router(admin_router.router)
app.include_router(authentication_router.router)
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

# ── Anti-cache middleware for frontend assets ──
app.add_middleware(VersionedAssetCacheMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

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
