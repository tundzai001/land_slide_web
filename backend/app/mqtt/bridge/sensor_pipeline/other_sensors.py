"""Rain, water-level, and IMU payload processing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class OtherSensorPayloadMixin:
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
            payload_json = json.loads(raw_payload)
            if sensor_type == 'rain': processed_data = processor.process(payload_json, current_timestamp)
            elif sensor_type == 'water': processed_data = processor.process(payload_json, current_timestamp)
            elif sensor_type == 'imu': 
                processed_data = processor.process(payload_json, station_config)
                # ✅ Auto-save baseline to DB khi vừa khóa lần đầu
                if processed_data and processor.origin_locked and not hasattr(processor, '_baseline_saved'):
                    processor._baseline_saved = True
                    baseline_data = {
                        "baseline_roll": processor.baseline["roll"],
                        "baseline_pitch": processor.baseline["pitch"],
                        "baseline_yaw": processor.baseline["yaw"]
                    }
                    asyncio.ensure_future(self._save_imu_baseline(station_id, baseline_data))
        except json.JSONDecodeError:
            return
        except Exception as e:
            logger.error(f"Processing error ({sensor_type}): {e}")
            return None
        return processed_data
