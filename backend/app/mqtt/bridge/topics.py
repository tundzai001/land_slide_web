"""MQTT topic subscriptions and sensor processor lifecycle."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

import paho.mqtt.client as mqtt

from app.shared.sensor_catalog import is_monitoring_type
from app.database import ConfigSessionLocal
from processors.gnss_processor import GNSSVelocityProcessor
from processors.imu_processor import IMUEngine
from processors.water_processor import RainEngine, WaterEngine

logger = logging.getLogger(__name__)


class MQTTTopicMixin:
    def _diag_should_log(self, key: str, interval_sec: int = 30) -> bool:
        now_ts = int(time.time())
        last_ts = int(self._diag_last_log_ts.get(key, 0) or 0)
        if (now_ts - last_ts) >= interval_sec:
            self._diag_last_log_ts[key] = now_ts
            return True
        return False

    def _apply_runtime_defaults_to_station_config(self, station_config: dict) -> dict:
        """Station config has priority; global system config is fallback."""
        cfg = dict(station_config or {})
        alerting_cfg = dict(cfg.get("alerting", {}) or {})
        alerting_cfg.setdefault("enabled", True)
        cfg["alerting"] = alerting_cfg

        gnss_cfg = dict(cfg.get("GnssAlerting", {}) or {})
        gnss_integrity_cfg = dict(cfg.get("GnssIntegrity", cfg.get("gnss_integrity", {})) or {})
        rain_cfg = dict(cfg.get("RainAlerting", {}) or {})
        water_cfg = dict(cfg.get("Water", {}) or {})
        imu_cfg = dict(cfg.get("ImuAlerting", {}) or {})

        gnss_cfg.setdefault("gnss_confirm_steps", self.runtime_confirmation["gnss"])
        gnss_cfg.setdefault("gnss_warning_confirm_steps", self.runtime_confirmation["gnss"])
        gnss_cfg.setdefault("gnss_critical_confirm_steps", max(1, self.runtime_confirmation["gnss"] - 1))
        gnss_integrity_cfg.setdefault("process_max_hdop", 2.0)
        gnss_integrity_cfg.setdefault("process_min_sats", 10)
        gnss_integrity_cfg.setdefault("origin_max_gap_s", 2.0)
        gnss_integrity_cfg.setdefault("reference_event_alignment_s", 30.0)
        gnss_integrity_cfg.setdefault("reference_transition_samples", 6)
        gnss_integrity_cfg.setdefault("reacquire_max_spread_xy_m", 0.03)
        gnss_integrity_cfg.setdefault("reacquire_max_spread_u_m", 0.05)
        rain_cfg.setdefault("rain_confirm_steps", self.runtime_confirmation["rain"])
        rain_cfg.setdefault("rain_warning_confirm_steps", self.runtime_confirmation["rain"])
        rain_cfg.setdefault("rain_critical_confirm_steps", max(1, self.runtime_confirmation["rain"] - 1))
        water_cfg.setdefault("water_confirm_steps", self.runtime_confirmation["water"])
        water_cfg.setdefault("water_warning_confirm_steps", self.runtime_confirmation["water"])
        water_cfg.setdefault("water_critical_confirm_steps", max(1, self.runtime_confirmation["water"] - 1))
        imu_cfg.setdefault("imu_confirm_steps", self.runtime_confirmation["imu"])
        imu_cfg.setdefault("imu_warning_confirm_steps", self.runtime_confirmation["imu"])
        imu_cfg.setdefault("imu_critical_confirm_steps", max(1, self.runtime_confirmation["imu"] - 1))

        cfg["GnssAlerting"] = gnss_cfg
        cfg["GnssIntegrity"] = gnss_integrity_cfg
        cfg["RainAlerting"] = rain_cfg
        cfg["Water"] = water_cfg
        cfg["ImuAlerting"] = imu_cfg
        return cfg

    def _is_station_alerting_enabled(self, station_config: Optional[dict]) -> bool:
        cfg = station_config or {}
        alerting_cfg = cfg.get("alerting", {}) or {}
        return alerting_cfg.get("enabled", cfg.get("alerting_enabled", True)) is not False

    def _reset_station_alert_state(self, station_id: int):
        """Drop in-memory alert counters so disabled stations restart cleanly if re-enabled."""
        try:
            self.analyzer.alert_counters.pop(station_id, None)
            self.analyzer.gnss_recent_history.pop(station_id, None)
        except Exception as e:
            logger.warning(f"Could not reset alert state for station {station_id}: {e}")

    async def reload_topics_from_db(self):
        logger.info("🔄 Started Topic Auto-Reload Task")
        while True:
            try:
                from app.models.config import Device, Station, Project
                from sqlalchemy import select
                
                async with ConfigSessionLocal() as db:
                    result = await db.execute(
                        select(Device, Station, Project)
                        .join(Station, Device.station_id == Station.id)
                        .join(Project, Station.project_id == Project.id)
                        .where(Device.is_active == True)
                    )
                    devices_with_stations = result.all()
                
                new_map = {}
                new_client_topics = defaultdict(set)
                new_station_brokers = {}
                
                for device, station, project in devices_with_stations:
                    if not device.mqtt_topic or device.mqtt_topic.strip() == "":
                        continue
                    
                    topic = device.mqtt_topic
                    sensor_type = device.device_type
                    proc_key = f"device_{device.id}"
                    device_context = (
                        f"project={project.name}({project.project_code}) "
                        f"station={station.name}({station.station_code}, id={station.id}) "
                        f"device={device.name}({device.device_code}, id={device.id}) "
                        f"topic={topic}"
                    )
                    
                    # Determine MQTT Broker configuration for this station/device
                    dev_cfg = device.config or {}
                    mqtt_cfg = dev_cfg.get("mqtt")
                    
                    if not mqtt_cfg:
                        # Fallback to station config for backward compatibility
                        st_cfg = station.config or {}
                        mqtt_cfg = st_cfg.get("mqtt", {}) or {}
                    
                    broker_host = (mqtt_cfg.get("host") or "").strip() or self.runtime_mqtt["broker"]
                    
                    broker_port = mqtt_cfg.get("port")
                    if broker_port is not None:
                        try:
                            broker_port = int(broker_port)
                        except (ValueError, TypeError):
                            broker_port = None
                    if not broker_port:
                        broker_port = self.runtime_mqtt["port"]
                        
                    broker_user = (mqtt_cfg.get("username") or "").strip() or self.runtime_mqtt["user"] or None
                    broker_pass = mqtt_cfg.get("password") or self.runtime_mqtt["password"] or None
                    broker_tls = bool(mqtt_cfg.get("use_tls", False))
                    
                    broker_key = (broker_host, broker_port, broker_user, broker_pass, broker_tls)
                    new_station_brokers[station.id] = broker_key
                    new_client_topics[broker_key].add(topic)
                    
                    if proc_key not in self.processors_cache:
                        if device.device_type == 'gnss':
                            self.processors_cache[proc_key] = GNSSVelocityProcessor(
                                device.id,
                                ConfigSessionLocal,
                                context_label=device_context
                            )
                        elif sensor_type == 'rain':
                            self.processors_cache[proc_key] = RainEngine()
                        elif sensor_type == 'water':
                            self.processors_cache[proc_key] = WaterEngine()
                        elif sensor_type == 'imu':
                            imu_engine = IMUEngine()
                            # ✅ Load baseline từ station config nếu có
                            imu_baseline = (station.config or {}).get('ImuBaseline', {})
                            if imu_baseline.get('baseline_roll') is not None:
                                imu_engine.set_baseline(
                                    float(imu_baseline.get('baseline_roll', 0)),
                                    float(imu_baseline.get('baseline_pitch', 0)),
                                    float(imu_baseline.get('baseline_yaw', 0))
                                )
                                logger.info(f"🎯 [IMU] Loaded baseline for station {station.name} from config")
                            self.processors_cache[proc_key] = imu_engine
                        elif is_monitoring_type(sensor_type):
                            self.processors_cache[proc_key] = None
                        else:
                            logger.warning('Unsupported sensor type %s for device %s', sensor_type, device.id)
                            continue
                    elif device.device_type == 'gnss' and hasattr(self.processors_cache[proc_key], 'set_context'):
                        self.processors_cache[proc_key].set_context(device_context)
                    
                    new_map[(broker_key, topic)] = {
                        "device_id": device.id,
                        "device_name": device.name,
                        "station_id": station.id,
                        "station_name": station.name,
                        "station_code": getattr(station, "station_code", None),
                        "project_id": project.id,
                        "project_gnss_clusters": project.gnss_clusters,
                        "station_origins": {},
                        "type": device.device_type,
                        "processor": self.processors_cache[proc_key],
                        "config": self._apply_runtime_defaults_to_station_config(station.config or {}),
                        "forwarding": (station.config or {}).get("gnss_rtk_forwarding", {})
                    }
                
                # 1. Terminate clients that are no longer needed
                for b_key in list(self._sub_clients.keys()):
                    if b_key not in new_client_topics:
                        logger.info(f"🔌 [DYNAMIC MQTT] Stopping client for {b_key[0]}:{b_key[1]} (no active topics)")
                        client = self._sub_clients[b_key]
                        try:
                            client.loop_stop()
                            client.disconnect()
                        except Exception as e:
                            logger.error(f"Error disconnecting client {b_key[0]}:{b_key[1]}: {e}")
                        self._sub_clients.pop(b_key, None)
                        self._client_topics.pop(b_key, None)
                
                # 2. Add or update clients for new/active broker keys
                for b_key, new_topics in new_client_topics.items():
                    broker_host, broker_port, broker_user, broker_pass, broker_tls = b_key
                    
                    # Create client if it doesn't exist
                    if b_key not in self._sub_clients:
                        logger.info(f"🔌 [DYNAMIC MQTT] Creating new subscription client for {broker_host}:{broker_port}")
                        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                        client.user_data_set(b_key)
                        client.on_connect = self.on_connect
                        client.on_message = self.on_message
                        client.on_disconnect = self.on_disconnect
                        client.on_connect_fail = self.on_connect_fail
                        
                        if broker_user:
                            client.username_pw_set(broker_user, broker_pass)
                        
                        if broker_tls:
                            import ssl
                            try:
                                client.tls_set_context(ssl.create_default_context())
                                logger.info(f"🔒 Enabled TLS for client {broker_host}:{broker_port}")
                            except Exception as tls_e:
                                logger.error(f"❌ Failed to set TLS for {broker_host}:{broker_port}: {tls_e}")
                                continue
                        
                        try:
                            client.connect_async(broker_host, broker_port, 60)
                            client.loop_start()
                            self._sub_clients[b_key] = client
                        except Exception as conn_e:
                            logger.error(f"❌ Failed to connect dynamic client to {broker_host}:{broker_port}: {conn_e}")
                            continue
                    
                    client = self._sub_clients[b_key]
                    current_topics = self._client_topics[b_key]
                    
                    # Perform diff subscribe/unsubscribe on this client
                    for t in new_topics - current_topics:
                        try:
                            client.subscribe(t)
                            logger.info(f"   ✓ Dynamic Subscribed to {t} on {broker_host}:{broker_port}")
                        except Exception as sub_e:
                            logger.error(f"❌ Failed to subscribe to {t} on {broker_host}:{broker_port}: {sub_e}")
                            
                    for t in current_topics - new_topics:
                        try:
                            client.unsubscribe(t)
                            logger.info(f"   ✓ Dynamic Unsubscribed from {t} on {broker_host}:{broker_port}")
                        except Exception as unsub_e:
                            logger.error(f"❌ Failed to unsubscribe from {t} on {broker_host}:{broker_port}: {unsub_e}")
                    
                    self._client_topics[b_key] = new_topics
                
                self.topic_map = new_map
                self._station_brokers = new_station_brokers
                
            except Exception as e:
                logger.error(f"Error reloading topics: {e}")
            await asyncio.sleep(self.topic_reload_interval)
