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

class Alert(BaseData):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, index=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    level = Column(String, nullable=False)  # CRITICAL, WARNING, INFO
    category = Column(String, nullable=False)  # GNSS, RAIN, WATER, IMU
    message = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)