"""MQTT persistence components grouped by storage responsibility."""

from .alerts import AlertPersistenceMixin
from .cache import SensorCachePersistenceMixin
from .gnss_audit import GnssAuditPersistenceMixin
from .ingest import SensorIngestPersistenceMixin


class MQTTPersistenceMixin(
    GnssAuditPersistenceMixin,
    SensorIngestPersistenceMixin,
    AlertPersistenceMixin,
    SensorCachePersistenceMixin,
):
    """Compatibility facade composed from focused MQTT persistence mixins."""


__all__ = ["MQTTPersistenceMixin"]
