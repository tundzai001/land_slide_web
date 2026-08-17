"""Buffered sensor persistence, alert, and heartbeat behavior for MQTT."""
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
from sqlalchemy import and_, select

from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import data as model_data
from app.websocket import manager
from .utils import clean_null_bytes

logger = logging.getLogger(__name__)


class MQTTPersistenceMixin:
    _GNSS_ANOMALY_STATUSES = {
        "UNSTABLE_FIX",
        "INVALID_DATA",
        "PERSISTENT_OFFSET_QUARANTINED",
        "UNVERIFIED_POSITION_SHIFT",
        "UNTRUSTED_GEOMETRY",
        "REJECTED_MEASUREMENT",
    }

    async def _append_gnss_audit_record(
        self,
        device_id: int,
        station_id: int,
        timestamp: int,
        data: dict,
    ) -> None:
        record = {
            "station_id": station_id,
            "timestamp": timestamp,
            "sensor_type": "gnss_audit",
            "data": clean_null_bytes(data),
            "value_1": None,
            "value_2": None,
            "value_3": None,
            "value_4": None,
            "value_5": None,
        }
        async with self._buffer_lock:
            self._sensor_buffer.append(record)
            self._station_update_buffer[station_id] = {
                "status": "online",
                "last_update": timestamp,
            }
            self._device_update_buffer[device_id] = timestamp

    async def _should_record_gnss_anomaly(self, device_id: int, result: dict) -> bool:
        status = str((result or {}).get("status") or "").upper()
        if status not in self._GNSS_ANOMALY_STATUSES:
            return False
        active = getattr(self, "_active_gnss_anomalies", None)
        if active is None:
            active = self._active_gnss_anomalies = set()
        key = (int(device_id), status)
        if key in active:
            return False
        active.add(key)
        return True

    async def _clear_gnss_anomaly(self, device_id: int) -> None:
        active = getattr(self, "_active_gnss_anomalies", None)
        if active is None:
            return
        target = int(device_id)
        active.difference_update(key for key in tuple(active) if key[0] == target)

    async def _buffer_gnss_audit(
        self,
        device_id: int,
        station_id: int,
        timestamp: int,
        raw_payload: str,
        result: dict,
        station_config: dict,
    ) -> bool:
        if not await self._should_record_gnss_anomaly(device_id, result):
            return False
        audit = dict(result or {})
        audit.update(
            {
                "raw_gngga": raw_payload,
                "forward_action": "blocked_invalid_measurement",
                "forward_payload": None,
            }
        )
        await self._append_gnss_audit_record(device_id, station_id, timestamp, audit)
        return True

    async def _buffer_gnss_forward_audit(
        self,
        device_id: int,
        station_id: int,
        timestamp: int,
        processed_data: dict,
        station_config: dict,
        forward_topic: str,
        forward_broker: str,
        forward_payload: str,
        forward_action: str,
        forward_rc: int,
    ) -> bool:
        if str(forward_action).lower() == "published" and int(forward_rc or 0) == 0:
            return False
        state = getattr(self, "_gnss_forward_error_state", None)
        if state is None:
            state = self._gnss_forward_error_state = {}
        signature = (str(forward_action), int(forward_rc or 0), str(forward_topic))
        if state.get(int(device_id)) == signature:
            return False
        state[int(device_id)] = signature
        audit = dict(processed_data or {})
        audit.update(
            {
                "forward_topic": forward_topic,
                "forward_broker": forward_broker,
                "forward_payload": forward_payload,
                "forward_action": forward_action,
                "forward_rc": forward_rc,
            }
        )
        await self._append_gnss_audit_record(device_id, station_id, timestamp, audit)
        return True

    async def _flush_loop(self):
        """Background task: gom write buffer và flush xuống DB mỗi N giây."""
        logger.info("🔄 Started DB Write Buffer Flush Task")
        while True:
            await asyncio.sleep(self._flush_interval)
            await self._flush_write_buffer()

    async def _flush_write_buffer(self):
        """Flush toàn bộ buffer ra DB bằng bulk insert / batch update."""
        async with self._buffer_lock:
            if (
                not self._sensor_buffer
                and not self._station_update_buffer
                and not self._device_update_buffer
                and not self._latest_cache_buffer
            ):
                return
            sensor_batch = [clean_null_bytes(r) for r in self._sensor_buffer]
            station_batch = dict(self._station_update_buffer)
            device_batch = dict(self._device_update_buffer)
            latest_cache_batch = list(self._latest_cache_buffer.values())
            self._sensor_buffer.clear()
            self._station_update_buffer.clear()
            self._device_update_buffer.clear()
            self._latest_cache_buffer.clear()

        logger.debug(
            f"[FLUSH] Flushing: {len(sensor_batch)} sensor records, "
            f"{len(station_batch)} station updates, {len(device_batch)} device updates"
        )

        # 1. Bulk insert sensor data (1 INSERT nhiều rows thay vì nhiều INSERT)
        if sensor_batch:
            try:
                async with DataSessionLocal() as db:
                    await db.execute(model_data.SensorData.__table__.insert(), sensor_batch)
                    await db.commit()
                logger.debug(f"💾 [BULK FLUSH] {len(sensor_batch)} sensor records saved")
            except Exception as e:
                logger.error(f"❌ Bulk sensor flush error: {e}")

        # 2. Batch update Device.last_data_time + Station.last_update / status
        if latest_cache_batch:
            try:
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                async with DataSessionLocal() as db:
                    stmt = pg_insert(model_data.LatestSensorCache).values(latest_cache_batch)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["station_id", "sensor_type"],
                        set_={
                            "timestamp": stmt.excluded.timestamp,
                            "data": stmt.excluded.data,
                        },
                        where=(
                            model_data.LatestSensorCache.timestamp
                            <= stmt.excluded.timestamp
                        ),
                    )
                    await db.execute(stmt)
                    await db.commit()
            except Exception as exc:
                logger.error("Latest sensor cache bulk UPSERT failed: %s", exc)
                async with self._buffer_lock:
                    for row in latest_cache_batch:
                        key = (int(row["station_id"]), str(row["sensor_type"]))
                        pending = self._latest_cache_buffer.get(key)
                        if not pending or int(row["timestamp"]) > int(pending["timestamp"]):
                            self._latest_cache_buffer[key] = row

        if station_batch or device_batch:
            try:
                from app.models.config import Station, Device
                async with ConfigSessionLocal() as db:
                    for sid, vals in station_batch.items():
                        await db.execute(
                            Station.__table__.update().where(Station.id == sid).values(**vals)
                        )
                    for did, ts in device_batch.items():
                        await db.execute(
                            Device.__table__.update().where(Device.id == did).values(last_data_time=ts)
                        )
                    await db.commit()
                logger.debug(f"✅ [BATCH CONFIG] {len(station_batch)} stations, {len(device_batch)} devices updated")
            except Exception as e:
                logger.error(f"❌ Batch config update error: {e}")

    async def _save_alert_immediate(self, device_id: int, station_id: int, sensor_record: dict, alert: dict, current_timestamp: int):
        """Ghi trực tiếp xuống DB ngay lập tức khi có alert (không qua buffer)."""
        try:
            from app.models.config import Device, Station
            async with ConfigSessionLocal() as db_config:
                await db_config.execute(
                    Device.__table__.update().where(Device.id == device_id).values(last_data_time=current_timestamp)
                )
                await db_config.execute(
                    Station.__table__.update().where(Station.id == station_id).values(last_update=current_timestamp, status="online")
                )
                await db_config.commit()
        except Exception as e:
            logger.error(f"❌ Alert config update error: {e}")

        try:
            async with DataSessionLocal() as db_data:
                db_data.add(model_data.SensorData(**clean_null_bytes(sensor_record)))
                # Tìm alert chưa resolve cùng category, cập nhật hoặc tạo mới.
                # Với IMU, gom cả alert legacy `tilt_warning` vào cùng luồng `tilt_critical`.
                alert_query = and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.category == alert['category'],
                    model_data.Alert.is_resolved == False
                )
                if sensor_record.get('sensor_type') == 'imu' and alert.get('category') == 'tilt_critical':
                    alert_query = and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.category.in_(['tilt_critical', 'tilt_warning']),
                        model_data.Alert.is_resolved == False
                    )

                res = await db_data.execute(select(model_data.Alert).where(alert_query))
                existing_alert = res.scalar_one_or_none()
                if existing_alert:
                    existing_alert.timestamp = current_timestamp
                    existing_alert.level = alert['level']
                    existing_alert.category = alert['category']
                    existing_alert.message = alert['message']
                else:
                    db_data.add(model_data.Alert(
                        station_id=station_id,
                        timestamp=current_timestamp,
                        level=alert['level'],
                        category=alert['category'],
                        message=alert['message'],
                        is_resolved=False
                    ))
                await db_data.commit()
        except Exception as e:
            logger.error(f"❌ Alert data save error: {e}")

    async def _suppress_station_alerts(self, station_id: int):
        """Resolve active alerts and keep station status LOW when alerting is disabled."""
        now = time.monotonic()
        if (
            now - self._alert_suppression_last_attempt[station_id]
            < self._alert_suppression_interval_seconds
        ):
            return
        self._alert_suppression_last_attempt[station_id] = now
        try:
            async with DataSessionLocal() as db_data:
                res = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False
                    ))
                    .values(is_resolved=True)
                )
                if res.rowcount > 0:
                    await db_data.commit()
                    cmd_topic = f"landslide/{station_id}/command"
                    self._get_client_for_station(station_id).publish(cmd_topic, json.dumps({"cmd": "auto_stop_siren", "ts": int(time.time())}), qos=1)
                    logger.info(f"Alerting disabled for station {station_id}; resolved {res.rowcount} active alerts.")

            await manager.broadcast({
                "type": "station_status",
                "station_id": station_id,
                "risk_level": "LOW"
            })
        except Exception as e:
            if self._diag_should_log(f"alert_suppression:{station_id}", 30):
                logger.error(
                    "Error suppressing alerts for station %s: %s: %r",
                    station_id,
                    e.__class__.__name__,
                    e,
                )

    async def _get_station_active_alert_summary(self, station_id: int, station_config: Optional[dict] = None) -> Dict[str, Any]:
        """Return highest active risk level and unresolved alert count for a station."""
        try:
            if not self._is_station_alerting_enabled(station_config):
                return {"risk_level": "LOW", "unresolved_count": 0}

            now_ts = int(time.time())
            gnss_offline = self._get_sensor_offline_threshold(station_config or {}, 'gnss')
            rain_offline = self._get_sensor_offline_threshold(station_config or {}, 'rain')
            water_offline = self._get_sensor_offline_threshold(station_config or {}, 'water')
            imu_offline = self._get_sensor_offline_threshold(station_config or {}, 'imu')

            default_ttl = {
                'gnss_velocity': max(90, gnss_offline * 2),
                'rainfall': max(120, rain_offline * 2),
                'water_level': max(120, water_offline * 2),
                'tilt': max(300, imu_offline),
                'tilt_warning': max(300, imu_offline),
                'tilt_critical': max(300, imu_offline),
                'shock': max(300, imu_offline),
            }

            ttl_cfg = (station_config or {}).get('alert_ttl_seconds', {}) if station_config else {}
            alert_ttl = {
                'gnss_velocity': int(ttl_cfg.get('gnss_velocity', default_ttl['gnss_velocity'])),
                'rainfall': int(ttl_cfg.get('rainfall', default_ttl['rainfall'])),
                'water_level': int(ttl_cfg.get('water_level', default_ttl['water_level'])),
                'tilt': int(ttl_cfg.get('tilt', default_ttl['tilt'])),
                'tilt_warning': int(ttl_cfg.get('tilt_warning', default_ttl['tilt_warning'])),
                'tilt_critical': int(ttl_cfg.get('tilt_critical', default_ttl['tilt_critical'])),
                'shock': int(ttl_cfg.get('shock', default_ttl['shock'])),
            }

            async with DataSessionLocal() as db_data:
                res = await db_data.execute(
                    select(model_data.Alert.level, model_data.Alert.category, model_data.Alert.timestamp)
                    .where(
                        and_(
                            model_data.Alert.station_id == station_id,
                            model_data.Alert.is_resolved == False
                        )
                    )
                )
                rows = res.all()

            fresh_levels = []
            for level, category, ts in rows:
                ttl = alert_ttl.get(category, 180)
                if (now_ts - int(ts or 0)) <= ttl:
                    normalized_level = str(level or '').upper()
                    if category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and normalized_level == 'WARNING':
                        normalized_level = 'CRITICAL'
                    fresh_levels.append(normalized_level)

            priority = {
                "EXTREME": 5,
                "CRITICAL": 4,
                "HIGH": 3,
                "WARNING": 2,
                "MEDIUM": 1,
                "LOW": 0,
            }
            normalized_levels = [str(level).upper() for level in fresh_levels if level is not None]
            highest_level = "LOW"
            highest_score = -1
            for level in normalized_levels:
                score = priority.get(level, 0)
                if score > highest_score:
                    highest_level = level
                    highest_score = score

            if highest_level in priority and highest_level != "LOW":
                return {"risk_level": highest_level, "unresolved_count": len(fresh_levels)}
            return {"risk_level": "LOW", "unresolved_count": len(fresh_levels)}
        except Exception as e:
            logger.error(f"❌ Error reading active alert summary for station {station_id}: {e}")
            return {"risk_level": "LOW", "unresolved_count": 0}

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
            logger.error(f"❌ [IMU] Failed to save baseline for station {station_id}: {e}")

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

    async def _buffer_sensor_record(self, device_id: int, station_id: int, sensor_type: str, current_timestamp: int, processed_data: dict):
        val_1, val_2, val_3, val_4, val_5 = 0.0, 0.0, 0.0, 0.0, 0.0

        if sensor_type == 'gnss':
            val_1 = processed_data.get('speed_2d_mm_s') if 'speed_2d_mm_s' in processed_data else None
            val_2 = processed_data.get('total_displacement_mm') if 'total_displacement_mm' in processed_data else None
        elif sensor_type == 'rain':
            val_1 = processed_data.get('intensity_mm_h', 0.0) or 0.0
            val_2 = processed_data.get('accumulated_mm', 0.0) or 0.0
        elif sensor_type == 'water':
            val_1 = processed_data.get('water_level', 0.0) or 0.0
            val_2 = processed_data.get('intensity_mm_h', 0.0) or 0.0
        elif sensor_type == 'imu':
            val_1 = processed_data.get('roll', 0.0) or 0.0
            val_2 = processed_data.get('pitch', 0.0) or 0.0
            val_3 = processed_data.get('yaw', 0.0) or 0.0
            val_4 = processed_data.get('total_accel', 0.0) or 0.0
            val_5 = processed_data.get('battery', 0.0) or 0.0

        sensor_record = {
            "station_id": station_id,
            "timestamp": current_timestamp,
            "sensor_type": sensor_type,
            "data": processed_data,
            "value_1": val_1,
            "value_2": val_2,
            "value_3": val_3,
            "value_4": val_4,
            "value_5": val_5,
        }
        self.last_save_time[station_id][sensor_type] = current_timestamp

        async with self._buffer_lock:
            self._sensor_buffer.append(sensor_record)
            self._station_update_buffer[station_id] = {
                "status": "online",
                "last_update": current_timestamp
            }
            self._device_update_buffer[device_id] = current_timestamp

    async def _touch_online_heartbeat(self, device_id: int, station_id: int, current_timestamp: int):
        """Mark device/station alive even when payload is not persisted in this cycle."""
        async with self._buffer_lock:
            self._station_update_buffer[station_id] = {
                "status": "online",
                "last_update": current_timestamp
            }
            self._device_update_buffer[device_id] = current_timestamp
            logger.debug(
                f"[HEARTBEAT] Touched station_id={station_id}, device_id={device_id}, ts={current_timestamp}, "
                f"queued_stations={len(self._station_update_buffer)}, queued_devices={len(self._device_update_buffer)}"
            )

    def _get_client_for_station(self, station_id: int) -> mqtt.Client:
        broker_key = self._station_brokers.get(station_id)
        if broker_key and broker_key in self._sub_clients:
            return self._sub_clients[broker_key]
        return self.client # Fallback to default client
