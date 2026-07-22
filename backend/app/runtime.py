"""Process-wide service instances shared by lifecycle code and routers."""
from mqtt_bridge import MQTTBridge

from .landslide_analyzer import LandslideAnalyzer

analyzer = LandslideAnalyzer()
mqtt_service = MQTTBridge()
cors_failover_status: list[dict] = []
