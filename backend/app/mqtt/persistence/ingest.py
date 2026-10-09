"""Buffered sensor ingest and crash-recovery persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.shared.sensor_catalog import SENSOR_CATALOG, is_custom_sensor, is_monitoring_type
from app.config import settings
from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import data as model_data
from app.infrastructure.ingest_spool import IngestSpool
from ..utils import clean_null_bytes

logger = logging.getLogger(__name__)

class SensorIngestPersistenceMixin:
    async def _flush_loop(self):
        """Background task: gom write buffer và flush xuống DB mỗi N giây."""
        logger.info("🔄 Started DB Write Buffer Flush Task")
        while True:
            await asyncio.sleep(self._flush_interval)
            await self._flush_write_buffer()
    def _get_ingest_spool(self) -> IngestSpool:
        spool = getattr(self, "_ingest_spool", None)
        if spool is None:
            spool = self._ingest_spool = IngestSpool()
        return spool
    def _ensure_ingest_metrics(self) -> dict[str, Any]:
        metrics = getattr(self, "_ingest_metrics", None)
        if metrics is None:
            metrics = self._ingest_metrics = {
                "inserted": 0,
                "deduped": 0,
                "null_identity": 0,
                "commit_unknown_retries": 0,
                "spool_retries": 0,
                "spool_rejected": 0,
                "drained_batches": 0,
                "last_success_at": 0,
                "last_error": None,
            }
        return metrics
    def _make_ingest_id(
        self,
        device_id: int,
        station_id: int,
        sensor_type: str,
        timestamp: int,
        processed_data: Any,
        source_payload: str | None = None,
    ) -> str:
        """Build a deterministic natural identity for a broker delivery.

        Device sequence is not available for every legacy field unit, so the
        timestamp and normalized payload are the fallback identity.  This is
        only used for retry/redelivery dedupe; rows without a stable identity
        remain at-least-once.
        """
        identity_timestamp = int(timestamp or 0)
        stable_measurement = None
        if is_monitoring_type(sensor_type) and isinstance(processed_data, dict):
            stable_measurement = processed_data.get('measured_at') or (processed_data.get('waveform') or {}).get('start_at')
        normalized = source_payload
        if stable_measurement is not None:
            identity_timestamp = stable_measurement
            normalized = json.dumps({key:value for key,value in processed_data.items() if key != 'received_at'},
                                    ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if not normalized:
            normalized = json.dumps(
                processed_data if processed_data is not None else {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        material = "|".join(
            [
                str(int(device_id or 0)),
                str(int(station_id or 0)),
                str(sensor_type or ""),
                str(identity_timestamp),
                normalized,
            ]
        )
        return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()
    async def _persist_sensor_batch(self, sensor_batch: list[dict]) -> dict[str, int]:
        """Persist one batch with identity-aware PostgreSQL conflict handling."""
        if not sensor_batch:
            return {"inserted": 0, "deduped": 0, "null_identity": 0}
        rows = [
            clean_null_bytes(
                {key: value for key, value in row.items() if not str(key).startswith("_")}
            )
            for row in sensor_batch
        ]
        for row in rows:
            row.setdefault("adjustment_key", None)
            row.setdefault("adjustment_project_id", None)
            row.setdefault("adjustment_cluster_index", None)
        identities = [row.get("ingest_id") for row in rows]
        metrics = {
            "inserted": 0,
            "deduped": 0,
            "null_identity": sum(1 for value in identities if not value),
        }
        async with DataSessionLocal() as db:
            dialect_obj = getattr(getattr(db, "bind", None), "dialect", None)
            dialect = str(getattr(dialect_obj, "name", "") or "")
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                # Bound statement parameters and payload size during bursts.
                inserted = 0
                for offset in range(0, len(rows), 256):
                    chunk = rows[offset:offset + 256]
                    statement = pg_insert(model_data.SensorData.__table__).values(chunk)
                    statement = statement.on_conflict_do_nothing()
                    result = await db.execute(statement)
                    count = getattr(result, 'rowcount', None)
                    inserted += count if isinstance(count, int) and count >= 0 else len(chunk)
            else:
                result = await db.execute(model_data.SensorData.__table__.insert(), rows)
            await db.commit()
            rowcount = getattr(result, "rowcount", None)
            metrics["inserted"] = inserted if dialect == 'postgresql' else (
                int(rowcount) if isinstance(rowcount, int) and rowcount >= 0 else len(rows)
            )
            metrics["deduped"] = max(0, len(rows) - metrics["inserted"])
        return metrics
    async def _spool_failed_sensor_batch(self, sensor_batch: list[dict], reason: str) -> set[str]:
        self._ensure_ingest_metrics()
        spool = self._get_ingest_spool()
        new_records: list[dict] = []
        batch_ids: set[str] = set()
        for record in sensor_batch:
            existing = str(record.get("_spool_id") or "").strip()
            if existing:
                batch_ids.add(existing)
                continue
            new_records.append(record)
        for offset in range(0, len(new_records), 256):
            chunk = new_records[offset:offset + 256]
            batch_id = hashlib.sha256(
                f"{time.time_ns()}:{id(sensor_batch)}:{offset}".encode("ascii")
            ).hexdigest()[:32]
            for record in chunk:
                record["_spool_id"] = batch_id
            payload = [
                {key: value for key, value in record.items() if not str(key).startswith("_")}
                for record in chunk
            ]
            try:
                persisted = await spool.append(batch_id, payload, reason)
            except Exception as exc:
                logger.error('Ingest spool write failed; retaining batch in RAM: %s', type(exc).__name__)
                persisted = False
            if persisted:
                batch_ids.add(batch_id)
                self._ingest_spool_ids = getattr(self, "_ingest_spool_ids", set())
                self._ingest_spool_ids.add(batch_id)
            else:
                for record in chunk:
                    record.pop('_spool_id', None)
                self._ingest_metrics["spool_rejected"] = self._ingest_metrics.get("spool_rejected", 0) + len(chunk)
                logger.critical("Ingest spool unavailable or full; retaining %s rows in RAM", len(chunk))
        return batch_ids
    async def _drain_ingest_spool_loop(self):
        self._ensure_ingest_metrics()
        logger.info("Started durable ingest spool drain task")
        retry_seconds = max(1.0, float(getattr(settings, "INGEST_SPOOL_RETRY_SECONDS", 5.0)))
        while True:
            await asyncio.sleep(retry_seconds)
            envelopes = await self._get_ingest_spool().pending(
                limit=1
            )
            for envelope in envelopes:
                batch_id = str(envelope.get("batch_id") or "")
                records = list(envelope.get("records") or [])
                if not batch_id or not records:
                    await self._get_ingest_spool().acknowledge(batch_id)
                    continue
                try:
                    lock = getattr(self, "_sensor_db_lock", None)
                    if lock is None:
                        lock = self._sensor_db_lock = asyncio.Lock()
                    async with lock:
                        metrics = await self._persist_sensor_batch(records)
                    await self._get_ingest_spool().acknowledge(batch_id)
                    self._ingest_metrics["inserted"] += metrics["inserted"]
                    self._ingest_metrics["deduped"] += metrics["deduped"]
                    self._ingest_metrics["drained_batches"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._ingest_metrics["spool_retries"] += 1
                    self._ingest_metrics["last_error"] = type(exc).__name__
                    logger.warning("Durable ingest spool retry deferred: %s", exc)
                    break
    async def ingest_diagnostics(self) -> dict[str, Any]:
        metrics = dict(getattr(self, "_ingest_metrics", {}) or {})
        try:
            spool = await self._get_ingest_spool().stats()
        except Exception as exc:
            spool = {
                "batches": -1,
                "records": -1,
                "bytes": -1,
                "oldest_age_seconds": -1,
                "error": type(exc).__name__,
            }
        return {
            "buffer_depth": len(getattr(self, "_sensor_buffer", []) or []),
            "station_update_depth": len(getattr(self, "_station_update_buffer", {}) or {}),
            "device_update_depth": len(getattr(self, "_device_update_buffer", {}) or {}),
            "latest_cache_depth": len(getattr(self, "_latest_cache_buffer", {}) or {}),
            "metrics": metrics,
            "spool": spool,
        }
    async def _flush_write_buffer(self):
        """Flush toàn bộ buffer ra DB bằng bulk insert / batch update."""
        self._ensure_ingest_metrics()
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
                lock = getattr(self, "_sensor_db_lock", None)
                if lock is None:
                    lock = self._sensor_db_lock = asyncio.Lock()
                async with lock:
                    metrics = await self._persist_sensor_batch(sensor_batch)
                self._ingest_metrics["inserted"] += metrics["inserted"]
                self._ingest_metrics["deduped"] += metrics["deduped"]
                self._ingest_metrics["null_identity"] += metrics["null_identity"]
                self._ingest_metrics["last_success_at"] = int(time.time())
                await self._get_ingest_spool().acknowledge(
                    *(str(row.get("_spool_id")) for row in sensor_batch if row.get("_spool_id"))
                )
                logger.debug(
                    f"💾 [BULK FLUSH] {len(sensor_batch)} sensor records saved "
                    f"(inserted={metrics['inserted']} deduped={metrics['deduped']})"
                )
            except Exception as e:
                logger.error(f"❌ Bulk sensor flush error: {e}")
                # The batch is removed from RAM before the transaction so the
                # MQTT callback can keep accepting data. Hand failures to disk,
                # retaining RAM only when that durable handoff is unavailable.
                self._ingest_metrics["commit_unknown_retries"] += 1
                durable_ids = await self._spool_failed_sensor_batch(sensor_batch, type(e).__name__)
                async with self._buffer_lock:
                    # The drain loop owns durable batches. Keep only records
                    # that could not reach disk; duplicating spool data in RAM
                    # makes long DB outages exhaust server memory.
                    self._sensor_buffer[0:0] = [row for row in sensor_batch if row.get('_spool_id') not in durable_ids]

        # 2. Batch update Device.last_data_time + Station.last_update / status
        if latest_cache_batch:
            try:
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                async with DataSessionLocal() as db:
                    for offset in range(0, len(latest_cache_batch), 256):
                        stmt = pg_insert(model_data.LatestSensorCache).values(latest_cache_batch[offset:offset + 256])
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["station_id", "sensor_type"],
                            set_={"timestamp": stmt.excluded.timestamp, "data": stmt.excluded.data},
                            where=(model_data.LatestSensorCache.timestamp <= stmt.excluded.timestamp),
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
                async with self._buffer_lock:
                    for sid, values in station_batch.items():
                        previous = self._station_update_buffer.get(sid)
                        if previous is None or int(values.get("last_update", 0)) >= int(previous.get("last_update", 0)):
                            self._station_update_buffer[sid] = values
                    for did, timestamp in device_batch.items():
                        if int(timestamp) >= int(self._device_update_buffer.get(did, 0)):
                            self._device_update_buffer[did] = int(timestamp)
    async def _buffer_sensor_record(
        self,
        device_id: int,
        station_id: int,
        sensor_type: str,
        current_timestamp: int,
        processed_data: dict,
        source_payload: str | None = None,
    ):
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

        if is_monitoring_type(sensor_type):
            values = (list(processed_data['points'].values()) if sensor_type == 'extensometer' else
                      [processed_data.get(field) for field in (['value'] if is_custom_sensor(sensor_type) else SENSOR_CATALOG[sensor_type]['fields'])])
            if processed_data.get('quality') == 'invalid':
                values = []  # Keep evidence in JSON, exclude invalid values from numeric summaries.
            val_1, val_2, val_3, val_4, val_5 = (values + [None] * 5)[:5]

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
                source_payload,
            ),
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
