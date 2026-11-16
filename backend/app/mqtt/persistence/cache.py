"""Latest sensor cache and IMU baseline persistence."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import ConfigSessionLocal
from ..utils import clean_null_bytes

logger = logging.getLogger(__name__)

class SensorCachePersistenceMixin:
    async def _save_imu_baseline(self, station_id: int, baseline_data: dict):
        """Lưu IMU baseline vào station config trong DB."""
        try:
            from app.models.config import Station
            async with ConfigSessionLocal() as db:
                result = await db.execute(
                    select(Station).where(Station.id == station_id)
                )
                station = result.scalar_one_or_none()
                if station:
                    config = station.config or {}
                    config['ImuBaseline'] = baseline_data
                    station.config = config
                    # Force SQLAlchemy to detect the change on mutable JSON
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(station, 'config')
                    await db.commit()
                    logger.info(f"💾 [IMU] Baseline saved to DB for station {station_id}: {baseline_data}")
        except Exception as e:
            logger.exception(f"❌ [IMU] Failed to save baseline for station {station_id}: {e}")
    async def _upsert_latest_sensor_cache(self, station_id: int, sensor_type: str, timestamp: int, data: dict):
        cache_key = (int(station_id), str(sensor_type))
        row = {
            "station_id": int(station_id),
            "sensor_type": str(sensor_type),
            "timestamp": int(timestamp),
            "data": clean_null_bytes(data),
        }
        async with self._buffer_lock:
            pending = self._latest_cache_buffer.get(cache_key)
            if not pending or row["timestamp"] >= int(pending["timestamp"]):
                self._latest_cache_buffer[cache_key] = row
    def _get_sensor_offline_threshold(self, station_config: dict, sensor_type: str) -> int:
        offline_config = (station_config or {}).get('offline_thresholds', {}) or {}
        try:
            default_threshold = self.DEFAULT_OFFLINE_THRESHOLDS.get(sensor_type, 60)
            return max(int(offline_config.get(sensor_type, default_threshold)), 15)
        except (TypeError, ValueError):
            return self.DEFAULT_OFFLINE_THRESHOLDS.get(sensor_type, 60)
    def _should_save_gnss_status(self, station_id: int, current_timestamp: int, station_config: dict) -> bool:
        last_saved = self.last_save_time[station_id].get('gnss', 0)
        if last_saved == 0:
            return True

        offline_threshold = self._get_sensor_offline_threshold(station_config, 'gnss')
        heartbeat_interval = max(5, offline_threshold // 2)
        return (current_timestamp - last_saved) >= heartbeat_interval
