# ==============================================================================
# == backend/mqtt_bridge.py - MQTT to Database Bridge (FIXED WITH SAVE INTERVALS) ==
# ==============================================================================

import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, Optional
from collections import defaultdict

import paho.mqtt.client as mqtt
from sqlalchemy import select, update, and_, desc, func
from app.websocket import manager
from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import config as model_config
from app.models import data as model_data
from app.config import settings
from app.landslide_analyzer import LandslideAnalyzer

from processors.gnss_processor import GNSSVelocityProcessor
from processors.water_processor import WaterEngine, RainEngine
from processors.imu_processor import IMUEngine
try:
    # Prefer the backend package when Uvicorn is launched from repository root;
    # this avoids importing the legacy top-level processors/ copy.
    from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
except ModuleNotFoundError:
    # backend/server.py runs with backend/ itself as sys.path[0].
    from processors.round_robin_manager import RoundRobinAdjustmentManager

# from aes128decrypt import aes128_decrypt_base64  # tạm vô hiệu hoá

def clean_null_bytes(data):
    if isinstance(data, str):
        return data.replace('\x00', '')
    elif isinstance(data, dict):
        return {k: clean_null_bytes(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_null_bytes(item) for item in data]
    return data

logger = logging.getLogger(__name__)

class MQTTBridge:
    DANGEROUS_ALERT_LEVELS = {"WARNING", "CRITICAL", "HIGH", "EXTREME"}
    DEFAULT_OFFLINE_THRESHOLDS = {
        "gnss": 30,
        "rain": 60,
        "water": 60,
        "imu": 2400,
    }

    def __init__(self):
        logger.info("🛠️ Initializing MQTT Bridge Instance...")
        
        self.analyzer = LandslideAnalyzer()
        
        # MQTT Client setup
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.runtime_mqtt = {
            "broker": settings.MQTT_BROKER,
            "port": settings.MQTT_PORT,
            "user": settings.MQTT_USER,
            "password": settings.MQTT_PASSWORD,
            "topic_reload_interval": settings.TOPIC_RELOAD_INTERVAL,
        }
        self.runtime_confirmation = {
            "gnss": 3,
            "rain": 2,
            "water": 3,
            "imu": 1,
        }
        self.runtime_save_intervals = {
            "gnss": settings.SAVE_INTERVAL_GNSS,
            "rain": settings.SAVE_INTERVAL_RAIN,
            "water": settings.SAVE_INTERVAL_WATER,
            "imu": settings.SAVE_INTERVAL_IMU,
            "default": settings.SAVE_INTERVAL_DEFAULT,
        }
        self.topic_reload_interval = settings.TOPIC_RELOAD_INTERVAL

        if self.runtime_mqtt["user"]:
            self.client.username_pw_set(self.runtime_mqtt["user"], self.runtime_mqtt["password"])
            
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # Topic management
        self.topic_map: Dict[tuple, Dict[str, Any]] = {}  # Key: (broker_key, topic)
        self.processors_cache: Dict[str, Any] = {}
        self.adjustment_phase: Dict[int, str] = {}  # {project_id: "IDLE" | "COLLECTING_BASELINE" | "FREE_NETWORK"}
        self.active_adjustment_clusters: Dict[int, list] = {}  # {project_id: [[station_id, ...], ...]}
        # Khởi tạo RoundRobin Manager, trỏ Caster Host về cùng địa chỉ với MQTT Broker (thường chung server)
        control_hosts = [
            host.strip()
            for host in settings.NTRIP_CONTROL_HOSTS.split(",")
            if host.strip()
        ]
        if settings.NTRIP_CONTROL_HOST:
            control_hosts.insert(0, settings.NTRIP_CONTROL_HOST.strip())
        control_hosts = list(dict.fromkeys(control_hosts))
        if not control_hosts:
            control_hosts = [settings.MQTT_BROKER]
        control_host = control_hosts[0]
        source_host = settings.NTRIP_SOURCE_HOST or control_host
        self.round_robin_manager = RoundRobinAdjustmentManager(
            self.client,
            caster_host=control_host,
            caster_hosts=control_hosts,
            caster_port=settings.NTRIP_CONTROL_PORT,
            source_host=source_host,
            source_port=settings.NTRIP_SOURCE_PORT,
            control_password=settings.NTRIP_CONTROL_PASSWORD,
            source_password=settings.NTRIP_SOURCE_PASSWORD,
            route_start_callback=self._start_round_robin_ntrip_route,
            route_stop_callback=self._stop_round_robin_ntrip_route,
            result_callback=self._handle_round_robin_adjustment_result,
            error_callback=self._handle_round_robin_adjustment_error,
            progress_callback=self._handle_round_robin_progress,
        )
        self._fwd_clients: Dict[tuple, mqtt.Client] = {}  # Cache for external brokers
        self._sub_clients: Dict[tuple, mqtt.Client] = {}  # Dynamic clients for subscriptions
        self._client_topics: Dict[tuple, set] = defaultdict(set)  # Broker key -> set of subscribed topics
        self._station_brokers: Dict[int, tuple] = {}  # station_id -> broker_key
        
        self.last_save_time = defaultdict(lambda: defaultdict(int))  # {station_id: {sensor_type: timestamp}}

        # ============================================================
        # Write buffer – gom nhiều bản ghi lại rồi flush 1 lần/chu kỳ
        # Tránh mở đóng session liên tục khi có nhiều trạm
        # ============================================================
        self._sensor_buffer: list = []
        self._station_update_buffer: dict = {}  # {station_id: {status, last_update}}
        self._device_update_buffer: dict = {}   # {device_id: last_data_time}
        self._buffer_lock = asyncio.Lock()
        self._flush_interval: int = 5  # giây – flush mỗi 5 giây 1 lần
        self._diag_last_log_ts = defaultdict(int)

        self.loop = None

    def _diag_should_log(self, key: str, interval_sec: int = 30) -> bool:
        now_ts = int(time.time())
        last_ts = int(self._diag_last_log_ts.get(key, 0) or 0)
        if (now_ts - last_ts) >= interval_sec:
            self._diag_last_log_ts[key] = now_ts
            return True
        return False

    async def load_runtime_config_from_db(self):
        """Load global system config (main_config) and apply as runtime defaults."""
        try:
            async with ConfigSessionLocal() as db:
                res = await db.execute(
                    select(model_config.GlobalConfig).where(model_config.GlobalConfig.key == "main_config")
                )
                cfg_row = res.scalar_one_or_none()
                if not cfg_row or not isinstance(cfg_row.value, dict):
                    return

                cfg = cfg_row.value
                mqtt_cfg = cfg.get("mqtt", {}) or {}
                confirm_cfg = cfg.get("confirmation", {}) or {}
                intervals_cfg = cfg.get("save_intervals", {}) or {}

                self.runtime_mqtt["broker"] = mqtt_cfg.get("broker", self.runtime_mqtt["broker"])
                self.runtime_mqtt["port"] = int(mqtt_cfg.get("port", self.runtime_mqtt["port"]))
                self.runtime_mqtt["user"] = mqtt_cfg.get("user", self.runtime_mqtt["user"])
                if mqtt_cfg.get("password"):
                    self.runtime_mqtt["password"] = mqtt_cfg.get("password")
                self.runtime_mqtt["topic_reload_interval"] = int(
                    mqtt_cfg.get("topic_reload_interval", self.runtime_mqtt["topic_reload_interval"])
                )
                self.topic_reload_interval = self.runtime_mqtt["topic_reload_interval"]

                self.runtime_confirmation["gnss"] = int(confirm_cfg.get("gnss", self.runtime_confirmation["gnss"]))
                self.runtime_confirmation["rain"] = int(confirm_cfg.get("rain", self.runtime_confirmation["rain"]))
                self.runtime_confirmation["water"] = int(confirm_cfg.get("water", self.runtime_confirmation["water"]))
                self.runtime_confirmation["imu"] = int(confirm_cfg.get("imu", self.runtime_confirmation["imu"]))

                self.runtime_save_intervals["gnss"] = int(intervals_cfg.get("gnss", self.runtime_save_intervals["gnss"]))
                self.runtime_save_intervals["rain"] = int(intervals_cfg.get("rain", self.runtime_save_intervals["rain"]))
                self.runtime_save_intervals["water"] = int(intervals_cfg.get("water", self.runtime_save_intervals["water"]))
                self.runtime_save_intervals["imu"] = int(intervals_cfg.get("imu", self.runtime_save_intervals["imu"]))
        except Exception as e:
            logger.error(f"Error loading runtime system config: {e}")

    def _apply_runtime_defaults_to_station_config(self, station_config: dict) -> dict:
        """Station config has priority; global system config is fallback."""
        cfg = dict(station_config or {})
        alerting_cfg = dict(cfg.get("alerting", {}) or {})
        alerting_cfg.setdefault("enabled", True)
        cfg["alerting"] = alerting_cfg

        gnss_cfg = dict(cfg.get("GnssAlerting", {}) or {})
        rain_cfg = dict(cfg.get("RainAlerting", {}) or {})
        water_cfg = dict(cfg.get("Water", {}) or {})
        imu_cfg = dict(cfg.get("ImuAlerting", {}) or {})

        gnss_cfg.setdefault("gnss_confirm_steps", self.runtime_confirmation["gnss"])
        gnss_cfg.setdefault("gnss_warning_confirm_steps", self.runtime_confirmation["gnss"])
        gnss_cfg.setdefault("gnss_critical_confirm_steps", max(1, self.runtime_confirmation["gnss"] - 1))
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

    def reload_config(self, config_dict: dict):
        """Apply system config at runtime and reconnect MQTT with new credentials."""
        try:
            mqtt_cfg = (config_dict or {}).get("mqtt", {}) or {}
            confirm_cfg = (config_dict or {}).get("confirmation", {}) or {}
            intervals_cfg = (config_dict or {}).get("save_intervals", {}) or {}

            old_signature = (
                self.runtime_mqtt["broker"],
                self.runtime_mqtt["port"],
                self.runtime_mqtt["user"],
                self.runtime_mqtt["password"],
            )

            self.runtime_mqtt["broker"] = mqtt_cfg.get("broker", self.runtime_mqtt["broker"])
            self.runtime_mqtt["port"] = int(mqtt_cfg.get("port", self.runtime_mqtt["port"]))
            self.runtime_mqtt["user"] = mqtt_cfg.get("user", self.runtime_mqtt["user"])
            if mqtt_cfg.get("password"):
                self.runtime_mqtt["password"] = mqtt_cfg.get("password")
            self.runtime_mqtt["topic_reload_interval"] = int(
                mqtt_cfg.get("topic_reload_interval", self.runtime_mqtt["topic_reload_interval"])
            )
            self.topic_reload_interval = self.runtime_mqtt["topic_reload_interval"]

            self.runtime_confirmation["gnss"] = int(confirm_cfg.get("gnss", self.runtime_confirmation["gnss"]))
            self.runtime_confirmation["rain"] = int(confirm_cfg.get("rain", self.runtime_confirmation["rain"]))
            self.runtime_confirmation["water"] = int(confirm_cfg.get("water", self.runtime_confirmation["water"]))
            self.runtime_confirmation["imu"] = int(confirm_cfg.get("imu", self.runtime_confirmation["imu"]))

            self.runtime_save_intervals["gnss"] = int(intervals_cfg.get("gnss", self.runtime_save_intervals["gnss"]))
            self.runtime_save_intervals["rain"] = int(intervals_cfg.get("rain", self.runtime_save_intervals["rain"]))
            self.runtime_save_intervals["water"] = int(intervals_cfg.get("water", self.runtime_save_intervals["water"]))
            self.runtime_save_intervals["imu"] = int(intervals_cfg.get("imu", self.runtime_save_intervals["imu"]))

            new_signature = (
                self.runtime_mqtt["broker"],
                self.runtime_mqtt["port"],
                self.runtime_mqtt["user"],
                self.runtime_mqtt["password"],
            )

            if old_signature != new_signature:
                logger.info("🔄 MQTT runtime config changed. Reconnecting with new credentials...")
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass

                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                if self.runtime_mqtt["user"]:
                    self.client.username_pw_set(self.runtime_mqtt["user"], self.runtime_mqtt["password"])
                self.client.on_connect = self.on_connect
                self.client.on_message = self.on_message
                self.client.on_disconnect = self.on_disconnect

                self.client.connect(self.runtime_mqtt["broker"], self.runtime_mqtt["port"], 60)
                self.client.loop_start()

            logger.info("✅ Runtime system config applied")
        except Exception as e:
            logger.error(f"❌ Failed to reload runtime config: {e}")

    def _get_fwd_client(self, host: str, port: int, user: Optional[str], password: Optional[str]):
        """Get or create a persistent MQTT client for external forwarding."""
        key = (host, port, user, password)
        if key in self._fwd_clients:
            client = self._fwd_clients[key]
            if client.is_connected():
                return client
            try:
                client.reconnect()
                return client
            except Exception:
                pass

        try:
            logger.info(f"🌐 [FORWARD] Creating new external MQTT client for {host}:{port}")
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if user:
                client.username_pw_set(user, password)
            client.connect(host, port, 60)
            client.loop_start()
            self._fwd_clients[key] = client
            return client
        except Exception as e:
            logger.error(f"❌ [FORWARD] Failed to connect to external broker {host}:{port}: {e}")
            return None

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if not isinstance(userdata, tuple) or len(userdata) < 5:
            # Default client
            if rc == 0:
                logger.info("✅ Default MQTT Connected to Broker.")
                client.subscribe("command/ntrip/#")
            else:
                logger.error(f"❌ Default MQTT Connection failed: rc={rc}")
            return

        broker_key = userdata
        if rc == 0:
            logger.info(f"✅ MQTT Connected to Broker {broker_key[0]}:{broker_key[1]}.")
            topics = self._client_topics.get(broker_key, set())
            for topic in topics:
                client.subscribe(topic)
                logger.info(f"   ✓ Subscribed: {topic} on {broker_key[0]}:{broker_key[1]}")
        else:
            logger.error(f"❌ MQTT Connection to {broker_key[0]}:{broker_key[1]} failed: rc={rc}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if not isinstance(userdata, tuple) or len(userdata) < 5:
            # Default client
            if reason_code != 0:
                logger.warning(f"⚠️ Default MQTT disconnect: rc={reason_code}. Reconnecting...")
                try:
                    client.reconnect()
                    logger.info("✅ Default MQTT Reconnected successfully")
                except Exception as e:
                    logger.error(f"❌ Default Reconnect failed: {e}. Will retry in 5s...")
                    if self.loop and self.loop.is_running():
                        self.loop.call_later(5, self._retry_connect)
            else:
                logger.info("✅ Default MQTT Disconnected gracefully")
            return

        broker_key = userdata
        if reason_code != 0:
            logger.warning(f"⚠️ MQTT disconnect from {broker_key[0]}:{broker_key[1]}: rc={reason_code}. Reconnecting...")
            try:
                client.reconnect()
                logger.info(f"✅ MQTT Reconnected to {broker_key[0]}:{broker_key[1]} successfully")
            except Exception as e:
                logger.error(f"❌ Reconnect to {broker_key[0]}:{broker_key[1]} failed: {e}.")
        else:
            logger.info(f"✅ MQTT Disconnected from {broker_key[0]}:{broker_key[1]} gracefully")

    def _retry_connect(self):
        try:
            self.client.reconnect()
            logger.info("✅ MQTT Reconnected after retry")
        except Exception as e:
            logger.error(f"❌ Retry failed: {e}. Next retry in 10s...")
            self.loop.call_later(10, self._retry_connect)

    def _extract_gga_from_payload(self, payload_bytes: bytes) -> Optional[str]:
        """Extract a single NMEA GGA sentence from mixed binary/text payload."""
        if not payload_bytes:
            return None

        gga_regex = re.compile(rb'\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?')

        match = gga_regex.search(payload_bytes)
        if not match and b'\x00' in payload_bytes:
            # Some encoders interleave NULL bytes; remove them and retry.
            compact_bytes = payload_bytes.replace(b'\x00', b'')
            match = gga_regex.search(compact_bytes)

        if not match:
            return None

        return match.group(0).decode('ascii', errors='ignore').strip()

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            
            if topic.startswith("command/ntrip/"):
                self._handle_ntrip_command(msg)
                return
            
            # Resolve the correct broker key for lookup
            if isinstance(userdata, tuple) and len(userdata) >= 5:
                broker_key = userdata
            else:
                # Default client's broker key
                broker_key = (
                    self.runtime_mqtt["broker"],
                    self.runtime_mqtt["port"],
                    self.runtime_mqtt["user"] or None,
                    self.runtime_mqtt["password"] or None,
                    False
                )
                
            info = self.topic_map.get((broker_key, topic))
            if not info:
                # Fallback to check with TLS=True in case default client gets hit
                info = self.topic_map.get(((broker_key[0], broker_key[1], broker_key[2], broker_key[3], True), topic))
                
            if not info:
                if self._diag_should_log(f"unknown_topic:{broker_key}:{topic}", 60):
                    logger.warning(f"[MQTT] Received message from {broker_key[0]}:{broker_key[1]} on unknown topic: {topic}")
                return

            sensor_type = (info or {}).get('type')
            if sensor_type == 'gnss':
                station_code = (info or {}).get('station_code')
                if station_code:
                    from app.modules.ntrip_pusher import ntrip_manager
                    ntrip_manager.feed_data(station_code, msg.payload)
                    
            try:
                if sensor_type == 'gnss':
                    # Decode full text payload, retaining AGRICA and other sentences
                    payload_str = msg.payload.decode('utf-8', errors='ignore')
                    decrypted_payload = payload_str.strip()
                else:
                    payload_str = msg.payload.decode('utf-8')
                    decrypted_payload = payload_str.strip()

                if sensor_type == 'gnss' and not decrypted_payload:
                    # Silently return on empty/binary frames to avoid console flooding
                    return
                
            except UnicodeDecodeError:
                return # Bỏ qua dữ liệu nhị phân (RTCM)

            if not decrypted_payload:
                return
            
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.process_pipeline(info, decrypted_payload), 
                    self.loop
                )
        except Exception as e:
            logger.error(f"Error in on_message: {e}")

    def _handle_ntrip_command(self, msg):
        try:
            import json
            payload = json.loads(msg.payload.decode('utf-8'))
            from app.modules.ntrip_pusher import ntrip_manager
            import asyncio
            if msg.topic == "command/ntrip/route/start":
                route_payload = payload.get("ntrip_route") if isinstance(payload.get("ntrip_route"), dict) else payload
                station_code = route_payload.get("station_code")
                mountpoint = route_payload.get("mountpoint")
                if not station_code and isinstance(mountpoint, str) and mountpoint.endswith("_BASE"):
                    station_code = mountpoint[:-5]
                host = route_payload.get("host") or route_payload.get("target_host") or "127.0.0.1"
                port = int(route_payload.get("port") or route_payload.get("target_port") or 2101)
                password = route_payload.get("password", "")
                if station_code and mountpoint:
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            ntrip_manager.start_pusher(station_code, host, port, mountpoint, password),
                            self.loop
                        )
                else:
                    logger.warning("[NTRIP COMMAND] Ignored start route missing station_code or mountpoint: %s", payload)
            elif msg.topic == "command/ntrip/route/stop":
                station_code = payload.get("station_code")
                if station_code:
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            ntrip_manager.stop_pusher(station_code),
                            self.loop
                        )
        except Exception as e:
            logger.error(f"[NTRIP COMMAND] Error processing command: {e}")

    async def _start_round_robin_ntrip_route(
        self,
        station_code: str,
        host: str,
        port: int,
        mountpoint: str,
        password: str,
    ) -> bool:
        """Start SOURCE in-process and wait until the caster accepts it."""

        from app.modules.ntrip_pusher import ntrip_manager

        mapped_topics = sorted({
            topic
            for (_broker_key, topic), info in self.topic_map.items()
            if str((info or {}).get("station_code") or "").casefold() == str(station_code).casefold()
            and (info or {}).get("type") == "gnss"
        })
        logger.info(
            "[Round-Robin RTCM] station=%s source_target=%s:%s/%s mqtt_topics=%s",
            station_code,
            host,
            port,
            mountpoint,
            mapped_topics,
        )
        try:
            await ntrip_manager.start_pusher(station_code, host, port, mountpoint, password)
            await ntrip_manager.wait_for_rtcm(station_code, timeout=25.0)
        except Exception as exc:
            diagnostics = ntrip_manager.get_diagnostics(station_code)
            diagnostics["mapped_mqtt_topics"] = mapped_topics
            logger.error(
                "[Round-Robin RTCM] station=%s failed: %s diagnostics=%s",
                station_code,
                exc,
                diagnostics,
            )
            await ntrip_manager.stop_pusher(station_code)
            raise RuntimeError(
                f"{exc}; mapped_mqtt_topics={mapped_topics}"
            ) from exc
        return True

    async def _stop_round_robin_ntrip_route(self, station_code: str) -> None:
        from app.modules.ntrip_pusher import ntrip_manager

        await ntrip_manager.stop_pusher(station_code)

    def start(self):
        logger.info("🚀 Starting MQTT Bridge inside FastAPI...")
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("❌ No running event loop found!")
            return

        try:
            if self.loop and self.loop.is_running():
                self.loop.create_task(self.load_runtime_config_from_db())

            self.client.connect(self.runtime_mqtt["broker"], self.runtime_mqtt["port"], 60)
            self.client.loop_start()
            self.loop.create_task(self.reload_topics_from_db())
            self.loop.create_task(self._flush_loop())  # ✅ Khởi động flush buffer
            logger.info("✅ MQTT Bridge started successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to start MQTT Bridge: {e}")

    def stop(self):
        logger.info("🛑 Stopping MQTT Bridge...")
        self.client.loop_stop()
        self.client.disconnect()

    async def reset_gnss_origin(self, device_id: int):
        """Trigger origin reset for a specific GNSS device."""
        proc_key = f"device_{device_id}"
        processor = self.processors_cache.get(proc_key)
        if processor and hasattr(processor, 'reset_origin'):
            processor.reset_origin()
            logger.info(f"🎯 [BRIDGE] Triggered origin reset for device {device_id}")
            return True
        return False

    async def reload_topics_from_db(self):
        logger.info("🔄 Started Topic Auto-Reload Task")
        while True:
            try:
                await self.load_runtime_config_from_db()
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
                        
                        if broker_user:
                            client.username_pw_set(broker_user, broker_pass)
                        
                        if broker_tls:
                            import ssl
                            try:
                                client.tls_set_context(ssl.create_default_context())
                                logger.info(f"🔒 Enabled TLS for client {broker_host}:{broker_port}")
                            except Exception as tls_e:
                                logger.error(f"❌ Failed to set TLS for {broker_host}:{broker_port}: {tls_e}")
                        
                        try:
                            client.connect(broker_host, broker_port, 60)
                            client.loop_start()
                            self._sub_clients[b_key] = client
                        except Exception as conn_e:
                            logger.error(f"❌ Failed to connect dynamic client to {broker_host}:{broker_port}: {conn_e}")
                            self._sub_clients[b_key] = client
                    
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

    async def _flush_loop(self):
        """Background task: gom write buffer và flush xuống DB mỗi N giây."""
        logger.info("🔄 Started DB Write Buffer Flush Task")
        while True:
            await asyncio.sleep(self._flush_interval)
            await self._flush_write_buffer()

    async def _flush_write_buffer(self):
        """Flush toàn bộ buffer ra DB bằng bulk insert / batch update."""
        async with self._buffer_lock:
            if not self._sensor_buffer and not self._station_update_buffer:
                return
            sensor_batch = [clean_null_bytes(r) for r in self._sensor_buffer]
            station_batch = dict(self._station_update_buffer)
            device_batch = dict(self._device_update_buffer)
            self._sensor_buffer.clear()
            self._station_update_buffer.clear()
            self._device_update_buffer.clear()

        logger.debug(
            f"[FLUSH] Flushing: {len(sensor_batch)} sensor records, "
            f"{len(station_batch)} station updates, {len(device_batch)} device updates"
        )

        # 1. Bulk insert sensor data (1 INSERT nhiều rows thay vì nhiều INSERT)
        if sensor_batch:
            try:
                async with DataSessionLocal() as db:
                    await db.execute(model_data.SensorData.__table__.insert(), sensor_batch)
                    await db.commit()
                logger.debug(f"💾 [BULK FLUSH] {len(sensor_batch)} sensor records saved")
            except Exception as e:
                logger.error(f"❌ Bulk sensor flush error: {e}")

        # 2. Batch update Device.last_data_time + Station.last_update / status
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

    async def _save_alert_immediate(self, device_id: int, station_id: int, sensor_record: dict, alert: dict, current_timestamp: int):
        """Ghi trực tiếp xuống DB ngay lập tức khi có alert (không qua buffer)."""
        try:
            from app.models.config import Device, Station
            async with ConfigSessionLocal() as db_config:
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
                    db_data.add(model_data.Alert(
                        station_id=station_id,
                        timestamp=current_timestamp,
                        level=alert['level'],
                        category=alert['category'],
                        message=alert['message'],
                        is_resolved=False
                    ))
                await db_data.commit()
        except Exception as e:
            logger.error(f"❌ Alert data save error: {e}")

    async def _suppress_station_alerts(self, station_id: int):
        """Resolve active alerts and keep station status LOW when alerting is disabled."""
        try:
            async with DataSessionLocal() as db_data:
                res = await db_data.execute(
                    model_data.Alert.__table__.update()
                    .where(and_(
                        model_data.Alert.station_id == station_id,
                        model_data.Alert.is_resolved == False
                    ))
                    .values(is_resolved=True)
                )
                if res.rowcount > 0:
                    await db_data.commit()
                    cmd_topic = f"landslide/{station_id}/command"
                    self._get_client_for_station(station_id).publish(cmd_topic, json.dumps({"cmd": "auto_stop_siren", "ts": int(time.time())}), qos=1)
                    logger.info(f"Alerting disabled for station {station_id}; resolved {res.rowcount} active alerts.")

            await manager.broadcast({
                "type": "station_status",
                "station_id": station_id,
                "risk_level": "LOW"
            })
        except Exception as e:
            logger.error(f"Error suppressing alerts for station {station_id}: {e}")

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

            fresh_levels = []
            for level, category, ts in rows:
                ttl = alert_ttl.get(category, 180)
                if (now_ts - int(ts or 0)) <= ttl:
                    normalized_level = str(level or '').upper()
                    if category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and normalized_level == 'WARNING':
                        normalized_level = 'CRITICAL'
                    fresh_levels.append(normalized_level)

            priority = {
                "EXTREME": 5,
                "CRITICAL": 4,
                "HIGH": 3,
                "WARNING": 2,
                "MEDIUM": 1,
                "LOW": 0,
            }
            normalized_levels = [str(level).upper() for level in fresh_levels if level is not None]
            highest_level = "LOW"
            highest_score = -1
            for level in normalized_levels:
                score = priority.get(level, 0)
                if score > highest_score:
                    highest_level = level
                    highest_score = score

            if highest_level in priority and highest_level != "LOW":
                return {"risk_level": highest_level, "unresolved_count": len(fresh_levels)}
            return {"risk_level": "LOW", "unresolved_count": len(fresh_levels)}
        except Exception as e:
            logger.error(f"❌ Error reading active alert summary for station {station_id}: {e}")
            return {"risk_level": "LOW", "unresolved_count": 0}

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
        """Luôn cập nhật giá trị mới nhất vào bảng cache riêng, bất kể chu kỳ lưu sensor_data."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        cleaned_data = clean_null_bytes(data)
        try:
            async with DataSessionLocal() as db:
                stmt = pg_insert(model_data.LatestSensorCache).values(
                    station_id=station_id,
                    sensor_type=sensor_type,
                    timestamp=timestamp,
                    data=cleaned_data,
                ).on_conflict_do_update(
                    index_elements=['station_id', 'sensor_type'],
                    set_=dict(timestamp=timestamp, data=cleaned_data),
                )
                await db.execute(stmt)
                await db.commit()
        except Exception as e:
            logger.error(f"❌ [CACHE] Upsert failed station={station_id} sensor={sensor_type}: {e}")

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

    async def _buffer_sensor_record(self, device_id: int, station_id: int, sensor_type: str, current_timestamp: int, processed_data: dict):
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


    def _append_raw_gnss_to_excel(self, station_id: int, timestamp: int, raw_payload: str):
        import os
        import openpyxl
        import datetime

        file_dir = os.path.join(os.path.dirname(__file__), "static", "raw_gnss")
        os.makedirs(file_dir, exist_ok=True)
        date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        file_path = os.path.join(file_dir, f"gnss_raw_{station_id}_{date_str}.xlsx")

        if os.path.exists(file_path):
            try:
                wb = openpyxl.load_workbook(file_path)
            except Exception:
                wb = openpyxl.Workbook()
                if "Sheet" in wb.sheetnames: wb.remove(wb["Sheet"])
        else:
            wb = openpyxl.Workbook()
            if "Sheet" in wb.sheetnames: wb.remove(wb["Sheet"])

        if "GGA" not in wb.sheetnames:
            ws_gga = wb.create_sheet("GGA")
            ws_gga.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_gga = wb["GGA"]
            
        if "AGRICA" not in wb.sheetnames:
            ws_agrica = wb.create_sheet("AGRICA")
            ws_agrica.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_agrica = wb["AGRICA"]
            
        if "OTHER" not in wb.sheetnames:
            ws_other = wb.create_sheet("OTHER")
            ws_other.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_other = wb["OTHER"]

        dt_str = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

        for line in raw_payload.splitlines():
            line = line.strip()
            if not line: continue
            if "GGA" in line:
                ws_gga.append([timestamp, dt_str, line])
            elif "AGRICA" in line:
                ws_agrica.append([timestamp, dt_str, line])
            else:
                ws_other.append([timestamp, dt_str, line])
        
        try:
            wb.save(file_path)
        except Exception as e:
            logger.error(f"Error saving raw GNSS excel: {e}")

    def _append_adjustment_to_excel(self, project_id: int, timestamp: int, data: dict, raw_payload: str):
        """Append a human-readable XYZ adjustment report to the project workbook."""
        import datetime
        import os

        import openpyxl
        from openpyxl.styles import Font, PatternFill

        file_dir = os.path.join(os.path.dirname(__file__), "static", "adjustments")
        os.makedirs(file_dir, exist_ok=True)
        # One immutable workbook per project/run.  A shared workbook caused
        # sheets from unrelated projects to be appended to the same file.
        file_path = os.path.join(
            file_dir,
            f"gnss_binh_sai_{project_id}_{timestamp}.xlsx",
        )
        try:
            wb = openpyxl.load_workbook(file_path) if os.path.exists(file_path) else openpyxl.Workbook()
        except Exception:
            wb = openpyxl.Workbook()
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])

        dt_obj = datetime.datetime.fromtimestamp(timestamp)
        sheet_name = f"Lan {len(wb.sheetnames) + 1} ({dt_obj:%H-%M-%S})"[:31]
        ws = wb.create_sheet(title=sheet_name)

        def section(title):
            ws.append([])
            ws.append([title])
            cell = ws.cell(ws.max_row, 1)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")

        def header(values):
            ws.append(values)
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="D9EAF7")

        def vector_row(prefix, *values):
            row = list(prefix)
            for value in values:
                row.extend(value) if isinstance(value, (list, tuple)) else row.append(value)
            ws.append(row)

        def relative_precision_text(loop, prefix):
            closure = loop.get(f"{prefix}_closure")
            if closure is not None and abs(float(closure)) < 1e-9:
                return "Khép kín"
            ratio = loop.get(f"{prefix}_relative_precision")
            return f"1/{ratio:.0f}" if ratio else "Không xác định"

        ws.append(["BÁO CÁO BÌNH SAI MẠNG GNSS (HỆ TỌA ĐỘ ECEF XYZ)"])
        ws.cell(1, 1).font = Font(bold=True, size=14)
        ws.append(["Mã dự án", project_id])
        ws.append(["Thời gian bình sai", dt_obj.strftime("%Y-%m-%d %H:%M:%S")])
        ws.append(["Số lượng Rover", data.get("rover_count", 0)])
        ws.append(["Động cơ bình sai", data.get("adjustment_engine", "")])

        baselines = data.get("baselines", [])
        loops = data.get("loops", [])
        section("BẢNG 1: BASELINE TRUNG BÌNH THEO CẶP ĐIỂM")
        header(["STT", "Từ điểm", "Đến điểm", "dX (m)", "dY (m)", "dZ (m)",
                "Std_X TB (m)", "Std_Y TB (m)", "Std_Z TB (m)", "Chiều dài TB (m)",
                "Std vận tốc Up TB (m/s)", "Số trị đo"])
        for index, baseline in enumerate(baselines, 1):
            vector_row([index, baseline.get("from"), baseline.get("to")],
                       baseline.get("observed_xyz") or baseline.get("observed_neu") or (0, 0, 0),
                       baseline.get("standard_deviation_xyz") or (None, None, None),
                       baseline.get("observed_length"), baseline.get("velocity_up_std"),
                       baseline.get("observation_count", 1))

        section("BẢNG 2: VÒNG KHÉP TỪ BASELINE TRUNG BÌNH")
        header(["Vòng", "Các điểm", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
                "Tổng chiều dài (m)", "Độ chính xác tương đối"])
        for loop in loops:
            vector_row([loop.get("loop"), " - ".join(loop.get("points", []))],
                       loop.get("observed_misclosure_xyz") or (0, 0, 0),
                       loop.get("observed_closure"), loop.get("total_length"),
                       relative_precision_text(loop, "observed"))

        section("BẢNG 3: BASELINE TRUNG BÌNH SAU BÌNH SAI")
        header(["STT", "Từ điểm", "Đến điểm", "vX (m)", "vY (m)", "vZ (m)",
                "dX_Adjusted (m)", "dY_Adjusted (m)", "dZ_Adjusted (m)", "Chiều dài (m)",
                "Số trị đo"])
        for index, baseline in enumerate(baselines, 1):
            vector_row([index, baseline.get("from"), baseline.get("to")],
                       baseline.get("residual_xyz") or baseline.get("residual_neu") or (0, 0, 0),
                       baseline.get("adjusted_xyz") or baseline.get("adjusted_neu") or (0, 0, 0),
                       baseline.get("adjusted_length"), baseline.get("observation_count", 1))

        section("BẢNG 4: VÒNG KHÉP SAU BÌNH SAI (ADJUSTED LOOPS)")
        ws.append(["Ghi chú", "Khép bằng 0 là hệ quả của mô hình bình sai, không phải kiểm tra độc lập dữ liệu gốc."])
        header(["Vòng", "Các điểm", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
                "Tổng chiều dài (m)", "Độ chính xác tương đối"])
        for loop in loops:
            vector_row([loop.get("loop"), " - ".join(loop.get("points", []))],
                       loop.get("adjusted_misclosure_xyz") or (0, 0, 0),
                       loop.get("adjusted_closure"), loop.get("total_length"),
                       relative_precision_text(loop, "adjusted"))

        section("BẢNG 5: ĐIỂM KHỐNG CHẾ (CONTROL POINT)")
        header(["Tên điểm", "X (m)", "Y (m)", "Z (m)", "Cố định"])
        base = data.get("base", {})
        base_name = base.get("name") or "BASE"
        base_label = base_name if base_name == "BASE" else f"{base_name} (alias: BASE)"
        vector_row([base_label], base.get("ecef_xyz") or (None, None, None),
                   bool(base.get("fixed", True)))

        section("BẢNG 6: TỌA ĐỘ ĐIỂM SAU BÌNH SAI (ADJUSTED POINTS)")
        header(["Tên Điểm", "Trạm ID", "X_Adjusted (m)", "Y_Adjusted (m)", "Z_Adjusted (m)",
                "dX: Adjusted - baseline mean from control (m)",
                "dY: Adjusted - baseline mean from control (m)",
                "dZ: Adjusted - baseline mean from control (m)",
                "Std_X ECEF tiên nghiệm (m)", "Std_Y ECEF tiên nghiệm (m)",
                "Std_Z ECEF tiên nghiệm (m)", "Std_E ENU tiên nghiệm (m)",
                "Std_N ENU tiên nghiệm (m)", "Std_U ENU tiên nghiệm (m)",
                "X_Raw TB hợp lệ (m)", "Y_Raw TB hợp lệ (m)",
                "Z_Raw TB hợp lệ (m)", "Số Raw dùng", "Số Raw bị loại"])
        for point_name, point in data.get("points", {}).items():
            raw = point.get("raw_rover_ecef") or (None, None, None)
            std_enu = point.get("standard_deviation_enu") or (None, None, None)
            ws.append([point_name, point.get("station_id"),
                       point.get("adjusted_x", point.get("adjusted_n")),
                       point.get("adjusted_y", point.get("adjusted_e")),
                       point.get("adjusted_z", point.get("adjusted_u")), point.get("dx"),
                       point.get("dy"), point.get("dz"), point.get("std_x"),
                       point.get("std_y"), point.get("std_z"), std_enu[0], std_enu[1],
                       std_enu[2], raw[0], raw[1], raw[2],
                       point.get("raw_rover_ecef_observation_count"),
                       point.get("raw_rover_ecef_rejected_count", 0)])

        section("BẢNG 7: CHỈ TIÊU CHẤT LƯỢNG")
        header(["Chỉ tiêu", "Giá trị"])
        quality = data.get("quality", {})
        for label, key in (("Số baseline quan sát dùng bình sai", "observation_baseline_count"),
                           ("Số baseline trung bình hiển thị", "averaged_baseline_count"),
                           ("Số phiên quan sát liên tục", "observation_session_count"),
                           ("Số baseline có STD vượt ngưỡng cảnh báo", "baseline_std_warning_count"),
                           ("Số ECEF rover không nhất quán với baseline", "raw_ecef_inconsistent_count"),
                           ("Bậc tự do", "degrees_of_freedom"),
                           ("Hệ số phương sai", "variance_factor"),
                           ("M0 hậu nghiệm (không dùng thu nhỏ STD công bố)", "reference_standard_deviation"),
                           ("Tổng bình phương số dư có trọng số", "weighted_residual_sum"),
                           ("Rank", "rank"), ("Condition number", "condition_number"),
                           ("Số dư chuẩn hóa tiên nghiệm lớn nhất", "max_standardized_residual")):
            ws.append([label, quality.get(key)])
        if quality.get("global_test"):
            global_test = quality["global_test"]
            ws.append(["Kiểm định phương sai tổng thể", "Đạt" if global_test.get("passed") else "Không đạt"])
            ws.append(["Chi-square statistic", global_test.get("statistic")])
            ws.append(["Chi-square lower critical", global_test.get("lower_critical_value")])
            ws.append(["Chi-square upper critical", global_test.get("upper_critical_value")])
            ws.append(["Chi-square p-value", global_test.get("p_value")])
            if not global_test.get("passed"):
                ws.append(["Cảnh báo", "Mô hình phương sai bị bác bỏ; không công bố STD hậu nghiệm đã thu nhỏ"])
        trusted_subset = quality.get("trusted_subset") or {}
        if trusted_subset:
            ws.append(["Trusted subset: số baseline đạt ngưỡng STD", trusted_subset.get("observation_baseline_count")])
            ws.append(["Trusted subset: bậc tự do", trusted_subset.get("degrees_of_freedom")])
            ws.append(["Trusted subset: vTPv", trusted_subset.get("weighted_residual_sum")])
            ws.append(["Trusted subset: M0", trusted_subset.get("reference_standard_deviation")])
            trusted_test = trusted_subset.get("global_test") or {}
            if trusted_test:
                ws.append(["Trusted subset: kiểm định phương sai", "Đạt" if trusted_test.get("passed") else "Không đạt"])
                ws.append(["Trusted subset: chi-square lower", trusted_test.get("lower_critical_value")])
                ws.append(["Trusted subset: chi-square upper", trusted_test.get("upper_critical_value")])
                ws.append(["Trusted subset: p-value", trusted_test.get("p_value")])
        ws.append(["Scale STD điểm công bố", quality.get("published_point_std_scale", "a_priori")])
        ws.append(["Scale số dư chuẩn hóa", quality.get("normalized_residual_scale", "a_priori")])
        ws.append(["Mô hình covariance baseline", quality.get("baseline_covariance_model")])
        ws.append(["Ngưỡng cảnh báo STD baseline (m)", quality.get("baseline_std_warning_threshold_m")])
        ws.append(["Dung sai nhất quán ECEF rover/baseline (m)", quality.get("raw_ecef_consistency_tolerance_m")])
        ws.append(["Ngưỡng tách phiên liên tục (s)", quality.get("observation_session_gap_seconds")])
        ws.append(["Đã lập block covariance ECEF 3x3 sau phép quay", bool(quality.get("full_covariance_available"))])
        ws.append(["AGRICA có covariance chéo gốc NE/EU/NU", bool(quality.get("source_cross_covariance_available"))])
        ws.append(["Đã chứng minh trị đo lặp độc lập", bool(quality.get("repeated_observations_independence_verified"))])
        ws.append(["Đã cộng sai số điểm khống chế", bool(quality.get("control_point_uncertainty_included"))])
        if not quality.get("repeated_observations_independence_verified"):
            ws.append(["Cảnh báo", "Bậc tự do và kiểm định chi-square đang giả định các baseline quan sát độc lập."])
        if not quality.get("control_point_uncertainty_included"):
            ws.append(["Cảnh báo", "STD điểm chỉ là độ chính xác tương đối so với BASE cố định."])
        if quality.get("baseline_std_warning_count"):
            ws.append(["Cảnh báo", (
                "Baseline vượt ngưỡng STD vẫn được giữ trong solver với covariance gốc; "
                "trọng số của chúng tự giảm và cờ chi tiết nằm ở Bảng 8."
            )])
        if quality.get("raw_ecef_inconsistent_count"):
            ws.append(["Cảnh báo", (
                "ECEF rover không nhất quán đã bị loại khỏi Raw TB, nhưng vector baseline "
                "vẫn được giữ để bình sai nếu đạt các điều kiện chất lượng khác."
            )])

        section("BẢNG 8: RAW PAYLOAD BẰNG CHỨNG")
        evidence = data.get("baseline_observations") or []
        if evidence:
            header(["STT", "Từ điểm", "Đến điểm", "Session", "Epoch",
                    "Position type", "GPS", "BDS", "GLONASS", "GAL", "Diff age (s)",
                    "Baseline_NStd (m)",
                    "Baseline_EStd (m)", "Baseline_UStd (m)", "Std vận tốc Up (m/s)",
                    "Xigema_ECEF_X rover (không dùng trọng số)",
                    "Xigema_ECEF_Y rover (không dùng trọng số)",
                    "Xigema_ECEF_Z rover (không dùng trọng số)",
                    "Sai lệch ECEF rover/baseline (m)", "Cờ chất lượng", "vX (m)",
                    "vY (m)", "vZ (m)", "Max |normalized residual|", "Raw AGRICA"])
            for index, observation in enumerate(evidence, 1):
                residual = observation.get("residual_xyz") or (None, None, None)
                normalized = observation.get("standardized_residual") or ()
                max_normalized = max((abs(float(value)) for value in normalized), default=None)
                baseline_std = observation.get("baseline_std_neu") or (None, None, None)
                rover_position_std = observation.get("rover_position_std_ecef") or (None, None, None)
                ws.append([index, observation.get("from"), observation.get("to"),
                           observation.get("session_id"), observation.get("observation_epoch"),
                           observation.get("position_type"), observation.get("gps_satellites"),
                           observation.get("bds_satellites"), observation.get("glonass_satellites"),
                           observation.get("galileo_satellites"), observation.get("diff_age"),
                           baseline_std[0], baseline_std[1], baseline_std[2],
                           observation.get("velocity_up_std"),
                           rover_position_std[0], rover_position_std[1], rover_position_std[2],
                           observation.get("raw_ecef_consistency_error_m"),
                           ", ".join(observation.get("quality_flags") or []),
                           residual[0], residual[1], residual[2],
                           max_normalized, observation.get("raw_payload")])
        else:
            for line in raw_payload.splitlines():
                ws.append([line])
            if not raw_payload.strip():
                ws.append(["Không có raw payload trong kết quả đầu vào"])

        sessions = quality.get("observation_sessions") or []
        section("BẢNG 9: NHÓM PHIÊN QUAN SÁT LIÊN TỤC")
        ws.append(["Ghi chú", (
            "Nhóm phiên chỉ mô tả tương quan thời gian; solver vẫn giữ từng epoch và "
            "không coi số phiên là bậc tự do hiệu dụng."
        )])
        header(["Session", "Từ điểm", "Đến điểm", "Epoch đầu", "Epoch cuối", "Số observation"])
        for session in sessions:
            ws.append([
                session.get("session_id"), session.get("from"), session.get("to"),
                session.get("start_epoch"), session.get("end_epoch"),
                session.get("observation_count"),
            ])
        ws.freeze_panes = "A2"
        for column in ws.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 42)
            ws.column_dimensions[column[0].column_letter].width = max(width, 12)
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000"
        try:
            wb.save(file_path)
        except Exception as exc:
            logger.error("Error saving adjustment Excel %s: %s", file_path, exc, exc_info=True)
            raise
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            raise OSError(f"Adjustment Excel was not created correctly: {file_path}")
        logger.info("GNSS adjustment Excel written: %s (%s bytes)", file_path, os.path.getsize(file_path))
        return file_path

    def _write_adjustment_reports(self, project_id: int, timestamp: int, data: dict) -> dict:
        """Write the report files referenced by the GNSS adjustment interface."""
        import os

        report_dir = os.path.join(os.path.dirname(__file__), "static", "adjustments")
        os.makedirs(report_dir, exist_ok=True)
        report_name = f"gnss_adjustment_{project_id}_{timestamp}.json"
        report_path = os.path.join(report_dir, report_name)
        try:
            with open(report_path, "w", encoding="utf-8") as report_file:
                json.dump(data, report_file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Error saving GNSS adjustment JSON %s: %s", report_path, exc, exc_info=True)
            raise
        if not os.path.isfile(report_path) or os.path.getsize(report_path) == 0:
            raise OSError(f"Adjustment JSON was not created correctly: {report_path}")
        logger.info("GNSS adjustment JSON written: %s (%s bytes)", report_path, os.path.getsize(report_path))

        excel_path = self._append_adjustment_to_excel(project_id, timestamp, data, "")
        if not excel_path:
            raise OSError("Adjustment Excel exporter did not return an output path")
        return {
            "report_file_url": f"/static/adjustments/{report_name}",
            "excel_report_url": f"/static/adjustments/{os.path.basename(excel_path)}",
        }

    async def _handle_round_robin_adjustment_result(self, project_id: int, adjustment: dict):
        """Persist and publish one completed, connected GNSS network adjustment."""
        current_timestamp = int(time.time())
        try:
            report_urls = self._write_adjustment_reports(project_id, current_timestamp, adjustment)
        except Exception as exc:
            message = f"Bình sai đã tính xong nhưng không thể xuất JSON/XLSX: {exc}"
            logger.error("Project %s: %s", project_id, message, exc_info=True)
            await self._handle_round_robin_adjustment_error(project_id, message)
            return
        adjustment.update(report_urls)
        self.adjustment_phase[project_id] = "COMPLETED"

        for point in adjustment.get("points", {}).values():
            station_id = point.get("station_id")
            if not station_id:
                continue
            payload = {
                "station_id": station_id,
                "timestamp": current_timestamp,
                "sensor_type": "gnss_adjusted",
                "data": adjustment,
                "value_1": None,
                "value_2": None,
                "value_3": None,
                "value_4": None,
                "value_5": None,
            }
            async with self._buffer_lock:
                self._sensor_buffer.append(payload)
            try:
                await self._upsert_latest_sensor_cache(
                    station_id,
                    "gnss_adjusted",
                    current_timestamp,
                    adjustment,
                )
                await manager.broadcast({
                    "type": "sensor_status",
                    "station_id": station_id,
                    "sensor_type": "gnss_adjusted",
                    "timestamp": current_timestamp,
                    "data": adjustment,
                })
            except Exception as exc:
                logger.error("Could not publish GNSS adjustment for station %s: %s", station_id, exc)

        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": project_id,
            "phase": "COMPLETED",
            "message": "Connected GNSS network adjustment completed.",
            "timestamp": current_timestamp,
            # The UI may not currently be viewing one of the adjusted stations,
            # so publish the downloadable result on the project-level event too.
            "data": adjustment,
        })

    async def _handle_round_robin_adjustment_error(self, project_id: int, message: str):
        self.adjustment_phase[project_id] = "ERROR"
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": project_id,
            "phase": "ERROR",
            "message": message,
        })

    async def _handle_round_robin_progress(self, project_id: int, message: str):
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": project_id,
            "phase": "FREE_NETWORK",
            "message": message,
        })

    async def process_pipeline(self, info: dict, raw_payload: str):
        if not info: return
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

        # Always refresh liveness on every message; do not depend on save interval.
        await self._touch_online_heartbeat(device_id, station_id, current_timestamp)
        
        # 1. PROCESS DATA
        try:
            if sensor_type == 'gnss':
                # AGRICA may arrive as multiple MQTT payloads.  Once a station
                # has sent the #AGRICA prefix, keep feeding its subsequent
                # fragments even though those fragments do not repeat the prefix.
                proj_id = int(info.get("project_id") or info.get("station_id") or 0)
                phase = self.adjustment_phase.get(proj_id)
                has_pending_agrica = self.round_robin_manager.has_pending_agrica_fragment(
                    proj_id,
                    station_id,
                )
                if "#AGRICA" in raw_payload or has_pending_agrica:
                    # AGRICA is collected only while an operator has started an
                    # adjustment session.  A single BASE->Rover observation is
                    # not a completed network adjustment.
                    valid_obs = []
                    if phase in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
                        valid_obs = self.round_robin_manager.add_agrica_payload(raw_payload, info)
                        seed_status = None
                        if phase == "COLLECTING_BASELINE":
                            seed_status = self.round_robin_manager.get_seed_collection_status(proj_id)
                            if seed_status["fallback_ready"]:
                                seed_status = self.round_robin_manager.skip_missing_seed_stations(proj_id)
                        diagnostic = self.round_robin_manager.get_last_ingest_diagnostic(proj_id)
                        if diagnostic:
                            if seed_status and seed_status["missing_station_ids"]:
                                diagnostic = {
                                    **diagnostic,
                                    "message": (
                                        f"{diagnostic['message']} "
                                        f"Seed step {seed_status['step_count']}/{seed_status['max_steps']}; "
                                        f"waiting for station IDs {seed_status['missing_station_ids']}."
                                    ),
                                }
                            diagnostic_message = str(diagnostic.get("message") or "")
                            is_fragment_update = diagnostic_message.startswith("Buffered AGRICA fragment")
                            should_broadcast_diagnostic = (
                                not is_fragment_update
                                or self._diag_should_log(
                                    f"gnss_adjustment_fragment:{proj_id}:{station_id}",
                                    2,
                                )
                            )
                            if should_broadcast_diagnostic:
                                await manager.broadcast({
                                    "type": "gnss_adjustment_debug",
                                    "project_id": proj_id,
                                    **diagnostic,
                                })
                        for obs in valid_obs:
                            try:
                                baseline_from = self.round_robin_manager.get_active_base_for_station(
                                    proj_id,
                                    station_id,
                                )
                                await manager.broadcast({
                                    "type": "gnss_baseline_collected",
                                    "project_id": proj_id,
                                    "station_id": station_id,
                                    "from": baseline_from,
                                    "rover_name": obs.rover_name,
                                    "baseline_neu": obs.baseline_neu,
                                    "std_neu": obs.std_neu,
                                    "rover_llh": obs.rover_llh,
                                    "base_llh": obs.base_llh,
                                    "full_data": obs.full_data,
                                })
                            except Exception as exc:
                                logger.error("Could not broadcast GNSS baseline: %s", exc)

                        if (
                            phase == "COLLECTING_BASELINE"
                            and self.round_robin_manager.has_complete_seed_observations(proj_id)
                        ):
                            skipped_station_ids = (seed_status or {}).get("skipped_station_ids", [])
                            self.adjustment_phase[proj_id] = "FREE_NETWORK"
                            await manager.broadcast({
                                "type": "gnss_adjustment_progress",
                                "project_id": proj_id,
                                "phase": "FREE_NETWORK",
                                "message": (
                                    "Skipped offline/no-data station IDs "
                                    f"{skipped_station_ids} after {self.round_robin_manager.SEED_COLLECTION_MAX_STEPS} seed steps. "
                                    "Starting Round-Robin with the remaining rovers."
                                    if skipped_station_ids
                                    else "All selected rovers have a fixed-base baseline. Starting Round-Robin."
                                ),
                            })
                            for cluster in info.get("project_gnss_clusters") or []:
                                if not isinstance(cluster, dict):
                                    continue
                                base_mountpoint = (
                                    cluster.get("base_stream_mp")
                                    or cluster.get("base_stream")
                                    or cluster.get("base_station")
                                )
                                if base_mountpoint:
                                    self.client.publish(
                                        "command/ntrip/route/stop",
                                        json.dumps({"station_code": base_mountpoint}),
                                    )
                            await self.round_robin_manager.start_cycle(proj_id)

                # Only process for GNSS position/status if payload actually contains GGA.
                # This prevents pure AGRICA sentences from triggering fake NO_DATA statuses
                # which causes the UI to rapidly blink between FIXED and NO_DATA.
                import re
                if re.search(r'\$G[NP]GGA,', raw_payload):
                    res = processor.process_gngga(raw_payload, station_config)
                    if res and res.get('type') == 'gnss_processed':
                        processed_data = res.get('data')
                        
                        # Cập nhật LLH cache cho RoundRobin
                        station_code = info.get("station_code")
                        lat = processed_data.get('latitude')
                        lon = processed_data.get('longitude')
                        alt = processed_data.get('altitude', 0.0)
                        if lat is not None and lon is not None:
                            self.round_robin_manager.update_rover_llh(station_code, lat, lon, alt)
                    elif res and res.get('type') == 'gnss_status':
                        status_payload = {
                            "status": res.get('status'),
                            "sub_status": res.get('sub_status'),
                            "fix_quality": res.get('fix_quality'),
                            "fix_mode": res.get('fix_mode'),
                            "message": res.get('message'),
                            "raw_payload": res.get('raw_payload', '')
                        }
                        
                        if res.get('status') == 'INVALID_DATA':
                            # Immediate buffering for anomalies
                            anomaly_record = {
                                "station_id": station_id,
                                "timestamp": current_timestamp,
                                "sensor_type": "gnss_anomaly",
                                "data": status_payload,
                                "value_1": None, "value_2": None, "value_3": None, "value_4": None, "value_5": None
                            }
                            async with self._buffer_lock:
                                self._sensor_buffer.append(anomaly_record)
                                
                        try:
                            await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, status_payload)
                        except Exception: pass
                        try:
                            await manager.broadcast({
                                "type": "sensor_status",
                                "station_id": station_id,
                                "sensor_type": "gnss",
                                "timestamp": current_timestamp,
                                "data": status_payload
                            })
                        except Exception as ws_e:
                            logger.error(f"❌ WS GNSS status error: {ws_e}")
                        return
                    elif res and res.get('type') == 'origin_locked':
                        logger.info(f"🎯 [{station_name}] GNSS Origin locked")
                        try:
                            await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, res.get('data', {}))
                        except Exception: pass
                        return
                    elif res and res.get('type') == 'origin_status':
                        status_payload = {
                            "status": res.get('status'),
                            "fix_quality": res.get('fix_quality'),
                            "fix_mode": res.get('fix_mode'),
                            "message": res.get('message')
                        }
                        try:
                            await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, status_payload)
                        except Exception: pass
                        try:
                            await manager.broadcast({
                                "type": "sensor_status",
                                "station_id": station_id,
                                "sensor_type": "gnss",
                                "timestamp": current_timestamp,
                                "data": status_payload
                            })
                        except Exception as ws_e:
                            logger.error(f"❌ WS GNSS origin status error: {ws_e}")
                        return
            else:
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
            return

        if not processed_data: return

        # ---------------------------------------------------------
        # ✅ REALTIME BROADCAST 1: SENSOR DATA (Số liệu)
        # Gửi ngay lập tức, không chờ DB
        # ---------------------------------------------------------
        try:
            await manager.broadcast({
                "type": "sensor_data",
                "station_id": station_id,
                "sensor_type": sensor_type,
                "timestamp": current_timestamp,
                "data": processed_data
            })
        except Exception as e:
            logger.error(f"❌ WS Sensor Error: {e}")

        # ✅ [NEW] GNSS RTK FORWARDING (1Hz)
        if sensor_type == 'gnss' and processed_data.get('forwarding_data'):
            fwd_cfg = info.get('forwarding', {})
            if fwd_cfg.get('enabled') and fwd_cfg.get('rtk_topic'):
                try:
                    target_topic = fwd_cfg['rtk_topic']
                    # Check for external broker config
                    fwd_host = fwd_cfg.get('host')
                    fwd_port = fwd_cfg.get('port', 1883)
                    fwd_user = fwd_cfg.get('username')
                    fwd_pass = fwd_cfg.get('password')

                    # Take the full payload as structured in gnss_processor.py
                    payload = processed_data['forwarding_data']
                    fields_cfg = fwd_cfg.get('fields', {})
                    
                    if fields_cfg and 'data' in payload:
                        # Map UI toggle names to JSON keys
                        # Format: { 'UI_KEY': ['JSON_KEY1', 'JSON_KEY2', ...] }
                        mapping = {
                            'X':   ['adv_x'],
                            'Y':   ['adv_y'],
                            'H':   ['adv_h', 'h', 'lat', 'lon'], # Lat/Lon/H usually grouped
                            'dX':  ['adv_dx', 'pos_e'],
                            'dY':  ['adv_dy', 'pos_n'],
                            'dH':  ['adv_dh', 'pos_u'],
                            'VdX': ['adv_vdx'],
                            'VdY': ['adv_vdy'],
                            'VdH': ['adv_vdh']
                        }
                        
                        # Filter the 'data' part of the nested payload
                        data_part = payload['data']
                        for ui_key, is_enabled in fields_cfg.items():
                            if not is_enabled and ui_key in mapping:
                                for json_key in mapping[ui_key]:
                                    if json_key in data_part:
                                        del data_part[json_key]
                    
                    # Decice which client to use
                    if fwd_host:
                        pub_client = self._get_fwd_client(fwd_host, int(fwd_port), fwd_user, fwd_pass)
                        if pub_client:
                            pub_client.publish(target_topic, json.dumps(payload))
                            logger.debug(f"🌐 [FORWARD-EXT] Published 1Hz data to {fwd_host}:{fwd_port} -> {target_topic}")
                        else:
                            logger.warning(f"⚠️ [FORWARD-EXT] Skipping publish: External broker {fwd_host} unavailable")
                    else:
                        # Default to local broker
                        self._get_client_for_station(station_id).publish(target_topic, json.dumps(payload))
                        logger.debug(f"📤 [FORWARD-LOCAL] Published 1Hz data to {target_topic}")
                except Exception as ex:
                    logger.error(f"❌ [FORWARD] Error publishing: {ex}")

        # ✅ Upsert latest_sensor_cache — luôn lưu giá trị mới nhất bất kể chu kỳ save
        try:
            await self._upsert_latest_sensor_cache(station_id, sensor_type, current_timestamp, processed_data)
        except Exception as e:
            logger.error(f"❌ LatestSensorCache upsert error: {e}")

        alerting_enabled = self._is_station_alerting_enabled(station_config)

        # 2. ANALYZE
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

        # ---------------------------------------------------------
        # ✅ REALTIME BROADCAST 2: STATION STATUS (Màu sắc)
        # Gửi ngay lập tức sau khi phân tích xong
        # ---------------------------------------------------------
        is_dangerous = False
        is_just_resolved = False
        is_pending = False
        if alert and str(alert.get('level', '')).upper() in self.DANGEROUS_ALERT_LEVELS:
            is_dangerous = True
        elif alert and alert.get('level') == 'PENDING':
            is_pending = True

        # IMU policy: dangerous IMU alerts are always CRITICAL (no WARNING in UI)
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
                        res = await db_data.execute(
                            model_data.Alert.__table__.update()
                            .where(and_(
                                model_data.Alert.station_id == station_id,
                                model_data.Alert.is_resolved == False,
                                model_data.Alert.category.in_(categories_to_resolve)
                            ))
                            .values(is_resolved=True)
                        )
                        if res.rowcount > 0:
                            await db_data.commit()
                            is_just_resolved = True
                            summary = await self._get_station_active_alert_summary(station_id, station_config)
                            unresolved_count = summary.get('unresolved_count', 0)
                            if unresolved_count == 0:
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

        # 3. SAVE TO DB (THROTTLED)
        # ✅ CHỈ LƯU KHI: Alert xảy ra HOẶC vừa resolve alert HOẶC đã đủ chu kỳ lưu
        save_data_now = False

        if is_dangerous:
            # ✅ ALERT → Lưu ngay lập tức / không quan tâm chu kỳ
            save_data_now = True
            logger.warning(f"⚠️ [FORCED SAVE] Alert detected - saving immediately")
        elif is_just_resolved:
            # ✅ VỪA RESOLVE ALERT → Lưu ngay để DB có dữ liệu an toàn mới nhất
            save_data_now = True
            logger.info(f"💾 [RESOLVE SAVE] Alert just resolved - saving safe data for station {station_id}")
        else:
            # ✅ KIỂM TRA CHU KỲ LƯU
            throttle_key_station = f"{station_id}_{sensor_type}"
            last_saved = self.last_save_time[station_id].get(sensor_type, 0)
            
            interval = self.runtime_save_intervals.get('default', settings.SAVE_INTERVAL_DEFAULT)
            if sensor_type == 'gnss':
                try:
                    interval = int(station_config.get("gnss_save_interval", self.runtime_save_intervals.get('gnss', settings.SAVE_INTERVAL_GNSS)))
                except (ValueError, TypeError):
                    interval = self.runtime_save_intervals.get('gnss', settings.SAVE_INTERVAL_GNSS)
            elif sensor_type == 'imu': interval = self.runtime_save_intervals.get('imu', settings.SAVE_INTERVAL_IMU)
            elif sensor_type == 'rain': interval = self.runtime_save_intervals.get('rain', settings.SAVE_INTERVAL_RAIN)
            elif sensor_type == 'water': interval = self.runtime_save_intervals.get('water', settings.SAVE_INTERVAL_WATER)
            
            time_since_last_save = current_timestamp - last_saved
            
            if last_saved == 0:
                # Lần đầu tiên → Lưu luôn
                save_data_now = True
                logger.info(f"💾 [FIRST SAVE] {station_name} - {sensor_type.upper()}")
            elif sensor_type == 'gnss':
                # GNSS: Logic lưu điểm đầu tiên của ngày (bao hàm cả điểm đầu tuần, tháng, năm)
                from datetime import datetime
                last_dt = datetime.fromtimestamp(last_saved)
                curr_dt = datetime.fromtimestamp(current_timestamp)
                
                if curr_dt.date() > last_dt.date():
                    save_data_now = True
                    logger.info(f"💾 [CALENDAR START DAY SAVE - GNSS] {station_name} ({curr_dt.date()})")
                elif interval < 86400 and time_since_last_save >= interval:
                    # Nếu Admin cố tình set sys-save-gnss nhỏ hơn 1 ngày (vd: 1 tiếng) thì vẫn tuân thủ
                    save_data_now = True
                    logger.info(f"💾 [PERIODIC SAVE - GNSS] {station_name} (Interval: {interval}s)")
            elif time_since_last_save >= interval:
                # Đã đủ chu kỳ → Lưu (Dành cho IMU, Rain, Water)
                save_data_now = True
                logger.info(f"💾 [PERIODIC SAVE] {station_name} - {sensor_type.upper()} (Interval: {interval}s)")
            else:
                # Chưa đủ chu kỳ → Skip
                logger.debug(f"⏭️ [SKIP SAVE] {station_name} - {sensor_type.upper()} ({time_since_last_save}/{interval}s)")

        # ✅ Thêm option chỉ lưu GNSS khi fix (fix_quality >= 4)
        if save_data_now and sensor_type == 'gnss':
            # Option gnss_save_only_fix trong station_config (mặc định False để tương thích ngược, có thể set True để bật)
            only_save_fix = station_config.get("gnss_save_only_fix", False)
            if only_save_fix and processed_data and processed_data.get('fix_quality', 0) < 4:
                save_data_now = False
                logger.info(f"⏭️ [SKIP SAVE] {station_name} - GNSS (Not fixed, quality={processed_data.get('fix_quality')})")

        try:
            if save_data_now:
                if sensor_type == 'gnss':
                    try:
                        self._append_raw_gnss_to_excel(station_id, current_timestamp, raw_payload)
                    except Exception as e:
                        logger.error(f"❌ Lỗi ghi file raw GNSS Excel: {e}")
                if is_dangerous:
                    sensor_record = {
                        "station_id": station_id,
                        "timestamp": current_timestamp,
                        "sensor_type": sensor_type,
                        "data": processed_data,
                        "value_1": processed_data.get('speed_2d_mm_s', 0.0) if sensor_type == 'gnss' else processed_data.get('intensity_mm_h', 0.0) if sensor_type == 'rain' else processed_data.get('water_level', 0.0) if sensor_type == 'water' else processed_data.get('roll', 0.0),
                        "value_2": processed_data.get('total_displacement_mm', 0.0) if sensor_type == 'gnss' else processed_data.get('accumulated_mm', 0.0) if sensor_type == 'rain' else processed_data.get('intensity_mm_h', 0.0) if sensor_type == 'water' else processed_data.get('pitch', 0.0),
                        "value_3": 0.0 if sensor_type != 'imu' else processed_data.get('yaw', 0.0),
                        "value_4": 0.0 if sensor_type != 'imu' else processed_data.get('total_accel', 0.0),
                        "value_5": 0.0 if sensor_type != 'imu' else processed_data.get('battery', 0.0),
                    }
                    self.last_save_time[station_id][sensor_type] = current_timestamp
                    # ✅ ALERT → Ghi thẳng xuống DB, không qua buffer
                    await self._save_alert_immediate(device_id, station_id, sensor_record, alert, current_timestamp)
                elif is_just_resolved:
                    # ✅ RESOLVE → Buffer rồi flush ngay, tránh mất dữ liệu khi server restart
                    await self._buffer_sensor_record(device_id, station_id, sensor_type, current_timestamp, processed_data)
                    await self._flush_write_buffer()
                    logger.info(f"💾 [RESOLVE FLUSH] {station_name} - {sensor_type.upper()} ts={current_timestamp} written immediately")
                else:
                    # ✅ BÌNH THƯỜNG → Đưa vào buffer, flush theo chu kỳ
                    await self._buffer_sensor_record(device_id, station_id, sensor_type, current_timestamp, processed_data)

        except Exception as e:
            logger.error(f"❌ DB Error: {e}")
