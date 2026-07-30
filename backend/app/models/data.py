#backend/app/models/data.py
from sqlalchemy import Column, Integer, String, Boolean, JSON, BigInteger, Float, Index
from app.database import BaseData

class SensorData(BaseData):

    __tablename__ = "sensor_data"
    # Composite index tối ưu cho truy vấn lịch sử theo trạm + loại sensor + thời gian
    __table_args__ = (
        Index('ix_sensor_data_station_type_ts', 'station_id', 'sensor_type', 'timestamp'),
        Index('ix_sensor_data_station_ts', 'station_id', 'timestamp'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # BigInteger cho dữ liệu lớn
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, index=True, nullable=False)
    sensor_type = Column(String, index=True, nullable=False)
    
    data = Column(JSON, nullable=False)
    
    value_1 = Column(Float, nullable=True) 
    value_2 = Column(Float, nullable=True)  
    value_3 = Column(Float, nullable=True)  
    value_4 = Column(Float, nullable=True)  
    value_5 = Column(Float, nullable=True)  

class LatestSensorCache(BaseData):
    """Bảng cache giá trị sensor mới nhất — upsert mỗi lần MQTT nhận data,
    không phụ thuộc chu kỳ lưu sensor_data. Dùng để frontend luôn hiện số mới nhất."""
    __tablename__ = "latest_sensor_cache"
    __table_args__ = (
        Index('ix_latest_cache_station_sensor', 'station_id', 'sensor_type', unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(Integer, nullable=False)
    sensor_type = Column(String, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    data = Column(JSON, nullable=False)


class Alert(BaseData):
    __tablename__ = "alerts"
    __table_args__ = (
        Index(
            "ix_alerts_station_unresolved_ts",
            "station_id",
            "is_resolved",
            "timestamp",
        ),
    )
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    level = Column(String, nullable=False)  # CRITICAL, WARNING, INFO
    category = Column(String, nullable=False)  # GNSS, RAIN, WATER, IMU
    message = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)


class GnssDailySummary(BaseData):
    __tablename__ = "gnss_daily_summary"
    __table_args__ = (
        Index('ix_gnss_daily_station_day', 'station_id', 'day_start_ts', unique=True),
        Index('ix_gnss_daily_day', 'day_start_ts'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    station_id = Column(Integer, index=True, nullable=False)
    day_start_ts = Column(BigInteger, nullable=False)  # UTC 00:00:00
    day_end_ts = Column(BigInteger, nullable=False)    # UTC 00:00:00 ngày kế tiếp

    sample_count = Column(Integer, default=0, nullable=False)
    first_ts = Column(BigInteger, nullable=True)
    last_ts = Column(BigInteger, nullable=True)
    duration_seconds = Column(BigInteger, default=0, nullable=False)

    net_displacement_mm = Column(Float, default=0.0, nullable=False)
    velocity_mm_day = Column(Float, default=0.0, nullable=False)
    velocity_mm_second = Column(Float, default=0.0, nullable=False)
    classification = Column(String, default="N/A", nullable=False)
    risk_level = Column(String, default="UNKNOWN", nullable=False)
    is_safe = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="insufficient_data", nullable=False)
    message = Column(String, default="", nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class GnssWeeklySummary(BaseData):
    __tablename__ = "gnss_weekly_summary"
    __table_args__ = (
        Index('ix_gnss_weekly_station_range', 'station_id', 'week_start_ts', 'week_end_ts', unique=True),
        Index('ix_gnss_weekly_end', 'week_end_ts'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    station_id = Column(Integer, index=True, nullable=False)
    week_start_ts = Column(BigInteger, nullable=False)
    week_end_ts = Column(BigInteger, nullable=False)

    day_count = Column(Integer, default=0, nullable=False)
    total_displacement_mm = Column(Float, default=0.0, nullable=False)
    avg_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    max_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    min_velocity_mm_day = Column(Float, default=0.0, nullable=False)
    classification = Column(String, default="N/A", nullable=False)
    risk_level = Column(String, default="UNKNOWN", nullable=False)
    is_safe = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="insufficient_data", nullable=False)
    message = Column(String, default="", nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class RescueRequest(BaseData):
    __tablename__ = "rescue_requests"
    __table_args__ = (
        Index('ix_rescue_requests_status_created', 'status', 'created_at'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(BigInteger, nullable=False, index=True)
    requester_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    message = Column(String, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_m = Column(Float, nullable=True)
    status = Column(String, nullable=False, default='pending')  # pending/resolved/rejected
    admin_note = Column(String, nullable=True)
    handled_by = Column(String, nullable=True)
    handled_at = Column(BigInteger, nullable=True)
