#backend/app/models/config.py
from sqlalchemy import Column, Integer, String, Boolean, Float, JSON, BigInteger
from app.database import BaseConfig

class Station(BaseConfig):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True, index=True)
    station_code = Column(String, unique=True, index=True)
    name = Column(String)
    location = Column(JSON)
    
    # Cấu hình thiết bị
    has_gnss = Column(Boolean, default=False)
    topic_gnss = Column(String, nullable=True)
    has_rain = Column(Boolean, default=False)
    topic_rain = Column(String, nullable=True)
    has_water = Column(Boolean, default=False)
    topic_water = Column(String, nullable=True)
    has_imu = Column(Boolean, default=False)
    topic_imu = Column(String, nullable=True)
    
    status = Column(String, default="offline")
    last_update = Column(BigInteger, default=0)
    config = Column(JSON, default={})

class GNSSOrigin(BaseConfig):
    __tablename__ = "gnss_origins"
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, unique=True) # Lưu ý: Không ForeignKey qua DB khác được
    lat = Column(Float)
    lon = Column(Float)
    h = Column(Float)
    locked_at = Column(BigInteger)