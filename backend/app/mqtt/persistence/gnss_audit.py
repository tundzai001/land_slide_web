"""GNSS anomaly and forwarding-audit persistence."""

from __future__ import annotations

import logging
from typing import Optional
from ..utils import clean_null_bytes

logger = logging.getLogger(__name__)

class GnssAuditPersistenceMixin:
    _GNSS_ANOMALY_STATUSES = {
        "UNSTABLE_FIX",
        "INVALID_DATA",
        "PERSISTENT_OFFSET_QUARANTINED",
        "UNVERIFIED_POSITION_SHIFT",
        "UNTRUSTED_GEOMETRY",
        "REJECTED_MEASUREMENT",
    }

    @staticmethod
    def _is_processing_storage_enabled(station_config: Optional[dict]) -> bool:
        """Return whether internal GNSS processing logs may be persisted."""
        config = station_config if isinstance(station_config, dict) else {}
        data_logging = config.get("data_logging")
        if isinstance(data_logging, dict) and "enabled" in data_logging:
            return data_logging.get("enabled") is not False
        # Existing stations do not have this key yet; keep their behavior.
        return True
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
            "ingest_id": self._make_ingest_id(
                device_id, station_id, "gnss_audit", timestamp, data
            ),
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
        async with self._buffer_lock:
            active = getattr(self, "_active_gnss_anomalies", None)
            if active is None:
                active = self._active_gnss_anomalies = set()
            key = (int(device_id), status)
            if key in active:
                return False
            active.add(key)
            return True
    async def _clear_gnss_anomaly(self, device_id: int) -> None:
        async with self._buffer_lock:
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
        if not self._is_processing_storage_enabled(station_config):
            return False
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
        if not self._is_processing_storage_enabled(station_config):
            return False
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
