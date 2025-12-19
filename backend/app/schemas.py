#backend/app/schemas.py
from pydantic import BaseModel
from typing import Optional, Dict, List, Any

# ✅ Schema trạm giám sát
class StationBase(BaseModel):
    station_code: str
    name: str
    location: Optional[Dict[str, Any]] = None 
    has_gnss: bool = False
    has_water: bool = False
    has_rain: bool = False
    has_imu: bool = False
    sensor_positions: Optional[Dict] = None
    config: Optional[Dict[str, Any]] = None
    sensors: Optional[Dict[str, Any]] = None 

class StationCreate(StationBase):
    pass

class StationConfigUpdate(BaseModel):
    thresholds: Dict[str, float]
    imu: Dict[str, float]
    gnss: Dict[str, float]
    rain: Dict[str, float]
    # gnss_classification có thể phức tạp, tạm thời để list dict
    gnss_classification: List[Dict]
    
class StationResponse(StationBase):
    id: int
    status: str
    last_update: int
    
    class Config:
        from_attributes = True

# ✅ Schema dữ liệu cảm biến
class SensorDataCreate(BaseModel):
    station_id: int
    timestamp: int
    sensor_type: str
    data: Dict

class SensorDataResponse(SensorDataCreate):
    id: int
    
    class Config:
        from_attributes = True

# ✅ Schema cảnh báo
class AlertCreate(BaseModel):
    station_id: int
    timestamp: int
    level: str
    category: str
    message: str

class AlertResponse(AlertCreate):
    id: int
    is_resolved: bool
    
    class Config:
        from_attributes = True

# ✅ Schema tọa độ gốc GNSS
class GNSSOriginResponse(BaseModel):
    station_id: int
    lat: float
    lon: float
    h: float
    locked_at: int
    spread_meters: float
    
    class Config:
        from_attributes = True

class UserBase(BaseModel):
    username: str
    full_name: Optional[str] = None
    role: str = "user"

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    is_active: bool
    permissions: List[str] = []
    
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class GNSSOriginCreate(BaseModel):
    lat: float
    lon: float
    h: float
    spread_meters: float

class GNSSOriginResponse(BaseModel):
    station_id: int
    lat: float
    lon: float
    h: float
    locked_at: int
    spread_meters: float
    
    class Config:
        from_attributes = True