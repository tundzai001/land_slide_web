# ==============================================================================
# == backend/app/main.py   ==
# ==============================================================================

import logging
import asyncio
import copy
import json
import time
import math
import sys
import os
import mimetypes

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
# Force utf-8 for text files to fix mojibake on Windows
mimetypes.init()
mimetypes.types_map['.js'] = 'application/javascript; charset=utf-8'
mimetypes.types_map['.css'] = 'text/css; charset=utf-8'
mimetypes.types_map['.html'] = 'text/html; charset=utf-8'

import base64
import binascii
import hashlib
import uuid
import requests
from contextlib import asynccontextmanager, suppress
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, delete, text

CORS_BASE_STATIONS_URL = "https://cors.aitogy.com/api/public/map-stations"
CORS_BASE_STATION_NAMES = {"SinQuyen1", "SinQuyen2"}


def is_offline_display_enabled(station_config: Optional[Dict[str, Any]]) -> bool:
    cfg = station_config or {}
    return bool(
        cfg.get("offline_display_enabled") is True or
        cfg.get("offline_display", {}).get("enabled") is True
    )


async def get_optional_current_user_from_request(
    request: Request,
    db: AsyncSession,
) -> Optional[Any]:
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = auth.jwt.decode(token, config.settings.SECRET_KEY, algorithms=[config.settings.ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        result = await db.execute(select(model_auth.User).where(model_auth.User.username == username))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        return user
    except Exception:
        return None


def user_project_filter_ids(user: Optional[Any]) -> Optional[set]:
    if user is None or user.role == "admin":
        return None
    assigned = getattr(user, "assigned_projects", None) or []
    if user.role == "viewer" and not assigned:
        return None
    return {int(project_id) for project_id in assigned}

LOG_FILE_NAME = 'landslide_system.log'
_ORIGINAL_STDOUT = sys.__stdout__
_ORIGINAL_STDERR = sys.__stderr__


class _LoggerWriter:
    """File-like adapter that redirects print/traceback output to logging."""
    def __init__(self, log_method):
        self.log_method = log_method
        self._buffer = ''

    def write(self, message):
        if not message:
            return 0
        self._buffer += str(message)
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            clean_line = line.rstrip()
            if clean_line:
                self.log_method(clean_line)
        return len(message)

    def flush(self):
        clean_line = self._buffer.rstrip()
        if clean_line:
            self.log_method(clean_line)
        self._buffer = ''

    def isatty(self):
        return False


def _configure_system_logging() -> None:
    if os.name == 'nt':
        os.system('chcp 65001 >nul')
    if hasattr(_ORIGINAL_STDOUT, "reconfigure"):
        try:
            _ORIGINAL_STDOUT.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE_NAME, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(_ORIGINAL_STDOUT)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    logging.captureWarnings(True)

    # Force uvicorn/fastapi logs to reuse root handlers (same file).
    for logger_name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'fastapi'):
        uv_logger = logging.getLogger(logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
        uv_logger.setLevel(logging.INFO)

    # Keep stdio untouched. Redirecting sys.stdout/sys.stderr through logging can
    # recurse when logging itself raises during startup, which hides the real error.


def _disable_windows_quick_edit_mode() -> None:
    """Prevent accidental console clicks from pausing the process on Windows."""
    if os.name != 'nt':
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        std_input_handle = -10  # STD_INPUT_HANDLE
        handle = kernel32.GetStdHandle(std_input_handle)
        if handle in (0, -1):
            return

        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return

        enable_quick_edit = 0x0040
        enable_extended_flags = 0x0080
        new_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit
        if new_mode != mode.value:
            kernel32.SetConsoleMode(handle, new_mode)
            logging.getLogger(__name__).info('Windows Quick Edit mode disabled for stable runtime.')
    except Exception as e:
        logging.getLogger(__name__).warning(f'Cannot disable Quick Edit mode: {e}')


_configure_system_logging()
_disable_windows_quick_edit_mode()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mqtt_bridge import MQTTBridge

# Import các module nội bộ
from . import schemas, auth, config
from .database import (
    auth_engine, config_engine, data_engine,
    get_auth_db, get_config_db, get_data_db,
    AuthSessionLocal, ConfigSessionLocal, DataSessionLocal
)
from .routers import admin as admin_router
from .routers import field as field_router
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data
from .models.pi_device import PiDevice  # noqa: F401 – ensures table is registered
from .websocket import manager as ws_manager
from .landslide_analyzer import LandslideAnalyzer

# Import security core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from security_core import AdvancedSecurityMiddleware, start_ipc_server

logger = logging.getLogger(__name__)

# Tắt log spam cho /api/field/heartbeat của Uvicorn
class HeartbeatFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/field/heartbeat" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(HeartbeatFilter())

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================
analyzer = LandslideAnalyzer()
mqtt_service = MQTTBridge()
gnss_rollup_task: Optional[asyncio.Task] = None
cors_failover_task: Optional[asyncio.Task] = None
cors_failover_status: list[dict] = []


def _utc_day_start(ts: int) -> int:
    return (int(ts) // 86400) * 86400


def _map_gnss_daily_risk(classification: str) -> str:
    cls_upper = str(classification or "").upper()
    if any(c in cls_upper for c in ("EXTREMELY RAPID", "VERY RAPID", "RAPID")):
        return "CRITICAL"
    if "MODERATE" in cls_upper:
        return "HIGH"
    if "SLOW" in cls_upper:
        return "MEDIUM"
    return "LOW"


async def _upsert_gnss_weekly_summary(station_id: int, ending_day_start_ts: int):
    """Tạo summary tuần từ 7 ngày daily gần nhất (liên tiếp) cho station."""
    week_end_ts = ending_day_start_ts + 86400
    async with DataSessionLocal() as db_data:
        res = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_end_ts <= week_end_ts,
                    model_data.GnssDailySummary.status == "success"
                )
            )
            .order_by(model_data.GnssDailySummary.day_start_ts.desc())
            .limit(7)
        )
        days = list(reversed(res.scalars().all()))

        if len(days) < 7:
            return

        # Bắt buộc 7 ngày liên tiếp
        for i in range(1, len(days)):
            if days[i].day_start_ts - days[i - 1].day_start_ts != 86400:
                return

        week_start_ts = days[0].day_start_ts
        now_ts = int(time.time())
        total_disp_mm = float(sum(float(d.net_displacement_mm or 0.0) for d in days))
        avg_vel_mm_day = float(sum(float(d.velocity_mm_day or 0.0) for d in days)) / 7.0
        max_vel_mm_day = float(max(float(d.velocity_mm_day or 0.0) for d in days))
        min_vel_mm_day = float(min(float(d.velocity_mm_day or 0.0) for d in days))
        vel_mm_second = avg_vel_mm_day / 86400.0
        vel_mm_year = avg_vel_mm_day * 365.0
        classification = analyzer._classify_velocity_extended(
            vel_mm_second,
            avg_vel_mm_day,
            vel_mm_year,
            {}
        )
        risk_level = _map_gnss_daily_risk(classification)
        is_safe = risk_level in ("LOW", "MEDIUM")

        existing_res = await db_data.execute(
            select(model_data.GnssWeeklySummary).where(
                and_(
                    model_data.GnssWeeklySummary.station_id == station_id,
                    model_data.GnssWeeklySummary.week_start_ts == week_start_ts,
                    model_data.GnssWeeklySummary.week_end_ts == week_end_ts,
                )
            )
        )
        existing = existing_res.scalar_one_or_none()

        if existing:
            existing.day_count = 7
            existing.total_displacement_mm = round(total_disp_mm, 3)
            existing.avg_velocity_mm_day = round(avg_vel_mm_day, 6)
            existing.max_velocity_mm_day = round(max_vel_mm_day, 6)
            existing.min_velocity_mm_day = round(min_vel_mm_day, 6)
            existing.classification = str(classification)
            existing.risk_level = risk_level
            existing.is_safe = is_safe
            existing.status = "success"
            existing.message = "Weekly summary computed from 7 consecutive daily summaries."
            existing.updated_at = now_ts
        else:
            db_data.add(model_data.GnssWeeklySummary(
                station_id=station_id,
                week_start_ts=week_start_ts,
                week_end_ts=week_end_ts,
                day_count=7,
                total_displacement_mm=round(total_disp_mm, 3),
                avg_velocity_mm_day=round(avg_vel_mm_day, 6),
                max_velocity_mm_day=round(max_vel_mm_day, 6),
                min_velocity_mm_day=round(min_vel_mm_day, 6),
                classification=str(classification),
                risk_level=risk_level,
                is_safe=is_safe,
                status="success",
                message="Weekly summary computed from 7 consecutive daily summaries.",
                created_at=now_ts,
                updated_at=now_ts,
            ))

        await db_data.commit()


async def _finalize_gnss_station_day(station_id: int, day_start_ts: int, purge_raw: bool):
    day_end_ts = day_start_ts + 86400
    now_ts = int(time.time())

    async with DataSessionLocal() as db_data:
        existing_res = await db_data.execute(
            select(model_data.GnssDailySummary).where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_start_ts == day_start_ts,
                )
            )
        )
        existing_summary = existing_res.scalar_one_or_none()

        # Nếu chưa có summary thì tính từ raw trong ngày
        if not existing_summary:
            rows_res = await db_data.execute(
                select(model_data.SensorData)
                .where(
                    and_(
                        model_data.SensorData.station_id == station_id,
                        model_data.SensorData.sensor_type == "gnss",
                        model_data.SensorData.timestamp >= day_start_ts,
                        model_data.SensorData.timestamp < day_end_ts,
                    )
                )
                .order_by(model_data.SensorData.timestamp.asc())
            )
            rows = rows_res.scalars().all()
            valid_points = [
                r for r in rows
                if isinstance(r.data, dict)
                and all(k in r.data for k in ("pos_e", "pos_n", "pos_u"))
            ]

            sample_count = len(valid_points)
            first_ts = int(valid_points[0].timestamp) if sample_count > 0 else None
            last_ts = int(valid_points[-1].timestamp) if sample_count > 0 else None
            duration_seconds = max((last_ts - first_ts), 0) if first_ts and last_ts else 0

            if sample_count >= 2 and duration_seconds > 0:
                first_data = valid_points[0].data
                last_data = valid_points[-1].data
                delta_e = float(last_data.get("pos_e", 0.0)) - float(first_data.get("pos_e", 0.0))
                delta_n = float(last_data.get("pos_n", 0.0)) - float(first_data.get("pos_n", 0.0))
                delta_u = float(last_data.get("pos_u", 0.0)) - float(first_data.get("pos_u", 0.0))
                net_disp_mm = math.sqrt(delta_e ** 2 + delta_n ** 2 + delta_u ** 2) * 1000.0
                duration_days = max(duration_seconds / 86400.0, 1e-6)
                velocity_mm_day = net_disp_mm / duration_days
                velocity_mm_second = velocity_mm_day / 86400.0
                velocity_mm_year = velocity_mm_day * 365.0

                classification = analyzer._classify_velocity_extended(
                    velocity_mm_second,
                    velocity_mm_day,
                    velocity_mm_year,
                    {}
                )
                risk_level = _map_gnss_daily_risk(classification)
                is_safe = risk_level in ("LOW", "MEDIUM")
                status = "success"
                message = "Daily summary computed from raw GNSS records."
            else:
                net_disp_mm = 0.0
                velocity_mm_day = 0.0
                velocity_mm_second = 0.0
                classification = "insufficient_data"
                risk_level = "INFO"
                is_safe = True
                status = "insufficient_data"
                message = "Not enough GNSS points for daily summary."

            db_data.add(model_data.GnssDailySummary(
                station_id=station_id,
                day_start_ts=day_start_ts,
                day_end_ts=day_end_ts,
                sample_count=sample_count,
                first_ts=first_ts,
                last_ts=last_ts,
                duration_seconds=duration_seconds,
                net_displacement_mm=round(float(net_disp_mm), 3),
                velocity_mm_day=round(float(velocity_mm_day), 6),
                velocity_mm_second=round(float(velocity_mm_second), 8),
                classification=str(classification),
                risk_level=risk_level,
                is_safe=is_safe,
                status=status,
                message=message,
                created_at=now_ts,
                updated_at=now_ts,
            ))
            await db_data.commit()

        # Xóa raw GNSS của ngày đã chốt nếu bật purge
        if purge_raw:
            await db_data.execute(
                delete(model_data.SensorData).where(
                    and_(
                        model_data.SensorData.station_id == station_id,
                        model_data.SensorData.sensor_type == "gnss",
                        model_data.SensorData.timestamp >= day_start_ts,
                        model_data.SensorData.timestamp < day_end_ts,
                    )
                )
            )
            await db_data.commit()

    await _upsert_gnss_weekly_summary(station_id, day_start_ts)


async def run_gnss_daily_rollup_daemon():
    """Daemon: chốt GNSS theo ngày rồi rollup tuần từ 7 ngày liên tiếp."""
    interval = max(int(config.settings.GNSS_ROLLUP_INTERVAL_SECONDS), 60)
    purge_raw = bool(config.settings.GNSS_PURGE_RAW_AFTER_DAILY_ROLLUP)
    logger.info(
        f"🔄 GNSS rollup daemon started (interval={interval}s, purge_raw={purge_raw})"
    )

    while True:
        try:
            now_ts = int(time.time())
            today_start = _utc_day_start(now_ts)

            async with DataSessionLocal() as db_data:
                pairs_res = await db_data.execute(text(
                    """
                    SELECT station_id, ((timestamp / 86400) * 86400) AS day_start
                    FROM sensor_data
                    WHERE sensor_type = 'gnss' AND timestamp < :cutoff
                    GROUP BY station_id, ((timestamp / 86400) * 86400)
                    ORDER BY day_start, station_id
                    """
                ), {"cutoff": today_start})
                pairs = [(int(r[0]), int(r[1])) for r in pairs_res.fetchall()]

            for station_id, day_start_ts in pairs:
                await _finalize_gnss_station_day(station_id, day_start_ts, purge_raw)

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("🛑 GNSS rollup daemon cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ GNSS rollup daemon error: {e}", exc_info=True)
            await asyncio.sleep(30)

async def run_cors_fixed_base_failover_daemon():
    """Continuously enforce configured cross-station S1/S2 failover pairs."""

    global cors_failover_status
    poll_seconds = max(
        2.0,
        float(os.getenv("GNSS_CORS_FAILOVER_POLL_SECONDS", "5")),
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
            cors_failover_status = (
                await mqtt_service.round_robin_manager.reconcile_cors_failover_pairs(
                    clusters
                )
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
        # 1. Khởi tạo AUTH DB
        async with auth_engine.begin() as conn:
            await conn.run_sync(model_auth.BaseAuth.metadata.create_all)
        logger.info("✓ Auth database initialized")

        # 2. Khởi tạo CONFIG DB (stations, devices, pi_devices, ...)
        async with config_engine.begin() as conn:
            await conn.run_sync(model_config.BaseConfig.metadata.create_all)
        logger.info("✓ Config database initialized (incl. pi_devices)")

        # 3. Khởi tạo DATA DB
        async with data_engine.begin() as conn:
            await conn.run_sync(model_data.BaseData.metadata.create_all)
        logger.info("✓ Data database initialized")

        # 3b. Đảm bảo composite index tồn tại (idempotent, không ảnh hưởng nếu đã có)
        async with data_engine.connect() as conn:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_sensor_data_station_type_ts "
                "ON sensor_data (station_id, sensor_type, timestamp)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_sensor_data_station_ts "
                "ON sensor_data (station_id, timestamp)"
            ))
            await conn.commit()
        logger.info("✓ sensor_data composite indexes ensured")
        
        # 4. Tạo Admin mặc định
        async with asyncio.timeout(10):
            async with AuthSessionLocal() as db_auth:
                result = await db_auth.execute(
                    select(model_auth.User).where(model_auth.User.username == "admin")
                )
                admin_user = result.scalar_one_or_none()
                
                if not admin_user:
                    hashed_password = await auth.get_password_hash("")
                    new_admin = model_auth.User(
                        username="admin",
                        hashed_password=hashed_password,
                        role="admin",
                        full_name="Administrator",
                        is_active=True
                    )
                    db_auth.add(new_admin)
                    await db_auth.commit()
                    logger.info("✓ Default admin user created (admin/)")

        async with asyncio.timeout(10):
            async with ConfigSessionLocal() as db_config:
                # Mật khẩu cứng bạn muốn
                TARGET_PASSWORD = "password"

                # Kiểm tra xem đã có system_password chưa
                result = await db_config.execute(
                    select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "system_password")
                )
                sys_pass_config = result.scalar_one_or_none()
                
                if not sys_pass_config:
                    # TRƯỜNG HỢP 1: Chưa có -> Tạo mới
                    logger.info(f"⚙️ Initializing System Password: {TARGET_PASSWORD}")
                    new_config = model_config.GlobalConfig(
                        key="system_password",
                        value=TARGET_PASSWORD, # ✅ Đã thêm value
                        updated_at=int(time.time()),
                        updated_by="system_init"
                    )
                    db_config.add(new_config)
                else:
                    if sys_pass_config.value != TARGET_PASSWORD:
                        logger.info(f"🔄 Updating System Password from '{sys_pass_config.value}' to '{TARGET_PASSWORD}'")
                        sys_pass_config.value = TARGET_PASSWORD
                        sys_pass_config.updated_at = int(time.time())
                    else:
                        logger.info("✓ System Password is up to date.")

        mqtt_service.start()
        logger.info("✓ Background MQTT Service started")

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

# Add Security Middleware FIRST (Before CORS or Routing)
app.add_middleware(AdvancedSecurityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class CharsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type and ("text/" in content_type or "application/javascript" in content_type or "application/json" in content_type):
            if "charset=" not in content_type.lower():
                response.headers["content-type"] = f"{content_type}; charset=utf-8"
        return response

app.add_middleware(CharsetMiddleware)
app.include_router(admin_router.router)
app.include_router(field_router.router)

# ── Anti-cache middleware for frontend assets ──
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    """Prevent browser from caching HTML/JS/CSS so deploys take effect immediately."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.endswith(('.html', '.js', '.css')):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

app.add_middleware(NoCacheHTMLMiddleware)

# Mount static files directory (for sounds, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

RESCUE_META_PREFIX = "__RESCUE_META_V1__"
RESCUE_IMAGE_DIR = os.path.join("static", "uploads", "rescue")


def persist_rescue_image_data_url(image_data_url: Optional[str]) -> Optional[str]:
    raw = (image_data_url or '').strip()
    if not raw:
        return None

    if not raw.startswith('data:image/'):
        raise HTTPException(status_code=400, detail="Invalid image format")

    header, sep, b64_payload = raw.partition(',')
    if not sep:
        raise HTTPException(status_code=400, detail="Invalid image payload")

    mime_type = header.split(';')[0].replace('data:', '').lower()
    ext_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
    }
    ext = ext_map.get(mime_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    try:
        image_bytes = base64.b64decode(b64_payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid image encoding")

    # Limit decoded image size to 400KB for lightweight storage.
    if len(image_bytes) > 400 * 1024:
        raise HTTPException(status_code=400, detail="Image too large")

    os.makedirs(RESCUE_IMAGE_DIR, exist_ok=True)
    digest = hashlib.sha1(image_bytes).hexdigest()  # nosec B324 - non-crypto dedupe hash
    file_name = f"{digest}{ext}"
    file_path = os.path.join(RESCUE_IMAGE_DIR, file_name)

    if not os.path.exists(file_path):
        with open(file_path, 'wb') as f:
            f.write(image_bytes)

    return f"/static/uploads/rescue/{file_name}"


async def persist_rescue_upload_file(image_file: Optional[UploadFile]) -> Optional[str]:
    if image_file is None:
        return None

    mime_type = (image_file.content_type or '').lower()
    ext_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
    }
    ext = ext_map.get(mime_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    image_bytes = await image_file.read()
    if not image_bytes:
        return None

    if len(image_bytes) > 400 * 1024:
        raise HTTPException(status_code=400, detail="Image too large")

    os.makedirs(RESCUE_IMAGE_DIR, exist_ok=True)
    file_name = f"{int(time.time())}_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(RESCUE_IMAGE_DIR, file_name)
    with open(file_path, 'wb') as f:
        f.write(image_bytes)

    return f"/static/uploads/rescue/{file_name}"


def pack_rescue_message(text: Optional[str], rescue_type: Optional[str], province_city: Optional[str],
                        source_link: Optional[str], image_url: Optional[str],
                        image_data_url: Optional[str] = None) -> Optional[str]:
    clean_text = (text or '').strip()
    clean_type = (rescue_type or '').strip() or None
    clean_province = (province_city or '').strip() or None
    clean_link = (source_link or '').strip() or None
    clean_image_url = (image_url or '').strip() or None
    clean_image = (image_data_url or '').strip() or None

    has_meta = any([clean_type, clean_province, clean_link, clean_image_url, clean_image])
    if not has_meta:
        return clean_text or None

    payload = {
        "text": clean_text,
        "rescue_type": clean_type,
        "province_city": clean_province,
        "source_link": clean_link,
        "image_url": clean_image_url,
        "image_data_url": clean_image,
    }
    return f"{RESCUE_META_PREFIX}{json.dumps(payload, ensure_ascii=False)}"


def unpack_rescue_message(raw_message: Optional[str]) -> dict:
    raw = raw_message or ''
    if not raw.startswith(RESCUE_META_PREFIX):
        return {
            "text": raw,
            "rescue_type": None,
            "province_city": None,
            "source_link": None,
            "image_url": None,
            "image_data_url": None,
        }

    try:
        obj = json.loads(raw[len(RESCUE_META_PREFIX):])
        return {
            "text": str(obj.get("text") or ''),
            "rescue_type": str(obj.get("rescue_type") or '') or None,
            "province_city": str(obj.get("province_city") or '') or None,
            "source_link": str(obj.get("source_link") or '') or None,
            "image_url": str(obj.get("image_url") or '') or None,
            "image_data_url": str(obj.get("image_data_url") or '') or None,
        }
    except Exception:
        return {
            "text": raw,
            "rescue_type": None,
            "province_city": None,
            "source_link": None,
            "image_url": None,
            "image_data_url": None,
        }


def resolve_rescue_image_path(image_url: Optional[str]) -> Optional[str]:
    url = (image_url or '').strip()
    if not url:
        return None

    prefix = '/static/uploads/rescue/'
    if not url.startswith(prefix):
        return None

    file_name = url[len(prefix):].strip().replace('..', '')
    if not file_name:
        return None

    file_path = os.path.join(RESCUE_IMAGE_DIR, file_name)
    return os.path.abspath(file_path)


class RescueRequestCreate(BaseModel):
    requester_name: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    rescue_type: Optional[str] = None
    province_city: Optional[str] = None
    source_link: Optional[str] = None
    image_data_url: Optional[str] = None


class RescueRequestUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None


def _fetch_cors_base_stations_sync() -> List[Dict[str, Any]]:
    response = requests.get(CORS_BASE_STATIONS_URL, timeout=8)
    response.raise_for_status()
    payload = response.json()
    raw_stations = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(raw_stations, list):
        return []

    stations: List[Dict[str, Any]] = []
    for item in raw_stations:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").strip()
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
            alt = float(item.get("alt")) if item.get("alt") is not None else 0.0
        except (TypeError, ValueError):
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        service_config = item.get("service_config") if isinstance(item.get("service_config"), dict) else {}
        status_text = str(item.get("status") or "").strip().casefold()
        is_online = (
            bool(item.get("is_online"))
            if isinstance(item.get("is_online"), bool)
            else (
                status_text in {"online", "active", "connected", "streaming"}
                if status_text
                else bool(item.get("ntrip_connected"))
            )
        )
        streams = []
        for position, raw_stream in enumerate(
            item.get("streams") if isinstance(item.get("streams"), list) else [],
            start=1,
        ):
            if not isinstance(raw_stream, dict):
                continue
            stream = dict(raw_stream)
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
            # Older WEB CORS responses expose only service_config.  Materialize
            # S1/S2 explicitly so Project Management can persist the exact
            # service identity instead of later guessing from a mountpoint.
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
        stations.append({
            "serial": item.get("serial"),
            "name": name,
            "status": item.get("status"),
            "is_online": is_online,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "mountpoint": service_config.get("mountpoint1") or item.get("mountpoint") or name,
            "streams": streams,
            "service_config": item.get("service_config") or {},
            "is_provisioned": bool(item.get("is_provisioned")),
            "server_host": service_config.get("serverhost1"),
            "stream_active": bool(service_config.get("stream_active")),
            "ntrip_connected": bool(item.get("ntrip_connected")),
            "bps": item.get("bps"),
        })

    stations.sort(key=lambda st: st["name"])
    return stations


@app.get("/api/public/cors-base-stations")
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
                        base_station = c.get("base_station")
                        if base_station:
                            used_bases.add(base_station)

        filtered_cors = [
            st for st in all_cors
            if st["name"] in used_bases or st.get("mountpoint") in used_bases or st.get("code") in used_bases
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

        return filtered_cors
    except requests.RequestException as e:
        logger.warning(f"CORS base station fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch CORS base stations")


@app.post("/api/public/rescue-requests")
async def create_rescue_request(
    request: Request,
    db: AsyncSession = Depends(get_data_db)
):
    content_type = (request.headers.get('content-type') or '').lower()

    if 'multipart/form-data' in content_type:
        form = await request.form()
        payload = RescueRequestCreate(
            requester_name=str(form.get('requester_name') or '').strip() or None,
            phone=str(form.get('phone') or '').strip() or None,
            message=str(form.get('message') or '').strip() or None,
            latitude=float(form.get('latitude') or 0),
            longitude=float(form.get('longitude') or 0),
            accuracy_m=float(form.get('accuracy_m')) if form.get('accuracy_m') not in (None, '', 'null') else None,
            rescue_type=str(form.get('rescue_type') or '').strip() or None,
            province_city=str(form.get('province_city') or '').strip() or None,
            source_link=str(form.get('source_link') or '').strip() or None,
            image_data_url=None,
        )
        raw_file = form.get('image_file')
        image_file = raw_file if isinstance(raw_file, UploadFile) else None
        image_url = await persist_rescue_upload_file(image_file)
    else:
        body = await request.json()
        payload = RescueRequestCreate(**body)
        clean_image_data_url = (payload.image_data_url or '').strip() or None
        image_url = persist_rescue_image_data_url(clean_image_data_url)

    if not (-90.0 <= float(payload.latitude) <= 90.0):
        raise HTTPException(status_code=400, detail="Invalid latitude")
    if not (-180.0 <= float(payload.longitude) <= 180.0):
        raise HTTPException(status_code=400, detail="Invalid longitude")

    packed_message = pack_rescue_message(
        payload.message,
        payload.rescue_type,
        payload.province_city,
        payload.source_link,
        image_url,
    )

    now_ts = int(time.time())
    req = model_data.RescueRequest(
        created_at=now_ts,
        requester_name=(payload.requester_name or '').strip()[:120] or None,
        phone=(payload.phone or '').strip()[:32] or None,
        message=packed_message,
        latitude=float(payload.latitude),
        longitude=float(payload.longitude),
        accuracy_m=float(payload.accuracy_m) if payload.accuracy_m is not None else None,
        status='pending'
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    parsed = unpack_rescue_message(req.message)

    try:
        await ws_manager.broadcast({
            "type": "rescue_request",
            "id": int(req.id),
            "created_at": req.created_at,
            "requester_name": req.requester_name,
            "phone": req.phone,
            "message": parsed["text"],
            "latitude": req.latitude,
            "longitude": req.longitude,
            "accuracy_m": req.accuracy_m,
            "status": req.status,
            "rescue_type": parsed["rescue_type"],
            "province_city": parsed["province_city"],
            "source_link": parsed["source_link"],
            "image_url": parsed["image_url"],
        })
    except Exception as e:
        logger.warning(f"WS rescue_request broadcast failed: {e}")

    return {"status": "ok", "id": int(req.id), "created_at": req.created_at}


@app.get("/api/admin/rescue-requests")
async def get_rescue_requests(
    status_filter: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")

    q = select(model_data.RescueRequest)
    normalized = (status_filter or '').strip().lower()
    if normalized in ('pending', 'resolved', 'rejected'):
        q = q.where(model_data.RescueRequest.status == normalized)

    lim = max(1, min(int(limit), 500))
    q = q.order_by(desc(model_data.RescueRequest.created_at)).limit(lim)
    res = await db.execute(q)
    rows = res.scalars().all()
    result = []
    for r in rows:
        parsed = unpack_rescue_message(r.message)
        result.append({
            "id": int(r.id),
            "created_at": int(r.created_at),
            "requester_name": r.requester_name,
            "phone": r.phone,
            "message": parsed["text"],
            "latitude": r.latitude,
            "longitude": r.longitude,
            "accuracy_m": r.accuracy_m,
            "status": r.status,
            "admin_note": r.admin_note,
            "handled_by": r.handled_by,
            "handled_at": r.handled_at,
            "rescue_type": parsed["rescue_type"],
            "province_city": parsed["province_city"],
            "source_link": parsed["source_link"],
            "image_url": parsed["image_url"],
        })
    return result


@app.patch("/api/admin/rescue-requests/{request_id}")
async def update_rescue_request(
    request_id: int,
    payload: RescueRequestUpdate,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")

    new_status = (payload.status or '').strip().lower()
    if new_status not in ('pending', 'resolved', 'rejected'):
        raise HTTPException(status_code=400, detail="Invalid status")

    res = await db.execute(
        select(model_data.RescueRequest).where(model_data.RescueRequest.id == request_id)
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Rescue request not found")

    row.status = new_status
    row.admin_note = (payload.admin_note or '').strip()[:500] or None
    if new_status in ('resolved', 'rejected'):
        row.handled_by = current_user.username
        row.handled_at = int(time.time())
    else:
        row.handled_by = None
        row.handled_at = None

    await db.commit()
    return {"status": "ok", "id": int(row.id), "new_status": row.status}


@app.delete("/api/admin/rescue-requests/{request_id}")
async def delete_rescue_request(
    request_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")

    res = await db.execute(
        select(model_data.RescueRequest).where(model_data.RescueRequest.id == request_id)
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Rescue request not found")

    if row.status == 'pending':
        raise HTTPException(status_code=400, detail="Cannot delete pending request. Resolve or reject first")

    parsed = unpack_rescue_message(row.message)
    target_image_url = parsed.get('image_url')

    # Only delete image file if no other rescue request references the same URL.
    can_delete_image = False
    if target_image_url:
        ref_res = await db.execute(
            select(model_data.RescueRequest)
            .where(model_data.RescueRequest.id != request_id)
        )
        other_rows = ref_res.scalars().all()
        still_referenced = False
        for other in other_rows:
            other_parsed = unpack_rescue_message(other.message)
            if (other_parsed.get('image_url') or '').strip() == str(target_image_url).strip():
                still_referenced = True
                break
        can_delete_image = not still_referenced

    await db.delete(row)
    await db.commit()

    if can_delete_image:
        image_path = resolve_rescue_image_path(target_image_url)
        if image_path and os.path.exists(image_path):
            try:
                rescue_dir_abs = os.path.abspath(RESCUE_IMAGE_DIR)
                if image_path.startswith(rescue_dir_abs):
                    os.remove(image_path)
            except Exception as e:
                logger.warning(f"Failed to remove rescue image {image_path}: {e}")

    return {"status": "ok", "deleted_id": int(request_id)}

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@app.post("/api/auth/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_auth_db)
):
    result = await db.execute(
        select(model_auth.User).where(model_auth.User.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not await auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Check remember_me from form scopes (OAuth2 extra fields)
    remember_me = 'remember_me' in (form_data.scopes or [])
    
    # If remember_me, issue a 30-day token; otherwise use default
    if remember_me:
        expires = timedelta(days=30)
    else:
        expires = None  # Uses default from settings
    
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=expires
    )
    
    logger.info(f"✅ Login successful: {user.username} (remember_me={remember_me})")
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    permissions = auth.get_user_permissions(current_user)
    user_response = schemas.UserResponse.from_orm(current_user)
    user_response.permissions = permissions
    user_response.assigned_projects = getattr(current_user, 'assigned_projects', []) or []
    return user_response

# ============================================================================
# ADMIN - USER MANAGEMENT
# ============================================================================
@app.get("/api/admin/users")
async def get_users(
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    result = await db.execute(select(model_auth.User))
    return result.scalars().all()

@app.post("/api/admin/users")
async def create_user(
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    exists = await db.execute(select(model_auth.User).where(model_auth.User.username == user_in.username))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    hashed_pw = await auth.get_password_hash(user_in.password)
    new_user = model_auth.User(
        username=user_in.username,
        hashed_password=hashed_pw,
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=True,
        assigned_projects=user_in.assigned_projects or []
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@app.delete("/api/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(model_auth.User).where(model_auth.User.id == user_id))
    await db.commit()
    return {"status": "success"}

# ============================================================================
# ADMIN - PROJECTS API
# ============================================================================
@app.get("/api/projects")
async def get_public_projects(
    request: Request,
    db: AsyncSession = Depends(get_config_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    try:
        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)

        stmt = (
            select(
                model_config.Project,
                func.count(model_config.Station.id).label('station_count')
            )
            .outerjoin(model_config.Station, model_config.Station.project_id == model_config.Project.id)
            .group_by(model_config.Project.id)
            .order_by(model_config.Project.created_at.desc())
        )

        if project_filter_ids is not None:
            if not project_filter_ids:
                return []
            stmt = stmt.where(model_config.Project.id.in_(project_filter_ids))

        result = await db.execute(stmt)

        return [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count,
                "gnss_clusters": getattr(p, "gnss_clusters", None)
            }
            for p, count in result.all()
        ]

    except Exception as e:
        logger.error(f"Error loading public projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/projects")
async def get_projects(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    try:
        result = await db.execute(
            select(
                model_config.Project,
                func.count(model_config.Station.id).label('station_count')
            )
            .outerjoin(model_config.Station, model_config.Station.project_id == model_config.Project.id)
            .group_by(model_config.Project.id)
            .order_by(model_config.Project.created_at.desc())
        )
        
        projects_with_counts = result.all()
        
        # Filter projects for operator role
        assigned = getattr(current_user, 'assigned_projects', None) or []
        if current_user.role == 'operator' and assigned:
            projects_with_counts = [(p, c) for p, c in projects_with_counts if p.id in assigned]
        
        return [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count,
                "gnss_clusters": getattr(p, "gnss_clusters", None)
            } 
            for p, count in projects_with_counts
        ]
        
    except Exception as e:
        logger.error(f"Error loading projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/projects")
async def create_project(
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        new_project = model_config.Project(
            project_code=project_data['project_code'],
            name=project_data['name'],
            description=project_data.get('description'),
            location=project_data.get('location'),
            created_at=int(time.time()),
            updated_at=int(time.time()),
            is_active=True
        )
        
        db.add(new_project)
        await db.commit()
        await db.refresh(new_project)
        
        return {
            "id": new_project.id,
            "project_code": new_project.project_code,
            "name": new_project.name,
            "description": new_project.description,
            "location": new_project.location
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/projects/cors-stations")
async def get_admin_cors_stations(
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        return await asyncio.to_thread(_fetch_cors_base_stations_sync)
    except requests.RequestException as e:
        logger.warning(f"CORS base station fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch CORS base stations")


@app.get("/api/admin/projects/cors-failover-status")
async def get_admin_cors_failover_status(
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.MANAGE_USERS)
    ),
):
    return {"pairs": copy.deepcopy(cors_failover_status)}

@app.put("/api/admin/projects/{project_id}")
async def update_project(
    project_id: int,
    project_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        if 'name' in project_data:
            project.name = project_data['name']
        if 'description' in project_data:
            project.description = project_data['description']
        if 'location' in project_data:
            project.location = project_data['location']
        if 'is_active' in project_data:
            project.is_active = project_data['is_active']
        if 'gnss_clusters' in project_data:
            project.gnss_clusters = project_data['gnss_clusters']
            
        project.updated_at = int(time.time())
        
        await db.commit()
        await db.refresh(project)
        
        return {
            "id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "description": project.description,
            "location": project.location,
            "gnss_clusters": project.gnss_clusters
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/projects/{project_id}")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "description": project.description,
            "location": project.location,
            "gnss_clusters": project.gnss_clusters
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Project).where(model_config.Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        await db.delete(project)
        await db.commit()
        
        return {"status": "success", "message": f"Deleted project {project_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ADMIN - STATIONS API
# ============================================================================

def calculate_station_location(sensors: dict, manual_location: dict = None):
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

# ============================================================================
# RBAC HELPER: Check operator project access
# ============================================================================
def check_operator_project_access(user, project_id: int):
    """Raise 403 if operator tries to access a project not in their assigned_projects."""
    if user.role == 'operator':
        assigned = getattr(user, 'assigned_projects', None) or []
        if project_id not in assigned:
            raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập dự án này")
    elif user.role == 'viewer':
        pass  # Viewers can view all projects (read-only)

async def check_operator_station_access(user, station_id: int, db: AsyncSession):
    """Raise 403 if operator tries to access a station not in their assigned projects."""
    if user.role == 'operator':
        assigned = getattr(user, 'assigned_projects', None) or []
        res = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        station = res.scalar_one_or_none()
        if not station or station.project_id not in assigned:
            raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập trạm này")
    elif user.role == 'viewer':
        pass  # Viewers can view all stations (read-only via VIEW_STATIONS)

@app.get("/api/admin/projects/{project_id}/stations")
async def get_stations_by_project(
    project_id: int,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    # Enforce operator project access
    check_operator_project_access(current_user, project_id)
    result = await db_config.execute(
        select(model_config.Station).where(model_config.Station.project_id == project_id)
    )
    stations = result.scalars().all()
    
    # Tính status động cho từng trạm
    current_time = int(time.time())
    
    stations_with_status = []
    for station in stations:
        # Lấy danh sách devices của trạm
        devices_result = await db_config.execute(
            select(model_config.Device).where(
                and_(
                    model_config.Device.station_id == station.id,
                    model_config.Device.is_active == True
                )
            )
        )
        devices = devices_result.scalars().all()
        
        # Kiểm tra status cho từng sensor type
        station_online = False
        
        for device in devices:
            sensor_type = device.device_type
            threshold = get_offline_threshold(station.config, sensor_type)
            
            # ✅ Ưu tiên lấy từ latest_sensor_cache
            cache_result = await db_data.execute(
                select(model_data.LatestSensorCache)
                .where(
                    and_(
                        model_data.LatestSensorCache.station_id == station.id,
                        model_data.LatestSensorCache.sensor_type == sensor_type
                    )
                )
            )
            cached = cache_result.scalar_one_or_none()
            
            if cached:
                latest_ts = cached.timestamp
            else:
                latest_data_result = await db_data.execute(
                    select(model_data.SensorData)
                    .where(
                        and_(
                            model_data.SensorData.station_id == station.id,
                            model_data.SensorData.sensor_type == sensor_type
                        )
                    )
                    .order_by(desc(model_data.SensorData.timestamp))
                    .limit(1)
                )
                latest_data = latest_data_result.scalar_one_or_none()
                latest_ts = latest_data.timestamp if latest_data else None
            
            # Nếu có ít nhất 1 sensor online -> station online
            if latest_ts and (current_time - latest_ts) < threshold:
                station_online = True
                break
        
        offline_display_enabled = is_offline_display_enabled(station.config)
        computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")
        
        devices_list = []
        for d in devices:
            devices_list.append({
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic
            })
            
        stations_with_status.append({
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status, 
            "config": station.config,
            "devices": devices_list
        })
    
    return stations_with_status

@app.get("/api/admin/stations/{station_id}/config")
async def get_station_config(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    """Fix lỗi 404 khi nhấn nút Cấu hình trên giao diện"""
    result = await db.execute(
        select(model_config.Station).where(model_config.Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm")
    
    # Enforce operator project access
    check_operator_project_access(current_user, station.project_id)
    
    # Trả về cả ID, thông tin cơ bản và config
    return {
        "id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "location": station.location,
        "config": station.config
    }

@app.post("/api/admin/projects/{project_id}/stations", response_model=schemas.StationResponse)
async def create_station_in_project(
    project_id: int,
    station_data: schemas.StationCreate,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    # Enforce operator project access
    check_operator_project_access(current_user, project_id)
    try:
        # 1. Kiểm tra mã trạm
        exist = await db.execute(select(model_config.Station).where(model_config.Station.station_code == station_data.station_code))
        if exist.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Mã trạm đã tồn tại")

        # 2. TỰ ĐỘNG TÍNH TOẠ ĐỘ TRẠM
        final_location = calculate_station_location(station_data.sensors, station_data.location)

        # 3. Tạo trạm
        new_station = model_config.Station(
            station_code=station_data.station_code,
            name=station_data.name,
            project_id=project_id,
            location=final_location, # Dùng tọa độ đã tính toán
            status="offline",
            config=station_data.config or {},
            created_at=int(time.time()),
            updated_at=int(time.time())
        )
        db.add(new_station)
        await db.flush() 

        # 4. Tạo thiết bị
        if station_data.sensors:
            for s_type, info in station_data.sensors.items():
                topic = info.get('topic', '').strip()
                if topic:
                    db.add(model_config.Device(
                        device_code=f"{new_station.station_code}_{s_type.upper()}",
                        name=f"{new_station.name} - {s_type.upper()}",
                        station_id=new_station.id,
                        device_type=s_type,
                        mqtt_topic=topic,
                        is_active=True,
                        config={"mqtt": info.get('mqtt')} if info.get('mqtt') else {},
                        created_at=int(time.time()),
                        updated_at=int(time.time())
                    ))
        
        await db.commit()
        await db.refresh(new_station)
        return new_station
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating station: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/stations/{station_id}/config")
async def update_station_full_config(
    station_id: int,
    update_data: schemas.StationCreate,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        res = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        station = res.scalar_one_or_none()
        if not station: raise HTTPException(status_code=404)

        # Enforce operator project access
        check_operator_project_access(current_user, station.project_id)

        # TÍNH LẠI TOẠ ĐỘ TỰ ĐỘNG
        station.location = calculate_station_location(update_data.sensors, update_data.location)
        station.name = update_data.name
        station.config = update_data.config
        station.updated_at = int(time.time())


        # Sync Devices
        # 1. Get all existing devices
        existing_devices_res = await db.execute(select(model_config.Device).where(model_config.Device.station_id == station_id))
        existing_devices = {d.device_type: d for d in existing_devices_res.scalars().all()}
        
        logger.info(f"📋 [UPDATE] Station {station_id}: existing_devices={list(existing_devices.keys())}")
        logger.info(f"📋 [UPDATE] Incoming sensors: {update_data.sensors}")
        
        # 2. Update or create provided sensors based on payload
        active_types = set()
        if update_data.sensors:
            for s_type, info in update_data.sensors.items():
                topic = info.get('topic', '').strip()
                if not topic: continue
                
                active_types.add(s_type)
                
                if s_type in existing_devices:
                    # Update existing
                    existing_devices[s_type].mqtt_topic = topic
                    existing_devices[s_type].is_active = True
                    dev_config = dict(existing_devices[s_type].config) if existing_devices[s_type].config else {}
                    dev_config['mqtt'] = info.get('mqtt')
                    existing_devices[s_type].config = dev_config
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(existing_devices[s_type], "config")
                    
                    logger.info(f"  ✅ Updated device {s_type}: topic={topic}, is_active=True, config.mqtt={dev_config.get('mqtt')}")
                else:
                    # Create new
                    dev_config = {'mqtt': info.get('mqtt')}
                    db.add(model_config.Device(
                        device_code=f"{station.station_code}_{s_type.upper()}",
                        name=f"{station.name} - {s_type.upper()}",
                        station_id=station_id,
                        device_type=s_type,
                        mqtt_topic=topic,
                        is_active=True,
                        config=dev_config,
                        created_at=int(time.time()),
                        updated_at=int(time.time())
                    ))
                    logger.info(f"  🆕 Created device {s_type}: topic={topic}")

        # 3. Deactivate missing sensors
        for d_type, dev in existing_devices.items():
            if d_type not in active_types:
                dev.is_active = False
                logger.info(f"  ❌ Deactivated device {d_type}")

        logger.info(f"📋 [UPDATE] Active types after update: {active_types}")
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.delete("/api/admin/stations/{station_id}")
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    res = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
    station = res.scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404)
    
    # Enforce operator project access
    check_operator_project_access(current_user, station.project_id)
    
    await db.delete(station)
    await db.commit()
    return {"status": "success"}

@app.post("/api/admin/gnss/fetch-live-origin")
async def fetch_live_gnss_origin(
    request_data: dict,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        topic = request_data.get('topic')
        if not topic: raise HTTPException(status_code=400, detail="Topic required")
        
        # Sử dụng Import nội bộ để tránh lỗi vòng lặp
        from app.routers.admin import GNSSLiveFetcher
        
        mqtt_cfg = request_data.get('mqtt', {}) or {}
        broker = (mqtt_cfg.get('host') or '').strip() or config.settings.MQTT_BROKER
        port = mqtt_cfg.get('port')
        if port is not None:
            try:
                port = int(port)
            except (ValueError, TypeError):
                port = None
        if not port:
            port = config.settings.MQTT_PORT
        username = (mqtt_cfg.get('username') or '').strip() or config.settings.MQTT_USER or ""
        password = mqtt_cfg.get('password') or config.settings.MQTT_PASSWORD or ""
        use_tls = bool(mqtt_cfg.get('use_tls', False))
        
        fetcher = GNSSLiveFetcher(
            broker=broker,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls
        )
        result = await fetcher.fetch_origin(topic, timeout=30)
        if not result: raise HTTPException(status_code=408, detail="Timeout")
        
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"GNSS Fetch Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ADMIN - GNSS ADJUSTMENT CONTROL API
# ============================================================================

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
        cluster["aicaster_clients"] = {}
        for station_id in station_ids:
            station = stations_by_id[station_id]
            station_config = station.config if isinstance(station.config, dict) else {}
            binding = station_config.get("gnss_aicaster_client") or {}
            username = str(binding.get("username") or "").strip()
            if not username:
                continue
            cluster["aicaster_clients"][station.station_code] = {
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


@app.get("/api/admin/gnss/aicaster-clients")
async def list_active_aicaster_clients(
    current_user: model_auth.User = Depends(
        auth.require_permission(auth.Permission.EDIT_STATIONS)
    ),
):
    """List live rover identities reported by AICaster GET /clienttable."""

    try:
        clients = await mqtt_service.round_robin_manager.list_active_aicaster_clients()
    except Exception as exc:
        logger.error("Could not load AICaster client table: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "clients": [
            {
                "username": item.get("Username") or "",
                "receiver_id": item.get("receiverID") or "",
                "mountpoint": item.get("Mountpoint") or "",
                "caster_host": item.get("CasterHost") or "",
                "caster_port": item.get("CasterPort"),
            }
            for item in clients
        ]
    }

@app.post("/api/admin/gnss/adjustment/start")
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


@app.get("/api/admin/gnss/adjustment/status")
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


@app.post("/api/admin/gnss/adjustment/stop")
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
# ADMIN - DEVICES API
# ============================================================================

@app.get("/api/admin/stations/{station_id}/devices")
async def get_station_devices(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    try:
        result = await db.execute(
            select(model_config.Device)
            .where(model_config.Device.station_id == station_id)
            .order_by(model_config.Device.created_at.desc())
        )
        
        devices = result.scalars().all()
        
        return [
            {
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "position": d.position,
                "is_active": d.is_active,
                "last_data_time": d.last_data_time,
                "config": d.config or {}
            }
            for d in devices
        ]
        
    except Exception as e:
        logger.error(f"Error loading devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/stations/{station_id}/devices")
async def create_device_in_station(
    station_id: int,
    device_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        # Verify station exists
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Station not found")
        
        new_device = model_config.Device(
            device_code=device_data['device_code'],
            name=device_data['name'],
            station_id=station_id,
            device_type=device_data['device_type'],
            mqtt_topic=device_data.get('mqtt_topic'),
            position=device_data.get('position'),
            is_active=True,
            last_data_time=0,
            config={},
            created_at=int(time.time()),
            updated_at=int(time.time())
        )
        
        db.add(new_device)
        await db.commit()
        await db.refresh(new_device)
        
        return {
            "id": new_device.id,
            "device_code": new_device.device_code,
            "name": new_device.name,
            "device_type": new_device.device_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/devices/{device_id}")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        result = await db.execute(
            select(model_config.Device).where(model_config.Device.id == device_id)
        )
        device = result.scalar_one_or_none()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        await db.delete(device)
        await db.commit()
        
        return {"status": "success", "message": f"Deleted device {device_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STATION DATA ENDPOINTS 
# ============================================================================
@app.get("/api/stations")
async def get_stations(
    request: Request,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    """
    ✅ Trả về danh sách tất cả các trạm với offline threshold tùy chỉnh
    """
    try:
        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)

        stmt = select(model_config.Station)
        if project_filter_ids is not None:
            if not project_filter_ids:
                return []
            stmt = stmt.where(model_config.Station.project_id.in_(project_filter_ids))

        result = await db_config.execute(stmt)
        stations = result.scalars().all()
        
        current_time = int(time.time())
        
        stations_with_status = []
        for station in stations:
            # ✅ Chỉ lấy devices ACTIVE
            devices_result = await db_config.execute(
                select(model_config.Device).where(
                    and_(
                        model_config.Device.station_id == station.id,
                        model_config.Device.is_active == True
                    )
                )
            )
            devices = devices_result.scalars().all()
            
            # Kiểm tra status cho từng sensor type
            station_online = False
            
            for device in devices:
                sensor_type = device.device_type
                threshold = get_offline_threshold(station.config, sensor_type)

                # ✅ Ưu tiên lấy từ latest_sensor_cache (luôn cập nhật mỗi lần MQTT nhận data)
                cache_result = await db_data.execute(
                    select(model_data.LatestSensorCache)
                    .where(
                        and_(
                            model_data.LatestSensorCache.station_id == station.id,
                            model_data.LatestSensorCache.sensor_type == sensor_type
                        )
                    )
                )
                cached = cache_result.scalar_one_or_none()

                if cached:
                    latest_ts = cached.timestamp
                else:
                    # Fallback: query SensorData nếu cache chưa có
                    latest_data_result = await db_data.execute(
                        select(model_data.SensorData)
                        .where(
                            and_(
                                model_data.SensorData.station_id == station.id,
                                model_data.SensorData.sensor_type == sensor_type
                            )
                        )
                        .order_by(desc(model_data.SensorData.timestamp))
                        .limit(1)
                    )
                    latest_row = latest_data_result.scalar_one_or_none()
                    latest_ts = latest_row.timestamp if latest_row else None

                # Nếu có ít nhất 1 sensor online -> station online
                if latest_ts and (current_time - latest_ts) < threshold:
                    station_online = True
                    break
            
            # ✅ Tính risk_level thực tế từ alerts (không hardcode LOW nữa)
            risk_assessment = await _calculate_station_risk_assessment(
                db_data,
                station.id,
                station.config
            )
            computed_risk = risk_assessment.get("overall_risk", "LOW")
            offline_display_enabled = is_offline_display_enabled(station.config)
            computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")
            
            stations_with_status.append({
                "id": station.id,
                "station_code": station.station_code,
                "name": station.name,
                "location": station.location,
                "status": computed_status,
                "offline_display_enabled": offline_display_enabled,
                "last_update": station.last_update, 
                "risk_level": computed_risk
            })
        
        return stations_with_status
        
    except Exception as e:
        logger.error(f"Error loading stations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stations/{station_id}/detail")
async def get_station_detail(
    station_id: int,
    request: Request,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
    db_auth: AsyncSession = Depends(get_auth_db)
):
    try:
        # 1. Lấy thông tin trạm từ Config DB
        result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        current_user = await get_optional_current_user_from_request(request, db_auth)
        project_filter_ids = user_project_filter_ids(current_user)
        if project_filter_ids is not None and station.project_id not in project_filter_ids:
            raise HTTPException(status_code=403, detail="Station not allowed")
        
        # 2. Lấy devices của trạm
        devices_result = await db_config.execute(
            select(model_config.Device).where(
                and_(
                    model_config.Device.station_id == station_id,
                    model_config.Device.is_active == True
                )
            )
        )
        devices = devices_result.scalars().all()
        
        # 3. Lấy dữ liệu mới nhất từ Data DB (24h gần nhất)
        cutoff_time = int(time.time()) - 86400  # 24h ago
        
        sensor_data = {}
        has_recent_data = False
        latest_data_timestamp = 0
        station_online = False  # Flag để kiểm tra trạm có online không
        
        for device in devices:
            sensor_type = device.device_type
            
            # ✅ Ưu tiên lấy từ latest_sensor_cache (luôn cập nhật mỗi lần MQTT nhận data)
            cache_result = await db_data.execute(
                select(model_data.LatestSensorCache)
                .where(
                    and_(
                        model_data.LatestSensorCache.station_id == station_id,
                        model_data.LatestSensorCache.sensor_type == sensor_type
                    )
                )
            )
            cached = cache_result.scalar_one_or_none()
            
            # Fallback: nếu cache chưa có (server mới khởi động) thì lấy từ sensor_data
            if not cached:
                latest_result = await db_data.execute(
                    select(model_data.SensorData)
                    .where(
                        and_(
                            model_data.SensorData.station_id == station_id,
                            model_data.SensorData.sensor_type == sensor_type
                        )
                    )
                    .order_by(desc(model_data.SensorData.timestamp))
                    .limit(1)
                )
                latest_row = latest_result.scalar_one_or_none()
                latest_data = latest_row.data if latest_row else None
                latest_ts = latest_row.timestamp if latest_row else None
            else:
                latest_data = cached.data
                latest_ts = cached.timestamp
            
            # ✅ Lấy offline threshold riêng cho sensor này
            threshold = get_offline_threshold(station.config, sensor_type)
            current_time = int(time.time())
            
            # Check xem sensor này có online không (dựa trên ts mới nhất thực sự)
            if latest_ts and (current_time - latest_ts) < threshold:
                station_online = True  # Chỉ cần 1 sensor online là trạm online
                has_recent_data = True
                if latest_ts > latest_data_timestamp:
                    latest_data_timestamp = latest_ts
            
            # Lấy lịch sử 24h
            history_result = await db_data.execute(
                select(model_data.SensorData)
                .where(
                    and_(
                        model_data.SensorData.station_id == station_id,
                        model_data.SensorData.sensor_type == sensor_type,
                        model_data.SensorData.timestamp >= cutoff_time
                    )
                )
                .order_by(desc(model_data.SensorData.timestamp))
                .limit(500)
            )
            history = history_result.scalars().all()
            if sensor_type == 'gnss':
                history = [
                    h for h in history
                    if isinstance(h.data, dict)
                    and (
                        h.data.get('speed_2d_mm_s') is not None
                        or (h.data.get('vel_e') is not None and h.data.get('vel_n') is not None)
                    )
                ]
            
            # ✅ Per-sensor online check (dựa trên cache timestamp)
            sensor_is_online = bool(latest_ts and (current_time - latest_ts) < threshold)

            # ✅ Sửa lỗi "ảo": Tự động bù đắp dữ liệu Advanced cho trạm Offline/Dữ liệu cũ
            if sensor_type == 'gnss' and latest_data and 'adv_x' not in latest_data:
                latest_data = dict(latest_data) # Clone to modify
                latest_data['adv_x'] = latest_data.get('pos_e', latest_data.get('lon', 0.0))
                latest_data['adv_y'] = latest_data.get('pos_n', latest_data.get('lat', 0.0))
                latest_data['adv_h'] = latest_data.get('pos_u', latest_data.get('h', 0.0))
                latest_data['adv_dx'] = 0.0
                latest_data['adv_dy'] = 0.0
                latest_data['adv_dh'] = 0.0
                latest_data['adv_vdx'] = 0.0
                latest_data['adv_vdy'] = 0.0
                latest_data['adv_vdh'] = 0.0

            sensor_data[sensor_type] = {
                "is_online": sensor_is_online,
                "latest": latest_data,
                "latest_timestamp": latest_ts,
                "history": [
                    {
                        "timestamp": h.timestamp,
                        "data": h.data
                    }
                    for h in reversed(history)
                ]
            }
        
        # 3.5. Fetch latest gnss_adjusted data from LatestSensorCache
        try:
            adj_cache_res = await db_data.execute(
                select(model_data.LatestSensorCache)
                .where(
                    and_(
                        model_data.LatestSensorCache.station_id == station_id,
                        model_data.LatestSensorCache.sensor_type == 'gnss_adjusted'
                    )
                )
            )
            adj_cached = adj_cache_res.scalar_one_or_none()
            if adj_cached:
                sensor_data["gnss_adjusted"] = {
                    "is_online": True,
                    "latest": adj_cached.data,
                    "latest_timestamp": adj_cached.timestamp,
                    "history": []
                }
        except Exception as adj_load_e:
            logger.error(f"Error loading cached gnss_adjusted for station {station_id}: {adj_load_e}")

        # ✅ Tính status dựa trên offline threshold tùy chỉnh
        offline_display_enabled = is_offline_display_enabled(station.config)
        computed_status = "online" if station_online else ("stale" if offline_display_enabled else "offline")
        
        # 4. Tính risk assessment
        risk_assessment = await _calculate_station_risk_assessment(
            db_data,
            station_id,
            station.config
        )

        # 4.5 Lấy Pi devices gắn với trạm (pi_point, pi_center)
        pi_devices_status = []
        try:
            pi_result = await db_config.execute(
                select(PiDevice).where(PiDevice.station_id == station_id)
            )
            pi_devs = pi_result.scalars().all()
            PI_ONLINE_THRESHOLD = 300  # 5 phút
            for pd in pi_devs:
                is_online = (current_time - (pd.last_seen or 0)) < PI_ONLINE_THRESHOLD
                pi_devices_status.append({
                    "id": pd.id,
                    "serial": pd.serial,
                    "name": pd.name,
                    "device_type": pd.device_type,
                    "is_online": is_online,
                    "last_seen": pd.last_seen,
                    "is_locked": pd.is_locked
                })
        except Exception as e:
            logger.error(f"Error fetching Pi devices for station {station_id}: {e}")

        # 5. Trả về response
        mqtt_connected = False
        try:
            mqtt_connected = bool(mqtt_service.client.is_connected())
        except Exception:
            mqtt_connected = False

        return {
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "project_id": station.project_id,
            "status": computed_status,
            "offline_display_enabled": offline_display_enabled,
            "offline_display": {"enabled": offline_display_enabled},
            "mqtt_connected": mqtt_connected,
            "last_update": latest_data_timestamp if has_recent_data else station.last_update,
            "config": station.config,
            "sensors": sensor_data,
            "risk_assessment": risk_assessment,
            "pi_devices": pi_devices_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading station detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
async def _calculate_station_risk_assessment(
    db_data: AsyncSession,
    station_id: int,
    station_config: Optional[Dict[str, Any]] = None
) -> Dict:
    """Helper: Tính toán risk assessment từ unresolved alerts còn hiệu lực thời gian."""
    try:
        now_ts = int(time.time())
        alerting_cfg = (station_config or {}).get("alerting", {}) if station_config else {}
        if alerting_cfg.get("enabled", (station_config or {}).get("alerting_enabled", True)) is False:
            return {"overall_risk": "LOW", "active_alerts": []}

        gnss_offline = get_offline_threshold(station_config or {}, 'gnss')
        rain_offline = get_offline_threshold(station_config or {}, 'rain')
        water_offline = get_offline_threshold(station_config or {}, 'water')
        imu_offline = get_offline_threshold(station_config or {}, 'imu')

        # Chỉ tính alert còn "tươi" để tránh kẹt WARNING/CRITICAL khi sensor đã ngừng gửi.
        default_ttl = {
            'gnss_velocity': max(90, gnss_offline * 2),
            'rainfall': max(120, rain_offline * 2),
            'water_level': max(120, water_offline * 2),
            'tilt': max(300, imu_offline),
            'tilt_warning': max(300, imu_offline),
            'tilt_critical': max(300, imu_offline),
            'shock': max(300, imu_offline),
        }
        ttl_cfg = (station_config or {}).get('alert_ttl_seconds', {}) if station_config else {}
        alert_ttl = {
            'gnss_velocity': int(ttl_cfg.get('gnss_velocity', default_ttl['gnss_velocity'])),
            'rainfall': int(ttl_cfg.get('rainfall', default_ttl['rainfall'])),
            'water_level': int(ttl_cfg.get('water_level', default_ttl['water_level'])),
            'tilt': int(ttl_cfg.get('tilt', default_ttl['tilt'])),
            'tilt_warning': int(ttl_cfg.get('tilt_warning', default_ttl['tilt_warning'])),
            'tilt_critical': int(ttl_cfg.get('tilt_critical', default_ttl['tilt_critical'])),
            'shock': int(ttl_cfg.get('shock', default_ttl['shock'])),
        }

        result = await db_data.execute(
            select(model_data.Alert).where(
                and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.is_resolved == False
                )
            )
        )
        alerts = result.scalars().all()

        # Lọc alert hết hạn theo category-specific TTL.
        fresh_alerts = []
        for a in alerts:
            ttl = alert_ttl.get(a.category, 180)
            if (now_ts - int(a.timestamp or 0)) <= ttl:
                fresh_alerts.append(a)
        
        # Dùng logic max-level giống mqtt_bridge._get_station_active_alert_summary()
        # để WebSocket và REST API trả về cùng giá trị risk_level.
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
        for a in fresh_alerts:
            level = str(a.level or "").upper()
            if a.category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and level == 'WARNING':
                level = 'CRITICAL'
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
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "timestamp": a.timestamp
                }
                for a in fresh_alerts
            ]
        }
    except Exception as e:
        logger.error(f"Error calculating risk: {e}")
        return {"overall_risk": "UNKNOWN", "active_alerts": []}

# ============================================================================
# LONG-TERM ANALYSIS ENDPOINT
# ============================================================================
@app.get("/api/stations/{station_id}/long-term-analysis")
async def get_long_term_analysis(
    station_id: int,
    days: float = 30.0,
    include_correlation: bool = False,
    correlation_model: str = "slide_model",
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    """
    Phân tích dài hạn cho GNSS displacement + IMU tilt.
    Rainfall correlation chỉ chạy khi include_correlation=True.
    correlation_model hiện hỗ trợ: slide_model.
    + Multi-window analysis + Inverse Velocity (Fukuzono)
    """
    try:
        def is_gnss_analysis_point(data: dict) -> bool:
            if not isinstance(data, dict):
                return False
            return all(key in data for key in ("pos_e", "pos_n", "pos_u"))

        def _trend_from_velocity_series(values: List[float]) -> str:
            clean = [float(v or 0.0) for v in values]
            if len(clean) < 2:
                return "stable"
            first_v = clean[0]
            last_v = clean[-1]
            if abs(first_v) < 1e-6 and abs(last_v) < 1e-6:
                return "stable"
            if abs(first_v) < 1e-6:
                return "accelerating" if last_v > 0 else "stable"
            ratio = (last_v - first_v) / (abs(first_v) + 1e-6)
            if ratio > 0.1:
                return "accelerating"
            if ratio < -0.1:
                return "decelerating"
            return "stable"

        def _severity(level: str) -> int:
            order = {
                "INFO": 0,
                "LOW": 1,
                "MEDIUM": 2,
                "HIGH": 3,
                "CRITICAL": 4,
                "EXTREME": 5,
            }
            return order.get(str(level or "").upper(), 0)

        def _build_gnss_analysis_from_daily_summaries(
            daily_rows: List[model_data.GnssDailySummary],
            station_cfg: Dict[str, Any]
        ) -> Dict[str, Any]:
            if not daily_rows:
                return {
                    "status": "insufficient_data",
                    "message": "Không có GNSS daily summary trong khoảng thời gian yêu cầu."
                }

            rows = sorted(daily_rows, key=lambda r: int(r.day_start_ts or 0))
            total_displacement_mm = float(sum(float(r.net_displacement_mm or 0.0) for r in rows))
            duration_seconds = int(sum(int(r.duration_seconds or 0) for r in rows))
            duration_days = duration_seconds / 86400.0 if duration_seconds > 0 else float(len(rows))
            if duration_days <= 0:
                duration_days = float(len(rows))

            velocity_mm_per_day = total_displacement_mm / duration_days if duration_days > 0 else 0.0
            velocity_mm_per_second = velocity_mm_per_day / 86400.0
            velocity_mm_per_year = velocity_mm_per_day * 365.0

            classification = analyzer._classify_velocity_extended(
                velocity_mm_per_second,
                velocity_mm_per_day,
                velocity_mm_per_year,
                station_cfg or {}
            )

            min_reliable_duration_days = analyzer._get_gnss_min_reliable_window_days(station_cfg or {})
            data_points_used = int(sum(int(r.sample_count or 0) for r in rows))
            reliability_points = data_points_used if data_points_used > 0 else len(rows)
            velocity_reliable = analyzer._is_reliable_observation_window(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )
            reliability_message = analyzer._build_gnss_preliminary_message(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )

            trend = _trend_from_velocity_series([float(r.velocity_mm_day or 0.0) for r in rows])
            derived_risk = _map_gnss_daily_risk(classification)
            max_row_risk = "LOW"
            for r in rows:
                row_risk = str(r.risk_level or "LOW").upper()
                if _severity(row_risk) > _severity(max_row_risk):
                    max_row_risk = row_risk
            risk_level = max_row_risk if _severity(max_row_risk) >= _severity(derived_risk) else derived_risk

            if risk_level in ("CRITICAL", "EXTREME"):
                warning_message = f"🚨 Cảnh báo cao từ GNSS daily summary ({classification})."
            elif risk_level == "HIGH":
                warning_message = f"⚠️ Cảnh báo: vận tốc có xu hướng tăng ({classification})."
            elif risk_level == "MEDIUM":
                warning_message = f"Cần theo dõi: GNSS có chuyển dịch mức trung bình ({classification})."
            else:
                warning_message = f"An toàn tương đối theo GNSS daily summary ({classification})."

            if not velocity_reliable:
                warning_message = reliability_message
                risk_level = "INFO"

            labels = []
            displacement_series = []
            cumulative_disp = 0.0
            for row in rows:
                labels.append(datetime.fromtimestamp(int(row.day_start_ts)).strftime('%d/%m'))
                cumulative_disp += float(row.net_displacement_mm or 0.0)
                displacement_series.append(round(cumulative_disp, 2))

            return {
                "status": "success",
                "source": "daily_summary_rollup",
                "analysis": {
                    "total_displacement_mm": round(total_displacement_mm, 2),
                    "net_displacement_mm": round(total_displacement_mm, 2),
                    "regression_displacement_mm": round(total_displacement_mm, 2),
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_ci_95": 0.0,
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "regression_velocity_mm_year": round(velocity_mm_per_year, 2),
                    "regression_velocity_mm_day": round(velocity_mm_per_day, 4),
                    "regression_velocity_mm_second": round(velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "cusum_change": False,
                    "cusum_message": "Daily summary mode: không chạy CUSUM trên raw sample.",
                    "displacement_basis": "daily_rollup_sum",
                    "velocity_reliable": velocity_reliable,
                    "reliability_message": reliability_message,
                    "min_reliable_duration_days": round(min_reliable_duration_days, 4),
                    "min_reliable_points": 3,
                    "duration_days": round(duration_days, 4),
                    "data_points_used": data_points_used,
                    "summary_days_used": len(rows),
                    "start_date": datetime.fromtimestamp(int(rows[0].day_start_ts)).isoformat(),
                    "end_date": datetime.fromtimestamp(int(rows[-1].day_end_ts)).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning_message,
                "inverse_velocity": {
                    "available": False,
                    "message": "Daily summary mode: inverse velocity cần raw GNSS chi tiết."
                },
                "time_series": {
                    "labels": labels,
                    "displacement": displacement_series,
                    "e": [],
                    "n": [],
                    "u": []
                }
            }

        # 1. Lấy config trạm
        station_result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Lấy window lớn nhất cho multi-window (tối thiểu = days, mở rộng 90 ngày)
        max_window = max(days, 90)
        cutoff_time = int(time.time() - (max_window * 86400))
        cutoff_requested = int(time.time() - (days * 86400))
        
        # 2. Lấy dữ liệu GNSS (mở rộng window cho multi-window)
        gnss_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "gnss",
                    model_data.SensorData.timestamp >= cutoff_time
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        gnss_data = gnss_result.scalars().all()

        # 2b. Lấy GNSS daily summary để fallback khi raw đã purge
        daily_summary_result = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_start_ts >= _utc_day_start(cutoff_time),
                    model_data.GnssDailySummary.status == "success"
                )
            )
            .order_by(model_data.GnssDailySummary.day_start_ts.asc())
        )
        daily_gnss_full = daily_summary_result.scalars().all()
        daily_gnss_requested = [
            d for d in daily_gnss_full
            if int(d.day_start_ts or 0) >= _utc_day_start(cutoff_requested)
        ]
        
        # 3. Lấy dữ liệu IMU
        imu_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "imu",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        imu_data = imu_result.scalars().all()
        
        # 4. Lấy dữ liệu mưa (cho rainfall-displacement correlation)
        rain_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "rain",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        rain_data = rain_result.scalars().all()
        
        model_key = str(correlation_model or "slide_model").strip().lower()
        result = {
            "station_id": station_id,
            "days": days,
            "correlation_model": model_key
        }
        
        # Chuyển sang list dict chung
        historical_gnss_full = [
            {"timestamp": d.timestamp, "data": d.data}
            for d in gnss_data
            if is_gnss_analysis_point(d.data)
        ]
        historical_gnss_requested = [p for p in historical_gnss_full if p['timestamp'] >= cutoff_requested]
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_gnss_requested) < 2 and len(historical_gnss_full) >= 2 and days <= 1:
            historical_gnss_requested = historical_gnss_full[-20:]

        # 5. Phân tích GNSS (trên window requested)
        if len(historical_gnss_requested) >= 2:
            gnss_analysis = analyzer.analyze_long_term_velocity(
                station_id=station_id,
                historical_data=historical_gnss_requested,
                config=station.config or {},
                window_days=days
            )
            
            # Tạo time-series GNSS (trung bình theo ngày/giờ) cho chart & 3D
            if gnss_analysis.get("status") == "success":
                from collections import OrderedDict
                from datetime import datetime as dt
                daily_gnss = OrderedDict()
                
                if days < 1/24:    fmt = '%H:%M:%S'
                elif days <= 1:    fmt = '%H:%M'
                elif days <= 7:    fmt = '%d/%m %H:00'
                else:              fmt = '%d/%m'
                
                first_e, first_n, first_u = None, None, None

                for point in historical_gnss_requested:
                    day_key = dt.fromtimestamp(point['timestamp']).strftime(fmt)
                    data = point['data']
                    
                    disp = data.get('total_displacement_mm', data.get('displacement_mm', 0))
                    e = data.get('pos_e', 0)
                    n = data.get('pos_n', 0)
                    u = data.get('pos_u', 0)
                    
                    if first_e is None:
                        first_e, first_n, first_u = e, n, u

                    if day_key not in daily_gnss:
                        daily_gnss[day_key] = {'disp': [], 'e': [], 'n': [], 'u': []}
                    
                    daily_gnss[day_key]['disp'].append(float(disp))
                    delta_e_mm = (e - first_e) * 1000
                    delta_n_mm = (n - first_n) * 1000
                    delta_u_mm = (u - first_u) * 1000
                    
                    daily_gnss[day_key]['e'].append(delta_e_mm)
                    daily_gnss[day_key]['n'].append(delta_n_mm)
                    daily_gnss[day_key]['u'].append(delta_u_mm)
                
                gnss_analysis["time_series"] = {
                    "labels": list(daily_gnss.keys()),
                    "displacement": [round(sum(v['disp']) / len(v['disp']), 2) for v in daily_gnss.values()],
                    "e": [round(sum(v['e']) / len(v['e']), 2) for v in daily_gnss.values()],
                    "n": [round(sum(v['n']) / len(v['n']), 2) for v in daily_gnss.values()],
                    "u": [round(sum(v['u']) / len(v['u']), 2) for v in daily_gnss.values()]
                }
            
            result["gnss"] = gnss_analysis
        elif len(daily_gnss_requested) >= 1:
            result["gnss"] = _build_gnss_analysis_from_daily_summaries(
                daily_rows=daily_gnss_requested,
                station_cfg=station.config or {}
            )
        else:
            result["gnss"] = {
                "status": "insufficient_data",
                "message": f"Không đủ dữ liệu GNSS raw ({len(historical_gnss_requested)} điểm) và chưa có daily summary trong cửa sổ {days} ngày."
            }
        
        # 6. Phân tích IMU
        historical_imu_full = [{"timestamp": d.timestamp, "data": d.data} for d in imu_data]
        historical_imu_requested = [p for p in historical_imu_full if p['timestamp'] >= cutoff_requested]
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_imu_requested) < 2 and len(historical_imu_full) >= 2 and days <= 1:
            historical_imu_requested = historical_imu_full[-60:]
            
        if len(historical_imu_requested) >= 2:
            imu_analysis = analyzer.analyze_long_term_tilt(
                station_id=station_id,
                historical_data=historical_imu_requested,
                window_days=days
            )
            
            # Format X-axis for IMU exactly like GNSS
            if imu_analysis.get("status") == "success" and "time_series" in imu_analysis:
                from collections import OrderedDict
                from datetime import datetime as dt
                fmt = '%H:%M:%S' if days < 1/24 else '%H:%M' if days <= 1 else '%d/%m %H:00' if days <= 7 else '%d/%m'
                
                daily_imu = OrderedDict()
                for ts, r, p in zip(imu_analysis["time_series"]["raw_timestamps"], imu_analysis["time_series"]["rolls"], imu_analysis["time_series"]["pitches"]):
                    day_key = dt.fromtimestamp(ts).strftime(fmt)
                    if day_key not in daily_imu:
                        daily_imu[day_key] = {'rolls': [], 'pitches': []}
                    daily_imu[day_key]['rolls'].append(r)
                    daily_imu[day_key]['pitches'].append(p)
                    
                imu_analysis["time_series"]["labels"] = list(daily_imu.keys())
                imu_analysis["time_series"]["rolls"] = [round(sum(v['rolls']) / len(v['rolls']), 2) for v in daily_imu.values()]
                imu_analysis["time_series"]["pitches"] = [round(sum(v['pitches']) / len(v['pitches']), 2) for v in daily_imu.values()]
                
            result["imu"] = imu_analysis
        else:
            result["imu"] = {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu IMU. Hiện có: {len(historical_imu_requested)}"
            }
        
        # 7. Phân tích tương quan Mưa - Dịch chuyển (chạy theo yêu cầu)
        if include_correlation:
            if model_key != "slide_model":
                raise HTTPException(status_code=400, detail="Unsupported correlation_model. Use slide_model.")

            # Nếu raw GNSS đã bị purge, dựng pseudo-GNSS từ daily summary
            gnss_for_correlation = historical_gnss_requested
            if len(gnss_for_correlation) < 2 and len(daily_gnss_requested) >= 2:
                logger.info(f"[Slide model] Raw GNSS insufficient ({len(historical_gnss_requested)} pts). "
                            f"Synthesizing from {len(daily_gnss_requested)} daily summaries.")
                cumulative_mm = 0.0
                gnss_for_correlation = []
                for row in sorted(daily_gnss_requested, key=lambda r: int(r.day_start_ts or 0)):
                    ts = int(row.day_start_ts or 0) + 43200  # giữa ngày (12h)
                    cumulative_mm += float(row.net_displacement_mm or 0.0)
                    # Dựng pseudo pos_e = cumulative (m), pos_n=0, pos_u=0
                    gnss_for_correlation.append({
                        "timestamp": ts,
                        "data": {
                            "pos_e": cumulative_mm / 1000.0,
                            "pos_n": 0.0,
                            "pos_u": 0.0
                        }
                    })

            if len(gnss_for_correlation) >= 2 and len(rain_data) >= 2:
                historical_rain = [{"timestamp": d.timestamp, "data": d.data} for d in rain_data]
                rain_correlation = analyzer.analyze_rainfall_displacement_correlation(
                    gnss_data=gnss_for_correlation,
                    rain_data=historical_rain,
                    window_days=days,
                    config=station.config or {}
                )
                rain_correlation["model"] = "slide_model"
                result["rainfall_correlation"] = rain_correlation
            else:
                gnss_count = len(gnss_for_correlation)
                rain_count = len(rain_data)
                result["rainfall_correlation"] = {
                    "available": False,
                    "model": "slide_model",
                    "message": f"Cần cả dữ liệu GNSS và mưa để phân tích tương quan. "
                               f"Hiện có: {gnss_count} điểm GNSS, {rain_count} bản ghi mưa."
                }
        else:
            result["rainfall_correlation"] = {
                "available": False,
                "model": "slide_model",
                "message": "Chưa chạy phân tích tương quan Slide model. Nhấn 'Chạy AI Slide model' để thực hiện."
            }
        
        # 8. Phân tích đa cửa sổ (Multi-Window) - dùng full GNSS data
        if len(historical_gnss_full) >= 2:
            multi_window = analyzer.analyze_multi_window(
                station_id=station_id,
                historical_data=historical_gnss_full,
                config=station.config or {},
                windows=[7, 30, 90]
            )
            result["multi_window"] = multi_window
        else:
            result["multi_window"] = {"available": False, "message": "Không đủ dữ liệu."}
        
        # 9. Overall status
        gnss_ok = result["gnss"].get("status") == "success"
        imu_ok = result["imu"].get("status") == "success"
        multi_window_ok = result.get("multi_window", {}).get("available") is True
        rainfall_ok = result.get("rainfall_correlation", {}).get("available") is True
        
        if gnss_ok or imu_ok or multi_window_ok or rainfall_ok:
            result["status"] = "success"
        else:
            result["status"] = "insufficient_data"
            result["message"] = "Không đủ dữ liệu GNSS và IMU để phân tích."

        # 10. Cross-sensor consensus — đánh giá đồng thuận giữa các model
        result["cross_sensor_consensus"] = analyzer.analyze_cross_sensor_consensus(
            gnss_result=result.get("gnss", {}),
            imu_result=result.get("imu", {}),
            rain_corr_result=result.get("rainfall_correlation", {})
        )

        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in long-term analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stations/{station_id}/gnss-daily-summary")
async def get_gnss_daily_summary(
    station_id: int,
    limit: int = 30,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo ngày (đã rollup)."""
    try:
        n = max(1, min(int(limit), 365))
        res = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(model_data.GnssDailySummary.station_id == station_id)
            .order_by(model_data.GnssDailySummary.day_start_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "day_start_ts": r.day_start_ts,
                    "day_end_ts": r.day_end_ts,
                    "sample_count": r.sample_count,
                    "duration_seconds": r.duration_seconds,
                    "net_displacement_mm": r.net_displacement_mm,
                    "velocity_mm_day": r.velocity_mm_day,
                    "velocity_mm_second": r.velocity_mm_second,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching GNSS daily summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stations/{station_id}/gnss-weekly-summary")
async def get_gnss_weekly_summary(
    station_id: int,
    limit: int = 12,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo tuần (từ 7 daily summaries liên tiếp)."""
    try:
        n = max(1, min(int(limit), 104))
        res = await db_data.execute(
            select(model_data.GnssWeeklySummary)
            .where(model_data.GnssWeeklySummary.station_id == station_id)
            .order_by(model_data.GnssWeeklySummary.week_end_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "week_start_ts": r.week_start_ts,
                    "week_end_ts": r.week_end_ts,
                    "day_count": r.day_count,
                    "total_displacement_mm": r.total_displacement_mm,
                    "avg_velocity_mm_day": r.avg_velocity_mm_day,
                    "max_velocity_mm_day": r.max_velocity_mm_day,
                    "min_velocity_mm_day": r.min_velocity_mm_day,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching GNSS weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS (cho Admin Panel)
# ============================================================================

# ============================================================================
# STATS API (Đếm tổng số lượng bản ghi thực tế)
# ============================================================================
@app.get("/api/admin/db/stats")  #
async def get_database_stats(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        # Đếm Stations
        count_stations = await config_db.execute(select(func.count()).select_from(model_config.Station))
        num_stations = count_stations.scalar()

        # Đếm Devices
        count_devices = await config_db.execute(select(func.count()).select_from(model_config.Device))
        num_devices = count_devices.scalar()

        # Đếm Sensor Data (Total)
        count_data = await data_db.execute(select(func.count()).select_from(model_data.SensorData))
        num_data = count_data.scalar()

        # Đếm Active Alerts (Chưa xử lý)
        count_alerts = await data_db.execute(
            select(func.count()).select_from(model_data.Alert).where(model_data.Alert.is_resolved == False)
        )
        num_alerts = count_alerts.scalar()

        return {
            "stations": num_stations,
            "devices": num_devices,
            "sensor_data": num_data,
            "alerts": num_alerts
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"stations": 0, "devices": 0, "sensor_data": 0, "alerts": 0}

@app.get("/api/admin/db/stations")
async def admin_get_all_stations(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tất cả stations từ DB"""
    try:
        result = await db.execute(select(model_config.Station))
        stations = result.scalars().all()
        
        return [
            {
                "id": s.id,
                "station_code": s.station_code,
                "name": s.name,
                "project_id": s.project_id,
                "location": s.location,
                "status": s.status,
                "last_update": s.last_update,
                "config": s.config,
                "created_at": s.created_at,
                "updated_at": s.updated_at
            }
            for s in stations
        ]
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/db/devices")
async def admin_get_all_devices(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tất cả devices từ DB"""
    try:
        result = await db.execute(select(model_config.Device))
        devices = result.scalars().all()
        
        return [
            {
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "station_id": d.station_id,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "position": d.position,
                "is_active": d.is_active,
                "last_data_time": d.last_data_time,
                "config": d.config,
                "created_at": d.created_at,
                "updated_at": d.updated_at
            }
            for d in devices
        ]
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/db/sensor-data")
async def admin_get_sensor_data(
    limit: int = 500,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy sensor data gần nhất"""
    try:
        result = await db.execute(
            select(model_data.SensorData)
            .order_by(desc(model_data.SensorData.timestamp))
            .limit(limit)
        )
        data = result.scalars().all()
        
        return [
            {
                "id": d.id,
                "station_id": d.station_id,
                "timestamp": d.timestamp,
                "sensor_type": d.sensor_type,
                "data": d.data,
                "value_1": d.value_1,
                "value_2": d.value_2,
                "value_3": d.value_3,
                "value_4": d.value_4,
                "value_5": d.value_5
            }
            for d in data
        ]
    except Exception as e:
        logger.error(f"Error fetching sensor data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/db/alerts")
async def admin_get_alerts(
    limit: int = 200,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy alerts gần nhất"""
    try:
        result = await db.execute(
            select(model_data.Alert)
            .order_by(desc(model_data.Alert.timestamp))
            .limit(limit)
        )
        alerts = result.scalars().all()
        
        return [
            {
                "id": a.id,
                "station_id": a.station_id,
                "timestamp": a.timestamp,
                "level": a.level,
                "category": a.category,
                "message": a.message,
                "is_resolved": a.is_resolved
            }
            for a in alerts
        ]
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# UPDATE/DELETE ENDPOINTS
# ============================================================================

@app.put("/api/admin/db/stations/{record_id}")
async def admin_update_station(
    record_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Cập nhật station record"""
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == record_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Update allowed fields
        for key, value in update_data.items():
            if key not in ['id', '_table'] and hasattr(station, key):
                setattr(station, key, value)
        
        station.updated_at = int(time.time())
        
        await db.commit()
        return {"status": "success", "message": "Station updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating station: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/db/stations/{record_id}")
async def admin_delete_station(
    record_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Xóa station"""
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == record_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Not found")
        
        await db.delete(station)
        await db.commit()
        
        return {"status": "success", "message": f"Deleted station {record_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/db/devices/{record_id}")
async def admin_update_device(
    record_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Device).where(model_config.Device.id == record_id)
        )
        device = result.scalar_one_or_none()
        
        if not device:
            raise HTTPException(status_code=404)
        
        for key, value in update_data.items():
            if key not in ['id', '_table'] and hasattr(device, key):
                setattr(device, key, value)
        
        device.updated_at = int(time.time())
        await db.commit()
        
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/db/devices/{record_id}")
async def admin_delete_device(
    record_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        await db.execute(
            delete(model_config.Device).where(model_config.Device.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/db/sensor-data/{record_id}")
async def admin_delete_sensor_data(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        from sqlalchemy import delete as sql_delete
        await db.execute(
            sql_delete(model_data.SensorData).where(model_data.SensorData.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/db/alerts/{record_id}")
async def admin_delete_alert(
    record_id: int,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        from sqlalchemy import delete as sql_delete
        await db.execute(
            sql_delete(model_data.Alert).where(model_data.Alert.id == record_id)
        )
        await db.commit()
        return {"status": "success"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
# ============================================================================
# WEBSOCKET & HEALTH CHECK
# ============================================================================
@app.websocket("/ws/updates")
@app.websocket("/ws/admin")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        logger.info("WebSocket receive loop ended: %s", detail)
    finally:
        ws_manager.disconnect(websocket)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": time.time(), "db_status": "3-DB-Active"}

@app.get("/")
async def read_root(request: Request):
    legacy_view = (request.query_params.get("view") or "").lower()
    if legacy_view in {"admin", "management"}:
        return RedirectResponse(url="/management", status_code=307)
    if legacy_view in {"map", "login"}:
        return RedirectResponse(url="/", status_code=307)

    file_path = os.path.join(os.path.dirname(__file__), "../../frontend/index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/html; charset=utf-8")
    return {"error": "Frontend not found"}

@app.get("/management")
@app.get("/management.html")
@app.get("/admin")
@app.get("/admin.html")
async def read_app():
    file_path = os.path.join(os.path.dirname(__file__), "../../frontend/app.html")
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/html; charset=utf-8")
    return {"error": "Frontend not found"}

@app.get("/map")
@app.get("/login")
async def redirect_legacy_frontend_routes_to_landing():
    return RedirectResponse(url="/", status_code=307)


# =====================
# Field Unit Provisioning API
# =====================
@app.post("/api/field/register")
async def field_register(payload: Dict[str, Any], db: AsyncSession = Depends(get_config_db)):
    """Register device (bootstrap). Payload: {"device_code": "hw123", "device_type":"pi"}
    Returns enrollment token and device info.
    """
    device_code = payload.get('device_code')
    device_type = payload.get('device_type', 'pi')
    if not device_code:
        raise HTTPException(status_code=400, detail="device_code required")

    # check existing
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()

    import uuid, time
    enroll_token = uuid.uuid4().hex
    token_expiry = int(time.time()) + 3600*24  # 24h

    now_ts = int(time.time())
    if not device:
        new_dev = model_config.Device(
            device_code=device_code,
            name=payload.get('name', device_code),
            station_id=0,
            device_type=device_type,
            mqtt_topic=None,
            position={},
            is_active=True,
            last_data_time=0,
            config={"enroll_token": enroll_token, "token_expiry": token_expiry},
            created_at=now_ts,
            updated_at=now_ts
        )
        db.add(new_dev)
        await db.commit()
        await db.refresh(new_dev)
        device = new_dev
    else:
        cfg = device.config or {}
        cfg.update({"enroll_token": enroll_token, "token_expiry": token_expiry})
        device.config = cfg
        device.updated_at = now_ts
        db.add(device)
        await db.commit()
        await db.refresh(device)

    provision_url = f"/api/field/provision"
    return {"device_code": device.device_code, "device_id": device.id, "enroll_token": enroll_token, "provision_url": provision_url, "token_expiry": token_expiry}


@app.post("/api/field/provision")
async def field_provision(payload: Dict[str, Any], db: AsyncSession = Depends(get_config_db)):
    """Provision device with station assignment and configs.
    Payload: {"device_code":"hw123","enroll_token":"...","station_id":1,"mqtt":{...},"audio_files":[...],"license":"..."}
    """
    device_code = payload.get('device_code')
    token = payload.get('enroll_token')
    if not device_code or not token:
        raise HTTPException(status_code=400, detail="device_code and enroll_token required")

    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    cfg = device.config or {}
    if cfg.get('enroll_token') != token:
        raise HTTPException(status_code=403, detail="invalid enroll token")

    # apply provisioning
    station_id = int(payload.get('station_id', 0))
    mqtt_conf = payload.get('mqtt') or {}
    audio_files = payload.get('audio_files') or []
    license_blob = payload.get('license')

    # set mqtt topic for alerts/commands
    mqtt_topic = f"landslide/{station_id}"

    cfg.update({
        "provisioned": True,
        "provisioned_at": int(time.time()),
        "mqtt": mqtt_conf,
        "audio_files": audio_files,
        "license": license_blob
    })

    device.station_id = station_id
    device.mqtt_topic = mqtt_topic
    device.config = cfg
    device.updated_at = int(time.time())

    db.add(device)
    await db.commit()
    await db.refresh(device)

    return {"status": "ok", "device_id": device.id, "station_id": station_id, "mqtt_topic": mqtt_topic}


@app.get("/api/field/{device_code}/config")
async def field_get_config(device_code: str, token: Optional[str] = None, db: AsyncSession = Depends(get_config_db)):
    """Device fetches its config. Provide enroll_token or provision token as query param 'token'"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    cfg = device.config or {}
    # Accept either enroll_token or provisioned state
    if (cfg.get('enroll_token') and token == cfg.get('enroll_token')) or cfg.get('provisioned'):
        return {"device_code": device.device_code, "device_id": device.id, "station_id": device.station_id, "mqtt_topic": device.mqtt_topic, "config": cfg}
    raise HTTPException(status_code=403, detail="unauthorized")


@app.post("/api/field/{device_code}/status")
async def field_status(device_code: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_config_db)):
    """Device posts health/status. payload example: {"status":"ok","uptime":1234, "audio_files": [...] }"""
    result = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    # update last_data_time and config audio list if provided
    now_ts = int(time.time())
    device.last_data_time = now_ts
    cfg = device.config or {}
    if 'audio_files' in payload:
        cfg['audio_files_local'] = payload.get('audio_files')
    if 'status' in payload:
        cfg['last_status'] = payload.get('status')

    device.config = cfg
    device.updated_at = now_ts
    db.add(device)
    await db.commit()
    return {"status": "ok", "updated_at": now_ts}

app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")
app.mount("/static", StaticFiles(directory="static"), name="static")
# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def get_offline_threshold(station_config: dict, sensor_type: str) -> int:
    """
    Lấy offline threshold từ config của station cho từng loại sensor
    Args:
        station_config: Dictionary config của station
        sensor_type: Loại sensor ('gnss', 'rain', 'water', 'imu')
    Returns:
        Thời gian offline threshold (giây)
    Mặc định:
        - gnss: 300s (5 phút)
        - rain: 300s (5 phút)  
        - water: 300s (5 phút)
        - imu: 300s (5 phút)
    """
    default_map = {
        'gnss': 30,
        'rain': 60,
        'water': 60,
        'imu': 2400,
    }
    default_threshold = default_map.get(sensor_type, 300)
    if not station_config:
        return default_threshold

    offline_config = station_config.get('offline_thresholds', {}) or {}
    try:
        return max(int(offline_config.get(sensor_type, default_threshold)), 15)
    except (TypeError, ValueError):
        return default_threshold

async def _calculate_station_risk_simple(db_data: AsyncSession, station_id: int) -> str:
    try:
        result = await db_data.execute(
            select(model_data.Alert).where(
                and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.is_resolved == False
                )
            )
        )
        alerts = result.scalars().all()
        critical = sum(1 for a in alerts if a.level == "CRITICAL")
        warning = sum(1 for a in alerts if a.level == "WARNING")
        
        if critical >= 1: return "EXTREME"
        elif warning >= 1: return "MEDIUM"
        return "LOW"
    except:
        return "LOW"
