#backend/app/schemas.py
from pydantic import AfterValidator, BaseModel, Field, StrictBool, field_validator
from typing import Annotated, Optional, Dict, List, Any, Literal
from .config import settings

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
    gnss_classification: List[Dict]

class StationResponse(StationBase):
    id: int
    status: str
    last_update: int

    class Config:
        from_attributes = True

class SensorDataCreate(BaseModel):
    station_id: int
    timestamp: int
    sensor_type: str
    data: Dict
    value_1: Optional[float] = None
    value_2: Optional[float] = None
    value_3: Optional[float] = None
    value_4: Optional[float] = None
    value_5: Optional[float] = None

class SensorDataResponse(SensorDataCreate):
    id: int

    class Config:
        from_attributes = True

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

def _valid_password(value: str) -> str:
    if len(value) < 12 or len(value.encode("utf-8")) > 72:
        raise ValueError("Password must contain at least 12 characters and at most 72 UTF-8 bytes")
    return value


NewPassword = Annotated[str, AfterValidator(_valid_password)]
ProjectIds = Annotated[
    List[Annotated[int, Field(strict=True, gt=0)]],
    Field(max_length=500),
    AfterValidator(lambda values: list(dict.fromkeys(values))),
]
UserRole = Literal["admin", "operator", "viewer"]


class UserCreate(UserBase):
    username: str = Field(min_length=1, max_length=150)
    full_name: Optional[str] = Field(default=None, max_length=255)
    role: UserRole = "viewer"
    password: NewPassword
    assigned_projects: ProjectIds = Field(default_factory=list)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() or not char.isprintable() for char in value):
            raise ValueError("Username cannot contain whitespace or control characters")
        return value

class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    role: Optional[UserRole] = None
    password: Optional[NewPassword] = None
    assigned_projects: Optional[ProjectIds] = None


class UserStatusUpdate(BaseModel):
    is_active: StrictBool


class UserProjectsUpdate(BaseModel):
    assigned_projects: ProjectIds

class UserResponse(UserBase):
    id: int
    is_active: bool
    permissions: List[str] = []
    assigned_projects: List[int] = []
    authz_scope_hash: str = ""
    private_authz_grace_seconds: int = 300
    server_time: int = 0

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

class NtripRouteStart(BaseModel):
    host: str = next(
        (item.strip() for item in settings.NTRIP_HOSTS.split(",") if item.strip()),
        "",
    )
    port: int = settings.NTRIP_PORT
    mountpoint: str
    password: str = settings.NTRIP_PASSWORD
