# backend/app/models/config.py 
from sqlalchemy import Column, Integer, String, Boolean, Float, JSON, BigInteger, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import BaseConfig

class Project(BaseConfig):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    project_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(JSON, nullable=True)  # Vùng địa lý chung
    
    # Metadata
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Quan hệ: 1 Project → N Stations
    stations = relationship("Station", back_populates="project", cascade="all, delete-orphan")


class Station(BaseConfig):
    """
    TRẠM GIÁM SÁT: Điểm cụ thể trong dự án
    VD: "Trạm núi Bà Đen", "Trạm thôn Hải Vân"
    """
    __tablename__ = "stations"
    
    id = Column(Integer, primary_key=True, index=True)
    station_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    
    # ✅ ForeignKey tới Project
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    # Vị trí GPS (tự động tính từ thiết bị hoặc nhập thủ công)
    location = Column(JSON, nullable=True)  # {lat, lon, h, source: "auto/manual"}
    
    # Trạng thái
    status = Column(String(20), default="offline")  # online/offline/maintenance
    last_update = Column(BigInteger, default=0)
    
    # Cấu hình chung (ngưỡng cảnh báo, phân loại...)
    config = Column(JSON, default={})
    
    # Metadata
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    
    # Quan hệ
    project = relationship("Project", back_populates="stations")
    devices = relationship("Device", back_populates="station", cascade="all, delete-orphan")


class Device(BaseConfig):
    """
    THIẾT BỊ CẢM BIẾN: Từng thiết bị trong trạm
    VD: "GNSS Receiver 01", "Rain Gauge 02"
    """
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    device_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    
    # ✅ ForeignKey tới Station
    station_id = Column(Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False)
    
    # Loại thiết bị
    device_type = Column(String(20), nullable=False)  # gnss, rain, water, imu
    
    # MQTT Topic riêng cho thiết bị này
    mqtt_topic = Column(String(255), nullable=True)
    
    # Vị trí GPS riêng (nếu có)
    position = Column(JSON, nullable=True)  # {lat, lon, h}
    
    # Trạng thái
    is_active = Column(Boolean, default=True)
    last_data_time = Column(BigInteger, default=0)
    
    # Cấu hình thiết bị riêng (nếu cần override station config)
    config = Column(JSON, default={})
    
    # Metadata
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    
    # Quan hệ
    station = relationship("Station", back_populates="devices")


class GNSSOrigin(BaseConfig):
    """
    ✅ LƯU TỌA ĐỘ GỐC VÀO DB (Persistence)
    """
    __tablename__ = "gnss_origins"
    
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    
    # Tọa độ gốc
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    
    # Metadata khóa
    locked_at = Column(BigInteger, nullable=False)
    spread_meters = Column(Float, nullable=True)  # Độ phân tán khi lock
    num_points = Column(Integer, nullable=True)   # Số điểm dùng để tính
    
    # Ma trận xoay (serialize thành JSON)
    rotation_matrix = Column(JSON, nullable=True)  # 3x3 matrix
    ecef_origin = Column(JSON, nullable=True)      # [X, Y, Z]