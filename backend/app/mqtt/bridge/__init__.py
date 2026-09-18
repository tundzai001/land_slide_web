"""MQTT bridge composed from focused runtime responsibilities."""

from .adjustment import MQTTAdjustmentMixin
from .core import MQTTBridgeCore
from .pipeline import SensorPipelineMixin
from .topics import MQTTTopicMixin
from ..persistence import MQTTPersistenceMixin
from ..transport import MQTTTransportMixin

class MQTTBridge(
    MQTTTransportMixin,
    MQTTPersistenceMixin,
    MQTTTopicMixin,
    MQTTAdjustmentMixin,
    SensorPipelineMixin,
    MQTTBridgeCore,
):
    """Compatibility facade for the MQTT bridge service."""


__all__ = ["MQTTBridge"]
