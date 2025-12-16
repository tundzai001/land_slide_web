#backend/app/models/data.py
from sqlalchemy import Column, Integer, String, Boolean, JSON, BigInteger, Float
from app.database import BaseData

class SensorData(BaseData):
    """
    ✅ FIXED: Thêm cột processed để lưu giá trị đã xử lý
    """
    __tablename__ = "sensor_data"
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, index=True, nullable=False)
    sensor_type = Column(String, index=True, nullable=False)
    
    # ✅ Raw data từ MQTT
    data = Column(JSON, nullable=False)
    
    # ✅ OPTIONAL: Cached values cho truy vấn nhanh
    # Tách các giá trị quan trọng thành cột riêng (indexed)
    value_1 = Column(Float, nullable=True)  # VD: water_level, rainfall_mm
    value_2 = Column(Float, nullable=True)  # VD: intensity_mm_h, speed_2d
    value_3 = Column(Float, nullable=True)  # VD: total_displacement_mm

class Alert(BaseData):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    level = Column(String, nullable=False)  # CRITICAL, WARNING, INFO
    category = Column(String, nullable=False)  # GNSS, RAIN, WATER, IMU
    message = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)