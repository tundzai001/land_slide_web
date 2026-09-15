"""Buffered sensor persistence, alert, and heartbeat behavior for MQTT."""
import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
from sqlalchemy import and_, select

from app.database import ConfigSessionLocal, DataSessionLocal
from app.config import settings
from app.models import data as model_data
from app.services.incident_cases import append_event, ensure_incident_case, serialize_case
from app.services.ingest_spool import IngestSpool
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
        normalized = source_payload
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
                str(int(timestamp or 0)),
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
            if dialect == "postgresql" and any(value for value in identities):
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                statement = pg_insert(model_data.SensorData.__table__).values(rows)
                statement = statement.on_conflict_do_nothing(
                    index_elements=["ingest_id"],
                    index_where=model_data.SensorData.__table__.c.ingest_id.is_not(None),
                )
                result = await db.execute(statement)
            else:
                result = await db.execute(model_data.SensorData.__table__.insert(), rows)
            await db.commit()
            rowcount = getattr(result, "rowcount", None)
            metrics["inserted"] = (
                int(rowcount)
                if isinstance(rowcount, int) and rowcount >= 0
                else len(rows)
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
        if new_records:
            batch_id = hashlib.sha256(
                f"{time.time_ns()}:{id(sensor_batch)}".encode("ascii")
            ).hexdigest()[:32]
            for record in new_records:
                record["_spool_id"] = batch_id
            payload = [
                {key: value for key, value in record.items() if not str(key).startswith("_")}
                for record in new_records
            ]
            persisted = await spool.append(batch_id, payload, reason)
            if persisted:
                batch_ids.add(batch_id)
                self._ingest_spool_ids = getattr(self, "_ingest_spool_ids", set())
                self._ingest_spool_ids.add(batch_id)
            else:
                self._ingest_metrics["spool_rejected"] = self._ingest_metrics.get("spool_rejected", 0) + len(new_records)
                logger.critical("Ingest spool hard limit reached; retaining %s rows in RAM", len(new_records))
        return batch_ids

    async def _drain_ingest_spool_loop(self):
        self._ensure_ingest_metrics()
        logger.info("Started durable ingest spool drain task")
        retry_seconds = max(1.0, float(getattr(settings, "INGEST_SPOOL_RETRY_SECONDS", 5.0)))
        while True:
            await asyncio.sleep(retry_seconds)
            envelopes = await self._get_ingest_spool().pending(
                limit=max(1, int(getattr(settings, "INGEST_SPOOL_BATCH_SIZE", 256)))
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
                # MQTT callback can keep accepting data.  Put it back when the
                # write fails; otherwise a short DB outage silently loses the
                # measurements that arrived during that window.
                self._ingest_metrics["commit_unknown_retries"] += 1
                await self._spool_failed_sensor_batch(sensor_batch, type(e).__name__)
                async with self._buffer_lock:
                    self._sensor_buffer[0:0] = sensor_batch

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
                async with self._buffer_lock:
                    for sid, values in station_batch.items():
                        previous = self._station_update_buffer.get(sid)
                        if previous is None or int(values.get("last_update", 0)) >= int(previous.get("last_update", 0)):
                            self._station_update_buffer[sid] = values
                    for did, timestamp in device_batch.items():
                        if int(timestamp) >= int(self._device_update_buffer.get(did, 0)):
                            self._device_update_buffer[did] = int(timestamp)

    async def _save_alert_immediate(self, device_id: int, station_id: int, sensor_record: dict, alert: dict, current_timestamp: int):
        """Ghi trực tiếp xuống DB ngay lập tức khi có alert (không qua buffer)."""
        incident_scope = {}
        try:
            from app.models.config import Device, Project, Station
            async with ConfigSessionLocal() as db_config:
                scope_row = (await db_config.execute(
                    select(Station.project_id, Station.name, Station.station_code, Project.name, Project.project_code)
                    .join(Project, Project.id == Station.project_id)
                    .where(Station.id == station_id)
                )).first()
                if scope_row:
                    incident_scope = {
                        "project_id": int(scope_row[0]), "station_name": scope_row[1],
                        "station_code": scope_row[2], "project_name": scope_row[3],
                        "project_code": scope_row[4],
                    }
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
                    existing_alert = model_data.Alert(
                        station_id=station_id,
                        timestamp=current_timestamp,
                        level=alert['level'],
                        category=alert['category'],
                        message=alert['message'],
                        is_resolved=False
                    )
                    db_data.add(existing_alert)
                await db_data.flush()
                incident_case, _, incident_event = await ensure_incident_case(
                    db_data,
                    source_kind="SENSOR_ALERT",
                    source_id=int(existing_alert.id),
                    title=f"Cảnh báo {str(alert.get('category') or 'sensor').upper()}",
                    summary=str(alert.get('message') or 'Cảnh báo sensor cần theo dõi'),
                    source_severity=str(alert.get('level') or 'UNKNOWN'),
                    signal_state="ACTIVE" if not existing_alert.is_resolved else "RETURNED",
                    station_id=int(station_id),
                    project_id=incident_scope.get("project_id"),
                    project_name=incident_scope.get("project_name"),
                    project_code=incident_scope.get("project_code"),
                    station_name=incident_scope.get("station_name"),
                    station_code=incident_scope.get("station_code"),
                    now=int(current_timestamp),
                )
                await db_data.commit()
                if incident_event is not None:
                    await db_data.refresh(incident_event)
                    await manager.broadcast_operations({
                        "protocol": 2,
                        "type": "incident_changed",
                        "event_id": int(incident_event.id),
                        "sequence_from": int(incident_event.sequence),
                        "sequence_to": int(incident_event.sequence),
                        "incident_id": int(incident_case.id),
                        "incident_revision": int(incident_case.revision),
                        "workflow_version": int(incident_case.version),
                        "action": "opened" if incident_event.event_type == "opened" else "updated",
                        "project_id": incident_case.project_id,
                        "station_id": incident_case.station_id,
                        "summary": serialize_case(incident_case),
                    })
        except Exception as e:
            logger.error(f"❌ Alert data save error: {e}")

    async def _touch_active_alert(self, station_id: int, category: str, timestamp: int) -> int:
        """Refresh an unresolved alert without changing its level/message.

        A restored GNSS quarantine is still an active operational condition.
        Refreshing its durable timestamp keeps the REST summary from treating
        a healthy restart as an automatic resolution while the processor is
        collecting a new velocity window.
        """
        # A rejected GNSS sample can arrive several times per second. Refreshing
        # the same alert for every packet creates a DB write storm while the
        # processor is intentionally quarantined. One touch per 15s preserves
        # the durable TTL without competing with sensor persistence.
        refresh_key = (int(station_id), str(category))
        refresh_attempts = getattr(self, "_active_alert_refresh_attempts", None)
        if refresh_attempts is None:
            refresh_attempts = self._active_alert_refresh_attempts = {}
        now = time.monotonic()
        last_attempt = float(refresh_attempts.get(refresh_key, 0.0) or 0.0)
        if now - last_attempt < 15.0:
            return 0
        refresh_attempts[refresh_key] = now
        try:
            async with DataSessionLocal() as db_data:
                result = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.category == category,
                        model_data.Alert.is_resolved.is_(False),
                    ))
                    .values(timestamp=int(timestamp))
                )
                await db_data.commit()
                return int(result.rowcount or 0)
        except Exception as exc:
            logger.error(
                "❌ Failed to refresh active alert station=%s category=%s: %s",
                station_id,
                category,
                exc,
            )
            return 0

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
                alert_ids = [int(value) for value in (await db_data.execute(
                    select(model_data.Alert.id).where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False,
                    ))
                )).scalars().all()]
                res = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False
                    ))
                    .values(is_resolved=True)
                )
                incident_events = []
                if alert_ids:
                    incident_rows = (await db_data.execute(
                        select(model_data.IncidentCase).where(
                            model_data.IncidentCase.source_kind == "SENSOR_ALERT",
                            model_data.IncidentCase.source_id.in_(alert_ids),
                        ).with_for_update()
                    )).scalars().all()
                    for incident_case in incident_rows:
                        if incident_case.status in {"resolved", "dismissed"}:
                            continue
                        incident_case.signal_state = "RETURNED"
                        incident_case.status = "resolved"
                        incident_case.resolved_at = int(time.time())
                        incident_case.version += 1
                        incident_events.append((incident_case, await append_event(
                            db_data, incident_case, "signal_returned",
                            payload={"signal_state": "RETURNED", "status": "resolved", "reason": "alerting_disabled"},
                        )))
                if res.rowcount > 0:
                    await db_data.commit()
                    for incident_case, incident_event in incident_events:
                        await db_data.refresh(incident_event)
                        await manager.broadcast_operations({
                            "protocol": 2, "type": "incident_changed", "event_id": int(incident_event.id),
                            "sequence_from": int(incident_event.sequence), "sequence_to": int(incident_event.sequence),
                            "incident_id": int(incident_case.id), "incident_revision": int(incident_case.revision),
                            "workflow_version": int(incident_case.version), "action": "resolved",
                            "project_id": incident_case.project_id, "station_id": incident_case.station_id,
                            "summary": serialize_case(incident_case),
                        })
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

            unresolved_levels = []
            stale_count = 0
            for level, category, ts in rows:
                ttl = alert_ttl.get(category, 180)
                age_seconds = max(0, now_ts - int(ts or 0))
                if age_seconds > ttl:
                    stale_count += 1
                normalized_level = str(level or '').upper()
                if category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and normalized_level == 'WARNING':
                    normalized_level = 'CRITICAL'
                unresolved_levels.append(normalized_level)

            priority = {
                "EXTREME": 5,
                "CRITICAL": 4,
                "HIGH": 3,
                "WARNING": 2,
                "MEDIUM": 1,
                "LOW": 0,
            }
            normalized_levels = [str(level).upper() for level in unresolved_levels if level is not None]
            highest_level = "LOW"
            highest_score = -1
            for level in normalized_levels:
                score = priority.get(level, 0)
                if score > highest_score:
                    highest_level = level
                    highest_score = score

            if highest_level in priority and highest_level != "LOW":
                return {
                    "risk_level": highest_level,
                    "unresolved_count": len(unresolved_levels),
                    "stale_count": stale_count,
                }
            return {
                "risk_level": "LOW",
                "unresolved_count": len(unresolved_levels),
                "stale_count": stale_count,
            }
        except Exception as e:
            logger.error(f"❌ Error reading active alert summary for station {station_id}: {e}")
            # Database uncertainty is not a safe reading.  Callers must keep
            # the last durable siren/alert state and avoid auto-stop actions.
            return {"risk_level": "UNKNOWN", "unresolved_count": 0, "degraded": True}

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

    def _get_client_for_station(self, station_id: int) -> mqtt.Client:
        broker_key = self._station_brokers.get(station_id)
        if broker_key and broker_key in self._sub_clients:
            return self._sub_clients[broker_key]
        return self.client # Fallback to default client
