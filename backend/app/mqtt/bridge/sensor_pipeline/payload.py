"""Sensor payload dispatcher."""

from __future__ import annotations

from app.mqtt.bridge.sensor_pipeline.gnss import GnssPayloadMixin
from app.mqtt.bridge.sensor_pipeline.other_sensors import OtherSensorPayloadMixin


class SensorPayloadMixin(GnssPayloadMixin, OtherSensorPayloadMixin):
    async def _process_sensor_payload(self, info: dict, **context):
        if info["type"] == "gnss":
            return await self._process_gnss_payload(info, **context)
        return await self._process_other_sensor_payload(info, **context)
