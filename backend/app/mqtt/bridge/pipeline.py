"""Sensor message pipeline composed by responsibility."""

from __future__ import annotations

import time

from app.mqtt.bridge.sensor_pipeline.alerts import SensorAlertMixin
from app.mqtt.bridge.sensor_pipeline.broadcast import SensorBroadcastMixin
from app.mqtt.bridge.sensor_pipeline.forwarding import SensorForwardingMixin
from app.mqtt.bridge.sensor_pipeline.payload import SensorPayloadMixin
from app.mqtt.bridge.sensor_pipeline.persistence import SensorPersistenceMixin


class SensorPipelineMixin(
    SensorPayloadMixin,
    SensorBroadcastMixin,
    SensorForwardingMixin,
    SensorAlertMixin,
    SensorPersistenceMixin,
):
    async def process_pipeline(self, info: dict, raw_payload: str):
        if not info: return

        adjustment_only = bool(info.get("_adjustment_only"))

        public_project_id = int(
            info.get("public_project_id")
            or info.get("project_id")
            or info.get("station_id")
            or 0
        )

        if not adjustment_only and info.get("type") == "gnss":
            station_id = int(info.get("station_id") or 0)
            parallel_run_ids = [
                int(run_id)
                for run_id, context in self.adjustment_run_contexts.items()
                if int(context.get("project_id") or 0) == public_project_id
                and int(run_id) != public_project_id
                and str(self.adjustment_phase.get(int(run_id)) or "").upper()
                    in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
                and any(
                    station_id in [int(value) for value in cluster.get("stations", [])]
                    for cluster in self.active_adjustment_clusters.get(int(run_id), [])
                )
            ]
            for run_id in parallel_run_ids:
                await self.process_pipeline(
                    {
                        **info,
                        "project_id": run_id,
                        "public_project_id": public_project_id,
                        "_adjustment_only": True,
                    },
                    raw_payload,
                )

        active_clusters = self.active_adjustment_clusters.get(info.get("project_id"))

        if active_clusters is not None:
            info = {**info, "project_gnss_clusters": active_clusters}

        device_id = info['device_id']

        station_id = info['station_id']

        station_name = info['station_name']

        sensor_type = info['type']

        processor = info['processor']

        station_config = info['config']

        current_timestamp = int(time.time())

        processed_data = None

        if not adjustment_only:
            await self._touch_online_heartbeat(device_id, station_id, current_timestamp)
        processed_data = await self._process_sensor_payload(
            info=info,
            raw_payload=raw_payload,
            public_project_id=public_project_id,
            station_id=station_id,
            station_name=station_name,
            processor=processor,
            station_config=station_config,
            device_id=device_id,
            adjustment_only=adjustment_only,
            current_timestamp=current_timestamp,
        )
        if not processed_data:
            return

        await self._broadcast_sensor_data(
            station_id, sensor_type, current_timestamp, processed_data, project_id=public_project_id
        )
        self._forward_gnss(info, station_id, sensor_type, processed_data)
        await self._update_latest_sensor_cache(
            station_id, sensor_type, current_timestamp, processed_data
        )
        alert, is_dangerous, is_just_resolved = await self._analyze_and_alert(
            station_id,
            station_name,
            sensor_type,
            station_config,
            processed_data,
            current_timestamp,
            project_id=public_project_id,
        )
        await self._save_processed_data(
            info,
            raw_payload,
            processed_data,
            alert,
            is_dangerous,
            is_just_resolved,
            station_id,
            station_name,
            sensor_type,
            device_id,
            station_config,
            current_timestamp,
        )
