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
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, delete, text

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
from .routers import field as field_router
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data
from .models.pi_device import PiDevice  # noqa: F401 – ensures table is registered
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

        # 2. Khởi tạo CONFIG DB (stations, devices, pi_devices, ...)
        async with config_engine.begin() as conn:
            await conn.run_sync(model_config.BaseConfig.metadata.create_all)
        logger.info("✓ Config database initialized (incl. pi_devices)")

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
app.include_router(field_router.router)

# Mount static files directory (for sounds, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
            
            # Nếu có ít nhất 1 sensor online -> station online
            if latest_data and (current_time - latest_data.timestamp) < threshold:
                station_online = True
                break
        
        computed_status = "online" if station_online else "offline"
        
        stations_with_status.append({
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status, 
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
                    logger.info(f"  ✅ Updated device {s_type}: topic={topic}, is_active=True")
                else:
                    # Create new
                    db.add(model_config.Device(
                        device_code=f"{station.station_code}_{s_type.upper()}",
                        name=f"{station.name} - {s_type.upper()}",
                        station_id=station_id,
                        device_type=s_type,
                        mqtt_topic=topic,
                        is_active=True,
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
    ✅ Trả về danh sách tất cả các trạm với offline threshold tùy chỉnh
    """
    try:
        result = await db_config.execute(select(model_config.Station))
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
                
                # Lấy dữ liệu mới nhất của sensor này
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
                
                # Nếu có ít nhất 1 sensor online -> station online
                if latest_data and (current_time - latest_data.timestamp) < threshold:
                    station_online = True
                    break
            
            # ✅ Tính risk_level thực tế từ alerts (không hardcode LOW nữa)
            risk_assessment = await _calculate_station_risk_assessment(db_data, station.id)
            computed_risk = risk_assessment.get("overall_risk", "LOW")
            
            stations_with_status.append({
                "id": station.id,
                "station_code": station.station_code,
                "name": station.name,
                "location": station.location,
                "status": "online" if station_online else "offline",
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
            
            # ✅ Lấy offline threshold riêng cho sensor này
            threshold = get_offline_threshold(station.config, sensor_type)
            current_time = int(time.time())
            
            # Check xem sensor này có online không
            if latest and (current_time - latest.timestamp) < threshold:
                station_online = True  # Chỉ cần 1 sensor online là trạm online
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
                .limit(500)
            )
            history = history_result.scalars().all()
            
            sensor_data[sensor_type] = {
                "latest": latest.data if latest else None,
                "history": [
                    {
                        "timestamp": h.timestamp,
                        "data": h.data
                    }
                    for h in reversed(history)
                ]
            }
        
        # ✅ Tính status dựa trên offline threshold tùy chỉnh
        computed_status = "online" if station_online else "offline"
        
        # 4. Tính risk assessment
        risk_assessment = await _calculate_station_risk_assessment(db_data, station_id)

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
        return {
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "location": station.location,
            "status": computed_status,
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
    Phân tích dài hạn cho GNSS displacement + IMU tilt
    """
    try:
        # 1. Lấy config trạm
        station_result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        cutoff_time = int(time.time()) - (days * 86400)
        
        # 2. Lấy dữ liệu GNSS
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
        
        # 3. Lấy dữ liệu IMU
        imu_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "imu",
                    model_data.SensorData.timestamp >= cutoff_time
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        imu_data = imu_result.scalars().all()
        
        result = {"station_id": station_id, "days": days}
        
        # 4. Phân tích GNSS
        if len(gnss_data) >= 2:
            historical_gnss = [{"timestamp": d.timestamp, "data": d.data} for d in gnss_data]
            gnss_analysis = analyzer.analyze_long_term_velocity(
                station_id=station_id,
                historical_data=historical_gnss,
                config=station.config or {},
                window_days=days
            )
            
            # Tạo time-series GNSS (trung bình theo ngày) cho chart & 3D
            if gnss_analysis.get("status") == "success":
                from collections import OrderedDict
                from datetime import datetime as dt
                daily_gnss = OrderedDict()
                
                # Biến lưu trữ giá trị của ngày đầu tiên để tính delta
                first_e, first_n, first_u = None, None, None

                for point in historical_gnss:
                    day_key = dt.fromtimestamp(point['timestamp']).strftime('%d/%m')
                    data = point['data']
                    
                    disp = data.get('total_displacement_mm', data.get('displacement_mm', 0))
                    # Lấy pos E, N, U (cộng dồn hoặc base)
                    e = data.get('pos_e', 0)
                    n = data.get('pos_n', 0)
                    u = data.get('pos_u', 0)
                    
                    if first_e is None:
                        first_e, first_n, first_u = e, n, u

                    if day_key not in daily_gnss:
                        daily_gnss[day_key] = {'disp': [], 'e': [], 'n': [], 'u': []}
                    
                    daily_gnss[day_key]['disp'].append(float(disp))
                    # Tính delta so với điểm đầu tiên (nếu data lưu raw coordinate)
                    # hoặc nếu data đã tự lưu delta thì bỏ qua trừ
                    
                    # Chúng ta sẽ trả về delta (mm) để 3D dễ vẽ
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
        else:
            result["gnss"] = {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu GNSS. Hiện có: {len(gnss_data)}"
            }
        
        # 5. Phân tích IMU
        if len(imu_data) >= 2:
            historical_imu = [{"timestamp": d.timestamp, "data": d.data} for d in imu_data]
            imu_analysis = analyzer.analyze_long_term_tilt(
                station_id=station_id,
                historical_data=historical_imu,
                window_days=days
            )
            result["imu"] = imu_analysis
        else:
            result["imu"] = {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu IMU. Hiện có: {len(imu_data)}"
            }
        
        # 6. Overall status
        gnss_ok = result["gnss"].get("status") == "success"
        imu_ok = result["imu"].get("status") == "success"
        
        if gnss_ok or imu_ok:
            result["status"] = "success"
        else:
            result["status"] = "insufficient_data"
            result["message"] = "Không đủ dữ liệu GNSS và IMU để phân tích."
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in long-term analysis: {e}", exc_info=True)
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
    if not station_config:
        return 60
    
    offline_config = station_config.get('offline_thresholds', {})
    return offline_config.get(sensor_type, 60)

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