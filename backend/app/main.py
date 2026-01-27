# ==============================================================================
# == backend/app/main.py   ==
# ==============================================================================

import logging
import asyncio
import time
import sys
import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, delete

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mqtt_bridge import MQTTBridge

# Import các module nội bộ
from . import schemas, auth, config
from .database import (
    auth_engine, config_engine, data_engine,
    get_auth_db, get_config_db, get_data_db,
    AuthSessionLocal, ConfigSessionLocal
)
from .routers import admin as admin_router
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data
from .websocket import manager as ws_manager
from .landslide_analyzer import LandslideAnalyzer

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - API - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('landslide_system.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================
analyzer = LandslideAnalyzer()
mqtt_service = MQTTBridge()

# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Landslide Monitoring System starting...")
    
    try:
        # 1. Khởi tạo AUTH DB
        async with auth_engine.begin() as conn:
            await conn.run_sync(model_auth.BaseAuth.metadata.create_all)
        logger.info("✓ Auth database initialized")

        # 2. Khởi tạo CONFIG DB
        async with config_engine.begin() as conn:
            await conn.run_sync(model_config.BaseConfig.metadata.create_all)
        logger.info("✓ Config database initialized")

        # 3. Khởi tạo DATA DB
        async with data_engine.begin() as conn:
            await conn.run_sync(model_data.BaseData.metadata.create_all)
        logger.info("✓ Data database initialized")
        
        # 4. Tạo Admin mặc định
        async with asyncio.timeout(10):
            async with AuthSessionLocal() as db_auth:
                result = await db_auth.execute(
                    select(model_auth.User).where(model_auth.User.username == "admin")
                )
                admin_user = result.scalar_one_or_none()
                
                if not admin_user:
                    hashed_password = await auth.get_password_hash("Admin@123")
                    new_admin = model_auth.User(
                        username="admin",
                        hashed_password=hashed_password,
                        role="admin",
                        full_name="Administrator",
                        is_active=True
                    )
                    db_auth.add(new_admin)
                    await db_auth.commit()
                    logger.info("✓ Default admin user created (admin/Admin@123)")

        async with asyncio.timeout(10):
            async with ConfigSessionLocal() as db_config:
                # Mật khẩu cứng bạn muốn
                TARGET_PASSWORD = "aitogy@aitogy"

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

        logger.info("=" * 60)
        logger.info("🎉 System ready to serve!")
        logger.info("=" * 60)
        
        yield
        
    finally:
        logger.info("🛑 Shutting down...")
        await auth_engine.dispose()
        await config_engine.dispose()
        await data_engine.dispose()
        mqtt_service.stop()
        logger.info("✅ Shutdown complete")

# ============================================================================
# APP SETUP
# ============================================================================
app = FastAPI(
    title="Landslide Monitoring API",
    lifespan=lifespan,
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router.router)
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
    
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role}
    )
    
    logger.info(f"✅ Login successful: {user.username}")
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    permissions = auth.get_user_permissions(current_user)
    user_response = schemas.UserResponse.from_orm(current_user)
    user_response.permissions = permissions
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
        is_active=True
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
        
        return [
            {
                "id": p.id,
                "project_code": p.project_code,
                "name": p.name,
                "description": p.description,
                "location": p.location,
                "is_active": p.is_active,
                "created_at": p.created_at,
                "station_count": count
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
            "description": new_project.description
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating project: {e}")
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

@app.get("/api/admin/projects/{project_id}/stations")
async def get_stations_by_project(
    project_id: int,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),  # ✅ Thêm db_data
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    result = await db_config.execute(
        select(model_config.Station).where(model_config.Station.project_id == project_id)
    )
    stations = result.scalars().all()
    
    # ✅ Tính status động cho từng trạm
    current_time = int(time.time())
    OFFLINE_THRESHOLD = 60
    
    stations_with_status = []
    for station in stations:
        latest_data_result = await db_data.execute(
            select(model_data.SensorData)
            .where(model_data.SensorData.station_id == station.id)
            .order_by(desc(model_data.SensorData.timestamp))
            .limit(1)
        )
        latest_data = latest_data_result.scalar_one_or_none()
        
        if latest_data and (current_time - latest_data.timestamp) < OFFLINE_THRESHOLD:
            computed_status = "online"
        else:
            computed_status = "offline"
        
        stations_with_status.append({
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status,  # ✅ Status động
            "config": station.config
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

        # TÍNH LẠI TOẠ ĐỘ TỰ ĐỘNG
        station.location = calculate_station_location(update_data.sensors, update_data.location)
        station.name = update_data.name
        station.config = update_data.config
        station.updated_at = int(time.time())

        # Sync Devices
        if update_data.sensors:
            for s_type, info in update_data.sensors.items():
                topic = info.get('topic', '').strip()
                if not topic: continue
                
                dev_res = await db.execute(select(model_config.Device).where(and_(model_config.Device.station_id == station_id, model_config.Device.device_type == s_type)))
                device = dev_res.scalar_one_or_none()
                if device:
                    device.mqtt_topic = topic
                else:
                    db.add(model_config.Device(
                        device_code=f"{station.station_code}_{s_type.upper()}",
                        name=f"{station.name} - {s_type.upper()}",
                        station_id=station_id,
                        device_type=s_type,
                        mqtt_topic=topic,
                        created_at=int(time.time()),
                        updated_at=int(time.time())
                    ))
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
    if station:
        await db.delete(station)
        await db.commit()
        return {"status": "success"}
    raise HTTPException(status_code=404)

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
        
        fetcher = GNSSLiveFetcher(
            broker=config.settings.MQTT_BROKER,
            port=config.settings.MQTT_PORT,
            username=config.settings.MQTT_USER,
            password=config.settings.MQTT_PASSWORD
        )
        result = await fetcher.fetch_origin(topic, timeout=30)
        if not result: raise HTTPException(status_code=408, detail="Timeout")
        
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"GNSS Fetch Error: {e}")
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
                "last_data_time": d.last_data_time
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
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    """
    ✅ Trả về danh sách tất cả các trạm
    ✅ FIXED: Status được tính động dựa trên dữ liệu sensor thực tế
    """
    try:
        # 1. Lấy tất cả stations
        result = await db_config.execute(select(model_config.Station))
        stations = result.scalars().all()
        
        # 2. Tính toán status cho từng trạm
        current_time = int(time.time())
        OFFLINE_THRESHOLD = 60  # 1 phút không có dữ liệu = offline
        
        stations_with_status = []
        
        for station in stations:
            # ✅ FIXED: Check dữ liệu sensor gần nhất
            latest_data_result = await db_data.execute(
                select(model_data.SensorData)
                .where(model_data.SensorData.station_id == station.id)
                .order_by(desc(model_data.SensorData.timestamp))
                .limit(1)
            )
            latest_data = latest_data_result.scalar_one_or_none()
            
            # ✅ Tính status động
            if latest_data and (current_time - latest_data.timestamp) < OFFLINE_THRESHOLD:
                computed_status = "online"
                last_update = latest_data.timestamp
            else:
                computed_status = "offline"
                last_update = station.last_update
            
            # Tính risk level
            risk_assessment = await _calculate_station_risk_simple(db_data, station.id)
            
            stations_with_status.append({
                "id": station.id,
                "station_code": station.station_code,
                "name": station.name,
                "location": station.location,
                "status": computed_status,  
                "last_update": last_update, 
                "risk_level": risk_assessment
            })

        return stations_with_status
        
    except Exception as e:
        logger.error(f"Error loading stations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/stations/{station_id}/detail")
async def get_station_detail(
    station_id: int,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    try:
        # 1. Lấy thông tin trạm từ Config DB
        result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # 2. Lấy devices của trạm
        devices_result = await db_config.execute(
            select(model_config.Device).where(model_config.Device.station_id == station_id)
        )
        devices = devices_result.scalars().all()
        
        # 3. Lấy dữ liệu mới nhất từ Data DB (24h gần nhất)
        cutoff_time = int(time.time()) - 86400  # 24h ago
        
        sensor_data = {}
        has_recent_data = False  # ✅ Flag để check có dữ liệu gần đây không
        latest_data_timestamp = 0  
        
        for device in devices:
            sensor_type = device.device_type
            
            # Lấy 1 điểm mới nhất
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
            latest = latest_result.scalar_one_or_none()
            
            # ✅ Check xem có dữ liệu gần đây không
            if latest and latest.timestamp >= cutoff_time:
                has_recent_data = True
                if latest.timestamp > latest_data_timestamp:
                    latest_data_timestamp = latest.timestamp
            
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
                .limit(100)
            )
            history = history_result.scalars().all()
            
            sensor_data[sensor_type] = {
                "latest": latest.data if latest else None,
                "history": [
                    {
                        "timestamp": h.timestamp,
                        "data": h.data
                    }
                    for h in reversed(history)  # Đảo ngược để cũ → mới
                ]
            }
        
        # ✅ 3.5. Tính toán status động dựa trên dữ liệu
        current_time = int(time.time())
        OFFLINE_THRESHOLD = 300  # 5 phút không có dữ liệu = offline
        
        if has_recent_data and (current_time - latest_data_timestamp) < OFFLINE_THRESHOLD:
            computed_status = "online"
        else:
            computed_status = "offline"
        
        # 4. Tính risk assessment
        risk_assessment = await _calculate_station_risk_assessment(db_data, station_id)
        
        # 5. Trả về response
        return {
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status,  # ✅ FIXED: Dùng status tính toán động
            "last_update": latest_data_timestamp if has_recent_data else station.last_update,  # ✅ Update với timestamp thật
            "config": station.config,
            "sensors": sensor_data,
            "risk_assessment": risk_assessment
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading station detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
async def _calculate_station_risk_assessment(db_data: AsyncSession, station_id: int) -> Dict:
    """Helper: Tính toán risk assessment từ alerts"""
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
        
        critical_count = sum(1 for a in alerts if a.level == "CRITICAL")
        warning_count = sum(1 for a in alerts if a.level == "WARNING")
        
        if critical_count >= 2:
            overall_risk = "EXTREME"
        elif critical_count == 1 or warning_count >= 3:
            overall_risk = "HIGH"
        elif warning_count >= 1:
            overall_risk = "MEDIUM"
        else:
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
                for a in alerts
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
    days: int = 30,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    """
    Phân tích dài hạn cho GNSS displacement
    """
    try:
        # 1. Lấy config trạm
        station_result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # 2. Lấy dữ liệu GNSS trong khoảng thời gian
        cutoff_time = int(time.time()) - (days * 86400)
        
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
        
        if len(gnss_data) < 2:
            return {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu GNSS. Hiện có: {len(gnss_data)}"
            }
        
        # 3. Chuyển đổi sang format cho analyzer
        historical_data = [
            {
                "timestamp": d.timestamp,
                "data": d.data
            }
            for d in gnss_data
        ]
        
        # 4. Gọi analyzer
        analysis_result = analyzer.analyze_long_term_velocity(
            station_id=station_id,
            historical_data=historical_data,
            config=station.config or {},
            window_days=days
        )
        
        return analysis_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in long-term analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS (cho Admin Panel)
# ============================================================================

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
                "value_3": d.value_3
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
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping": 
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": time.time(), "db_status": "3-DB-Active"}

@app.get("/")
async def read_root():
    file_path = os.path.join(os.path.dirname(__file__), "../../frontend/index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "Frontend not found"}

app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
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
        
        if critical >= 2: return "EXTREME"
        elif critical == 1 or warning >= 3: return "HIGH"
        elif warning >= 1: return "MEDIUM"
        return "LOW"
    except:
        return "LOW"