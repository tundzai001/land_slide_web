# backend/app/models/__init__.py
from .auth import User, BaseAuth
from .config import Project, Station, Device, GNSSOrigin, GlobalConfig, BaseConfig
from .data import SensorData, LatestSensorCache, Alert, GnssDailySummary, GnssWeeklySummary, RescueRequest, BaseData
from .pi_device import PiDevice

# For backward compatibility and Alembic
Base = BaseData
AuthBase = BaseAuth
