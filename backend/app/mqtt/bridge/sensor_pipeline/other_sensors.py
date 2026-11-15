"""Rain, water-level, and IMU payload processing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.shared.sensor_catalog import is_custom_sensor, is_monitoring_type, process_monitoring_payload

logger = logging.getLogger(__name__)


class OtherSensorPayloadMixin:
    def _handle_imu_baseline_lock(self, station_id: int, processor: Any, processed_data: dict | None) -> None:
        if processed_data and processor.origin_locked and not hasattr(processor, '_baseline_saved'):
            processor._baseline_saved = True
            baseline_data = {
                "baseline_roll": processor.baseline["roll"],
                "baseline_pitch": processor.baseline["pitch"],
                "baseline_yaw": processor.baseline["yaw"],
            }
            task = asyncio.create_task(self._save_imu_baseline(station_id, baseline_data))
            if not hasattr(self, '_baseline_save_tasks'):
                self._baseline_save_tasks = set()
            self._baseline_save_tasks.add(task)
            task.add_done_callback(self._baseline_save_tasks.discard)

    async def _process_other_sensor_payload(
        self,
        info: dict,
        raw_payload: str,
        public_project_id: int,
        station_id: int,
        station_name: str,
        processor: Any,
        station_config: dict,
        device_id: int,
        adjustment_only: bool,
        current_timestamp: int,
    ) -> dict | None:
        sensor_type = info["type"]
        processed_data = None
        try:
            if is_monitoring_type(sensor_type) and len(raw_payload.encode('utf-8')) > 256 * 1024:
                logger.warning('Monitoring payload exceeds 256 KiB: station=%s type=%s', station_id, sensor_type)
                return None
            payload_json = json.loads(raw_payload)
            if is_monitoring_type(sensor_type):
                custom_unit = (station_config.get('custom_sensors') or {}).get(sensor_type, {}).get('unit') if is_custom_sensor(sensor_type) else None
                processed_data = process_monitoring_payload(sensor_type, payload_json, custom_unit)
                if processed_data is not None:
                    processed_data['received_at'] = current_timestamp
            elif sensor_type == 'rain': processed_data = processor.process(payload_json, current_timestamp)
            elif sensor_type == 'water': processed_data = processor.process(payload_json, current_timestamp)
            elif sensor_type == 'imu': 
                processed_data = processor.process(payload_json, station_config)
                self._handle_imu_baseline_lock(station_id, processor, processed_data)
        except json.JSONDecodeError:
            return
        except Exception as e:
            logger.error(f"Processing error ({sensor_type}): {e}")
            return None
        await asyncio.sleep(0)
        return processed_data
