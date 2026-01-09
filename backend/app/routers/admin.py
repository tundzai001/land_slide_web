# ==============================================================================
# == backend/app/routers/admin.py
# ==============================================================================

import asyncio
import json
import logging
import time
from typing import Optional, Dict, List

import paho.mqtt.client as mqtt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc
from datetime import datetime, timedelta
from .. import schemas, auth, config
from ..database import get_auth_db, get_config_db, get_data_db
from ..models import auth as model_auth
from ..models import config as model_config
from ..models import data as model_data

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Console"]
)

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
        is_active=True
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
    
    await db.execute(delete(model_auth.User).where(model_auth.User.id == user_id))
    await db.commit()
    return {"status": "success"}

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
# SYSTEM PASSWORD VERIFICATION
# ============================================================================
@router.post("/verify-system-password")
async def verify_system_password(
    payload: schemas.SystemPasswordCheck,
    db: AsyncSession = Depends(get_config_db), # ✅ Cần DB Session
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """
    API kiểm tra mật khẩu cấp 2 (Lấy từ Database)
    """
    # Log yêu cầu gửi vào, chứa địa chỉ nguôn, username và method
    logger.info(f"Request from {payload.ip_address} - Method: {payload.method} - User: {current_user.username}")
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
    db: AsyncSession = Depends(get_config_db), # ✅ Dùng Config DB
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
        if 'has_gnss' in config_data: station.has_gnss = config_data['has_gnss']
        if 'has_rain' in config_data: station.has_rain = config_data['has_rain']
        if 'has_water' in config_data: station.has_water = config_data['has_water']
        if 'has_imu' in config_data: station.has_imu = config_data['has_imu']
        
        # Update config JSON (Deep merge simple)
        if 'config' in config_data:
            current_config = station.config or get_default_station_config()
            new_config = config_data['config']
            
            for key, value in new_config.items():
                if isinstance(value, dict) and key in current_config and isinstance(current_config[key], dict):
                    current_config[key].update(value)
                else:
                    current_config[key] = value
            
            station.config = current_config
        
        await db.commit()
        await db.refresh(station)
        return schemas.StationResponse.from_orm(station)
        
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