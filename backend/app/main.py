# ==============================================================================
# == backend/app/main.py - Landslide Monitoring System (Complete Version)   ==
# ==============================================================================

import logging
import asyncio
import time
import sys
import os
from contextlib import asynccontextmanager
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mqtt_bridge import MQTTBridge

# Import các module nội bộ
from . import schemas, auth, config
from .database import (
    auth_engine, config_engine, data_engine,
    get_auth_db, get_config_db, get_data_db,
    AuthSessionLocal
)
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
@app.post("/api/admin/projects/{project_id}/stations")
async def create_station_in_project(
    project_id: int,
    station_data: schemas.StationCreate, # Dùng Schema để lấy dữ liệu sensors
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        result = await db.execute(
            select(
                model_config.Station,
                func.count(model_config.Device.id).label('device_count')
            )
            .outerjoin(model_config.Device, model_config.Device.station_id == model_config.Station.id)
            .where(model_config.Station.project_id == project_id)
            .group_by(model_config.Station.id)
            .order_by(model_config.Station.created_at.desc())
        )
        
        stations_with_counts = result.all()
        
        return [
            {
                "id": s.id,
                "station_code": s.station_code,
                "name": s.name,
                "location": s.location,
                "status": s.status,
                "last_update": s.last_update,
                "device_count": count
            }
            for s, count in stations_with_counts
        ]
        
    except Exception as e:
        logger.error(f"Error loading stations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# SỬA TRONG FILE: backend/app/main.py
# ============================================================================

@app.post("/api/admin/projects/{project_id}/stations", response_model=schemas.StationResponse)
async def create_station_in_project(
    project_id: int,
    station_data: schemas.StationCreate, # Dùng Schema để nhận cả object 'sensors'
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.EDIT_STATIONS))
):
    try:
        # 1. Kiểm tra Dự án có tồn tại không
        project_res = await db.execute(select(model_config.Project).where(model_config.Project.id == project_id))
        if not project_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Dự án không tồn tại")

        # 2. Kiểm tra Mã trạm đã tồn tại chưa (Tránh lỗi 500 DB Crash)
        stmt = select(model_config.Station).where(model_config.Station.station_code == station_data.station_code)
        existing = await db.execute(stmt)
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Mã trạm '{station_data.station_code}' đã tồn tại. Vui lòng chọn mã khác.")

        # 3. Tạo Trạm (Station)
        new_station = model_config.Station(
            station_code=station_data.station_code,
            name=station_data.name,
            project_id=project_id,
            location=station_data.location,
            status="offline",
            last_update=0,
            config=station_data.config or {},
            created_at=int(time.time()),
            updated_at=int(time.time())
        )
        db.add(new_station)
        
        # Flush để lấy ID của trạm vừa tạo (dùng cho foreign key của device)
        await db.flush() 

        # 4. TỰ ĐỘNG TẠO THIẾT BỊ (DEVICES) TỪ DỮ LIỆU GIAO DIỆN
        
        if station_data.sensors:
            for sensor_type, info in station_data.sensors.items():
                # Chỉ tạo nếu có thông tin và có topic
                if info and isinstance(info, dict) and info.get('topic'):
                    mqtt_topic = info['topic'].strip()
                    if not mqtt_topic:
                        continue

                    # Tạo mã thiết bị tự động: MÃTRẠM_LOẠI (VD: ST01_GNSS)
                    dev_code = f"{new_station.station_code}_{sensor_type.upper()}"
                    
                    new_device = model_config.Device(
                        device_code=dev_code,
                        name=f"{new_station.name} - {sensor_type.upper()}",
                        station_id=new_station.id,
                        device_type=sensor_type, # gnss, rain, water, imu
                        mqtt_topic=mqtt_topic,
                        is_active=True,
                        last_data_time=0,
                        config={}, # Có thể lưu config riêng từng sensor nếu cần
                        created_at=int(time.time()),
                        updated_at=int(time.time())
                    )
                    db.add(new_device)
                    logger.info(f"➕ Auto-created Device: {dev_code} (Topic: {mqtt_topic})")
        await db.commit()
        await db.refresh(new_station)
        
        return new_station
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating station: {e}", exc_info=True)
        # Trả về lỗi rõ ràng hơn là 500 chung chung
        raise HTTPException(status_code=500, detail=f"Lỗi khi tạo trạm: {str(e)}")

@app.delete("/api/admin/stations/{station_id}")
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_config_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        result = await db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        await db.delete(station)
        await db.commit()
        
        return {"status": "success", "message": f"Deleted station {station_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting station: {e}")
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
# STATION DATA ENDPOINTS (giữ nguyên từ version cũ)
# ============================================================================
@app.get("/api/stations")
async def get_all_stations(
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    try:
        result = await db_config.execute(select(model_config.Station))
        stations = result.scalars().all()
        
        stations_with_risk = []
        for station in stations:
            station_dict = {
                "id": station.id,
                "station_code": station.station_code,
                "name": station.name,
                "location": station.location,
                "status": station.status,
                "last_update": station.last_update
            }
            
            station_dict['risk_level'] = await _calculate_station_risk_simple(db_data, station.id)
            stations_with_risk.append(station_dict)
        
        return stations_with_risk
        
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
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