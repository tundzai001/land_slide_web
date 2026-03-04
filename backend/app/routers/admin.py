# ==============================================================================
# == backend/app/routers/admin.py
# ==============================================================================

import asyncio
import json
import logging
import time
import zipfile 
from typing import Optional, Dict, List, Any

import paho.mqtt.client as mqtt
import pandas as pd
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc, text, func
from datetime import datetime, timedelta
from .. import schemas, auth, config
from ..database import get_auth_db, get_config_db, get_data_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data
import math
import json

# Schema cho request
class ExportExcelRequest(BaseModel):
    tables: List[str]  # Danh sách bảng cần export: ['projects', 'stations', 'devices', 'sensor_data', 'alerts']

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Console"]
)


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
        "ImuAlerting": {
            "tilt_warning_deg": 5.0,
            "tilt_critical_deg": 15.0,
            "imu_confirm_steps": 2,
            "shock_threshold_ms2": 5.0
        },
        # Nhóm cảnh báo GNSS (kỹ thuật)
        "GnssAlerting": {
            "gnss_max_hdop": 4.0,
            "gnss_confirm_steps": 3,
            "gnss_safe_streak": 10,
            "gnss_degraded_timeout": 300
        },
        # Nhóm cảnh báo Mưa
        "RainAlerting": {
            "rain_intensity_watch_threshold": 10.0,
            "rain_intensity_warning_threshold": 25.0,
            "rain_intensity_critical_threshold": 50.0
        },
        # Nhóm cảnh báo Mực nước & Chuyển dịch
        "Water": {
            "warning_threshold": 0.15,
            "critical_threshold": 0.30
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
                        df = pd.DataFrame([{
                            'id': p.id,
                            'code': p.project_code,
                            'name': p.name,
                            'description': p.description,
                            'active': p.is_active
                        } for p in data])
                        
                        # Ghi vào file CSV bên trong ZIP
                        zf.writestr("projects.csv", df.to_csv(index=False))
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
                        df = pd.DataFrame([{
                            'id': s.id,
                            'code': s.station_code,
                            'name': s.name,
                            'status': s.status,
                            'last_update': datetime.fromtimestamp(s.last_update).strftime('%Y-%m-%d %H:%M:%S') if s.last_update else '',
                            'location': str(s.location)
                        } for s in data])
                        
                        zf.writestr("stations.csv", df.to_csv(index=False))
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
                        df = pd.DataFrame([{
                            'id': d.id,
                            'code': d.device_code,
                            'type': d.device_type,
                            'topic': d.mqtt_topic,
                            'station_id': d.station_id
                        } for d in data])
                        
                        zf.writestr("devices.csv", df.to_csv(index=False))
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
                    # Query không dùng .limit()
                    res = await data_db.execute(
                        select(model_data.SensorData)
                        .order_by(desc(model_data.SensorData.timestamp))
                    )
                    data = res.scalars().all()
                    
                    if data:
                        # Chuyển đổi dữ liệu (tối ưu tốc độ)
                        export_list = []
                        for d in data:
                            export_list.append({
                                'id': d.id,
                                'time_str': datetime.fromtimestamp(d.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                'timestamp': d.timestamp,
                                'station_id': d.station_id,
                                'type': d.sensor_type,
                                'val1': d.value_1,
                                'val2': d.value_2,
                                'val3': d.value_3,
                                'raw_json': str(d.data)
                            })
                        
                        df = pd.DataFrame(export_list)
                        zf.writestr("sensor_data.csv", df.to_csv(index=False))
                        has_data = True
                        logger.info(f"✅ CSV: Exported {len(data)} sensor records")
                    else:
                        logger.info("⚠️ CSV: No sensor data found")
                        
                except Exception as e:
                    logger.error(f"❌ CSV Error sensor_data: {e}")

            # ============================================
            # 5. ALERTS 
            # ============================================
            if 'alerts' in request.tables:
                try:
                    res = await data_db.execute(
                        select(model_data.Alert)
                        .order_by(desc(model_data.Alert.timestamp))
                    )
                    data = res.scalars().all()
                    
                    if data:
                        df = pd.DataFrame([{
                            'id': a.id,
                            'time_str': datetime.fromtimestamp(a.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                            'station_id': a.station_id,
                            'level': a.level,
                            'category': a.category,
                            'message': a.message,
                            'resolved': a.is_resolved
                        } for a in data])
                        
                        zf.writestr("alerts.csv", df.to_csv(index=False))
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
        
        # (Tùy chọn) Trigger reload MQTT Service nếu cần thiết
        # mqtt_service.reload_config(config_dict) 
        
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
    stored_password = config_record.value if config_record else "aitogy@aitogy"
    
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
    
    return {
        "station_id": station.id,
        "station_code": station.station_code,
        "name": station.name,
        "config": station.config or get_default_station_config()
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
                
                if s_type in existing_devices:
                    existing_devices[s_type].mqtt_topic = topic
                    existing_devices[s_type].is_active = True
                    existing_devices[s_type].updated_at = int(time.time())
                    logger.info(f"  ✅ Updated {s_type}: topic={topic}")
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
                        logger.info(f"  🔄 Reassigned existing device {dev_code}: topic={topic}")
                    else:
                        db.add(model_config.Device(
                            device_code=dev_code,
                            name=f"{station.name} - {s_type.upper()}",
                            station_id=station_id,
                            device_type=s_type,
                            mqtt_topic=topic,
                            is_active=True,
                            created_at=int(time.time()),
                            updated_at=int(time.time())
                        ))
                        logger.info(f"  🆕 Created {s_type}: topic={topic}")
            
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
    def __init__(self, broker: str, port: int, username: str = "", password: str = ""):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
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
            
            h = float(parts[9]) if parts[9] else 0.0
            fix_quality = int(parts[6]) if parts[6] else 0
            num_sats = int(parts[7]) if parts[7] else 0
            
            return {'lat': lat, 'lon': lon, 'h': h, 'fix_quality': fix_quality, 'num_sats': num_sats}
        except (ValueError, IndexError):
            return None
    
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            client.subscribe(userdata['topic'])
    
    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
            parsed = self._parse_gngga(payload)
            if parsed and parsed['fix_quality'] >= 1:
                self.received_data = parsed
                client.disconnect()
        except Exception:
            pass
    
    async def fetch_origin(self, topic: str, timeout: int = 30) -> Optional[dict]:
        try:
            self.received_data = None
            client = mqtt.Client(userdata={'topic': topic})
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            if self.username: client.username_pw_set(self.username, self.password)
            
            client.connect(self.broker, self.port, 60)
            client.loop_start()
            
            start_time = asyncio.get_event_loop().time()
            while self.received_data is None:
                if asyncio.get_event_loop().time() - start_time > timeout:
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
        
        fetcher = GNSSLiveFetcher(
            broker=config.settings.MQTT_BROKER,
            port=config.settings.MQTT_PORT,
            username=config.settings.MQTT_USER,
            password=config.settings.MQTT_PASSWORD
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
