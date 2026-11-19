"""Latest-value cache and throttled durable sensor persistence."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _extract_metric_values(sensor_type: str, processed_data: dict) -> tuple[float, float]:
    if sensor_type == 'gnss':
        return (
            processed_data.get('speed_2d_mm_s', 0.0),
            processed_data.get('total_displacement_mm', 0.0),
        )
    if sensor_type == 'rain':
        return (
            processed_data.get('intensity_mm_h', 0.0),
            processed_data.get('accumulated_mm', 0.0),
        )
    if sensor_type == 'water':
        return (
            processed_data.get('water_level', 0.0),
            processed_data.get('intensity_mm_h', 0.0),
        )
    return (
        processed_data.get('roll', 0.0),
        processed_data.get('pitch', 0.0),
    )


class SensorPersistenceMixin:
    async def _update_latest_sensor_cache(
        self, station_id: int, sensor_type: str, current_timestamp: int, processed_data: dict
    ) -> None:
        try:
            await self._upsert_latest_sensor_cache(station_id, sensor_type, current_timestamp, processed_data)
        except Exception as e:
            logger.exception(f"❌ LatestSensorCache upsert error: {e}")

    def _resolve_save_interval(self, sensor_type: str, station_config: dict) -> int:
        if sensor_type == "gnss":
            try:
                return int(station_config.get("gnss_save_interval", self.runtime_save_intervals.get("gnss", settings.SAVE_INTERVAL_GNSS)))
            except (ValueError, TypeError):
                return self.runtime_save_intervals.get("gnss", settings.SAVE_INTERVAL_GNSS)
        return self.runtime_save_intervals.get(sensor_type, settings.SAVE_INTERVAL_DEFAULT)

    def _should_save_gnss(self, last_saved: int, current_timestamp: int, interval: int, station_name: str) -> bool:
        from datetime import datetime
        last_dt = datetime.fromtimestamp(last_saved)
        curr_dt = datetime.fromtimestamp(current_timestamp)
        if curr_dt.date() > last_dt.date():
            logger.info(f"💾 [CALENDAR START DAY SAVE - GNSS] {station_name} ({curr_dt.date()})")
            return True
        if interval < 86400 and (current_timestamp - last_saved) >= interval:
            logger.info(f"💾 [PERIODIC SAVE - GNSS] {station_name} (Interval: {interval}s)")
            return True
        return False

    def _should_save_now(self, last_saved: int, current_timestamp: int, sensor_type: str, interval: int, station_name: str) -> bool:
        if last_saved == 0:
            logger.info(f"💾 [FIRST SAVE] {station_name} - {sensor_type.upper()}")
            return True
        if sensor_type == "gnss":
            return self._should_save_gnss(last_saved, current_timestamp, interval, station_name)
        time_since = current_timestamp - last_saved
        if time_since >= interval:
            logger.info(f"💾 [PERIODIC SAVE] {station_name} - {sensor_type.upper()} (Interval: {interval}s)")
            return True
        logger.debug(f"⏭️ [SKIP SAVE] {station_name} - {sensor_type.upper()} ({time_since}/{interval}s)")
        return False

    def _determine_save_needed(self, is_waveform: bool, is_dangerous: bool, is_just_resolved: bool, station_id: int, station_name: str, sensor_type: str, station_config: dict, current_timestamp: int, processed_data: dict) -> bool:
        if is_waveform or is_dangerous or is_just_resolved:
            return True
        last_saved = self.last_save_time[station_id].get(sensor_type, 0)
        interval = self._resolve_save_interval(sensor_type, station_config)
        save_now = self._should_save_now(last_saved, current_timestamp, sensor_type, interval, station_name)
        if save_now and sensor_type == "gnss":
            only_fix = station_config.get("gnss_save_only_fix", False)
            if only_fix and processed_data and processed_data.get("fix_quality", 0) < 4:
                logger.info(f"⏭️ [SKIP SAVE] {station_name} - GNSS (Not fixed, quality={processed_data.get('fix_quality')})")
                return False
        return save_now

    async def _persist_urgent_or_normal(self, is_dangerous: bool, is_just_resolved: bool, device_id: int, station_id: int, station_name: str, sensor_type: str, current_timestamp: int, processed_data: dict, raw_payload: str, alert: dict | None):
        if is_dangerous:
            val_1, val_2 = _extract_metric_values(sensor_type, processed_data)
            sensor_record = {
                "station_id": station_id, "timestamp": current_timestamp, "sensor_type": sensor_type,
                "ingest_id": self._make_ingest_id(device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload),
                "data": processed_data, "value_1": val_1, "value_2": val_2,
                "value_3": 0.0 if sensor_type != "imu" else processed_data.get("yaw", 0.0),
                "value_4": 0.0 if sensor_type != "imu" else processed_data.get("total_accel", 0.0),
                "value_5": 0.0 if sensor_type != "imu" else processed_data.get("battery", 0.0),
            }
            self.last_save_time[station_id][sensor_type] = current_timestamp
            await self._save_alert_immediate(device_id, station_id, sensor_record, alert, current_timestamp)
        elif is_just_resolved:
            await self._buffer_sensor_record(device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload)
            await self._flush_write_buffer()
            logger.info(f"💾 [RESOLVE FLUSH] {station_name} - {sensor_type.upper()} ts={current_timestamp} written immediately")
        else:
            await self._buffer_sensor_record(device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload)

    async def _save_processed_data(
        self,
        info: dict,
        raw_payload: str,
        processed_data: dict,
        alert: dict | None,
        is_dangerous: bool,
        is_just_resolved: bool,
        station_id: int,
        station_name: str,
        sensor_type: str,
        device_id: int,
        station_config: dict,
        current_timestamp: int,
    ) -> None:
        _ = info
        is_waveform = sensor_type == "accelerometer" and bool(processed_data.get("waveform"))
        save_data_now = self._determine_save_needed(
            is_waveform, is_dangerous, is_just_resolved, station_id, station_name,
            sensor_type, station_config, current_timestamp, processed_data
        )
        if not save_data_now:
            return
        try:
            await self._persist_urgent_or_normal(
                is_dangerous, is_just_resolved, device_id, station_id, station_name,
                sensor_type, current_timestamp, processed_data, raw_payload, alert
            )
        except Exception as e:
            logger.exception(f"❌ DB Error: {e}")
