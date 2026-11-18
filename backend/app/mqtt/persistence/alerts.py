"""Alert and incident persistence for MQTT sensor events."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import data as model_data
from app.features.incidents.cases import append_event, ensure_incident_case, serialize_case
from app.websocket import manager
from ..utils import clean_null_bytes

logger = logging.getLogger(__name__)

async def _resolve_suppression_incidents(db_data, alert_ids: list[int]) -> list:
    incident_events = []
    if not alert_ids:
        return incident_events
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
    return incident_events


class AlertPersistenceMixin:
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
            logger.exception(f"❌ Alert config update error: {e}")

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
            logger.exception(f"❌ Alert data save error: {e}")
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
        in_flight = getattr(self, "_active_alert_refresh_in_flight", None)
        if in_flight is None:
            in_flight = self._active_alert_refresh_in_flight = set()
        now = time.monotonic()
        last_attempt = float(refresh_attempts.get(refresh_key, 0.0) or 0.0)
        if refresh_key in in_flight or now - last_attempt < 15.0:
            return 0
        refresh_attempts[refresh_key] = now
        # A slow DB call can outlive the throttle interval. Do not queue
        # another refresh for the same alert while it still owns a connection.
        in_flight.add(refresh_key)
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
            logger.exception(
                "❌ Failed to refresh active alert station=%s category=%s: %s: %r",
                station_id,
                category,
                exc.__class__.__name__,
                exc,
            )
            return 0
        finally:
            in_flight.discard(refresh_key)
            refresh_attempts[refresh_key] = time.monotonic()
    async def _suppress_station_alerts(self, station_id: int, *, project_id: int | None = None):
        """Resolve active alerts and keep station status LOW when alerting is disabled."""
        now = time.monotonic()
        attempts = getattr(self, "_alert_suppression_last_attempt", None)
        if attempts is None:
            attempts = self._alert_suppression_last_attempt = {}
        in_flight = getattr(self, "_alert_suppression_in_flight", None)
        if in_flight is None:
            in_flight = self._alert_suppression_in_flight = set()
        last_attempt = float(attempts.get(station_id, 0.0) or 0.0)
        if station_id in in_flight or now - last_attempt < self._alert_suppression_interval_seconds:
            return
        attempts[station_id] = now
        in_flight.add(station_id)
        try:
            async with DataSessionLocal() as db_data:
                alert_ids = [int(value) for value in (await db_data.execute(
                    select(model_data.Alert.id).where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False,
                    ))
                )).scalars().all()]
                if not alert_ids:
                    # No active alerts to suppress; avoid empty UPDATE and back off interval
                    self._alert_suppression_last_attempt[station_id] = time.monotonic() + 25.0
                    return
                res = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False
                    ))
                    .values(is_resolved=True)
                )
                incident_events = await _resolve_suppression_incidents(db_data, alert_ids)
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
                "project_id": project_id,
                "station_id": station_id,
                "risk_level": "LOW"
            })
        except Exception as e:
            if self._diag_should_log(f"alert_suppression:{station_id}", 30):
                logger.exception(
                    "Error suppressing alerts for station %s: %s: %r",
                    station_id,
                    e.__class__.__name__,
                    e,
                )
        finally:
            in_flight.discard(station_id)
            attempts[station_id] = max(attempts[station_id], time.monotonic())
    def _build_alert_ttl_map(self, station_config: Optional[dict]) -> Dict[str, int]:
        cfg = station_config or {}
        default_ttl = {
            'gnss_velocity': max(90, self._get_sensor_offline_threshold(cfg, 'gnss') * 2),
            'rainfall': max(120, self._get_sensor_offline_threshold(cfg, 'rain') * 2),
            'water_level': max(120, self._get_sensor_offline_threshold(cfg, 'water') * 2),
            'tilt': max(300, self._get_sensor_offline_threshold(cfg, 'imu')),
            'tilt_warning': max(300, self._get_sensor_offline_threshold(cfg, 'imu')),
            'tilt_critical': max(300, self._get_sensor_offline_threshold(cfg, 'imu')),
            'shock': max(300, self._get_sensor_offline_threshold(cfg, 'imu')),
        }
        ttl_cfg = cfg.get('alert_ttl_seconds', {})
        return {k: int(ttl_cfg.get(k, v)) for k, v in default_ttl.items()}

    @staticmethod
    def _highest_alert_priority(unresolved_levels: list) -> str:
        priority = {
            "EXTREME": 5,
            "CRITICAL": 4,
            "HIGH": 3,
            "WARNING": 2,
            "MEDIUM": 1,
            "LOW": 0,
        }
        normalized = [str(l).upper() for l in unresolved_levels if l is not None]
        return max(normalized, key=lambda l: priority.get(l, 0), default="LOW")

    async def _get_station_active_alert_summary(
        self,
        station_id: int,
        station_config: Optional[dict] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Return highest active risk level and unresolved alert count for a station."""
        try:
            if not self._is_station_alerting_enabled(station_config):
                return {"risk_level": "LOW", "unresolved_count": 0}

            now_ts = int(time.time())
            alert_ttl = self._build_alert_ttl_map(station_config)

            stmt = (
                select(model_data.Alert.level, model_data.Alert.category, model_data.Alert.timestamp)
                .where(
                    and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False
                    )
                )
            )
            if db is not None:
                res = await db.execute(stmt)
                rows = res.all()
            else:
                async with DataSessionLocal() as db_data:
                    res = await db_data.execute(stmt)
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

            highest_level = self._highest_alert_priority(unresolved_levels)
            return {
                "risk_level": highest_level,
                "unresolved_count": len(unresolved_levels),
                "stale_count": stale_count,
            }
        except Exception as e:
            logger.exception(f"❌ Error reading active alert summary for station {station_id}: {e}")
            # Database uncertainty is not a safe reading.  Callers must keep
            # the last durable siren/alert state and avoid auto-stop actions.
            return {"risk_level": "UNKNOWN", "unresolved_count": 0, "degraded": True}
