# ==============================================================================
# == backend/app/routers/admin.py
# ==============================================================================

import asyncio
import csv
import io
import openpyxl
from openpyxl.utils import get_column_letter
import json
import logging
import re
import time
import zipfile
from typing import Optional, Dict, List, Any

import paho.mqtt.client as mqtt
import io
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc, text, func, and_, or_
from datetime import datetime, timedelta
from openpyxl import Workbook
from .. import schemas, auth, config
from ..database import get_auth_db, get_config_db, get_data_db, ConfigSessionLocal, DataSessionLocal
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data
import math
import json
import uuid
import os

EXPORT_TASKS: Dict[str, dict] = {}
EXPORT_LOCK = asyncio.Lock()
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "temp_exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

# Schema cho request
class ExportExcelRequest(BaseModel):
    tables: List[str]  # projects, stations, devices, sensor_data, gnss_adjustments, alerts
    project_ids: Optional[List[int]] = None
    station_ids: Optional[List[int]] = None
    sensor_types: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Console"]
)


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""

    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _excel_sheet_name(base: str, used: set) -> str:
    """Return a valid, unique Excel sheet name (maximum 31 characters)."""
    cleaned = re.sub(r'[\\/*?:\[\]]', '_', str(base or 'Sheet')).strip(" '") or 'Sheet'
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 2
    while candidate.lower() in used:
        tail = f"_{suffix}"
        candidate = f"{cleaned[:31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _zip_component(value: Any, fallback: str) -> str:
    """Return a safe, readable folder/file component for exported ZIP paths."""
    component = str(value or "").strip()
    component = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", component)
    component = re.sub(r"\s+", "_", component).strip(" ._")
    if not component or component in {".", ".."}:
        return fallback
    return component[:120]


def _station_export_path(
    project_code: Any, station_code: Any, station_id: Any, filename: str
) -> str:
    project_folder = _zip_component(project_code, "UNKNOWN_PROJECT")
    station_folder = _zip_component(station_code, f"station_{station_id}")
    safe_filename = _zip_component(filename, "DATA.csv")
    return f"{project_folder}/{station_folder}/{safe_filename}"


def _excel_chunks(value: Any, chunk_count: int = 8) -> List[Optional[str]]:
    """Preserve large JSON/payload text across cells without silent truncation."""
    if value is None:
        return [None] * chunk_count
    text_value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    chunk_size = 32760  # Excel cell limit is 32767 characters.
    chunks = [text_value[i:i + chunk_size] for i in range(0, len(text_value), chunk_size)]
    if len(chunks) > chunk_count:
        raise ValueError(f"Export cell content is too large ({len(text_value)} characters)")
    return chunks + [None] * (chunk_count - len(chunks))


def _package_workbook_zip(workbook: Workbook, timestamp_suffix: int):
    """Return one ZIP containing exactly one multi-sheet XLSX workbook."""
    xlsx_output = BytesIO()
    workbook.save(xlsx_output)
    xlsx_output.seek(0)
    xlsx_filename = f"landslide_full_export_{timestamp_suffix}.xlsx"
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(xlsx_filename, xlsx_output.getvalue())
    output.seek(0)
    return output, xlsx_filename


# ------------------------------------------------------------------
# Device provisioning endpoints for admin UI
# ------------------------------------------------------------------


@router.get("/devices/pending")
async def get_pending_devices(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Return devices that are not yet assigned to a station (waiting for provisioning).
    Devices created by field units during registration are created with station_id=0.
    """
    try:
        res = await db.execute(
            select(model_config.Device).where(model_config.Device.station_id == 0)
        )
        devices = res.scalars().all()

        # Simplify output for frontend
        out = []
        for d in devices:
            out.append({
                "id": d.id,
                "device_code": d.device_code,
                "name": d.name,
                "device_type": d.device_type,
                "mqtt_topic": d.mqtt_topic,
                "created_at": d.created_at,
                "config": d.config or {}
            })

        return out
    except Exception as e:
        logger.error(f"Error fetching pending devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProvisionDeviceRequest(BaseModel):
    device_code: str
    station_id: int
    license: Optional[str] = None
    mqtt_topic: Optional[str] = None


@router.post("/devices/provision")
async def provision_device(
    payload: ProvisionDeviceRequest,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Admin action to assign a waiting device to a station and mark it provisioned.
    This updates the device.station_id, mqtt_topic and writes provision metadata to device.config.
    """
    try:
        res = await db.execute(select(model_config.Device).where(model_config.Device.device_code == payload.device_code))
        device = res.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Update station assignment and mqtt topic
        device.station_id = payload.station_id
        if payload.mqtt_topic:
            device.mqtt_topic = payload.mqtt_topic

        # Update config metadata
        cfg = device.config or {}
        cfg['provisioned'] = True
        if payload.license:
            cfg['license'] = payload.license
        cfg['provisioned_by'] = current_user.username
        cfg['provisioned_at'] = int(time.time())
        device.config = cfg

        await db.commit()
        await db.refresh(device)

        return {"status": "ok", "device_code": device.device_code, "station_id": device.station_id}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error provisioning device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# GNSS Origin Reset
# ------------------------------------------------------------------

@router.post("/gnss/reset-origin/{station_id}")
async def reset_gnss_origin(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Locked monitoring origins are immutable by design."""
    raise HTTPException(
        status_code=409,
        detail="GNSS origin is permanently locked and cannot be reset",
    )


# -------------------------
# License generation utils
# -------------------------

def get_license_code_from_string(string_number: str) -> str:
    """Tạo mã license từ một chuỗi số, thuật toán xáo trộn."""
    try:
        length = len(string_number)
        if length == 0:
            return ""
        arr = [0] * (length + 1)
        narr = [0.0] * (length + 1)
        number = float(string_number)
        r_string = ""
        n = length
        number *= n
        arr[0] = int(number * math.pow(10.0, -float(n)))
        for i in range(1, length):
            number = number - float(arr[i - 1]) / math.pow(10.0, -float(n))
            n -= 1
            arr[i] = int(number * math.pow(10, -float(n)))
        arr[length] = (arr[length - 2] + arr[length - 1]) / 2 + 1
        narr[0] = float(arr[0])
        for i in range(1, length + 1):
            narr[i] = (narr[i - 1] + float(arr[i])) / 2.0
        for i in range(length):
            A = narr[i + 1] * math.exp(-0.2)
            # guard against math domain error
            B = 0
            try:
                if arr[length] > 0 and arr[i + 1] > 0:
                    B = (math.log(arr[length], 10)) * math.pow(arr[i + 1], 0.2)
            except Exception:
                B = 0
            r_string += str(int(round(A + B)))
        return r_string
    except (ValueError, IndexError, TypeError, ZeroDivisionError):
        return ""


def generate_pi_license_base(serial_number: str) -> str:
    """Tạo chuỗi số cơ sở từ Serial Number của Pi."""
    base_code_str = ""
    temp_str = ""
    # Chỉ lấy 10 ký tự cuối của serial để tạo mã ngắn gọn và nhất quán
    s_number_part = serial_number[-10:]

    for c in s_number_part:
        temp_str += c.upper() if 'a' <= c.lower() <= 'z' else c

    for char in temp_str:
        base_code_str += str(ord(char))

    # Đảm bảo chuỗi số luôn có độ dài 12
    if len(base_code_str) > 12:
        return base_code_str[:12]
    else:
        return base_code_str.ljust(12, '0')


def generate_customer_license_base(identifier: str) -> str:
    """Tạo chuỗi số cơ sở từ định danh của khách hàng."""
    processed_id = ''.join(filter(str.isalnum, identifier.upper()))
    if len(processed_id) > 12:
        return processed_id[:12]
    return processed_id.ljust(12, '0')


@router.post("/devices/generate-license")
async def generate_license_for_device(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Generate a license for a device and push it to the field unit via MQTT (if possible).
    Payload: {"device_code": "HW123", "customer_id": "OptionalCustomer"}
    """
    device_code = payload.get('device_code')
    customer_id = payload.get('customer_id', '')
    if not device_code:
        raise HTTPException(status_code=400, detail="device_code required")

    try:
        res = await db.execute(select(model_config.Device).where(model_config.Device.device_code == device_code))
        device = res.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Use device_code (serial) as base for generation
        pi_base = generate_pi_license_base(device.device_code)
        customer_base = generate_customer_license_base(customer_id or device.name or "CUSTOMER")

        # Combine bases then produce license string
        combined = pi_base + customer_base
        license_code = get_license_code_from_string(combined)

        # Persist license into device.config
        cfg = device.config or {}
        cfg['license'] = license_code
        cfg['license_generated_by'] = current_user.username
        cfg['license_generated_at'] = int(time.time())
        device.config = cfg
        db.add(device)
        await db.commit()
        await db.refresh(device)

        # Attempt to push license to device via MQTT command
        pushed = False
        try:
            # late import to avoid circular
            from app.main import mqtt_service
            # Pi subscribes to landslide/{station_id}/command
            cmd_topic = f"landslide/{device.station_id}/command"
            payload_msg = json.dumps({
                "cmd": "install_license",
                "license": license_code,
                "device_code": device.device_code,
                "customer_base": customer_base
            })
            mqtt_service.client.publish(cmd_topic, payload_msg)
            pushed = True
            logger.info(f"📡 License pushed to {cmd_topic}")
        except Exception as e:
            logger.warning(f"Could not push license via MQTT: {e}")

        return {"status": "ok", "license": license_code, "pushed": pushed}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating license: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_default_station_config():
    """
    ✅ Cấu hình mặc định cho mỗi trạm
    """
    return {
        "mqtt_topics": {
            "gnss": "",
            "rain": "",
            "water": "",
            "imu": ""
        },
        # Nhóm cảnh báo IMU
        "alerting": {
            "enabled": True
        },
        "ImuAlerting": {
            "tilt_warning_deg": 5.0,
            "tilt_critical_deg": 15.0,
            "imu_warning_confirm_steps": 2,
            "imu_critical_confirm_steps": 1,
            "imu_confirm_steps": 2,
            "shock_threshold_ms2": 5.0
        },
        # Nhóm cảnh báo GNSS (kỹ thuật)
        "GnssAlerting": {
            "gnss_max_hdop": 4.0,
            "gnss_warning_confirm_steps": 3,
            "gnss_critical_confirm_steps": 2,
            "gnss_confirm_steps": 3,
            "gnss_degraded_timeout": 300
        },
        # Nhóm cảnh báo Mưa
        "RainAlerting": {
            "rain_intensity_watch_threshold": 10.0,
            "rain_intensity_warning_threshold": 25.0,
            "rain_intensity_critical_threshold": 50.0,
            "rain_warning_confirm_steps": 2,
            "rain_critical_confirm_steps": 1,
            "rain_confirm_steps": 2
        },
        # Nhóm cảnh báo Mực nước & Chuyển dịch
        "Water": {
            "warning_threshold": 0.15,
            "critical_threshold": 0.30,
            "water_warning_confirm_steps": 3,
            "water_critical_confirm_steps": 2,
            "water_confirm_steps": 3
        },
        "offline_thresholds": {
            "gnss": 30,
            "rain": 60,
            "water": 60,
            "imu": 2400
        },
        # Bảng Cruden & Varnes
        "GNSS_Classification": [
            { "name": "Extremely rapid", "mm_giay": 5000, "m_giay": 0.05, "desc": "> 5 m/s" },
            { "name": "Very rapid", "mm_giay": 4000.0, "m_giay": 0.04, "desc": "3 m/min to 5 m/s" },
            { "name": "Rapid", "mm_giay": 2000.0, "m_giay": 0.005, "desc": "1.8 m/h to 3 m/min" },
            { "name": "Moderate", "mm_giay": 1000.0, "m_giay": 0.03, "desc": "13 mm/mo to 1.8 m/h" },
            { "name": "Slow", "mm_giay": 0.000051, "m_giay": 0.01, "desc": "1.6 m/y to 13 mm/mo" },
            { "name": "Very slow", "mm_giay": 0.000001, "m_giay": 1.0E-09, "desc": "16 mm/y to 1.6 m/y" },
            { "name": "Extremely slow", "mm_giay": 0, "m_giay": 0.0, "desc": "< 16 mm/y" }
        ],
        "long_term_analysis": {
            "enabled": True,
            "window_days": 30,
            "trend_detection": True
        },
        # Cấu hình Truyền dữ liệu RTK (1Hz) ra ngoài
        "gnss_rtk_forwarding": {
            "enabled": False,
            "rtk_topic": "",       # Publish RTK Topic (1Hz, cm accuracy)
            "fields": {
                "X":   True,   # Tọa độ E hiện tại (m)
                "Y":   True,   # Tọa độ N hiện tại (m)
                "H":   True,   # Độ cao tuyệt đối (m)
                "dX":  True,   # Chuyển vị E (m)
                "dY":  True,   # Chuyển vị N (m)
                "dH":  True,   # Chuyển vị U (m)
                "VdX": True,   # Vận tốc E (mm/phút)
                "VdY": True,   # Vận tốc N (mm/phút)
                "VdH": True    # Vận tốc U (mm/phút)
            }
        },
        "data_logging": {
            "gnss": {
                "interval": 1,
                "enabled_fields": ["raw_gngga", "gga_utc", "gga_timestamp", "received_timestamp", "lat", "lon", "h", "pos_e", "pos_n", "pos_u", "total_displacement_mm", "vel_e", "vel_n", "vel_u", "speed_2d", "speed_2d_mm_s", "raw_vel_e_mm_s", "raw_vel_n_mm_s", "raw_vel_u_mm_s", "raw_speed_2d_mm_s", "velocity_method", "velocity_sample_count", "velocity_window_duration_s", "velocity_residual_rms_mm", "velocity_residual_mad_mm", "velocity_uncertainty_mm_s", "velocity_confidence_95_mm_s", "velocity_reliable", "velocity_significant", "velocity_out_of_range", "fix_quality", "fix_mode", "num_sats", "hdop"],
                "save_rejected_raw": True,
                "save_forward_payload": True,
                "save_no_data_status": False
            },
            "imu": {
                "interval": 300,
                "enabled_fields": ["roll", "pitch", "yaw", "total_accel", "battery"]
            },
            "rain": {
                "interval": 300,
                "enabled_fields": ["intensity_mm_h", "accumulated_mm"]
            },
            "water": {
                "interval": 300,
                "enabled_fields": ["water_level", "intensity_mm_h"]
            }
        }
    }

# ============================================================================
# USER MANAGEMENT (Sử dụng Auth DB)
# ============================================================================

@router.get("/users", response_model=List[schemas.UserResponse])
async def get_users(
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    result = await db.execute(select(model_auth.User))
    return result.scalars().all()

@router.post("/users", response_model=schemas.UserResponse)
async def create_user(
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
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

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_auth_db), # ✅ Dùng Auth DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot delete the admin user")
    
    await db.execute(delete(model_auth.User).where(model_auth.User.id == user_id))
    await db.commit()
    return {"status": "success"}

@router.put("/users/{user_id}/status")
async def toggle_user_status(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.username == 'admin':
        raise HTTPException(status_code=400, detail="Cannot change status of the admin user")

    is_active = payload.get("is_active", True)
    user.is_active = is_active
    await db.commit()
    return {"status": "success", "is_active": user.is_active}

@router.put("/users/{user_id}/projects")
async def update_user_projects(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_auth_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Update project assignments for a user (typically operator)."""
    result = await db.execute(select(model_auth.User).where(model_auth.User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.assigned_projects = payload.get("assigned_projects", [])
    await db.commit()
    return {"status": "success", "assigned_projects": user.assigned_projects}

@router.post("/db/export-csv")  
async def export_database_csv(
    request: ExportExcelRequest,
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):

    try:
        # Buffer trong RAM để tạo file ZIP
        zip_buffer = BytesIO()
        
        has_data = False
        
        # Mở file ZIP để ghi
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
            
            # ============================================
            # 1. PROJECTS
            # ============================================
            if 'projects' in request.tables:
                try:
                    res = await config_db.execute(select(model_config.Project))
                    data = res.scalars().all()
                    if data:
                        rows = [{
                            'id': p.id,
                            'code': p.project_code,
                            'name': p.name,
                            'description': p.description,
                            'active': p.is_active
                        } for p in data]
                        
                        # Ghi vào file CSV bên trong ZIP
                        zf.writestr("projects.csv", rows_to_csv(rows))
                        has_data = True
                        logger.info(f"✅ CSV: Exported {len(data)} projects")
                except Exception as e:
                    logger.error(f"❌ CSV Error projects: {e}")

            # ============================================
            # 2. STATIONS
            # ============================================
            if 'stations' in request.tables:
                try:
                    res = await config_db.execute(select(model_config.Station))
                    data = res.scalars().all()
                    if data:
                        rows = [{
                            'id': s.id,
                            'code': s.station_code,
                            'name': s.name,
                            'status': s.status,
                            'last_update': datetime.fromtimestamp(s.last_update).strftime('%Y-%m-%d %H:%M:%S') if s.last_update else '',
                            'location': str(s.location)
                        } for s in data]

                        zf.writestr("stations.csv", rows_to_csv(rows))
                        has_data = True
                        logger.info(f"✅ CSV: Exported {len(data)} stations")
                except Exception as e:
                    logger.error(f"❌ CSV Error stations: {e}")

            # ============================================
            # 3. DEVICES
            # ============================================
            if 'devices' in request.tables:
                try:
                    res = await config_db.execute(select(model_config.Device))
                    data = res.scalars().all()
                    if data:
                        rows = [{
                            'id': d.id,
                            'code': d.device_code,
                            'type': d.device_type,
                            'topic': d.mqtt_topic,
                            'station_id': d.station_id
                        } for d in data]

                        zf.writestr("devices.csv", rows_to_csv(rows))
                        has_data = True
                        logger.info(f"✅ CSV: Exported {len(data)} devices")
                except Exception as e:
                    logger.error(f"❌ CSV Error devices: {e}")

            # ============================================
            # 4. SENSOR DATA 
            # ============================================
            if 'sensor_data' in request.tables:
                try:
                    logger.info("⏳ CSV: Querying ALL sensor data (Please wait)...")
                    
                    # Pre-fetch station mapping (project_code, station_code) for path hierarchy
                    stations_res = await config_db.execute(select(model_config.Station))
                    stations = stations_res.scalars().all()
                    
                    projects_res = await config_db.execute(select(model_config.Project))
                    projects = {p.id: p.project_code for p in projects_res.scalars().all()}
                    
                    station_mapping = {}
                    for s in stations:
                        p_code = projects.get(s.project_id, "UNKNOWN_PROJECT")
                        station_mapping[s.id] = {
                            "project_code": p_code,
                            "station_code": s.station_code
                        }

                    res = await data_db.execute(
                        select(model_data.SensorData)
                        .order_by(desc(model_data.SensorData.timestamp))
                    )
                    data = res.scalars().all()
                    
                    if data:
                        # Group data by (project_code, station_code, sensor_type)
                        grouped_data = {}
                        
                        for d in data:
                            mapping = station_mapping.get(d.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{d.station_id}"
                            })
                            p_code = mapping["project_code"]
                            s_code = mapping["station_code"]
                            
                            export_sensor_type = d.sensor_type
                            if d.sensor_type == 'gnss_audit':
                                data_dict = d.data if isinstance(d.data, dict) else {}
                                is_abnormal = False
                                suspicious = ["NON_MONOTONIC_GGA_TIME", "UNSTABLE_FIX", "PERSISTENT_OFFSET_QUARANTINED"]
                                if data_dict.get("reason") in suspicious:
                                    is_abnormal = True
                                elif data_dict.get("record_kind") == "forward":
                                    if data_dict.get("forward_action") != "published" or str(data_dict.get("forward_rc", "0")) != "0":
                                        is_abnormal = True
                                export_sensor_type = 'gnss_bat_thuong' if is_abnormal else 'gnss_raw_1hz'
                            elif d.sensor_type == 'gnss':
                                export_sensor_type = 'gnss'
                            
                            if export_sensor_type == 'gnss_raw_1hz':
                                continue
                                
                            group_key = (p_code, s_code, export_sensor_type)
                            if group_key not in grouped_data:
                                grouped_data[group_key] = []
                            
                            # Flatten raw_json (data) fields
                            row_dict = {
                                'id': d.id,
                                'time_str': datetime.fromtimestamp(d.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                'timestamp': d.timestamp,
                                'project_code': p_code,
                                'station_code': s_code,
                                'station_id': d.station_id,
                                'type': d.sensor_type,
                                'record_type': 'audit' if d.sensor_type == 'gnss_audit' else 'measurement',
                            }
                            
                            # Flatten các giá trị quan trọng từ raw JSON
                            if isinstance(d.data, dict):
                                for k, v in d.data.items():
                                    row_dict[k] = v
                            else:
                                row_dict['raw_json'] = str(d.data)
                                
                            grouped_data[group_key].append(row_dict)
                            
                        # Ghi từng group ra từng file CSV trong thư mục phân cấp tương ứng trong file ZIP
                        gnss_by_station = {}
                        for (p_code, s_code, s_type), items in grouped_data.items():
                            if s_type in ['gnss', 'gnss_bat_thuong', 'gnss_anomaly']:
                                key = (p_code, s_code)
                                if key not in gnss_by_station:
                                    gnss_by_station[key] = {'gnss': [], 'gnss_bat_thuong': [], 'gnss_anomaly': []}
                                gnss_by_station[key][s_type] = items
                            else:
                                export_name = "binhsai.csv" if s_type == "gnss_adjustment_result" else f"{s_type}.csv"
                                file_name = f"sensor_data/{p_code}/{s_code}/{export_name}"
                                zf.writestr(file_name, rows_to_csv(items))
                                has_data = True
                        
                        # Process GNSS data to XLSX
                        for (p_code, s_code), data_types in gnss_by_station.items():
                            wb = openpyxl.Workbook()
                            ws_gngga = wb.active
                            ws_gngga.title = "GNGGA"
                            ws_agric = wb.create_sheet("AGRIC")
                            ws_anomaly = wb.create_sheet("Ngoại lệ")
                            
                            # Helper to write rows
                            def write_rows(ws, headers, data_list):
                                ws.append(headers)
                                for item in data_list:
                                    row = [item.get(h, "") for h in headers]
                                    ws.append(row)
                                    
                            # GNGGA & AGRIC
                            gngga_data = []
                            agric_data = []
                            gnss_items = data_types.get('gnss', [])
                            
                            # Also collect from gnss_anomaly
                            anomaly_items = data_types.get('gnss_anomaly', []) + data_types.get('gnss_bat_thuong', [])
                            
                            for item in gnss_items:
                                payload = item.get('raw_payload') or ""
                                lines = payload.split('\n')
                                for line in lines:
                                    line = line.strip()
                                    if '$GNGGA' in line or '$GPGGA' in line:
                                        row_data = item.copy()
                                        row_data['GNGGA'] = line
                                        gngga_data.append(row_data)
                                    elif '$AGRIC' in line:
                                        row_data = item.copy()
                                        row_data['AGRIC'] = line
                                        agric_data.append(row_data)
                                        
                            gngga_headers = ['time_str', 'GNGGA']
                            agric_headers = ['time_str', 'AGRIC']
                            anomaly_headers = ['time_str', 'reason', 'type', 'raw_payload', 'raw_json']
                            
                            write_rows(ws_gngga, gngga_headers, gngga_data)
                            write_rows(ws_agric, agric_headers, agric_data)
                            write_rows(ws_anomaly, anomaly_headers, anomaly_items)
                            
                            # Auto-adjust column width
                            for ws in [ws_gngga, ws_agric, ws_anomaly]:
                                for column_cells in ws.columns:
                                    length = max(len(str(cell.value)) for cell in column_cells)
                                    ws.column_dimensions[get_column_letter(column_cells[0].column)].width = min(length + 2, 100)
                                    
                            mem_file = io.BytesIO()
                            wb.save(mem_file)
                            file_name = f"sensor_data/{p_code}/{s_code}/gnss.xlsx"
                            zf.writestr(file_name, mem_file.getvalue())
                            has_data = True
                            
                        logger.info(f"✅ CSV: Exported {len(data)} sensor records into {len(grouped_data)} files")
                    else:
                        logger.info("⚠️ CSV: No sensor data found")
                        
                except Exception as e:
                    logger.error(f"❌ CSV Error sensor_data: {e}")

            # ============================================
            # 5. ALERTS 
            # ============================================
            if 'alerts' in request.tables:
                try:
                    # Pre-fetch station mapping if it wasn't already queried
                    if 'sensor_data' not in request.tables:
                        stations_res = await config_db.execute(select(model_config.Station))
                        stations = stations_res.scalars().all()
                        
                        projects_res = await config_db.execute(select(model_config.Project))
                        projects = {p.id: p.project_code for p in projects_res.scalars().all()}
                        
                        station_mapping = {}
                        for s in stations:
                            p_code = projects.get(s.project_id, "UNKNOWN_PROJECT")
                            station_mapping[s.id] = {
                                "project_code": p_code,
                                "station_code": s.station_code
                            }

                    res = await data_db.execute(
                        select(model_data.Alert)
                        .order_by(desc(model_data.Alert.timestamp))
                    )
                    data = res.scalars().all()
                    
                    if data:
                        rows = []
                        for a in data:
                            mapping = station_mapping.get(a.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{a.station_id}"
                            })
                            p_code = mapping["project_code"]
                            s_code = mapping["station_code"]
                            
                            rows.append({
                                'id': a.id,
                                'time_str': datetime.fromtimestamp(a.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                'timestamp': a.timestamp,
                                'project_code': p_code,
                                'station_code': s_code,
                                'station_id': a.station_id,
                                'level': a.level,
                                'category': a.category,
                                'message': a.message,
                                'resolved': a.is_resolved
                            })

                        zf.writestr("alerts.csv", rows_to_csv(rows))
                        has_data = True
                        logger.info(f"✅ CSV: Exported {len(data)} alerts")
                except Exception as e:
                    logger.error(f"❌ CSV Error alerts: {e}")

        # Kết thúc việc ghi ZIP
        if not has_data:
            raise HTTPException(status_code=400, detail="Không có dữ liệu để xuất")
            
        zip_buffer.seek(0)
        
        # Trả về file ZIP
        filename = f"landslide_backup_{int(time.time())}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        logger.error(f"❌ Export CSV Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# CLEAR ALL DATABASE
# ============================================================================

@router.post("/db/export-excel/start")
async def start_export_database_excel(
    request: ExportExcelRequest,
    background_tasks: BackgroundTasks,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Bắt đầu tác vụ xuất Excel chạy ngầm."""
    allowed = {'projects', 'stations', 'devices', 'sensor_data', 'gnss_adjustments', 'alerts'}
    selected = [table for table in request.tables if table in allowed]
    if not selected:
        raise HTTPException(status_code=400, detail="No valid export table selected")

    task_id = str(uuid.uuid4())
    EXPORT_TASKS[task_id] = {
        "status": "pending",
        "percent": 0,
        "message": "Đang chuẩn bị...",
        "file_path": None,
        "filename": None,
        "error": None
    }
    
    background_tasks.add_task(_export_excel_task, task_id, request, selected)
    return {"task_id": task_id}

@router.get("/db/export-excel/{task_id}/progress")
async def get_export_progress(
    task_id: str,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tiến độ của tác vụ xuất."""
    if task_id not in EXPORT_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return EXPORT_TASKS[task_id]

@router.get("/db/export-excel/{task_id}/download")
async def download_export_excel(
    task_id: str,
    background_tasks: BackgroundTasks,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Tải file ZIP đã xuất xong."""
    if task_id not in EXPORT_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = EXPORT_TASKS[task_id]
    if task["status"] != "completed" or not task["file_path"]:
        raise HTTPException(status_code=400, detail="Export not completed yet")
    
    filepath = task["file_path"]
    filename = task["filename"]
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    def cleanup_file():
        try:
            os.remove(filepath)
            del EXPORT_TASKS[task_id]
        except Exception as e:
            logger.error(f"Failed to delete temp export file {filepath}: {e}")
            
    background_tasks.add_task(cleanup_file)
    
    return FileResponse(
        path=filepath, 
        filename=filename, 
        media_type="application/zip"
    )

async def _export_excel_task(task_id: str, request: ExportExcelRequest, selected: List[str]):
    filepath = None
    lock_acquired = False
    try:
        EXPORT_TASKS[task_id]["message"] = "Đang chờ lượt xuất dữ liệu..."
        await EXPORT_LOCK.acquire()
        lock_acquired = True
        EXPORT_TASKS[task_id]["status"] = "running"
        EXPORT_TASKS[task_id]["message"] = "Đang phân tích phạm vi dữ liệu..."
        
        timestamp_suffix = int(time.time())
        filename = f"landslide_backup_{timestamp_suffix}.zip"
        filepath = os.path.join(EXPORT_DIR, f"{task_id}_{filename}")
        
        # Level 1 is dramatically lighter on the event loop while still shrinking
        # repetitive CSV well. Only one export runs at once (EXPORT_LOCK).
        with zipfile.ZipFile(
            filepath, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            
            def add_csv(filename_in_zip: str, headers: List[str], rows: List[List[Any]]):
                if not rows:
                    return 0
                with archive.open(filename_in_zip, "w") as bin_f:
                    with io.TextIOWrapper(bin_f, encoding="utf-8-sig", newline='') as text_f:
                        writer = csv.writer(text_f)
                        writer.writerow(headers)
                        for r in rows:
                            writer.writerow(r)
                return len(rows)

            async with ConfigSessionLocal() as config_db:
                async with DataSessionLocal() as data_db:
                    exported_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    total_records = 0
                    records_processed = 0
                    summary_rows = []

                    # 1. Fetch config boundaries
                    projects_result = await config_db.execute(select(model_config.Project))
                    all_project_rows = projects_result.scalars().all()
                    project_filter = set(request.project_ids or [])
                    project_rows = [p for p in all_project_rows if not project_filter or p.id in project_filter]
                    project_codes = {project.id: project.project_code for project in all_project_rows}
                    
                    stations_result = await config_db.execute(select(model_config.Station))
                    all_station_rows = stations_result.scalars().all()
                    station_filter = set(request.station_ids or [])
                    station_rows = [
                        s for s in all_station_rows
                        if (not project_filter or s.project_id in project_filter)
                        and (not station_filter or s.id in station_filter)
                    ]
                    scope_station_ids = {station.id for station in station_rows}
                    station_mapping = {
                        station.id: {
                            "project_code": project_codes.get(station.project_id, "UNKNOWN_PROJECT"),
                            "station_code": station.station_code,
                        }
                        for station in station_rows
                    }
                    all_station_mapping = {
                        station.id: {
                            "project_code": project_codes.get(station.project_id, "UNKNOWN_PROJECT"),
                            "station_code": station.station_code,
                        }
                        for station in all_station_rows
                    }
                    requested_sensor_types = set(request.sensor_types or [])

                    # 2. Count data
                    EXPORT_TASKS[task_id]["message"] = "Đang tính toán dung lượng dữ liệu..."
                    total_expected_data = 0
                    
                    sensor_query = select(model_data.SensorData)
                    if scope_station_ids:
                        sensor_query = sensor_query.where(model_data.SensorData.station_id.in_(scope_station_ids))
                    else:
                        sensor_query = sensor_query.where(text("1=0"))

                    # Historical builds stored every successful 1 Hz GNSS forward
                    # as audit data. The filter that previously excluded routine noise
                    # has been removed as per user request to export everything.
                    pass

                    
                    sensor_type_filter = set(requested_sensor_types)
                    if sensor_type_filter:
                        db_sensor_types = set(sensor_type_filter)
                        if 'gnss' in db_sensor_types:
                            db_sensor_types.add('gnss_audit')
                        sensor_query = sensor_query.where(model_data.SensorData.sensor_type.in_(db_sensor_types))
                    # Network-adjustment payloads have their own project-level export.
                    sensor_query = sensor_query.where(
                        model_data.SensorData.sensor_type != 'gnss_adjusted'
                    )
                        
                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            sensor_query = sensor_query.where(model_data.SensorData.timestamp >= start_ts)
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())
                            sensor_query = sensor_query.where(model_data.SensorData.timestamp <= end_ts)
                        except ValueError:
                            pass

                    if 'sensor_data' in selected:
                        count_q = select(func.count()).select_from(sensor_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0

                    adjustment_query = select(model_data.SensorData).where(
                        model_data.SensorData.sensor_type == 'gnss_adjusted'
                    )
                    if scope_station_ids:
                        adjustment_query = adjustment_query.where(
                            model_data.SensorData.station_id.in_(scope_station_ids)
                        )
                    else:
                        adjustment_query = adjustment_query.where(text("1=0"))
                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            adjustment_query = adjustment_query.where(
                                model_data.SensorData.timestamp >= start_ts
                            )
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(
                                f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S'
                            ).timestamp())
                            adjustment_query = adjustment_query.where(
                                model_data.SensorData.timestamp <= end_ts
                            )
                        except ValueError:
                            pass
                    if 'gnss_adjustments' in selected:
                        count_q = select(func.count()).select_from(adjustment_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0
                    
                    alert_query = select(model_data.Alert)
                    if scope_station_ids:
                        alert_query = alert_query.where(model_data.Alert.station_id.in_(scope_station_ids))
                    else:
                        alert_query = alert_query.where(text("1=0"))
                        
                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            alert_query = alert_query.where(model_data.Alert.timestamp >= start_ts)
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())
                            alert_query = alert_query.where(model_data.Alert.timestamp <= end_ts)
                        except ValueError:
                            pass
                    
                    if 'alerts' in selected:
                        count_q = select(func.count()).select_from(alert_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0
                    
                    if total_expected_data == 0 and not any(t in selected for t in ['projects', 'stations', 'devices']):
                        EXPORT_TASKS[task_id]["status"] = "error"
                        EXPORT_TASKS[task_id]["error"] = "No data available for export"
                        return

                    EXPORT_TASKS[task_id]["message"] = "Đang trích xuất cấu hình (Projects, Stations, Devices)..."

                    if 'projects' in selected:
                        count = add_csv(
                            "PROJECTS.csv", ["id", "code", "name", "description", "active"],
                            [[p.id, p.project_code, p.name, p.description, p.is_active] for p in project_rows]
                        )
                        summary_rows.append(["PROJECTS", count, exported_at, "FULL"])
                        total_records += count

                    if 'stations' in selected:
                        count = add_csv(
                            "STATIONS.csv",
                            ["id", "project_code", "code", "name", "status", "last_update", "location"],
                            [[
                                s.id, project_codes.get(s.project_id, "UNKNOWN_PROJECT"), s.station_code,
                                s.name, s.status,
                                datetime.fromtimestamp(s.last_update).strftime('%Y-%m-%d %H:%M:%S') if s.last_update else None,
                                str(s.location) if s.location is not None else None,
                            ] for s in station_rows]
                        )
                        summary_rows.append(["STATIONS", count, exported_at, "FULL"])
                        total_records += count

                    if 'devices' in selected:
                        devices_result = await config_db.execute(select(model_config.Device))
                        devices = [
                            d for d in devices_result.scalars().all()
                            if d.station_id in scope_station_ids
                            and (not requested_sensor_types or d.device_type in requested_sensor_types)
                        ]
                        count = add_csv(
                            "DEVICES.csv",
                            ["id", "project_code", "station_code", "station_id", "code", "type", "topic"],
                            [[
                                d.id,
                                station_mapping.get(d.station_id, {}).get("project_code", "UNKNOWN_PROJECT"),
                                station_mapping.get(d.station_id, {}).get("station_code", f"station_{d.station_id}"),
                                d.station_id, d.device_code, d.device_type, d.mqtt_topic,
                            ] for d in devices]
                        )
                        summary_rows.append(["DEVICES", count, exported_at, "FULL"])
                        total_records += count

                    if 'gnss_adjustments' in selected:
                        EXPORT_TASKS[task_id]["message"] = "Đang đóng gói kết quả bình sai GNSS theo dự án/cụm..."
                        adjustment_result = await data_db.execute(
                            adjustment_query.order_by(
                                model_data.SensorData.timestamp,
                                model_data.SensorData.id,
                            )
                        )
                        unique_adjustments: Dict[tuple, dict] = {}
                        for record in adjustment_result.scalars().all():
                            payload = record.data if isinstance(record.data, dict) else {}
                            payload_project_id = int(payload.get("project_id") or 0)
                            key = (
                                payload_project_id,
                                payload.get("cluster_index"),
                                int(payload.get("computed_at") or record.timestamp or 0),
                            )
                            item = unique_adjustments.setdefault(key, {
                                "payload": payload,
                                "timestamp": int(record.timestamp or 0),
                                "record_ids": [],
                            })
                            item["record_ids"].append(int(record.id))

                        adjustment_rows_by_project: Dict[str, List[List[Any]]] = {}
                        adjustment_headers = [
                            "database_record_ids", "time", "computed_at", "project_id",
                            "project_code", "cluster_index", "cluster_name", "source",
                            "station_ids", "station_codes", "rover_count", "base_name",
                            "base_lat", "base_lon", "base_h", "observation_baselines",
                            "averaged_baselines", "independent_loops", "degrees_of_freedom",
                            "variance_factor", "reference_std_m0", "weighted_residual_sum",
                            "max_normalized_residual", "global_variance_test_passed",
                            "excel_report_url", "audit_json_url",
                            "payload_json",
                        ]
                        for key, item in unique_adjustments.items():
                            payload = item["payload"]
                            project_id = int(payload.get("project_id") or key[0] or 0)
                            project_code = project_codes.get(project_id, f"PROJECT_{project_id or 'UNKNOWN'}")
                            points = payload.get("points") if isinstance(payload.get("points"), dict) else {}
                            station_ids = sorted({
                                int(point.get("station_id"))
                                for point in points.values()
                                if isinstance(point, dict) and point.get("station_id") is not None
                            })
                            station_codes = [
                                all_station_mapping.get(station_id, {}).get(
                                    "station_code", f"station_{station_id}"
                                )
                                for station_id in station_ids
                            ]
                            quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
                            global_test = quality.get("global_test") if isinstance(quality.get("global_test"), dict) else {}
                            base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
                            computed_at = int(payload.get("computed_at") or item["timestamp"] or 0)
                            safe_project = _zip_component(project_code, f"project_{project_id}")
                            cluster_label = _zip_component(
                                payload.get("cluster_name") or f"cluster_{payload.get('cluster_index', 0)}",
                                "cluster",
                            )
                            run_stem = f"{computed_at}_{cluster_label}"
                            folder = f"gnss_adjustments/{safe_project}"
                            archive.writestr(
                                f"{folder}/{run_stem}.json",
                                json.dumps(payload, ensure_ascii=False, indent=2),
                            )
                            excel_url = payload.get("excel_report_url")
                            if isinstance(excel_url, str) and excel_url:
                                excel_name = os.path.basename(excel_url.split("?", 1)[0])
                                excel_path = os.path.abspath(os.path.join(
                                    os.path.dirname(__file__), "..", "..", "static", "adjustments", excel_name
                                ))
                                if os.path.isfile(excel_path):
                                    archive.write(excel_path, f"{folder}/{run_stem}.xlsx")

                            adjustment_rows_by_project.setdefault(safe_project, []).append([
                                ";".join(map(str, sorted(item["record_ids"]))),
                                datetime.fromtimestamp(computed_at).strftime('%Y-%m-%d %H:%M:%S') if computed_at else None,
                                computed_at, project_id, project_code,
                                payload.get("cluster_index"), payload.get("cluster_name"), payload.get("source"),
                                ";".join(map(str, station_ids)), ";".join(station_codes),
                                payload.get("rover_count"), base.get("name"), base.get("lat"),
                                base.get("lon"), base.get("h"),
                                quality.get("observation_baseline_count", len(payload.get("baseline_observations") or [])),
                                quality.get("averaged_baseline_count", len(payload.get("baselines") or [])),
                                len(payload.get("loops") or []), quality.get("degrees_of_freedom"),
                                quality.get("variance_factor"), quality.get("reference_standard_deviation"),
                                quality.get("weighted_residual_sum"), quality.get("max_standardized_residual"),
                                global_test.get("passed"), excel_url,
                                payload.get("audit_json_url"),
                                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                            ])

                        adjustment_count = 0
                        for project_code, rows in sorted(adjustment_rows_by_project.items()):
                            count = add_csv(
                                f"gnss_adjustments/{project_code}/ADJUSTMENTS.csv",
                                adjustment_headers,
                                rows,
                            )
                            adjustment_count += count
                            summary_rows.append([
                                f"{project_code}/gnss_adjustments", count, exported_at, "PROJECT/CLUSTER/STATIONS"
                            ])
                        if not adjustment_rows_by_project:
                            summary_rows.append(["GNSS_ADJUSTMENTS", 0, exported_at, "FILTERED"])
                        total_records += adjustment_count
                        records_processed += sum(
                            len(item["record_ids"]) for item in unique_adjustments.values()
                        )

                    sensor_headers = [
                        "id", "time", "timestamp", "project_code", "station_code", "station_id",
                        "sensor_type", "record_type", "raw_gngga", "fix_quality", "fix_mode",
                        "accepted", "reason", "message", "total_displacement_mm", "speed_2d_mm_s",
                        "forward_action", "forward_topic", "forward_broker", "forward_rc",
                        *[f"forward_payload_{i}" for i in range(1, 9)],
                        "value_1", "value_2", "value_3", "value_4", "value_5",
                        *[f"data_json_{i}" for i in range(1, 9)],
                    ]

                    if 'sensor_data' in selected:
                        sensor_stream = await data_db.stream(
                            sensor_query.order_by(
                                model_data.SensorData.station_id,
                                model_data.SensorData.sensor_type,
                                model_data.SensorData.timestamp,
                                model_data.SensorData.id,
                            ).execution_options(yield_per=500)
                        )
                        
                        current_key = None
                        bin_f = None
                        text_f = None
                        writer = None
                        sensor_counts = {}

                        async for d in sensor_stream.scalars():
                            mapping = station_mapping.get(d.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{d.station_id}",
                            })
                            p_code, s_code = mapping["project_code"], mapping["station_code"]
                            sheet_type = d.sensor_type
                            if d.sensor_type == 'gnss_audit':
                                data_dict = d.data if isinstance(d.data, dict) else {}
                                is_abnormal = False
                                suspicious = ["NON_MONOTONIC_GGA_TIME", "UNSTABLE_FIX", "PERSISTENT_OFFSET_QUARANTINED"]
                                if data_dict.get("reason") in suspicious:
                                    is_abnormal = True
                                elif data_dict.get("record_kind") == "forward":
                                    if data_dict.get("forward_action") != "published" or str(data_dict.get("forward_rc", "0")) != "0":
                                        is_abnormal = True
                                sheet_type = 'gnss_bat_thuong' if is_abnormal else 'gnss_raw_1hz'
                            elif d.sensor_type == 'gnss':
                                sheet_type = 'gnss'

                            if sheet_type == 'gnss_raw_1hz':
                                continue

                            key = (p_code, s_code, sheet_type)
                            
                            if current_key != key:
                                if text_f:
                                    text_f.close()
                                    bin_f.close()
                                
                                export_name = f"{_zip_component(sheet_type, 'sensor').upper()}.csv"
                                base_sheet_title = _station_export_path(
                                    p_code, s_code, d.station_id, export_name
                                )
                                bin_f = archive.open(base_sheet_title, "w")
                                text_f = io.TextIOWrapper(bin_f, encoding="utf-8-sig", newline='')
                                writer = csv.writer(text_f)
                                writer.writerow(sensor_headers)
                                current_key = key

                            payload = d.data if isinstance(d.data, dict) else {"raw_value": d.data}
                            writer.writerow([
                                d.id, datetime.fromtimestamp(d.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                d.timestamp, p_code, s_code, d.station_id, d.sensor_type,
                                "audit" if d.sensor_type == "gnss_audit" else "measurement",
                                payload.get("raw_gngga"), payload.get("fix_quality"), payload.get("fix_mode"),
                                payload.get("accepted"), payload.get("reason"), payload.get("message"),
                                payload.get("total_displacement_mm"), payload.get("speed_2d_mm_s"),
                                payload.get("forward_action"), payload.get("forward_topic"),
                                payload.get("forward_broker"), payload.get("forward_rc"),
                                *_excel_chunks(payload.get("forward_payload"), 8),
                                d.value_1, d.value_2, d.value_3, d.value_4, d.value_5,
                                *_excel_chunks(payload, 8),
                            ])
                            
                            count_key = f"{p_code}/{s_code}/{sheet_type}"
                            sensor_counts[count_key] = sensor_counts.get(count_key, 0) + 1
                            total_records += 1
                            records_processed += 1
                            
                            if records_processed % 250 == 0:
                                EXPORT_TASKS[task_id]["percent"] = min(99, int((records_processed / total_expected_data) * 99)) if total_expected_data else 50
                                EXPORT_TASKS[task_id]["message"] = f"Đang xuất {records_processed}/{total_expected_data} dòng dữ liệu..."
                                await asyncio.sleep(0) # yield control to avoid blocking event loop

                        if text_f:
                            text_f.close()
                            bin_f.close()

                        if sensor_counts:
                            for dataset, count in sorted(sensor_counts.items()):
                                summary_rows.append([dataset, count, exported_at, "FULL"])
                        else:
                            summary_rows.append(["SENSOR_DATA", 0, exported_at, "FULL"])

                    if 'alerts' in selected:
                        alert_headers = [
                            "id", "time", "timestamp", "project_code", "station_code", "station_id",
                            "level", "category", "message", "resolved",
                        ]
                        alert_count = 0
                        alert_counts = {}
                        current_alert_key = None
                        bin_f = None
                        text_f = None
                        writer = None
                        alert_stream = await data_db.stream(
                            alert_query.order_by(
                                model_data.Alert.station_id,
                                model_data.Alert.timestamp,
                                model_data.Alert.id,
                            ).execution_options(yield_per=500)
                        )
                        async for alert in alert_stream.scalars():
                            mapping = station_mapping.get(alert.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{alert.station_id}",
                            })
                            alert_key = (
                                mapping["project_code"], mapping["station_code"], alert.station_id
                            )
                            if current_alert_key != alert_key:
                                if text_f:
                                    text_f.close()
                                bin_f = archive.open(
                                    _station_export_path(
                                        mapping["project_code"],
                                        mapping["station_code"],
                                        alert.station_id,
                                        "ALERTS.csv",
                                    ),
                                    "w",
                                )
                                text_f = io.TextIOWrapper(
                                    bin_f, encoding="utf-8-sig", newline=''
                                )
                                writer = csv.writer(text_f)
                                writer.writerow(alert_headers)
                                current_alert_key = alert_key

                            writer.writerow([
                                alert.id, datetime.fromtimestamp(alert.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                alert.timestamp, mapping["project_code"], mapping["station_code"], alert.station_id,
                                alert.level, alert.category, alert.message, alert.is_resolved,
                            ])
                            alert_count += 1
                            alert_dataset = (
                                f"{mapping['project_code']}/{mapping['station_code']}/alerts"
                            )
                            alert_counts[alert_dataset] = alert_counts.get(alert_dataset, 0) + 1
                            total_records += 1
                            records_processed += 1
                            
                            if records_processed % 250 == 0:
                                EXPORT_TASKS[task_id]["percent"] = min(99, int((records_processed / total_expected_data) * 99)) if total_expected_data else 50
                                EXPORT_TASKS[task_id]["message"] = f"Đang xuất {records_processed}/{total_expected_data} dòng dữ liệu..."
                                await asyncio.sleep(0)
                        
                        if text_f:
                            text_f.close()
                        if alert_counts:
                            for dataset, count in sorted(alert_counts.items()):
                                summary_rows.append([dataset, count, exported_at, "FULL"])
                        else:
                            summary_rows.append(["ALERTS", 0, exported_at, "FULL"])

                    summary_rows.append(["TOTAL", total_records, exported_at, "FULL"])
                    add_csv("EXPORT_SUMMARY.csv", ["dataset", "record_count", "exported_at", "scope"], summary_rows)

        # ZipFile is closed automatically by the context manager, finishing the compression.
        
        EXPORT_TASKS[task_id]["status"] = "completed"
        EXPORT_TASKS[task_id]["percent"] = 100
        EXPORT_TASKS[task_id]["message"] = "Hoàn thành!"
        EXPORT_TASKS[task_id]["file_path"] = filepath
        EXPORT_TASKS[task_id]["filename"] = filename

    except Exception as e:
        logger.error(f"Excel full export background task failed: {e}", exc_info=True)
        EXPORT_TASKS[task_id]["status"] = "error"
        EXPORT_TASKS[task_id]["error"] = str(e)
        EXPORT_TASKS[task_id]["message"] = "Xuất dữ liệu thất bại"
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                logger.warning("Could not remove partial export file %s", filepath)
    finally:
        if lock_acquired:
            EXPORT_LOCK.release()


@router.post("/db/clear-all")
async def clear_all_database(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ XÓA TOÀN BỘ dữ liệu trong Data DB
    Chỉ xóa sensor_data và alerts, GIỮ LẠI stations & devices
    """
    try:
        # ⚠️ NGUY HIỂM: Chỉ dành cho Admin
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin can clear database")

        # Sử dụng TRUNCATE để xóa nhanh và reset sequence (ID) về 1
        await data_db.execute(text("TRUNCATE TABLE sensor_data, alerts RESTART IDENTITY CASCADE"))
        await data_db.commit()

        logger.warning(f"⚠️ Data Database TRUNCATED by {current_user.username}")

        return {
            "status": "success",
            "message": "Đã xóa sạch dữ liệu cảm biến và Reset ID về 1."
        }

    except HTTPException:
        raise
    except Exception as e:
        await data_db.rollback()
        logger.error(f"❌ Clear database error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# THÊM ENDPOINT ĐỂ XÓA RIÊNG TỪNG TABLE
# ============================================================================

@router.post("/db/clear-table/{table_name}")
async def clear_specific_table(
    table_name: str,
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ Xóa dữ liệu của 1 bảng cụ thể
    Hỗ trợ: sensor_data, alerts
    """
    try:
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin")
        
        if table_name == 'sensor_data':
            count = await data_db.execute(text("SELECT COUNT(*) FROM sensor_data"))
            await data_db.execute(delete(model_data.SensorData))
            
        elif table_name == 'alerts':
            count = await data_db.execute(text("SELECT COUNT(*) FROM alerts"))
            await data_db.execute(delete(model_data.Alert))
            
        else:
            raise HTTPException(status_code=400, detail="Table not supported")
        
        await data_db.commit()
        
        deleted = count.scalar()
        logger.warning(f"⚠️ Table {table_name} cleared: {deleted} records")
        
        return {
            "status": "success",
            "table": table_name,
            "deleted_count": deleted
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await data_db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
# ============================================================================
# SYSTEM CONFIG VIEW
# ============================================================================

@router.get("/system-config")
async def get_system_config(
    db: AsyncSession = Depends(get_config_db), 
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    # 1. Thử lấy từ DB
    result = await db.execute(
        select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "main_config")
    )
    db_config = result.scalar_one_or_none()
    
    if db_config:
        return db_config.value

    # 2. Nếu DB chưa có, trả về mặc định từ file Settings
    return {
        "mqtt": {
            "broker": config.settings.MQTT_BROKER,
            "port": config.settings.MQTT_PORT,
            "user": config.settings.MQTT_USER,
            "password": config.settings.MQTT_PASSWORD,
            "topic_reload_interval": config.settings.TOPIC_RELOAD_INTERVAL
        },
        "confirmation": {
            "gnss": 3, "rain": 2, "water": 3, "imu": 1
        },
        "save_intervals": {
            "gnss": config.settings.SAVE_INTERVAL_GNSS,
            "rain": config.settings.SAVE_INTERVAL_RAIN,
            "water": config.settings.SAVE_INTERVAL_WATER,
            "imu": config.settings.SAVE_INTERVAL_IMU
        }
    }


@router.get("/mqtt-status")
async def get_mqtt_status(
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Trả về trạng thái MQTT runtime thực tế (không phải text cứng ở UI)."""
    try:
        from app.main import mqtt_service

        res = await db.execute(
            select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "main_config")
        )
        db_cfg = res.scalar_one_or_none()
        config_source = "database" if db_cfg else "env"

        return {
            "connected": bool(mqtt_service.client.is_connected()),
            "broker": mqtt_service.runtime_mqtt.get("broker", config.settings.MQTT_BROKER),
            "port": int(mqtt_service.runtime_mqtt.get("port", config.settings.MQTT_PORT)),
            "user": mqtt_service.runtime_mqtt.get("user", config.settings.MQTT_USER),
            "topic_reload_interval": int(
                mqtt_service.runtime_mqtt.get("topic_reload_interval", config.settings.TOPIC_RELOAD_INTERVAL)
            ),
            "config_source": config_source,
        }
    except Exception as e:
        logger.error(f"❌ Error getting MQTT status: {e}")
        raise HTTPException(status_code=500, detail="Cannot get MQTT runtime status")

@router.put("/system-config")
async def update_system_config(
    config_in: schemas.SystemConfigPayload,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ API MỚI: Lưu cấu hình hệ thống vào Database
    Chỉ Admin mới gọi được API này (đã được check bởi require_permission)
    """
    try:
        # Chuyển Pydantic model thành Dict
        config_dict = config_in.dict()
        
        # Kiểm tra xem đã có record chưa
        result = await db.execute(
            select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "main_config")
        )
        existing_config = result.scalar_one_or_none()
        
        if existing_config:
            # Update
            existing_config.value = config_dict
            existing_config.updated_at = int(time.time())
            existing_config.updated_by = current_user.username
        else:
            # Create new
            new_config = model_config.GlobalConfig(
                key="main_config",
                value=config_dict,
                updated_at=int(time.time()),
                updated_by=current_user.username
            )
            db.add(new_config)
            
        await db.commit()
        
        # Áp dụng ngay cho service đang chạy để tránh lệch giữa UI và runtime.
        try:
            from app.main import mqtt_service
            mqtt_service.reload_config(config_dict)
        except Exception as reload_err:
            logger.warning(f"⚠️ Saved config but runtime reload failed: {reload_err}")
        
        logger.info(f"✅ System config updated by {current_user.username}")
        return {"status": "success", "message": "Configuration saved successfully"}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error saving system config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE PROVISIONING (Pending Devices)
# ============================================================================


# ============================================================================
# SYSTEM PASSWORD VERIFICATION

# ============================================================================
@router.post("/verify-system-password")
async def verify_system_password(
    payload: schemas.SystemPasswordCheck,
    db: AsyncSession = Depends(get_config_db), # ✅ Cần DB Session
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    # Log yêu cầu gửi vào, chứa địa chỉ nguôn, username và method
    #logger.info(f"Request from {payload.ip_address} - Method: {payload.method} - User: {current_user.username}")
    # 1. Lấy mật khẩu từ DB
    result = await db.execute(
        select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "system_password")
    )
    config_record = result.scalar_one_or_none()
    
    # Mặc định là 2025 nếu lỡ DB bị lỗi
    stored_password = config_record.value if config_record else "password"
    
    # 2. So sánh
    if payload.password == stored_password:
        return {"status": "success", "message": "Access granted"}
    
    # Giả lập delay để chống brute-force
    await asyncio.sleep(0.5)
    raise HTTPException(status_code=403, detail="Mật khẩu hệ thống không đúng")

# ============================================================================
# STATION MANAGEMENT (Sử dụng Config DB)
# ============================================================================

@router.delete("/stations/{station_id}")
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
            
        await db.delete(station)
        await db.commit()
        
        logger.info(f"✅ Deleted station {station_id}: {station.name}")
        return {"status": "success", "message": f"Deleted station {station_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error deleting station: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi khi xóa trạm: {str(e)}")

@router.post("/stations", response_model=schemas.StationResponse)
async def create_station(
    station_in: schemas.StationCreate,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    # 1. Check trùng mã
    exists = await db.execute(select(model_config.Station).where(model_config.Station.station_code == station_in.station_code))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mã trạm đã tồn tại")

    station_data = station_in.dict()
    config_data = station_data.get("config", {}) or {}

    # Logic location
    final_location = None
    if station_data.get("has_gnss"):
        gnss_origin = config_data.get("gnss_origin")
        if gnss_origin and "lat" in gnss_origin:
            final_location = {
                "lat": gnss_origin["lat"],
                "lon": gnss_origin["lon"],
                "h": gnss_origin.get("h", 0),
                "source": "GNSS Origin"
            }
        else:
            final_location = {"lat": 0, "lon": 0, "source": "Pending GNSS"}
    elif station_data.get("sensor_positions"):
        positions = station_data["sensor_positions"]
        lats = [p['lat'] for p in positions.values() if 'lat' in p]
        lons = [p['lon'] for p in positions.values() if 'lon' in p]
        if lats and lons:
            final_location = {
                "lat": sum(lats) / len(lats),
                "lon": sum(lons) / len(lons),
                "source": "Sensor Average"
            }
    if not final_location:
        final_location = {"lat": 0, "lon": 0, "source": "Unknown"}

    station_data["location"] = final_location

    # 4. Tạo và lưu
    new_station = model_config.Station(**station_data)
    
    try:
        db.add(new_station)
        await db.commit()
        await db.refresh(new_station)
        return new_station
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error creating station: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")
    
@router.get("/stations/{station_id}/config")
async def get_station_config(
    station_id: int,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_STATIONS))
):
    result = await db.execute(
        select(model_config.Station).where(model_config.Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Deep-merge: defaults ← station config (station wins)
    import copy
    merged = copy.deepcopy(get_default_station_config())
    raw = station.config or {}
    for key, value in raw.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key].update(value)
        else:
            merged[key] = value
    
    return {
        "station_id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "config": merged
    }

@router.put("/stations/{station_id}/config")
async def update_station_config(
    station_id: int,
    config_data: dict,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        if not config_data:
            raise HTTPException(status_code=400, detail="Config data is empty")
        
        # Update basic info
        if 'station_code' in config_data: station.station_code = config_data['station_code']
        if 'name' in config_data: station.name = config_data['name']
        
        # Update config JSON — ⚠️ PHẢI deepcopy để SQLAlchemy detect thay đổi
        if 'config' in config_data:
            import copy
            from sqlalchemy.orm.attributes import flag_modified
            
            current_config = copy.deepcopy(station.config) if station.config else get_default_station_config()
            new_config = config_data['config']

            # The monitoring reference is immutable. A station edit may update all
            # other settings, but it cannot blank or replace a locked origin.
            locked_origin = copy.deepcopy(current_config.get('gnss_origin'))
            if locked_origin and locked_origin.get('lat') is not None and locked_origin.get('lon') is not None:
                new_config = copy.deepcopy(new_config)
                new_config['gnss_origin'] = locked_origin

            # Backward compatibility for VN2000 config key:
            # normalize legacy `vn2000_params` into canonical `vn2000`.
            if isinstance(new_config, dict) and 'vn2000_params' in new_config and 'vn2000' not in new_config:
                new_config['vn2000'] = new_config.get('vn2000_params') or {}
            
            logger.info(f"📋 [CONFIG] Before merge, offline_thresholds: {current_config.get('offline_thresholds')}")
            logger.info(f"📋 [CONFIG] Incoming config keys: {list(new_config.keys())}")
            
            for key, value in new_config.items():
                if isinstance(value, dict) and key in current_config and isinstance(current_config[key], dict):
                    current_config[key].update(value)
                else:
                    current_config[key] = value
            
            logger.info(f"📋 [CONFIG] After merge, offline_thresholds: {current_config.get('offline_thresholds')}")
            
            station.config = current_config  # Assign NEW dict object
            flag_modified(station, 'config')  # Force SQLAlchemy to detect change
        
        # ✅ SYNC DEVICES từ sensors payload
        if 'sensors' in config_data and isinstance(config_data['sensors'], dict):
            sensors = config_data['sensors']
            logger.info(f"📋 [UPDATE] Station {station_id}: syncing sensors={list(sensors.keys())}")
            
            # 1. Get all existing devices
            existing_res = await db.execute(
                select(model_config.Device).where(model_config.Device.station_id == station_id)
            )
            existing_devices = {d.device_type: d for d in existing_res.scalars().all()}
            logger.info(f"📋 [UPDATE] Existing devices: {list(existing_devices.keys())}")
            
            # 2. Update or create sensors
            active_types = set()
            for s_type, info in sensors.items():
                topic = info.get('topic', '').strip() if isinstance(info, dict) else ''
                if not topic:
                    continue
                
                active_types.add(s_type)
                
                # Build per-device MQTT config from sensor payload
                mqtt_payload = info.get('mqtt') if isinstance(info, dict) else None
                
                if s_type in existing_devices:
                    existing_devices[s_type].mqtt_topic = topic
                    existing_devices[s_type].is_active = True
                    existing_devices[s_type].updated_at = int(time.time())
                    
                    # Save per-device MQTT broker config
                    import copy
                    dev_config = copy.deepcopy(existing_devices[s_type].config) if existing_devices[s_type].config else {}
                    dev_config['mqtt'] = mqtt_payload
                    existing_devices[s_type].config = dev_config
                    flag_modified(existing_devices[s_type], "config")
                    
                    logger.info(f"  ✅ Updated {s_type}: topic={topic}, config.mqtt={mqtt_payload}")
                else:
                    # Check if device_code already exists globally (orphaned or other station)
                    dev_code = f"{station.station_code}_{s_type.upper()}"
                    existing_by_code = await db.execute(
                        select(model_config.Device).where(model_config.Device.device_code == dev_code)
                    )
                    found_dev = existing_by_code.scalar_one_or_none()
                    
                    if found_dev:
                        # Reassign existing device to this station
                        found_dev.station_id = station_id
                        found_dev.device_type = s_type
                        found_dev.mqtt_topic = topic
                        found_dev.is_active = True
                        found_dev.updated_at = int(time.time())
                        
                        dev_config = copy.deepcopy(found_dev.config) if found_dev.config else {}
                        dev_config['mqtt'] = mqtt_payload
                        found_dev.config = dev_config
                        flag_modified(found_dev, "config")
                        
                        logger.info(f"  🔄 Reassigned existing device {dev_code}: topic={topic}, config.mqtt={mqtt_payload}")
                    else:
                        db.add(model_config.Device(
                            device_code=dev_code,
                            name=f"{station.name} - {s_type.upper()}",
                            station_id=station_id,
                            device_type=s_type,
                            mqtt_topic=topic,
                            is_active=True,
                            config={"mqtt": mqtt_payload},
                            created_at=int(time.time()),
                            updated_at=int(time.time())
                        ))
                        logger.info(f"  🆕 Created {s_type}: topic={topic}, config.mqtt={mqtt_payload}")
            
            # 3. Deactivate unchecked sensors
            for d_type, dev in existing_devices.items():
                if d_type not in active_types:
                    dev.is_active = False
                    dev.updated_at = int(time.time())
                    logger.info(f"  ❌ Deactivated {d_type}")
            
            logger.info(f"📋 [UPDATE] Active types: {active_types}")
        
        # ✅ AUTO-COMPUTE station location from average of sensor coordinate origins
        final_config = station.config or {}
        origin_keys = ['gnss_origin', 'rain_origin', 'water_origin', 'imu_origin']
        lats, lons = [], []
        for key in origin_keys:
            origin = final_config.get(key, {})
            try:
                lat_val = float(origin.get('lat', 0))
                lon_val = float(origin.get('lon', 0))
                if lat_val != 0 and lon_val != 0:
                    lats.append(lat_val)
                    lons.append(lon_val)
            except (ValueError, TypeError, AttributeError):
                continue
        
        if lats and lons:
            avg_lat = sum(lats) / len(lats)
            avg_lon = sum(lons) / len(lons)
            station.location = {"lat": round(avg_lat, 8), "lon": round(avg_lon, 8)}
            logger.info(f"📍 [LOCATION] Auto-set station {station_id} location to ({avg_lat:.6f}, {avg_lon:.6f}) from {len(lats)} origins")
        
        station.updated_at = int(time.time())
        await db.commit()
        
        return {"status": "success", "message": f"Updated station {station_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error updating station config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi cập nhật cấu hình: {str(e)}")

@router.post("/stations/{station_id}/reset-config")
async def reset_station_config(
    station_id: int,
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        new_default_config = get_default_station_config()
        station.config = new_default_config
        
        await db.commit()
        return {
            "status": "success",
            "message": "Config reset to default",
            "config": new_default_config
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# GNSS COORDINATE MANAGEMENT (Live Fetcher)
# ============================================================================

class GNSSLiveFetcher:
    def __init__(self, broker: str, port: int, username: str = "", password: str = "", use_tls: bool = False):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.received_data = None
        self.is_connected = False
        
    def _parse_gngga(self, gngga_string: str) -> Optional[dict]:
        try:
            parts = gngga_string.strip().split(',')
            if len(parts) < 10 or not parts[2] or not parts[4]: return None
            
            lat_str, lat_dir = parts[2], parts[3]
            lat = float(lat_str[:2]) + float(lat_str[2:]) / 60.0
            if lat_dir == 'S': lat = -lat
            
            lon_str, lon_dir = parts[4], parts[5]
            lon = float(lon_str[:3]) + float(lon_str[3:]) / 60.0
            if lon_dir == 'W': lon = -lon
            
            # GGA altitude is MSL; convert to ellipsoidal for consistency with GNSS pipeline.
            altitude_msl = float(parts[9]) if parts[9] else 0.0
            geoid_sep = float(parts[11]) if len(parts) > 11 and parts[11] else 0.0
            h = altitude_msl + geoid_sep
            fix_quality = int(parts[6]) if parts[6] else 0
            num_sats = int(parts[7]) if parts[7] else 0
            
            return {'lat': lat, 'lon': lon, 'h': h, 'fix_quality': fix_quality, 'num_sats': num_sats}
        except (ValueError, IndexError):
            return None

    def _extract_gngga(self, payload_bytes: bytes) -> Optional[str]:
        if not payload_bytes:
            return None

        import re
        gga_regex = re.compile(rb'\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?')

        match = gga_regex.search(payload_bytes)
        if not match and b'\x00' in payload_bytes:
            # Some encoders interleave NULL bytes; remove them and retry.
            compact_bytes = payload_bytes.replace(b'\x00', b'')
            match = gga_regex.search(compact_bytes)

        if not match:
            return None

        return match.group(0).decode('ascii', errors='ignore').strip()
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_connected = True
            logger.info(f"[GNSSLiveFetcher] Connected to broker, subscribing to {userdata['topic']}")
            client.subscribe(userdata['topic'])
        else:
            logger.error(f"[GNSSLiveFetcher] Connect failed with code {rc}")
    
    def _on_message(self, client, userdata, msg):
        try:
            payload = self._extract_gngga(msg.payload)
            if not payload:
                # Log full payload representation if it's binary or invalid
                raw_repr = msg.payload[:100].hex() if b'\x00' in msg.payload else msg.payload[:100].decode('utf-8', errors='ignore')
                logger.info(f"[GNSSLiveFetcher] No GGA found in payload on {msg.topic}. Raw start: {raw_repr}")
                return

            logger.info(f"[GNSSLiveFetcher] Received GNSS message on {msg.topic}: {payload}")
            parsed = self._parse_gngga(payload)
            if parsed and parsed['fix_quality'] >= 1:
                logger.info(f"[GNSSLiveFetcher] Valid GNSS parsed: {parsed}")
                self.received_data = parsed
                client.disconnect()
            else:
                logger.warning(f"[GNSSLiveFetcher] Parse failed or invalid fix_quality: {parsed}")
        except Exception as e:
            logger.error(f"[GNSSLiveFetcher] Exception processing message: {e}")
    
    async def fetch_origin(self, topic: str, timeout: int = 30) -> Optional[dict]:
        try:
            self.received_data = None
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata={'topic': topic})
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            if self.username: client.username_pw_set(self.username, self.password)
            
            if self.use_tls:
                import ssl
                client.tls_set_context(ssl.create_default_context())
                
            client.connect(self.broker, self.port, 60)
            client.loop_start()
            
            start_time = asyncio.get_event_loop().time()
            while self.received_data is None:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    logger.warning("[GNSSLiveFetcher] Timeout reached waiting for GNSS data.")
                    client.loop_stop()
                    client.disconnect()
                    return None
                await asyncio.sleep(0.5)
            
            client.loop_stop()
            return self.received_data
        except Exception as e:
            logger.error(f"Error in fetch_origin: {e}")
            return None

@router.post("/gnss/fetch-live-origin")
async def fetch_live_gnss_origin(
    request_data: dict,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        topic = request_data.get('topic')
        if not topic:
            raise HTTPException(status_code=400, detail="MQTT topic is required")
        
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
        
        if not result:
            raise HTTPException(status_code=408, detail="Timeout: Không nhận được dữ liệu GNSS")
        
        return {
            "status": "success",
            "lat": result['lat'],
            "lon": result['lon'],
            "h": result['h'],
            "fix_quality": result['fix_quality'],
            "num_sats": result['num_sats'],
            "message": f"Success! Fix: {result['fix_quality']}, Sats: {result['num_sats']}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching live GNSS: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# SYSTEM CONFIG - QUICK PRESETS
# ============================================================================

@router.post("/system-config/apply-preset")
async def apply_system_preset(
    preset_data: dict,  # {"preset": "conservative" | "balanced" | "sensitive"}
    db: AsyncSession = Depends(get_config_db),
    current_user = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    ✅ Áp dụng preset cho hệ thống
    - Conservative: Ít cảnh báo sai (5/3/5/2 xác nhận, 2h-2 ngày chu kỳ lưu)
    - Balanced: Cân bằng (3/2/3/1 xác nhận, 1h-1 ngày chu kỳ lưu)
    - Sensitive: Nhạy cảm (1 xác nhận, 30 phút-1 giờ chu kỳ lưu)
    """
    try:
        preset_name = preset_data.get("preset")
        
        # ✅ ĐỊNH NGHĨA CÁC PRESET
        presets = {
            "conservative": {
                "confirmation": {
                    "gnss": 5,   # 5 lần mới báo
                    "rain": 3,
                    "water": 5,
                    "imu": 2
                },
                "save_intervals": {
                    "gnss": 172800,   # 2 ngày
                    "rain": 7200,     # 2 giờ
                    "water": 7200,
                    "imu": 5184000    # 60 ngày
                }
            },
            "balanced": {
                "confirmation": {
                    "gnss": 3,
                    "rain": 2,
                    "water": 3,
                    "imu": 1
                },
                "save_intervals": {
                    "gnss": 86400,    # 1 ngày
                    "rain": 3600,     # 1 giờ
                    "water": 3600,
                    "imu": 2592000    # 30 ngày
                }
            },
            "sensitive": {
                "confirmation": {
                    "gnss": 1,   # Báo ngay
                    "rain": 1,
                    "water": 1,
                    "imu": 1
                },
                "save_intervals": {
                    "gnss": 3600,     # 1 giờ
                    "rain": 1800,     # 30 phút
                    "water": 1800,
                    "imu": 604800     # 7 ngày
                }
            }
        }
        
        if preset_name not in presets:
            raise HTTPException(status_code=400, detail="Invalid preset name")
        
        selected_preset = presets[preset_name]
        
        # ✅ LƯU VÀO DATABASE
        from sqlalchemy import select
        
        # Update Confirmation Config
        result = await db.execute(
            select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "confirmation_config")
        )
        confirm_config = result.scalar_one_or_none()
        
        if confirm_config:
            confirm_config.value = selected_preset["confirmation"]
            confirm_config.updated_at = int(time.time())
        else:
            db.add(model_config.GlobalConfig(
                key="confirmation_config",
                value=selected_preset["confirmation"],
                updated_at=int(time.time()),
                updated_by=current_user.username
            ))
        
        # Update Save Intervals Config
        result = await db.execute(
            select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "save_intervals_config")
        )
        intervals_config = result.scalar_one_or_none()
        
        if intervals_config:
            intervals_config.value = selected_preset["save_intervals"]
            intervals_config.updated_at = int(time.time())
        else:
            db.add(model_config.GlobalConfig(
                key="save_intervals_config",
                value=selected_preset["save_intervals"],
                updated_at=int(time.time()),
                updated_by=current_user.username
            ))
        
        await db.commit()
        
        logger.info(f"✅ Preset '{preset_name}' applied by {current_user.username}")
        
        return {
            "status": "success",
            "message": f"✅ Đã áp dụng preset: {preset_name}",
            "config": selected_preset
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error applying preset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# FACTORY RESET - XÓA TOÀN BỘ HỆ THỐNG
# ============================================================================


@router.post("/db/factory-reset")
async def factory_reset_database(
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    🧨 NGUY HIỂM: XÓA TOÀN BỘ HỆ THỐNG (Project, Station, Device, Data...)
    ID sẽ quay về 1. Chỉ giữ lại User admin.
    """
    try:
        if current_user.role != 'admin':
            raise HTTPException(status_code=403, detail="Only admin")

        # 1. Xóa Data DB (Sensor, Alert)
        await data_db.execute(text("TRUNCATE TABLE sensor_data, alerts RESTART IDENTITY CASCADE"))
        await data_db.commit()

        # 2. Xóa Config DB (Project, Station, Device...)
        # Thứ tự quan trọng: Xóa bảng con trước hoặc dùng CASCADE
        # gnss_origins phụ thuộc devices -> devices phụ thuộc stations -> stations phụ thuộc projects
        await config_db.execute(text("TRUNCATE TABLE gnss_origins, devices, stations, projects RESTART IDENTITY CASCADE"))
        # Lưu ý: Không xóa bảng global_configs để giữ mật khẩu hệ thống
        await config_db.commit()

        logger.critical(f"🧨 FACTORY RESET executed by {current_user.username}")

        return {
            "status": "success",
            "message": "Hệ thống đã được reset về trạng thái ban đầu (ID = 1). Hãy tạo Dự án mới."
        }

    except HTTPException:
        raise
    except Exception as e:
        await config_db.rollback()
        await data_db.rollback()

# ============================================================================
# COMMAND API
# ============================================================================
class PlayAudioRequest(BaseModel):
    audio_code: str

@router.post("/stations/{station_id}/command/play")
async def send_audio_command(
    station_id: int,
    payload: PlayAudioRequest,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    """
    Send a 'play audio' command to the station via MQTT.
    """
    try:
        # Import mqtt_service here to avoid circular imports
        from app.main import mqtt_service
        
        # 1. Verify station exists
        res = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        station = res.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
            
        audio_code = payload.audio_code
        if not audio_code:
             raise HTTPException(status_code=400, detail="audio_code required")

        # 2. Publish to MQTT
        topic = f"landslide/{station_id}/command"
        message = json.dumps({
            "cmd": "play_audio",
            "audio_code": audio_code,
            "ts": int(time.time())
        })
        
        mqtt_service.client.publish(topic, message, retain=False)
        logger.info(f"📢 Command sent to {topic}: {message}")
        
        return {"status": "success", "message": f"Command sent: {audio_code}"}

    except Exception as e:
        logger.error(f"❌ Error sending command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SERVER-SIDE PDF EXPORT FOR STATION REPORT
# ============================================================================

@router.get("/export/station/{station_id}/pdf")
async def export_station_pdf(
    station_id: int,
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
):
    """
    Generate a professional PDF report for a station.
    Includes: station info, latest sensor readings, recent alerts, GNSS daily summaries.
    No auth required so guests can also download (station data is public on map).
    """
    try:
        # 1) Get station info
        res = await config_db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = res.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        # 2) Latest sensor cache
        res = await data_db.execute(
            select(model_data.LatestSensorCache)
            .where(model_data.LatestSensorCache.station_id == station_id)
        )
        sensor_cache = res.scalars().all()

        # 3) Recent alerts (last 20)
        res = await data_db.execute(
            select(model_data.Alert)
            .where(model_data.Alert.station_id == station_id)
            .order_by(desc(model_data.Alert.timestamp))
            .limit(20)
        )
        alerts = res.scalars().all()

        # 4) GNSS daily summaries (last 7 days)
        seven_days_ago_ts = int(time.time()) - 7 * 86400
        res = await data_db.execute(
            select(model_data.GnssDailySummary)
            .where(
                model_data.GnssDailySummary.station_id == station_id,
                model_data.GnssDailySummary.day_start_ts >= seven_days_ago_ts
            )
            .order_by(desc(model_data.GnssDailySummary.day_start_ts))
        )
        daily_summaries = res.scalars().all()

        # --- Build PDF with reportlab ---
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=20*mm, bottomMargin=15*mm,
                                leftMargin=15*mm, rightMargin=15*mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('TitleCustom', parent=styles['Title'],
                                     fontSize=18, textColor=colors.HexColor('#0d6efd'))
        subtitle_style = ParagraphStyle('Subtitle', parent=styles['Heading2'],
                                        fontSize=13, textColor=colors.HexColor('#1e293b'),
                                        spaceAfter=6)
        normal_style = styles['Normal']

        elements = []

        # Header
        elements.append(Paragraph(f"Landslide Monitor - Station Report", title_style))
        elements.append(Spacer(1, 4*mm))

        # Station info table
        loc = station.location or {}
        last_up = datetime.fromtimestamp(station.last_update).strftime('%Y-%m-%d %H:%M:%S') if station.last_update else 'N/A'
        info_data = [
            ['Station Name', station.name],
            ['Station Code', station.station_code],
            ['Status', station.status or 'N/A'],
            ['Location', f"Lat: {loc.get('lat', 'N/A')}, Lon: {loc.get('lon', 'N/A')}"],
            ['Last Update', last_up],
            ['Report Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ]
        info_table = Table(info_data, colWidths=[45*mm, 120*mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 8*mm))

        # Latest Sensor Readings
        elements.append(Paragraph("Latest Sensor Readings", subtitle_style))
        if sensor_cache:
            sensor_rows = [['Sensor Type', 'Timestamp', 'Key Values']]
            for sc in sensor_cache:
                ts_str = datetime.fromtimestamp(sc.timestamp).strftime('%H:%M:%S %d/%m') if sc.timestamp else '—'
                data_dict = sc.data if isinstance(sc.data, dict) else {}
                # Extract top 3 key-value pairs
                kv_str = ', '.join([f"{k}: {v}" for k, v in list(data_dict.items())[:4]])
                sensor_rows.append([sc.sensor_type.upper(), ts_str, kv_str[:80]])

            s_table = Table(sensor_rows, colWidths=[30*mm, 35*mm, 100*mm])
            s_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(s_table)
        else:
            elements.append(Paragraph("No sensor data available.", normal_style))
        elements.append(Spacer(1, 6*mm))

        # GNSS Daily Summaries
        if daily_summaries:
            elements.append(Paragraph("GNSS Daily Summary (7 days)", subtitle_style))
            gnss_rows = [['Date', 'Displacement (mm)', 'Velocity (mm/day)', 'Risk', 'Classification']]
            for ds in daily_summaries:
                day_str = datetime.fromtimestamp(ds.day_start_ts).strftime('%d/%m/%Y')
                gnss_rows.append([
                    day_str,
                    f"{ds.net_displacement_mm:.3f}",
                    f"{ds.velocity_mm_day:.4f}",
                    ds.risk_level,
                    ds.classification
                ])
            g_table = Table(gnss_rows, colWidths=[28*mm, 35*mm, 35*mm, 30*mm, 37*mm])
            g_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(g_table)
            elements.append(Spacer(1, 6*mm))

        # Recent Alerts
        if alerts:
            elements.append(Paragraph("Recent Alerts (max 20)", subtitle_style))
            alert_rows = [['Time', 'Level', 'Category', 'Message']]
            for a in alerts[:15]:  # limit rows for PDF space
                a_time = datetime.fromtimestamp(a.timestamp).strftime('%H:%M %d/%m')
                msg = (a.message or '')[:60]
                alert_rows.append([a_time, a.level, a.category, msg])
            a_table = Table(alert_rows, colWidths=[28*mm, 22*mm, 22*mm, 93*mm])
            a_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ef4444')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fef2f2')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(a_table)

        # Build PDF
        doc.build(elements)
        buffer.seek(0)

        import urllib.parse
        safe_name = station.name.replace(' ', '_')
        filename = f"BaoCao_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
        encoded_filename = urllib.parse.quote(filename)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"}
        )

    except HTTPException:
        raise
    except ImportError:
        logger.error("reportlab not installed. Run: pip install reportlab")
        raise HTTPException(status_code=500, detail="Server missing reportlab library. Ask admin to: pip install reportlab")
    except Exception as e:
        logger.error(f"❌ PDF export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stations/{station_code}/ntrip_route/start")
async def start_ntrip_route(
    station_code: str,
    payload: schemas.NtripRouteStart,
    current_admin: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
    db: AsyncSession = Depends(get_config_db)
):
    from ..modules.ntrip_pusher import ntrip_manager
    
    # Check if station exists
    stmt = select(model_config.Station).where(model_config.Station.station_code == station_code)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
        
    if station_code and payload.mountpoint:
        await ntrip_manager.start_pusher(
            station_code, 
            payload.host, 
            payload.port, 
            payload.mountpoint, 
            payload.password
        )
    
    return {"status": "ok", "message": f"NTRIP route started for {station_code}"}

@router.post("/stations/{station_code}/ntrip_route/stop")
async def stop_ntrip_route(
    station_code: str,
    current_admin: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS)),
    db: AsyncSession = Depends(get_config_db)
):
    from ..modules.ntrip_pusher import ntrip_manager
    
    # Check if station exists
    stmt = select(model_config.Station).where(model_config.Station.station_code == station_code)
    result = await db.execute(stmt)
    station = result.scalar_one_or_none()
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
        
    if station_code:
        await ntrip_manager.stop_pusher(station_code)
    
    return {"status": "ok", "message": f"NTRIP route stopped for {station_code}"}
