"""Realtime sensor-data WebSocket delivery."""

from __future__ import annotations

import logging

from app.websocket import manager

logger = logging.getLogger(__name__)


class SensorBroadcastMixin:
    async def _broadcast_sensor_data(
        self, station_id: int, sensor_type: str, timestamp: int, processed_data: dict
    ) -> None:
        try:
            await manager.broadcast({
                "type": "sensor_data",
                "station_id": station_id,
                "sensor_type": sensor_type,
                "timestamp": timestamp,
                "data": processed_data,
            })
        except Exception as exc:
            logger.error("❌ WS Sensor Error: %s", exc)
