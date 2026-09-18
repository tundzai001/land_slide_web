"""Latest-value cache and throttled durable sensor persistence."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class SensorPersistenceMixin:
    async def _update_latest_sensor_cache(
        self, station_id: int, sensor_type: str, current_timestamp: int, processed_data: dict
    ) -> None:
        try:
            await self._upsert_latest_sensor_cache(station_id, sensor_type, current_timestamp, processed_data)
        except Exception as e:
            logger.error(f"❌ LatestSensorCache upsert error: {e}")

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
        save_data_now = False

        if is_dangerous:
            # ✅ ALERT → Lưu ngay lập tức / không quan tâm chu kỳ
            save_data_now = True
            logger.warning(f"⚠️ [FORCED SAVE] Alert detected - saving immediately")
        elif is_just_resolved:
            # ✅ VỪA RESOLVE ALERT → Lưu ngay để DB có dữ liệu an toàn mới nhất
            save_data_now = True
            logger.info(f"💾 [RESOLVE SAVE] Alert just resolved - saving safe data for station {station_id}")
        else:
            # ✅ KIỂM TRA CHU KỲ LƯU
            throttle_key_station = f"{station_id}_{sensor_type}"
            last_saved = self.last_save_time[station_id].get(sensor_type, 0)

            interval = self.runtime_save_intervals.get('default', settings.SAVE_INTERVAL_DEFAULT)
            if sensor_type == 'gnss':
                try:
                    interval = int(station_config.get("gnss_save_interval", self.runtime_save_intervals.get('gnss', settings.SAVE_INTERVAL_GNSS)))
                except (ValueError, TypeError):
                    interval = self.runtime_save_intervals.get('gnss', settings.SAVE_INTERVAL_GNSS)
            elif sensor_type == 'imu': interval = self.runtime_save_intervals.get('imu', settings.SAVE_INTERVAL_IMU)
            elif sensor_type == 'rain': interval = self.runtime_save_intervals.get('rain', settings.SAVE_INTERVAL_RAIN)
            elif sensor_type == 'water': interval = self.runtime_save_intervals.get('water', settings.SAVE_INTERVAL_WATER)

            time_since_last_save = current_timestamp - last_saved

            if last_saved == 0:
                # Lần đầu tiên → Lưu luôn
                save_data_now = True
                logger.info(f"💾 [FIRST SAVE] {station_name} - {sensor_type.upper()}")
            elif sensor_type == 'gnss':
                # GNSS: Logic lưu điểm đầu tiên của ngày (bao hàm cả điểm đầu tuần, tháng, năm)
                from datetime import datetime
                last_dt = datetime.fromtimestamp(last_saved)
                curr_dt = datetime.fromtimestamp(current_timestamp)

                if curr_dt.date() > last_dt.date():
                    save_data_now = True
                    logger.info(f"💾 [CALENDAR START DAY SAVE - GNSS] {station_name} ({curr_dt.date()})")
                elif interval < 86400 and time_since_last_save >= interval:
                    # Nếu Admin cố tình set sys-save-gnss nhỏ hơn 1 ngày (vd: 1 tiếng) thì vẫn tuân thủ
                    save_data_now = True
                    logger.info(f"💾 [PERIODIC SAVE - GNSS] {station_name} (Interval: {interval}s)")
            elif time_since_last_save >= interval:
                # Đã đủ chu kỳ → Lưu (Dành cho IMU, Rain, Water)
                save_data_now = True
                logger.info(f"💾 [PERIODIC SAVE] {station_name} - {sensor_type.upper()} (Interval: {interval}s)")
            else:
                # Chưa đủ chu kỳ → Skip
                logger.debug(f"⏭️ [SKIP SAVE] {station_name} - {sensor_type.upper()} ({time_since_last_save}/{interval}s)")

        if save_data_now and sensor_type == 'gnss':
            # Option gnss_save_only_fix trong station_config (mặc định False để tương thích ngược, có thể set True để bật)
            only_save_fix = station_config.get("gnss_save_only_fix", False)
            if only_save_fix and processed_data and processed_data.get('fix_quality', 0) < 4:
                save_data_now = False
                logger.info(f"⏭️ [SKIP SAVE] {station_name} - GNSS (Not fixed, quality={processed_data.get('fix_quality')})")

        try:
            if save_data_now:
                if is_dangerous:
                    sensor_record = {
                        "station_id": station_id,
                        "timestamp": current_timestamp,
                        "sensor_type": sensor_type,
                        "ingest_id": self._make_ingest_id(
                            device_id,
                            station_id,
                            sensor_type,
                            current_timestamp,
                            processed_data,
                            raw_payload,
                        ),
                        "data": processed_data,
                        "value_1": processed_data.get('speed_2d_mm_s', 0.0) if sensor_type == 'gnss' else processed_data.get('intensity_mm_h', 0.0) if sensor_type == 'rain' else processed_data.get('water_level', 0.0) if sensor_type == 'water' else processed_data.get('roll', 0.0),
                        "value_2": processed_data.get('total_displacement_mm', 0.0) if sensor_type == 'gnss' else processed_data.get('accumulated_mm', 0.0) if sensor_type == 'rain' else processed_data.get('intensity_mm_h', 0.0) if sensor_type == 'water' else processed_data.get('pitch', 0.0),
                        "value_3": 0.0 if sensor_type != 'imu' else processed_data.get('yaw', 0.0),
                        "value_4": 0.0 if sensor_type != 'imu' else processed_data.get('total_accel', 0.0),
                        "value_5": 0.0 if sensor_type != 'imu' else processed_data.get('battery', 0.0),
                    }
                    self.last_save_time[station_id][sensor_type] = current_timestamp
                    # ✅ ALERT → Ghi thẳng xuống DB, không qua buffer
                    await self._save_alert_immediate(device_id, station_id, sensor_record, alert, current_timestamp)
                elif is_just_resolved:
                    # ✅ RESOLVE → Buffer rồi flush ngay, tránh mất dữ liệu khi server restart
                    await self._buffer_sensor_record(
                        device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload
                    )
                    await self._flush_write_buffer()
                    logger.info(f"💾 [RESOLVE FLUSH] {station_name} - {sensor_type.upper()} ts={current_timestamp} written immediately")
                else:
                    # ✅ BÌNH THƯỜNG → Đưa vào buffer, flush theo chu kỳ
                    await self._buffer_sensor_record(
                        device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload
                    )

        except Exception as e:
            logger.error(f"❌ DB Error: {e}")
