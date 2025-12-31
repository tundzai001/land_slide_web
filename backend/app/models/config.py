from sqlalchemy import Column, Integer, String, Boolean, Float, JSON, BigInteger, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import BaseConfig

class Project(BaseConfig):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    project_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True)
    
    stations = relationship("Station", back_populates="project", cascade="all, delete-orphan")

class Station(BaseConfig):
    __tablename__ = "stations"
    
    id = Column(Integer, primary_key=True, index=True)
    station_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    location = Column(JSON, nullable=True)
    status = Column(String(20), default="offline")
    last_update = Column(BigInteger, default=0)
    config = Column(JSON, default={})
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    
    project = relationship("Project", back_populates="stations")
    devices = relationship("Device", back_populates="station", cascade="all, delete-orphan")

class Device(BaseConfig):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    device_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False)
    device_type = Column(String(20), nullable=False)
    mqtt_topic = Column(String(255), nullable=True)
    position = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    last_data_time = Column(BigInteger, default=0)
    config = Column(JSON, default={})
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    
    station = relationship("Station", back_populates="devices")

class GNSSOrigin(BaseConfig):
    __tablename__ = "gnss_origins"
    
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    locked_at = Column(BigInteger, nullable=False)
    spread_meters = Column(Float, nullable=True)
    num_points = Column(Integer, nullable=True)
    rotation_matrix = Column(JSON, nullable=True)
    ecef_origin = Column(JSON, nullable=True)

# ✅ THÊM CLASS NÀY ĐỂ FIX LỖI
class GlobalConfig(BaseConfig):
    __tablename__ = "global_configs"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, index=True, nullable=False) # VD: "system_password", "main_config"
    value = Column(JSON, nullable=False) # Lưu giá trị (string hoặc JSON object)
    updated_at = Column(BigInteger, nullable=False)
    updated_by = Column(String, nullable=True)