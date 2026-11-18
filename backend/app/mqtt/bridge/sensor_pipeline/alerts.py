"""Sensor alert analysis, notification, and recovery handling."""

from __future__ import annotations

import json
import logging
import time

from sqlalchemy import and_, select

from app.database import DataSessionLocal
from app.features.incidents.cases import append_event, serialize_case
from app.models import data as model_data
from app.websocket import manager

logger = logging.getLogger(__name__)


async def _resolve_incident_cases_for_alerts(db_data, alert_ids: list[int]) -> list:
    if not alert_ids:
        return []
    incident_events = []
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
            payload={"signal_state": "RETURNED", "status": "resolved", "reason": "sensor_recovered"},
        )))
    return incident_events


class SensorAlertMixin:
    def _run_sensor_analyzer(self, sensor_type: str, station_id: int, data_wrapper: list, station_config: dict) -> dict | None:
        try:
            if sensor_type == 'gnss':
                return self.analyzer.analyze_gnss_displacement(station_id, data_wrapper, station_config)
            if sensor_type == 'rain':
                return self.analyzer.analyze_rainfall(station_id, data_wrapper, [], station_config)
            if sensor_type == 'water':
                return self.analyzer.analyze_water_level(station_id, data_wrapper, station_config)
            if sensor_type == 'imu':
                return self.analyzer.analyze_tilt(station_id, data_wrapper, station_config)
        except Exception as e:
            logger.exception(f"Analyzer error: {e}")
        return None

    async def _broadcast_dangerous_alert(self, station_id: int, station_name: str, sensor_type: str, alert: dict, project_id: int | None):
        try:
            await manager.broadcast({
                "type": "station_status",
                "project_id": project_id,
                "station_id": station_id,
                "risk_level": alert['level']
            })
            await manager.broadcast({
                "type": "alert",
                "project_id": project_id,
                "station_id": station_id,
                "sensor_type": sensor_type,
                "level": alert['level'],
                "message": alert['message'],
                "audio_code": alert.get('audio_code', ''),
                "details": alert.get('details', {})
            })
            audio_code = alert.get('audio_code', '')
            if audio_code:
                cmd_topic = f"landslide/{station_id}/command"
                cmd_payload = json.dumps({
                    "audio_code": audio_code,
                    "level": alert['level'],
                    "message": alert['message'],
                    "ts": int(time.time())
                })
                self._get_client_for_station(station_id).publish(cmd_topic, cmd_payload, qos=1)
                logger.warning(f"🔊 [{station_name}] MQTT audio command → {cmd_topic}: {audio_code}")

            logger.warning(f"🚨 [{station_name}] Alert broadcast: {alert['message']}")
        except Exception as e:
            logger.exception(f"❌ WS Alert Broadcast Error: {e}")

    async def _auto_resolve_sensor_alerts(
        self,
        station_id: int,
        station_name: str,
        sensor_type: str,
        station_config: dict,
        project_id: int | None,
    ) -> bool:
        categories_map = {
            'gnss': ['gnss_velocity'],
            'rain': ['rainfall'],
            'water': ['water_level'],
            'imu': ['tilt_critical', 'tilt_warning', 'shock', 'tilt'],
        }
        categories_to_resolve = categories_map.get(sensor_type, [])
        if not categories_to_resolve:
            return False

        try:
            async with DataSessionLocal() as db_data:
                summary_before = await self._get_station_active_alert_summary(station_id, station_config, db=db_data)
                if summary_before.get('degraded'):
                    logger.warning(
                        f"⚠️ Alert summary unavailable for station {station_id}; "
                        "skipping auto-resolve and keeping siren state unchanged."
                    )
                    return False

                alert_ids = [int(value) for value in (await db_data.execute(
                    select(model_data.Alert.id).where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False,
                        model_data.Alert.category.in_(categories_to_resolve),
                    ))
                )).scalars().all()]

                res = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False,
                        model_data.Alert.category.in_(categories_to_resolve)
                    ))
                    .values(is_resolved=True)
                )
                incident_events = await _resolve_incident_cases_for_alerts(db_data, alert_ids)

                if res is not None and res.rowcount > 0:
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
                    summary = await self._get_station_active_alert_summary(station_id, station_config, db=db_data)
                    unresolved_count = summary.get('unresolved_count', 0)
                    if summary.get('degraded'):
                        logger.warning(
                            f"⚠️ Alert summary unavailable for station {station_id}; "
                            "keeping siren state unchanged."
                        )
                    elif unresolved_count == 0:
                        logger.info(f"✅ Auto-resolved {res.rowcount} alerts for station {station_id} (sensor: {sensor_type}). Sending stop_siren command...")
                        cmd_topic = f"landslide/{station_id}/command"
                        cmd_payload = json.dumps({"cmd": "auto_stop_siren", "ts": int(time.time())})
                        self._get_client_for_station(station_id).publish(cmd_topic, cmd_payload, qos=1)
                    else:
                        logger.info(
                            f"✅ Auto-resolved {res.rowcount} alerts for station {station_id} (sensor: {sensor_type}) "
                            f"but {unresolved_count} alerts still active; keep siren active state."
                        )
                    return True
        except Exception as e:
            logger.exception(f"❌ Error auto-resolving alerts: {e}")
        return False

    async def _analyze_and_alert(
        self,
        station_id: int,
        station_name: str,
        sensor_type: str,
        station_config: dict,
        processed_data: dict,
        current_timestamp: int,
        *, project_id: int | None = None,
    ) -> tuple[dict | None, bool, bool]:
        alerting_enabled = self._is_station_alerting_enabled(station_config)
        data_wrapper = [{"timestamp": current_timestamp, "data": processed_data}]

        if not alerting_enabled:
            self._reset_station_alert_state(station_id)
            await self._suppress_station_alerts(station_id, project_id=project_id)
            alert = {"level": "PENDING", "category": "alerting_disabled"}
        else:
            alert = self._run_sensor_analyzer(sensor_type, station_id, data_wrapper, station_config)

        is_dangerous = bool(alert and str(alert.get('level', '')).upper() in self.DANGEROUS_ALERT_LEVELS)
        is_pending = bool(alert and alert.get('level') == 'PENDING')

        if is_dangerous and sensor_type == 'imu' and alert:
            alert['level'] = 'CRITICAL'
            if alert.get('category') == 'tilt_warning':
                alert['category'] = 'tilt_critical'
            if not alert.get('audio_code') or alert.get('audio_code') == 'imu_warning':
                alert['audio_code'] = 'imu_critical'

        is_just_resolved = False
        if is_dangerous:
            await self._broadcast_dangerous_alert(station_id, station_name, sensor_type, alert, project_id)
        elif not is_pending:
            is_just_resolved = await self._auto_resolve_sensor_alerts(
                station_id, station_name, sensor_type, station_config, project_id
            )
            try:
                summary = await self._get_station_active_alert_summary(station_id, station_config)
                await manager.broadcast({
                    "type": "station_status",
                    "project_id": project_id,
                    "station_id": station_id,
                    "risk_level": summary['risk_level']
                })
            except Exception as e:
                logger.exception(f"❌ WS Station Status Error: {e}")

        return alert, is_dangerous, is_just_resolved
