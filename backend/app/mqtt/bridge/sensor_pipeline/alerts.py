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


class SensorAlertMixin:
    async def _analyze_and_alert(
        self,
        station_id: int,
        station_name: str,
        sensor_type: str,
        station_config: dict,
        processed_data: dict,
        current_timestamp: int,
    ) -> tuple[dict | None, bool, bool]:
        alerting_enabled = self._is_station_alerting_enabled(station_config)

        alert = None

        data_wrapper = [{"timestamp": current_timestamp, "data": processed_data}]

        if not alerting_enabled:
            self._reset_station_alert_state(station_id)
            await self._suppress_station_alerts(station_id)
            alert = {"level": "PENDING", "category": "alerting_disabled"}
        else:
            try:
                if sensor_type == 'gnss':
                    alert = self.analyzer.analyze_gnss_displacement(station_id, data_wrapper, station_config)
                elif sensor_type == 'rain':
                    alert = self.analyzer.analyze_rainfall(station_id, data_wrapper, [], station_config)
                elif sensor_type == 'water':
                    alert = self.analyzer.analyze_water_level(station_id, data_wrapper, station_config)
                elif sensor_type == 'imu':
                    alert = self.analyzer.analyze_tilt(station_id, data_wrapper, station_config)
            except Exception as e:
                logger.error(f"Analyzer error: {e}")

        is_dangerous = False

        is_just_resolved = False

        is_pending = False

        if alert and str(alert.get('level', '')).upper() in self.DANGEROUS_ALERT_LEVELS:
            is_dangerous = True
        elif alert and alert.get('level') == 'PENDING':
            is_pending = True

        if is_dangerous and sensor_type == 'imu' and alert:
            alert['level'] = 'CRITICAL'
            if alert.get('category') == 'tilt_warning':
                alert['category'] = 'tilt_critical'
            if not alert.get('audio_code') or alert.get('audio_code') == 'imu_warning':
                alert['audio_code'] = 'imu_critical'

        if is_dangerous:
            try:
                # 1. Update UI Status
                await manager.broadcast({
                    "type": "station_status",
                    "station_id": station_id,
                    "risk_level": alert['level']
                })

                # 2. Send Alert to Pi Audio Player (and UI) via WebSocket
                await manager.broadcast({
                    "type": "alert",
                    "station_id": station_id,
                    "sensor_type": sensor_type,
                    "level": alert['level'],
                    "message": alert['message'],
                    "audio_code": alert.get('audio_code', ''),
                    "details": alert.get('details', {})
                })

                # 3. ✅ CRITICAL: Gửi MQTT command đến Pi để phát audio
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
                logger.error(f"❌ WS Alert Broadcast Error: {e}")
        elif not is_pending:
            # ✅ Tự động đánh dấu Resolved cho Alert của sensor này và tắt còi
            try:
                categories_to_resolve = []
                if sensor_type == 'gnss': categories_to_resolve = ['gnss_velocity']
                elif sensor_type == 'rain': categories_to_resolve = ['rainfall']
                elif sensor_type == 'water': categories_to_resolve = ['water_level']
                elif sensor_type == 'imu': categories_to_resolve = ['tilt_critical', 'tilt_warning', 'shock', 'tilt']

                if categories_to_resolve:
                    async with DataSessionLocal() as db_data:
                        # A database/read failure must never turn an uncertain
                        # station into a resolved one.  Check the durable
                        # summary before mutating alert rows so a restart or
                        # transient pool outage cannot silence a real alarm.
                        summary_before = await self._get_station_active_alert_summary(station_id, station_config)
                        if summary_before.get('degraded'):
                            logger.warning(
                                f"⚠️ Alert summary unavailable for station {station_id}; "
                                "skipping auto-resolve and keeping siren state unchanged."
                            )
                            res = None
                        incident_events = []
                        if summary_before.get('degraded'):
                            alert_ids = []
                        else:
                            alert_ids = [int(value) for value in (await db_data.execute(
                                select(model_data.Alert.id).where(and_(
                                    model_data.Alert.station_id == station_id,
                                    model_data.Alert.is_resolved == False,
                                    model_data.Alert.category.in_(categories_to_resolve),
                                ))
                            )).scalars().all()]
                        if not summary_before.get('degraded'):
                            res = await db_data.execute(
                                model_data.Alert.__table__.update()
                                .where(and_(
                                    model_data.Alert.station_id == station_id,
                                    model_data.Alert.is_resolved == False,
                                    model_data.Alert.category.in_(categories_to_resolve)
                                ))
                                .values(is_resolved=True)
                            )
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
                                        payload={"signal_state": "RETURNED", "status": "resolved", "reason": "sensor_recovered"},
                                    )))
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
                            is_just_resolved = True
                            summary = await self._get_station_active_alert_summary(station_id, station_config)
                            unresolved_count = summary.get('unresolved_count', 0)
                            if summary.get('degraded'):
                                logger.warning(
                                    f"⚠️ Alert summary unavailable for station {station_id}; "
                                    "keeping siren state unchanged."
                                )
                            elif unresolved_count == 0:
                                logger.info(f"✅ Auto-resolved {res.rowcount} alerts for station {station_id} (sensor: {sensor_type}). Sending stop_siren command...")
                                # Gửi MQTT auto_stop_siren để Pi tắt loa nhưng không bị 'MUTE'
                                cmd_topic = f"landslide/{station_id}/command"
                                cmd_payload = json.dumps({"cmd": "auto_stop_siren", "ts": int(time.time())})
                                self._get_client_for_station(station_id).publish(cmd_topic, cmd_payload, qos=1)
                            else:
                                logger.info(
                                    f"✅ Auto-resolved {res.rowcount} alerts for station {station_id} (sensor: {sensor_type}) "
                                    f"but {unresolved_count} alerts still active; keep siren active state."
                                )
            except Exception as e:
                logger.error(f"❌ Error auto-resolving alerts: {e}")

            # Chỉ gửi LOW khi trạm thực sự không còn alert unresolved.
            try:
                summary = await self._get_station_active_alert_summary(station_id, station_config)
                await manager.broadcast({
                    "type": "station_status",
                    "station_id": station_id,
                    "risk_level": summary['risk_level']
                })
            except Exception as e:
                logger.error(f"❌ WS Station Status Error: {e}")
        return alert, is_dangerous, is_just_resolved
