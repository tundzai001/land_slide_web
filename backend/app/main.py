# ==============================================================================
# == backend/app/main.py - Landslide Monitoring System                       ==
# ==============================================================================

import logging
import asyncio
import time
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
from sqlalchemy import select, and_, desc

# Import các module nội bộ
from . import schemas, auth, config
# Import Database Engines & Dependencies
from .database import (
    auth_engine, config_engine, data_engine,
    get_auth_db, get_config_db, get_data_db,
    AuthSessionLocal
)
# Import Models theo cấu trúc 3 DB
from .models import auth as model_auth
from .models import config as model_config
from .models import data as model_data

from .websocket import manager as ws_manager
from .landslide_analyzer import LandslideAnalyzer
from .routers import admin

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

# ============================================================================
# LIFESPAN MANAGEMENT (Khởi tạo & Dọn dẹp)
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Hàm chạy khi ứng dụng khởi động và tắt.
    Khởi tạo bảng cho cả 3 Database riêng biệt.
    """
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
        
        # 4. Tạo Admin mặc định (trong Auth DB)
        async with asyncio.timeout(10):
            async with AuthSessionLocal() as db_auth:
                # Kiểm tra admin tồn tại chưa
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
        
        logger.info("=" * 60)
        logger.info("🎉 System ready to serve!")
        logger.info("=" * 60)
        
        yield  # Ứng dụng chạy tại đây
        
    finally:
        logger.info("🛑 Shutting down...")
        await auth_engine.dispose()
        await config_engine.dispose()
        await data_engine.dispose()
        logger.info("✅ Shutdown complete")


# ============================================================================
# APP SETUP
# ============================================================================
app = FastAPI(
    title="Landslide Monitoring API",
    lifespan=lifespan,
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Admin Router
app.include_router(admin.router)

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@app.post("/api/auth/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_auth_db)  # Dùng Auth DB
):
    """Đăng nhập lấy Token"""
    result = await db.execute(
        select(model_auth.User).where(model_auth.User.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    if not await auth.verify_password(form_data.password, user.hashed_password):
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
    """Lấy thông tin user hiện tại"""
    permissions = auth.get_user_permissions(current_user)
    user_response = schemas.UserResponse.from_orm(current_user)
    user_response.permissions = permissions
    return user_response

# ============================================================================
# STATION MANAGEMENT (Config DB)
# ============================================================================

@app.get("/api/stations", response_model=List[schemas.StationResponse])
async def get_all_stations(
    db_config: AsyncSession = Depends(get_config_db), # Config DB
    db_data: AsyncSession = Depends(get_data_db)      # Data DB (để tính risk)
):
    try:
        # Lấy danh sách trạm từ Config DB
        result = await db_config.execute(select(model_config.Station))
        stations = result.scalars().all()
        
        stations_with_risk = []
        for station in stations:
            station_dict = schemas.StationResponse.from_orm(station).model_dump()
            
            # Tính risk level từ Data DB
            station_dict['risk_level'] = await _calculate_station_risk_simple(db_data, station.id)
            stations_with_risk.append(station_dict)
        
        return stations_with_risk
        
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stations/{station_id}/detail")
async def get_station_detail(
    station_id: int,
    db_config: AsyncSession = Depends(get_config_db), # Cần cả 2 DB
    db_data: AsyncSession = Depends(get_data_db),
):
    try:
        # 1. Lấy thông tin trạm (Config DB)
        result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = result.scalar_one_or_none()
        
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # 2. Lấy dữ liệu cảm biến (Data DB)
        now = int(time.time())
        seven_days_ago = now - (7 * 86400)
        
        # GNSS Data
        gnss_res = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "gnss",
                    model_data.SensorData.timestamp >= seven_days_ago
                )
            ).order_by(model_data.SensorData.timestamp.asc())
        )
        gnss_data = gnss_res.scalars().all()
        
        # Rain Data
        rain_res = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "rain",
                    model_data.SensorData.timestamp >= seven_days_ago
                )
            ).order_by(model_data.SensorData.timestamp.asc())
        )
        rain_data = rain_res.scalars().all()
        
        # Water Data
        water_res = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "water",
                    model_data.SensorData.timestamp >= seven_days_ago
                )
            ).order_by(model_data.SensorData.timestamp.asc())
        )
        water_data = water_res.scalars().all()

        # IMU Data
        imu_res = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "imu",
                    model_data.SensorData.timestamp >= seven_days_ago
                )
            ).order_by(model_data.SensorData.timestamp.desc())
        )
        imu_data = imu_res.scalars().all()

        # 3. Helper format
        def to_list(data_objs):
            return [{"timestamp": d.timestamp, "data": d.data} for d in data_objs]

        # 4. Phân tích nhanh (Analyzer)
        st_config = station.config or {}
        
        gnss_alert = analyzer.analyze_gnss_displacement(station_id, to_list(gnss_data), st_config)
        
        # Tách rain 24h & 72h
        rain_24h = [d for d in rain_data if d.timestamp >= now - 86400]
        rain_72h = [d for d in rain_data if d.timestamp >= now - 259200]
        rain_alert = analyzer.analyze_rainfall(station_id, to_list(rain_24h), to_list(rain_72h), st_config)
        
        water_alert = analyzer.analyze_water_level(station_id, to_list(water_data), st_config)
        imu_alert = analyzer.analyze_tilt(station_id, to_list(imu_data), st_config)
        
        risk_assessment = analyzer.generate_combined_risk_assessment(
            station_id, gnss_alert, rain_alert, water_alert, imu_alert
        )

        # 5. Lấy Alerts (Data DB)
        alerts_res = await db_data.execute(
            select(model_data.Alert)
            .where(
                and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.is_resolved == False
                )
            ).order_by(desc(model_data.Alert.timestamp)).limit(10)
        )
        active_alerts = alerts_res.scalars().all()

        # 6. Build Response
        return {
            "id": station.id,
            "name": station.name,
            "station_code": station.station_code,
            "location": station.location,
            "status": station.status,
            "last_update": station.last_update,
            "config": st_config,
            "has_gnss": station.has_gnss,
            "has_rain": station.has_rain,
            "has_water": station.has_water,
            "has_imu": station.has_imu,
            "sensors": {
                "gnss": { "has_data": bool(gnss_data), "latest": gnss_data[-1].data if gnss_data else None, "history": to_list(gnss_data) },
                "rain": { "has_data": bool(rain_data), "latest": rain_data[-1].data if rain_data else None, "history": to_list(rain_data) },
                "water": { "has_data": bool(water_data), "latest": water_data[-1].data if water_data else None, "history": to_list(water_data) },
                "imu": { "has_data": bool(imu_data), "latest": imu_data[0].data if imu_data else None, "history": to_list(imu_data) }
            },
            "risk_assessment": risk_assessment,
            "active_alerts": [
                {
                    "id": a.id, "timestamp": a.timestamp, "level": a.level,
                    "category": a.category, "message": a.message
                } for a in active_alerts
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detail station: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stations", response_model=schemas.StationResponse)
async def create_station(
    station_data: schemas.StationCreate,
    db: AsyncSession = Depends(get_config_db), # Config DB
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    try:
        # Check trùng code
        existing = await db.execute(select(model_config.Station).where(model_config.Station.station_code == station_data.station_code))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Station code exists")
        
        # Config mặc định (nếu không gửi lên)
        # Lưu ý: Hàm get_default_station_config nên để ở routers/admin hoặc utils
        # Ở đây dùng đơn giản
        default_config = station_data.config or {}
        
        new_station = model_config.Station(
            station_code=station_data.station_code,
            name=station_data.name,
            location=station_data.location,
            has_gnss=station_data.has_gnss,
            has_water=station_data.has_water,
            has_rain=station_data.has_rain,
            has_imu=station_data.has_imu,
            config=default_config,
            status="offline",
            last_update=int(time.time())
        )
        db.add(new_station)
        await db.commit()
        await db.refresh(new_station)
        return schemas.StationResponse.from_orm(new_station)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stations/{station_id}/gnss/lock-origin")
async def lock_gnss_origin(
    station_id: int,
    origin_data: schemas.GNSSOriginCreate,
    db: AsyncSession = Depends(get_config_db), # Config DB
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    try:
        result = await db.execute(select(model_config.Station).where(model_config.Station.id == station_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Station not found")
            
        existing_origin = await db.execute(select(model_config.GNSSOrigin).where(model_config.GNSSOrigin.station_id == station_id))
        origin = existing_origin.scalar_one_or_none()
        
        if origin:
            origin.lat = origin_data.lat
            origin.lon = origin_data.lon
            origin.h = origin_data.h
            origin.locked_at = int(time.time())
            origin.spread_meters = origin_data.spread_meters
        else:
            origin = model_config.GNSSOrigin(
                station_id=station_id,
                lat=origin_data.lat,
                lon=origin_data.lon,
                h=origin_data.h,
                locked_at=int(time.time()),
                spread_meters=origin_data.spread_meters
            )
            db.add(origin)
        
        await db.commit()
        await db.refresh(origin)
        
        # Broadcast
        await ws_manager.broadcast({
            "type": "gnss_origin_locked",
            "station_id": station_id,
            "data": origin_data.dict()
        })
        
        return schemas.GNSSOriginResponse.from_orm(origin)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# SENSOR DATA & ALERTS (Data DB)
# ============================================================================

@app.get("/api/stations/{station_id}/sensors/{sensor_type}/history")
async def get_sensor_history(
    station_id: int,
    sensor_type: str,
    hours: int = 24,
    db: AsyncSession = Depends(get_data_db), # Data DB
):
    start_time = int(time.time()) - (hours * 3600)
    result = await db.execute(
        select(model_data.SensorData)
        .where(
            and_(
                model_data.SensorData.station_id == station_id,
                model_data.SensorData.sensor_type == sensor_type,
                model_data.SensorData.timestamp >= start_time
            )
        ).order_by(model_data.SensorData.timestamp.asc())
    )
    data = result.scalars().all()
    return {
        "station_id": station_id, "sensor_type": sensor_type, "hours": hours,
        "data_count": len(data),
        "data": [{"timestamp": d.timestamp, "data": d.data} for d in data]
    }

@app.get("/api/alerts", response_model=List[schemas.AlertResponse])
async def get_all_alerts(
    resolved: Optional[bool] = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_data_db), # Data DB
):
    query = select(model_data.Alert)
    if resolved is not None:
        query = query.where(model_data.Alert.is_resolved == resolved)
    query = query.order_by(desc(model_data.Alert.timestamp)).limit(limit)
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    return [schemas.AlertResponse.from_orm(a) for a in alerts]

@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_data_db), # Data DB
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    result = await db.execute(select(model_data.Alert).where(model_data.Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_resolved = True
    await db.commit()
    return {"status": "resolved", "alert_id": alert_id}

# ============================================================================
# LONG TERM ANALYSIS (Hybrid)
# ============================================================================

@app.get("/api/stations/{station_id}/long-term-analysis")
async def get_long_term_analysis(
    station_id: int,
    days: int = 30,
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db),
):
    # 1. Get Station Config
    res_st = await db_config.execute(select(model_config.Station).where(model_config.Station.id == station_id))
    station = res_st.scalar_one_or_none()
    if not station or not station.has_gnss:
        return {"status": "error", "message": "Station not found or no GNSS"}
    
    # 2. Get Data
    start_time = int(time.time()) - (days * 86400)
    res_data = await db_data.execute(
        select(model_data.SensorData)
        .where(
            and_(
                model_data.SensorData.station_id == station_id,
                model_data.SensorData.sensor_type == "gnss",
                model_data.SensorData.timestamp >= start_time
            )
        ).order_by(model_data.SensorData.timestamp.asc())
    )
    gnss_data = res_data.scalars().all()
    
    # 3. Analyze
    analysis = analyzer.analyze_long_term_velocity(
        station_id, 
        [{"timestamp": d.timestamp, "data": d.data} for d in gnss_data], 
        station.config or {}
    )
    return {
        "status": "success" if analysis else "insufficient_data",
        "station_name": station.name,
        "analysis": analysis
    }

# ============================================================================
# HELPERS
# ============================================================================

async def _calculate_station_risk_simple(db_data: AsyncSession, station_id: int) -> str:
    """Tính risk level từ Data DB"""
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

# ============================================================================
# WEBSOCKET & STATIC FILES
# ============================================================================

@app.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping": await websocket.send_json({"type": "pong"})
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