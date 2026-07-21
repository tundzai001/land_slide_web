# ==============================================================================
# == backend/mqtt_bridge.py - MQTT to Database Bridge (FIXED WITH SAVE INTERVALS) ==
# ==============================================================================

import asyncio
import json
import logging
import math
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
        self.adjustment_message: Dict[int, str] = {}
        self.adjustment_results: Dict[int, dict] = {}
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
            web_cors_api_base_url=settings.WEB_CORS_API_BASE_URL,
            web_cors_api_token=settings.WEB_CORS_API_TOKEN,
            web_cors_api_username=settings.WEB_CORS_API_USERNAME,
            web_cors_api_password=settings.WEB_CORS_API_PASSWORD,
            route_start_callback=self._start_round_robin_ntrip_route,
            route_wait_callback=self._wait_round_robin_ntrip_route,
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
        # Coalesce best-effort latest-value work. Fragmented GNSS/AGRICA can
        # create several pipeline tasks per second for one station; one DB
        # transaction per fragment can exhaust the connection pool.
        self._latest_cache_write_locks = defaultdict(asyncio.Lock)
        self._latest_cache_last_attempt = defaultdict(float)
        self._latest_cache_min_interval_seconds = 0.75
        self._alert_suppression_last_attempt = defaultdict(float)
        self._alert_suppression_interval_seconds = 5.0

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

                if sensor_type == 'gnss':
                    # SET socket data only proves that AICaster echoed the bytes.
                    # Receiver acceptance is reported on this rover's own GNSS
                    # MQTT topic as: exact command echo, then OK/ERROR.
                    self.round_robin_manager.add_receiver_command_payload(
                        decrypted_payload,
                        info,
                        topic,
                    )
                
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
        """Open every SOURCE target and wait for all caster handshakes."""

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

    async def _wait_round_robin_ntrip_route(
        self,
        station_code: str,
        timeout: float = 25.0,
    ) -> None:
        """Require the first valid RTCM frame on every primed mountpoint."""

        from app.modules.ntrip_pusher import ntrip_manager

        try:
            await ntrip_manager.wait_for_rtcm(station_code, timeout=timeout)
        except Exception:
            logger.error(
                "[Round-Robin RTCM] station=%s fanout verification failed diagnostics=%s",
                station_code,
                ntrip_manager.get_diagnostics(station_code),
            )
            raise
        logger.info(
            "[Round-Robin RTCM] station=%s fanout verified diagnostics=%s",
            station_code,
            ntrip_manager.get_diagnostics(station_code),
        )

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
        now = time.monotonic()
        if (
            now - self._alert_suppression_last_attempt[station_id]
            < self._alert_suppression_interval_seconds
        ):
            return
        self._alert_suppression_last_attempt[station_id] = now
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
        cache_key = (int(station_id), str(sensor_type))
        async with self._latest_cache_write_locks[cache_key]:
            now = time.monotonic()
            if (
                now - self._latest_cache_last_attempt[cache_key]
                < self._latest_cache_min_interval_seconds
            ):
                return
            # Mark before awaiting DB. If the pool times out, queued fragments
            # must not retry together as a thundering herd.
            self._latest_cache_last_attempt[cache_key] = now
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
                if self._diag_should_log(
                    f"latest_cache:{station_id}:{sensor_type}", 30
                ):
                    logger.error(
                        "❌ [CACHE] Upsert failed station=%s sensor=%s: %s: %r",
                        station_id,
                        sensor_type,
                        e.__class__.__name__,
                        e,
                    )

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

    def _append_adjustment_audit_to_excel(self, project_id: int, timestamp: int, data: dict, raw_payload: str):
        """Legacy verbose audit workbook retained for backwards reference only."""
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
        for label, key in (("Tổng số raw nhận được", "raw_observation_count"),
                           ("Raw loại do nguồn chưa xác nhận", "unconfirmed_source_excluded_count"),
                           ("Raw loại trong cửa sổ chuyển nguồn/chờ ổn định", "pre_stable_window_excluded_count"),
                           ("Raw loại do cửa sổ ổn định chưa đủ", "insufficient_stable_window_excluded_count"),
                           ("Raw loại do drift quay lại", "unstable_solver_window_excluded_count"),
                           ("Số raw bị loại", "raw_rejected_count"),
                           ("Số raw bị loại do vector nhảy nghiệm", "vector_outlier_count"),
                           ("Số baseline quan sát dùng bình sai", "observation_baseline_count"),
                           ("Số baseline trung bình hiển thị", "averaged_baseline_count"),
                           ("Số phiên quan sát liên tục", "observation_session_count"),
                           ("Số baseline có STD vượt ngưỡng cảnh báo", "baseline_std_warning_count"),
                           ("Tổng raw vượt ngưỡng STD", "baseline_std_raw_warning_count"),
                           ("Số raw bị loại do STD", "baseline_std_rejected_count"),
                           ("Số raw Type 7 bị loại", "position_type_rejected_count"),
                           ("Số ECEF rover không nhất quán với baseline", "raw_ecef_inconsistent_count"),
                           ("Số ECEF rover lệch thuần phương đứng do hệ cao", "raw_ecef_vertical_datum_offset_count"),
                           ("Số cạnh trộn nhiều position type", "mixed_position_type_edge_count"),
                           ("Bậc tự do", "degrees_of_freedom"),
                           ("Hệ số phương sai", "variance_factor"),
                           ("M0 hậu nghiệm (không dùng thu nhỏ STD công bố)", "reference_standard_deviation"),
                           ("Tổng bình phương số dư có trọng số", "weighted_residual_sum"),
                           ("Rank", "rank"), ("Condition number", "condition_number"),
                           ("Số dư chuẩn hóa tiên nghiệm lớn nhất", "max_standardized_residual")):
            ws.append([label, quality.get(key)])
        quality_gate = data.get("quality_gate") or {}
        ws.append(["Quality gate", quality_gate.get("status")])
        ws.append([
            "Quality interpretation",
            quality_gate.get("interpretation_status") or quality_gate.get("status"),
        ])
        for warning in quality_gate.get("diagnostic_warnings") or []:
            ws.append([
                f"Diagnostic warning: {warning.get('code') or 'WARNING'}",
                warning.get("message"),
            ])
        ws.append(["Vòng khép trước bình sai lớn nhất (m, chỉ chẩn đoán)", quality_gate.get("max_pre_adjustment_loop_closure_m")])
        ws.append(["Cho phép publish tọa độ chính thức", bool(data.get("official_publish_allowed"))])
        if quality.get("global_test"):
            global_test = quality["global_test"]
            ws.append(["Kiểm định chất lượng mạng (phía trên)", "Đạt" if global_test.get("passed") else "Không đạt - số dư lớn"])
            ws.append(["Chi-square statistic", global_test.get("statistic")])
            ws.append(["Chi-square upper critical 95%", global_test.get("upper_critical_value")])
            ws.append(["Chi-square upper-tail p-value", global_test.get("p_value")])
            if not global_test.get("passed"):
                ws.append(["Cảnh báo", "Số dư mạng vượt ngưỡng trên; kiểm tra cạnh yếu, ngoại lai và covariance"])
        if quality.get("stochastic_model_test"):
            stochastic_test = quality["stochastic_model_test"]
            ws.append(["Chẩn đoán mô hình trọng số (hai phía)", stochastic_test.get("status")])
            ws.append(["Chi-square calibration lower", stochastic_test.get("lower_critical_value")])
            ws.append(["Chi-square calibration upper", stochastic_test.get("upper_critical_value")])
            if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
                ws.append(["Ghi chú", "Covariance bảo thủ; đây không phải lỗi chất lượng mạng và không thu nhỏ STD theo M0"])
        trusted_subset = quality.get("trusted_subset") or {}
        if trusted_subset:
            for label, key in (
                ("Trusted subset: số baseline đạt ngưỡng STD", "observation_baseline_count"),
                ("Trusted subset: bậc tự do", "degrees_of_freedom"),
                ("Trusted subset: vTPv", "weighted_residual_sum"),
                ("Trusted subset: M0", "reference_standard_deviation"),
            ):
                if trusted_subset.get(key) is not None:
                    ws.append([label, trusted_subset[key]])
            trusted_test = trusted_subset.get("global_test") or {}
            if trusted_test:
                ws.append(["Trusted subset: kiểm định phương sai", "Đạt" if trusted_test.get("passed") else "Không đạt"])
                ws.append(["Trusted subset: chi-square lower", trusted_test.get("lower_critical_value")])
                ws.append(["Trusted subset: chi-square upper", trusted_test.get("upper_critical_value")])
                ws.append(["Trusted subset: p-value", trusted_test.get("p_value")])
        ws.append(["Scale STD điểm công bố", quality.get("published_point_std_scale", "a_priori")])
        ws.append(["Scale số dư chuẩn hóa", quality.get("normalized_residual_scale", "a_priori")])
        ws.append(["Mô hình covariance baseline", quality.get("baseline_covariance_model")])
        ws.append([
            "Chính sách rolling stability",
            json.dumps(quality.get("rolling_stability_policy") or {}, ensure_ascii=False),
        ])
        ws.append(["Ngưỡng cảnh báo STD baseline (m)", quality.get("baseline_std_warning_threshold_m")])
        ws.append(["Dung sai nhất quán ECEF rover/baseline (m)", quality.get("raw_ecef_consistency_tolerance_m")])
        ws.append(["Ngưỡng tách phiên liên tục (s)", quality.get("observation_session_gap_seconds")])
        ws.append(["Đã lập block covariance ECEF 3x3 sau phép quay", bool(quality.get("full_covariance_available"))])
        ws.append(["AGRICA có covariance chéo gốc NE/EU/NU", bool(quality.get("source_cross_covariance_available"))])
        ws.append(["Đã chứng minh trị đo lặp độc lập", bool(quality.get("repeated_observations_independence_verified"))])
        ws.append(["Đã cộng sai số điểm khống chế", bool(quality.get("control_point_uncertainty_included"))])
        if not quality.get("repeated_observations_independence_verified"):
            ws.append(["Cảnh báo", "Mỗi cạnh chỉ vào solver một lần sau khi lấy trung bình có trọng số; kiểm định chi-square giả định các cạnh trung bình độc lập."])
        if not quality.get("control_point_uncertainty_included"):
            ws.append(["Cảnh báo", "STD điểm chỉ là độ chính xác tương đối so với BASE cố định."])
        if quality.get("baseline_std_rejected_count"):
            ws.append(["Cảnh báo", (
                f"Đã loại {quality.get('baseline_std_rejected_count')} raw vượt ngưỡng STD "
                "khỏi solver; cờ chi tiết nằm ở Bảng 8."
            )])
        if quality.get("raw_ecef_inconsistent_count"):
            ws.append(["Cảnh báo", (
                "ECEF rover không nhất quán đã bị loại khỏi Raw TB, nhưng vector baseline "
                "vẫn được giữ để bình sai nếu đạt các điều kiện chất lượng khác."
            )])
        if quality.get("vector_outlier_count"):
            ws.append(["Cảnh báo", (
                f"Đã loại {quality.get('vector_outlier_count')} raw có vector baseline nhảy nghiệm/sai thô "
                "trước khi lấy trung bình cạnh và trước khi bình sai."
            )])
        mixed_threshold = float(
            quality.get("mixed_position_type_warning_threshold_m") or 0.01
        )
        for mixed_edge in quality.get("mixed_position_type_edges") or []:
            separation = float(mixed_edge.get("mean_separation_m") or 0.0)
            if separation < mixed_threshold:
                continue
            ws.append(["Cảnh báo", (
                f"Cạnh {mixed_edge.get('from')} -> {mixed_edge.get('to')} trộn position type "
                f"{'/'.join(map(str, mixed_edge.get('position_types') or []))}; "
                f"trung bình theo loại nghiệm lệch {separation:.4f} m."
            )])
        for filtered_edge in quality.get("position_type_filter_edges") or []:
            ws.append(["Đã lọc", (
                f"Cạnh {filtered_edge.get('from')} -> {filtered_edge.get('to')}: giữ Position Type "
                f"{filtered_edge.get('selected_position_type')}; loại "
                f"{filtered_edge.get('rejected_count')} raw Type "
                f"{'/'.join(map(str, filtered_edge.get('rejected_position_types') or []))}."
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
                    "Sai lệch ECEF rover/baseline (m)", "Lệch vector cạnh (m)",
                    "Ngưỡng lọc vector (m)", "Cờ chất lượng", "vX (m)",
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
                           observation.get("vector_deviation_from_edge_m"),
                           observation.get("vector_outlier_threshold_m"),
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
            "Các epoch 1 Hz trong cùng cạnh đã được gom thành một trị trung bình có trọng số trước solver; "
            "số epoch không được tính là bậc tự do độc lập."
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

    def _append_adjustment_to_excel(
        self,
        project_id: int,
        timestamp: int,
        data: dict,
        raw_payload: str,
    ):
        """Write the compact XLSX handed to users.

        Its main sections intentionally mirror ``slbskqbs.txt``. Every raw
        AGRICA epoch remains available in the visible ``RAW_AUDIT`` worksheet
        and in the JSON artifact for independent recalculation.
        """
        import datetime
        import os

        import openpyxl
        from openpyxl.cell.cell import MergedCell
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        report_dir = os.path.join(os.path.dirname(__file__), "static", "adjustments")
        os.makedirs(report_dir, exist_ok=True)
        file_path = os.path.join(
            report_dir,
            f"gnss_binh_sai_{project_id}_{timestamp}.xlsx",
        )

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Binh sai"
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"

        title_fill = PatternFill("solid", fgColor="0F4C5C")
        section_fill = PatternFill("solid", fgColor="1F6F78")
        header_fill = PatternFill("solid", fgColor="DDEBF7")
        thin_gray = Side(style="thin", color="B7C9CE")
        table_border = Border(bottom=thin_gray)

        def append_title(value):
            sheet.append([value])
            row = sheet.max_row
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=11)
            cell = sheet.cell(row, 1)
            cell.font = Font(bold=True, color="FFFFFF", size=14)
            cell.fill = title_fill
            cell.alignment = Alignment(horizontal="center")

        def append_section(value):
            sheet.append([])
            sheet.append([value])
            row = sheet.max_row
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=11)
            cell = sheet.cell(row, 1)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = section_fill

        def append_header(values):
            sheet.append(values)
            for cell in sheet[sheet.max_row]:
                if cell.column > len(values):
                    break
                cell.font = Font(bold=True, color="17324D")
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", wrap_text=True)
                cell.border = table_border

        def values3(value):
            value = value or (None, None, None)
            return [value[index] if index < len(value) else None for index in range(3)]

        def loop_ratio(loop):
            ratio = loop.get("observed_relative_precision")
            return f"1/{float(ratio):.0f}" if ratio else "-"

        computed_at = int(data.get("computed_at") or timestamp)
        dt_obj = datetime.datetime.fromtimestamp(computed_at)
        baselines = list(data.get("baselines") or [])
        loops = list(data.get("loops") or [])
        points = data.get("points") or {}
        base = data.get("base") or {}
        quality = data.get("quality") or {}
        base_name = base.get("name") or "BASE"
        base_label = base_name if base_name == "BASE" else f"{base_name} (BASE)"

        append_title("BÁO CÁO BÌNH SAI MẠNG GNSS - ECEF XYZ")
        # Column A is reserved for STT in all detail tables.  Keeping metadata
        # labels in column B prevents long labels from being clipped by the
        # intentionally narrow STT column.
        sheet.append([None, "Dự án", project_id, "Cụm", data.get("cluster_name") or "-"])
        sheet.append([None, "Thời gian", dt_obj.strftime("%Y-%m-%d %H:%M:%S")])
        sheet.append([
            None,
            "BASE cố định",
            base_label,
            "Số rover",
            data.get("rover_count", len(points)),
        ])

        append_section("CALCULATED BASELINES - BASELINE TRUNG BÌNH")
        append_header([
            "STT", "From_Point", "To_Point", "dX (m)", "dY (m)", "dZ (m)",
            "Std_X (m)", "Std_Y (m)", "Std_Z (m)", "Length (m)", "Raw / n_eff",
            "Variance_Inflation", "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
        ])
        for index, baseline in enumerate(baselines, 1):
            cov = baseline.get("session_covariance_used_xyz")
            formal_cov = baseline.get("formal_covariance_xyz")
            sheet.append([
                index,
                baseline.get("from"),
                baseline.get("to"),
                *values3(baseline.get("observed_xyz") or baseline.get("observed_neu")),
                *values3(baseline.get("standard_deviation_xyz")),
                baseline.get("observed_length"),
                (
                    f"{baseline.get('observation_count', 1)} / "
                    f"{float(baseline.get('effective_sample_size')):.2f}"
                    if baseline.get("effective_sample_size") is not None
                    else baseline.get("observation_count", 1)
                ),
                baseline.get("variance_inflation"),
                cov[0][1] if cov else None,
                cov[0][2] if cov else None,
                cov[1][2] if cov else None,
                formal_cov[0][1] if formal_cov else None,
                formal_cov[0][2] if formal_cov else None,
                formal_cov[1][2] if formal_cov else None,
            ])

        append_section("FOUND LOOPS - VÒNG KHÉP TRƯỚC BÌNH SAI")
        append_header([
            "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
            "Length (m)", "fs/s",
        ])
        for index, loop in enumerate(loops, 1):
            sheet.append([
                index,
                " - ".join(loop.get("points") or []),
                *values3(loop.get("observed_misclosure_xyz")),
                loop.get("observed_closure"),
                loop.get("total_length"),
                loop_ratio(loop),
            ])

        append_section("ADJUSTMENT RESULT - KẾT QUẢ BÌNH SAI")
        append_section("ADJUSTED BASELINES")
        append_header([
            "STT", "From_Point", "To_Point", "vX (m)", "vY (m)", "vZ (m)",
            "Adj_X (m)", "Adj_Y (m)", "Adj_Z (m)", "Length (m)", "Raw / n_eff",
            "Variance_Inflation", "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
        ])
        for index, baseline in enumerate(baselines, 1):
            cov = baseline.get("session_covariance_used_xyz")
            formal_cov = baseline.get("formal_covariance_xyz")
            sheet.append([
                index,
                baseline.get("from"),
                baseline.get("to"),
                *values3(baseline.get("residual_xyz") or baseline.get("residual_neu")),
                *values3(baseline.get("adjusted_xyz") or baseline.get("adjusted_neu")),
                baseline.get("adjusted_length"),
                (
                    f"{baseline.get('observation_count', 1)} / "
                    f"{float(baseline.get('effective_sample_size')):.2f}"
                    if baseline.get("effective_sample_size") is not None
                    else baseline.get("observation_count", 1)
                ),
                baseline.get("variance_inflation"),
                cov[0][1] if cov else None,
                cov[0][2] if cov else None,
                cov[1][2] if cov else None,
                formal_cov[0][1] if formal_cov else None,
                formal_cov[0][2] if formal_cov else None,
                formal_cov[1][2] if formal_cov else None,
            ])

        append_section("ADJUSTED LOOPS")
        sheet.append([
            None,
            "Ghi chú",
            (
                "Chỉ liệt kê fundamental cycle basis độc lập theo topology; "
                "các vòng phụ thuộc đã được loại. Closure sau bình sai gần 0 "
                "là hệ quả của mô hình, không phải phép kiểm tra độc lập dữ liệu gốc."
            ),
        ])
        loop_note_row = sheet.max_row
        sheet.merge_cells(
            start_row=loop_note_row,
            start_column=3,
            end_row=loop_note_row,
            end_column=11,
        )
        append_header([
            "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
            "Length (m)", "Kết quả",
        ])
        for index, loop in enumerate(loops, 1):
            sheet.append([
                index,
                " - ".join(loop.get("points") or []),
                *values3(loop.get("adjusted_misclosure_xyz")),
                loop.get("adjusted_closure"),
                loop.get("total_length"),
                "Khép kín" if abs(float(loop.get("adjusted_closure") or 0.0)) < 1e-9 else "Kiểm tra",
            ])

        append_section("CONTROL POINT")
        append_header(["STT", "Point_name", "X (m)", "Y (m)", "Z (m)", "Cố định"])
        sheet.append([1, base_label, *values3(base.get("ecef_xyz")), True])

        append_section("ADJUSTED POINTS")
        append_header([
            "STT", "Point_name", "X (m)", "Y (m)", "Z (m)",
            "X-Std (m)", "Y-Std (m)", "Z-Std (m)", "Raw dùng", "Raw loại",
        ])
        for index, (point_name, point) in enumerate(points.items(), 1):
            sheet.append([
                index,
                point_name,
                point.get("adjusted_x", point.get("adjusted_n")),
                point.get("adjusted_y", point.get("adjusted_e")),
                point.get("adjusted_z", point.get("adjusted_u")),
                point.get("std_x", point.get("std_n")),
                point.get("std_y", point.get("std_e")),
                point.get("std_z", point.get("std_u")),
                point.get("raw_rover_ecef_observation_count"),
                point.get("raw_rover_ecef_rejected_count", 0),
            ])

        append_section("REFERENCE STANDARD DEVIATION / QUALITY")
        append_header(["", "Chỉ tiêu", "Giá trị"])
        quality_value_rows = set()
        quality_warning_rows = set()
        quality_rows = [
            ("Raw nhận được", quality.get("raw_observation_count")),
            ("Raw loại do nguồn chưa xác nhận", quality.get("unconfirmed_source_excluded_count")),
            (
                "Raw loại trong cửa sổ chuyển nguồn/chờ ổn định",
                quality.get("pre_stable_window_excluded_count"),
            ),
            (
                "Raw loại do thời gian thu chưa đạt tối thiểu",
                quality.get("insufficient_duration_excluded_count"),
            ),
            (
                "Raw loại do cửa sổ ổn định chưa đủ",
                quality.get("insufficient_stable_window_excluded_count"),
            ),
            (
                "Raw loại do drift quay lại",
                quality.get("unstable_solver_window_excluded_count"),
            ),
            ("Raw dùng", quality.get("observation_baseline_count")),
            ("Raw bị loại", quality.get("raw_rejected_count")),
            ("Raw vector sai thô", quality.get("vector_outlier_count")),
            ("Raw loại do STD", quality.get("baseline_std_rejected_count")),
            (
                "Raw STD cao giữ bảo thủ nhờ lặp ổn định",
                quality.get("baseline_std_repeatability_fallback_count"),
            ),
            ("Raw loại Type 7", quality.get("position_type_rejected_count")),
            (
                "Raw ECEF lệch thuần phương đứng do hệ cao",
                quality.get("raw_ecef_vertical_datum_offset_count"),
            ),
            ("Số cạnh trung bình", quality.get("averaged_baseline_count", len(baselines))),
            ("Số vòng cơ sở", quality.get("fundamental_loop_count")),
            ("Chiều không gian vòng", quality.get("cycle_space_dimension")),
            ("Rank ma trận vòng", quality.get("fundamental_loop_basis_rank")),
            ("Bậc tự do", quality.get("degrees_of_freedom")),
            ("vTPv (covariance theo phiên)", quality.get("weighted_residual_sum")),
            ("M0 (covariance theo phiên)", quality.get("reference_standard_deviation")),
            ("Rank", quality.get("rank")),
            ("Condition number", quality.get("condition_number")),
        ]
        quality_gate = data.get("quality_gate") or {}
        quality_rows.extend([
            ("Quality gate", quality_gate.get("status")),
            (
                "Quality interpretation",
                quality_gate.get("interpretation_status") or quality_gate.get("status"),
            ),
            ("Vòng khép trước bình sai lớn nhất (m, chỉ chẩn đoán)", quality_gate.get("max_pre_adjustment_loop_closure_m")),
            ("Cho phép publish tọa độ chính thức", bool(data.get("official_publish_allowed"))),
        ])
        global_test = quality.get("global_test") or {}
        stochastic_test = quality.get("stochastic_model_test") or {}
        independent_test = quality.get("independent_epoch_sensitivity") or {}
        ess_edges = quality.get("effective_sample_size_edges") or []
        if ess_edges:
            effective_sizes = [
                float(edge.get("effective_sample_size"))
                for edge in ess_edges
                if edge.get("effective_sample_size") is not None
            ]
            if effective_sizes:
                quality_rows.extend([
                    ("n_eff nhỏ nhất", min(effective_sizes)),
                    ("n_eff lớn nhất", max(effective_sizes)),
                ])
        if global_test:
            quality_rows.extend([
                (
                    "Kiểm định chất lượng mạng",
                    "ĐẠT" if global_test.get("passed") else "KHÔNG ĐẠT - SỐ DƯ LỚN",
                ),
                (
                    "Ngưỡng trên Chi-square 95%",
                    global_test.get("upper_critical_value"),
                ),
            ])
        if stochastic_test:
            stochastic_labels = {
                "CONSERVATIVE_WEIGHTS": "TRỌNG SỐ BẢO THỦ",
                "CONSISTENT": "NHẤT QUÁN",
                "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR": "TRỌNG SỐ QUÁ LẠC QUAN / SAI MÔ HÌNH",
            }
            quality_rows.append((
                "Chẩn đoán mô hình trọng số",
                stochastic_labels.get(
                    stochastic_test.get("status"),
                    stochastic_test.get("status"),
                ),
            ))
        if independent_test:
            quality_rows.extend([
                (
                    "Chi-square giả định epoch độc lập",
                    "ĐẠT (tham khảo)" if independent_test.get("passed") else "KHÔNG ĐẠT (tham khảo)",
                ),
                ("vTPv giả định độc lập", independent_test.get("weighted_residual_sum")),
                ("M0 giả định độc lập", independent_test.get("reference_standard_deviation")),
            ])
        for label, value in quality_rows:
            if value is not None:
                sheet.append([None, label, value])
                quality_value_rows.add(sheet.max_row)

        quality_notes = []
        if global_test and global_test.get("approximate"):
            quality_notes.append(
                "Covariance nghiệm chính chỉ tính một trị đo độc lập cho mỗi phiên RTK FIXED "
                "liên tục; các epoch 1 Hz trong cùng phiên không được cộng như các trị đo độc lập. "
                "ACF chỉ được lưu để chẩn đoán độ nhạy."
            )
        if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
            quality_notes.append(
                "vTPv thấp hơn cận dưới hai phía: covariance đang bảo thủ. Đây là cảnh báo "
                "hiệu chỉnh mô hình trọng số, không phải lỗi chất lượng mạng và không dùng M0 "
                "để thu nhỏ STD công bố."
            )
        if global_test and not global_test.get("passed"):
            quality_notes.append(
                "vTPv vượt ngưỡng trên một phía 95%: số dư mạng lớn hơn mức covariance cho phép."
            )
        for fallback_edge in (
            quality.get("baseline_std_repeatability_fallback_edges") or []
        ):
            quality_notes.append(
                (
                    f"Giữ bảo thủ cạnh {fallback_edge.get('from')} - "
                    f"{fallback_edge.get('to')}: "
                    f"{fallback_edge.get('observation_count')} epoch RTK Fixed, "
                    f"độ lặp vector lớn nhất "
                    f"{float(fallback_edge.get('max_vector_deviation_m') or 0.0):.4f} m, "
                    f"sai số nhất quán ECEF lớn nhất "
                    f"{float(fallback_edge.get('max_ecef_consistency_error_m') or 0.0):.4f} m; "
                    "vẫn giữ covariance STD cao gốc để không tăng trọng số."
                )
            )
        for quality_note in quality_notes:
            sheet.append([
                None,
                "Ghi chú",
                quality_note,
            ])
            note_row = sheet.max_row
            sheet.merge_cells(
                start_row=note_row,
                start_column=3,
                end_row=note_row,
                end_column=11,
            )
            quality_warning_rows.add(note_row)

        for mixed_edge in quality.get("mixed_position_type_edges") or []:
            separation = float(mixed_edge.get("mean_separation_m") or 0.0)
            threshold = float(quality.get("mixed_position_type_warning_threshold_m") or 0.01)
            if separation < threshold:
                continue
            sheet.append([
                None,
                "Cảnh báo",
                (
                    f"{mixed_edge.get('from')} -> {mixed_edge.get('to')} trộn position type "
                    f"{'/'.join(map(str, mixed_edge.get('position_types') or []))}; "
                    f"lệch {separation:.4f} m"
                ),
            ])
            warning_row = sheet.max_row
            sheet.merge_cells(
                start_row=warning_row,
                start_column=3,
                end_row=warning_row,
                end_column=11,
            )
            quality_warning_rows.add(warning_row)

        for filtered_edge in quality.get("position_type_filter_edges") or []:
            sheet.append([
                None,
                "Đã lọc",
                (
                    f"{filtered_edge.get('from')} -> {filtered_edge.get('to')}: giữ Position Type "
                    f"{filtered_edge.get('selected_position_type')}; loại "
                    f"{filtered_edge.get('rejected_count')} raw Type "
                    f"{'/'.join(map(str, filtered_edge.get('rejected_position_types') or []))}."
                ),
            ])
            filter_row = sheet.max_row
            sheet.merge_cells(
                start_row=filter_row,
                start_column=3,
                end_row=filter_row,
                end_column=11,
            )
            quality_warning_rows.add(filter_row)

        merged_banner_rows = {
            cell_range.min_row
            for cell_range in sheet.merged_cells.ranges
            if (
                cell_range.min_row == cell_range.max_row
                and cell_range.min_col == 1
                and cell_range.max_col == 11
            )
        }
        for row_index, row in enumerate(sheet.iter_rows(), 1):
            populated = any(
                not isinstance(cell, MergedCell) and cell.value is not None
                for cell in row
            )
            for cell in row:
                if isinstance(cell, MergedCell):
                    continue
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000"
                horizontal = cell.alignment.horizontal
                if horizontal is None:
                    if row_index in merged_banner_rows:
                        horizontal = "center" if row_index == 1 else "left"
                    elif row_index in quality_value_rows and cell.column == 3:
                        horizontal = "right" if isinstance(cell.value, (int, float)) else "left"
                    elif cell.column == 1:
                        horizontal = "center"
                    elif cell.column in (2, 3):
                        horizontal = "left"
                    elif isinstance(cell.value, (int, float)):
                        horizontal = "right"
                    else:
                        horizontal = "left"
                cell.alignment = Alignment(
                    horizontal=horizontal,
                    vertical="center",
                    wrap_text=cell.column in (2, 3) or row_index in quality_warning_rows,
                )
                if populated and row_index not in merged_banner_rows:
                    cell.border = table_border

            if row_index == 1:
                sheet.row_dimensions[row_index].height = 26
            elif row_index in quality_warning_rows:
                sheet.row_dimensions[row_index].height = 34
            elif any(
                not isinstance(cell, MergedCell)
                and cell.column in (2, 3)
                and len(str(cell.value or "")) > 34
                for cell in row
            ):
                sheet.row_dimensions[row_index].height = 32

        # Fixed widths keep all table headings on the same vertical guides.
        # Auto-sizing from the merged title or long warnings previously made
        # columns A/B huge and made correctly placed values look shifted.
        main_column_widths = {
            "A": 8,
            "B": 34,
            "C": 18,
            "D": 15,
            "E": 15,
            "F": 15,
            "G": 15,
            "H": 15,
            "I": 15,
            "J": 15,
            "K": 12,
        }
        for letter, width in main_column_widths.items():
            sheet.column_dimensions[letter].width = width

        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True
        sheet.page_margins.left = 0.25
        sheet.page_margins.right = 0.25

        # Preserve every source epoch in the same XLSX for independent
        # recalculation. Keep the compact report as the opening sheet while
        # exposing RAW_AUDIT as a normal tab so users can inspect it directly.
        raw_sheet = workbook.create_sheet("RAW_AUDIT")
        sheet.sheet_properties.tabColor = "1F6F78"
        raw_sheet.sheet_properties.tabColor = "D4A017"
        raw_headers = [
            "Raw_STT", "From_Point", "To_Point", "Session", "Effective_Session_ID", "Rotation_ID", "Stable_Window_ID", "Epoch",
            "Position_Type", "Baseline_N (m)", "Baseline_E (m)", "Baseline_U (m)",
            "Std_N_Raw (m)", "Std_E_Raw (m)", "Std_U_Raw (m)",
            "Std_N_Used (m)", "Std_E_Used (m)", "Std_U_Used (m)",
            "Baseline_dX (m)", "Baseline_dY (m)", "Baseline_dZ (m)",
            "Raw_Base_Lat", "Raw_Base_Lon", "Raw_Base_h (m)",
            "Base_Lat", "Base_Lon", "Base_h (m)",
            "Rover_X (m)", "Rover_Y (m)", "Rover_Z (m)",
            "Rover_StdX_Raw (m)", "Rover_StdY_Raw (m)", "Rover_StdZ_Raw (m)",
            "Rover_StdX_Used (m)", "Rover_StdY_Used (m)", "Rover_StdZ_Used (m)",
            "Vector_Deviation (m)", "Vector_Filter_Threshold (m)", "Vector_Filter_Status",
            "ECEF_Consistency_Error (m)",
            "ECEF_Residual_E (m)", "ECEF_Residual_N (m)", "ECEF_Residual_U (m)",
            "Quality_Flags", "Accepted_For_Solver",
            "Raw_AGRICA",
        ]
        raw_sheet.append(raw_headers)
        for cell in raw_sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = title_fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)

        for raw_index, observation in enumerate(
            data.get("baseline_observations") or [],
            1,
        ):
            flags = list(observation.get("quality_flags") or [])
            rejected = any(
                str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                for flag in flags
            )
            raw_sheet.append([
                raw_index,
                observation.get("from"),
                observation.get("to"),
                observation.get("session_id"),
                observation.get("effective_session_id"),
                observation.get("rotation_index"),
                observation.get("stable_window_index"),
                observation.get("observation_epoch"),
                observation.get("position_type"),
                *values3(observation.get("baseline_neu")),
                *values3(
                    observation.get("baseline_std_neu_raw")
                    if "baseline_std_neu_raw" in observation
                    else observation.get("baseline_std_neu")
                ),
                *values3(observation.get("baseline_std_neu")),
                *values3(observation.get("baseline_ecef_xyz")),
                *values3(observation.get("raw_base_llh")),
                *values3(observation.get("base_llh")),
                *values3(observation.get("rover_ecef")),
                *values3(
                    observation.get("rover_position_std_ecef_raw")
                    if "rover_position_std_ecef_raw" in observation
                    else observation.get("rover_position_std_ecef")
                ),
                *values3(observation.get("rover_position_std_ecef")),
                observation.get("vector_deviation_from_edge_m"),
                observation.get("vector_outlier_threshold_m"),
                observation.get("vector_filter_status"),
                observation.get("raw_ecef_consistency_error_m"),
                *values3(observation.get("raw_ecef_consistency_residual_enu_m")),
                ", ".join(flags),
                not rejected,
                observation.get("raw_payload"),
            ])

        raw_sheet.freeze_panes = "A2"
        raw_sheet.auto_filter.ref = raw_sheet.dimensions
        raw_sheet.sheet_view.showGridLines = False
        for row_index, row in enumerate(raw_sheet.iter_rows(), 1):
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000000"
                cell.alignment = Alignment(
                    horizontal="center" if row_index == 1 else None,
                    vertical="center" if row_index == 1 else "top",
                    wrap_text=row_index == 1,
                )
        for column_index in range(1, raw_sheet.max_column + 1):
            letter = get_column_letter(column_index)
            if column_index == raw_sheet.max_column:
                raw_sheet.column_dimensions[letter].width = 42
                continue
            max_length = max(
                len(str(raw_sheet.cell(row_index, column_index).value or ""))
                for row_index in range(1, min(raw_sheet.max_row, 250) + 1)
            )
            raw_sheet.column_dimensions[letter].width = min(max(max_length + 2, 11), 24)

        # Defensive cleanup: only these two report tabs are valid.  An empty
        # default Sheet/Sheet1 must never sit between the compact result and raw
        # audit, otherwise Excel's tab strip makes RAW_AUDIT look absent.
        for extra_sheet in list(workbook.worksheets):
            if extra_sheet.title not in {"Binh sai", "RAW_AUDIT"}:
                workbook.remove(extra_sheet)
        workbook.active = 0
        workbook.views[0].activeTab = 0
        workbook.views[0].firstSheet = 0
        sheet.sheet_view.tabSelected = True
        raw_sheet.sheet_view.tabSelected = False

        workbook.save(file_path)
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            raise OSError(f"Adjustment Excel was not created correctly: {file_path}")
        logger.info(
            "Compact GNSS adjustment Excel written: %s (%s bytes)",
            file_path,
            os.path.getsize(file_path),
        )
        return file_path

    @staticmethod
    def _format_adjustment_summary_text(project_id: int, timestamp: int, data: dict) -> str:
        """Build the compact user-facing report without raw AGRICA rows."""
        import datetime

        def number(value, decimals=4):
            if value is None:
                return "-"
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not math.isfinite(numeric):
                return "-"
            return f"{numeric:.{decimals}f}"

        def vector(values, decimals=4):
            values = values or (None, None, None)
            return " ".join(
                number(values[index] if index < len(values) else None, decimals)
                for index in range(3)
            )

        def relative_precision(loop):
            try:
                ratio = float(loop.get("observed_relative_precision"))
            except (TypeError, ValueError):
                return "-"
            return f"1/{ratio:.0f}" if math.isfinite(ratio) and ratio > 0 else "-"

        baselines = list(data.get("baselines") or [])
        loops = list(data.get("loops") or [])
        points = data.get("points") or {}
        quality = data.get("quality") or {}
        base = data.get("base") or {}
        raw_rows = list(data.get("baseline_observations") or [])
        rejected_rows = [
            row for row in raw_rows
            if any(
                str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                for flag in (row.get("quality_flags") or [])
            )
        ]

        raw_total = quality.get("raw_observation_count", len(raw_rows))
        raw_rejected = quality.get("raw_rejected_count", len(rejected_rows))
        raw_used = quality.get("observation_baseline_count")
        if raw_used is None and raw_total is not None:
            raw_used = max(0, int(raw_total) - int(raw_rejected or 0))

        computed_at = data.get("computed_at") or timestamp
        dt_obj = datetime.datetime.fromtimestamp(int(computed_at))
        base_name = base.get("name") or "BASE"
        base_alias = base_name if base_name == "BASE" else f"{base_name} (BASE)"

        lines = [
            "================ BÁO CÁO BÌNH SAI GNSS ================",
            f"Dự án: {project_id} | Cụm: {data.get('cluster_name') or '-'}",
            f"Thời gian: {dt_obj:%Y-%m-%d %H:%M:%S}",
            f"BASE cố định: {base_alias}",
            (
                f"Lat/Lon/h: {number(base.get('lat'), 10)} "
                f"{number(base.get('lon'), 10)} {number(base.get('h'), 4)} m"
            ),
            (
                f"Rover: {data.get('rover_count', len(points))} | Raw: {raw_total} | "
                f"Dùng: {raw_used} | Loại: {raw_rejected} | "
                f"Cạnh trung bình: {len(baselines)} | Vòng khép: {len(loops)}"
            ),
            "",
            "---------------- BASELINE TRUNG BÌNH ----------------",
            "STT  Từ           Đến          dX(m) dY(m) dZ(m)  StdX StdY StdZ  Dài(m)  n",
        ]
        for index, baseline in enumerate(baselines, 1):
            observed = baseline.get("observed_xyz") or baseline.get("observed_neu")
            std = baseline.get("standard_deviation_xyz") or (None, None, None)
            lines.append(
                f"{index:<4} {str(baseline.get('from') or '-'):<12} "
                f"{str(baseline.get('to') or '-'):<12} {vector(observed, 4)}  "
                f"{vector(std, 6)}  {number(baseline.get('observed_length'), 3)}  "
                f"{baseline.get('observation_count', 1)}"
            )

        lines.extend([
            "",
            "---------------- VÒNG KHÉP TRƯỚC BÌNH SAI ----------------",
            "STT  Các điểm  fx(m) fy(m) fz(m)  fs(m)  Tổng dài(m)  Tỷ lệ",
        ])
        if loops:
            for index, loop in enumerate(loops, 1):
                closure_vector = loop.get("observed_misclosure_xyz") or (None, None, None)
                lines.append(
                    f"{index:<4} {' - '.join(loop.get('points') or [])}  "
                    f"{vector(closure_vector, 5)}  "
                    f"{number(loop.get('observed_closure'), 5)}  "
                    f"{number(loop.get('total_length'), 3)}  {relative_precision(loop)}"
                )
        else:
            lines.append("Không tìm thấy vòng khép hình học độc lập.")

        lines.extend([
            "",
            "---------------- BASELINE SAU BÌNH SAI ----------------",
            "STT  Từ           Đến          vX(m) vY(m) vZ(m)  dX'(m) dY'(m) dZ'(m)",
        ])
        for index, baseline in enumerate(baselines, 1):
            residual = baseline.get("residual_xyz") or baseline.get("residual_neu")
            adjusted = baseline.get("adjusted_xyz") or baseline.get("adjusted_neu")
            lines.append(
                f"{index:<4} {str(baseline.get('from') or '-'):<12} "
                f"{str(baseline.get('to') or '-'):<12} {vector(residual, 5)}  "
                f"{vector(adjusted, 4)}"
            )

        lines.extend([
            "",
            "---------------- TỌA ĐỘ SAU BÌNH SAI ----------------",
            "Điểm  X(m) Y(m) Z(m)  StdX(m) StdY(m) StdZ(m)  Raw dùng/loại",
            f"{base_alias}  {vector(base.get('ecef_xyz'), 6)}  CỐ ĐỊNH",
        ])
        for point_name, point in points.items():
            coordinate = (
                point.get("adjusted_x", point.get("adjusted_n")),
                point.get("adjusted_y", point.get("adjusted_e")),
                point.get("adjusted_z", point.get("adjusted_u")),
            )
            point_std = (point.get("std_x"), point.get("std_y"), point.get("std_z"))
            point_used = point.get("raw_rover_ecef_observation_count", "-")
            point_rejected = point.get("raw_rover_ecef_rejected_count", 0)
            lines.append(
                f"{point_name}  {vector(coordinate, 6)}  {vector(point_std, 6)}  "
                f"{point_used}/{point_rejected}"
            )

        global_test = quality.get("global_test") or {}
        stochastic_test = quality.get("stochastic_model_test") or {}
        independent_test = quality.get("independent_epoch_sensitivity") or {}
        lines.extend([
            "",
            "---------------- CHỈ TIÊU BÌNH SAI ----------------",
            (
                f"Số ẩn: {3 * int(data.get('rover_count', len(points)) or 0)} | "
                f"Bậc tự do: {quality.get('degrees_of_freedom', '-')} | "
                f"vTPv theo phiên: {number(quality.get('weighted_residual_sum'), 6)} | "
                f"M0 theo phiên: {number(quality.get('reference_standard_deviation'), 6)}"
            ),
            (
                f"Rank: {quality.get('rank', '-')} | "
                f"Condition number: {number(quality.get('condition_number'), 6)} | "
                f"Max |số dư chuẩn hóa|: "
                f"{number(quality.get('max_standardized_residual'), 4)}"
            ),
        ])
        if global_test:
            chi_square_status = (
                "ĐẠT" if global_test.get("passed") else "KHÔNG ĐẠT - SỐ DƯ LỚN"
            )
            lines.append(
                f"Kiểm định chất lượng mạng (phía trên): {chi_square_status} | "
                f"Statistic: {number(global_test.get('statistic'), 6)} | "
                f"Ngưỡng trên 95%: {number(global_test.get('upper_critical_value'), 6)} | "
                f"p-value phía trên: {number(global_test.get('p_value'), 9)}"
            )
        if stochastic_test:
            stochastic_labels = {
                "CONSERVATIVE_WEIGHTS": "TRỌNG SỐ BẢO THỦ",
                "CONSISTENT": "NHẤT QUÁN",
                "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR": "TRỌNG SỐ QUÁ LẠC QUAN / SAI MÔ HÌNH",
            }
            lines.append(
                "Chẩn đoán mô hình trọng số (hai phía): "
                f"{stochastic_labels.get(stochastic_test.get('status'), stochastic_test.get('status'))} | "
                f"Khoảng kỳ vọng: [{number(stochastic_test.get('lower_critical_value'), 6)}, "
                f"{number(stochastic_test.get('upper_critical_value'), 6)}]"
            )
        if independent_test:
            lines.append(
                "Chi-square giả định epoch độc lập (chỉ phân tích độ nhạy): "
                f"{'ĐẠT' if independent_test.get('passed') else 'KHÔNG ĐẠT'} | "
                f"vTPv: {number(independent_test.get('weighted_residual_sum'), 6)} | "
                f"M0: {number(independent_test.get('reference_standard_deviation'), 6)}"
            )

        warnings = []
        vector_outlier_count = int(quality.get("vector_outlier_count") or 0)
        if vector_outlier_count:
            warnings.append(
                f"Đã loại {vector_outlier_count} raw có vector baseline nhảy nghiệm/sai thô."
            )
        std_warning_count = int(
            quality.get("baseline_std_raw_warning_count")
            or quality.get("baseline_std_warning_count")
            or 0
        )
        if std_warning_count:
            warnings.append(
                f"Đã loại {std_warning_count} raw vượt ngưỡng STD baseline khỏi solver."
            )
        inconsistent_count = int(quality.get("raw_ecef_inconsistent_count") or 0)
        if inconsistent_count:
            warnings.append(
                f"Có {inconsistent_count} tọa độ rover ECEF không nhất quán với baseline."
            )
        mixed_threshold = float(
            quality.get("mixed_position_type_warning_threshold_m") or 0.01
        )
        mixed_position_type_edges = [
            edge for edge in (quality.get("mixed_position_type_edges") or [])
            if float(edge.get("mean_separation_m") or 0.0) >= mixed_threshold
        ]
        for edge in mixed_position_type_edges:
            warnings.append(
                f"Cạnh {edge.get('from')} -> {edge.get('to')} trộn position type "
                f"{'/'.join(map(str, edge.get('position_types') or []))}; "
                f"hai nghiệm lệch {number(edge.get('mean_separation_m'), 4)} m."
            )
        for edge in quality.get("position_type_filter_edges") or []:
            warnings.append(
                f"Cạnh {edge.get('from')} -> {edge.get('to')}: giữ Position Type "
                f"{edge.get('selected_position_type')}, loại {edge.get('rejected_count')} raw "
                f"Type {'/'.join(map(str, edge.get('rejected_position_types') or []))}."
            )
        if global_test and global_test.get("approximate"):
            warnings.append(
                "Chi-square dùng covariance bảo thủ: mỗi phiên RTK FIXED liên tục chỉ có "
                "n_eff=1; ACF chỉ là chẩn đoán trong JSON audit."
            )
        if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
            warnings.append(
                "vTPv thấp hơn cận dưới hai phía: covariance đang bảo thủ; đây không phải lỗi "
                "chất lượng mạng và không thu nhỏ STD công bố theo M0."
            )
        if global_test and not global_test.get("passed"):
            warnings.append(
                "Số dư mạng vượt ngưỡng Chi-square phía trên 95%; cần kiểm tra cạnh yếu, "
                "ngoại lai và covariance."
            )
        if warnings or rejected_rows:
            lines.extend(["", "---------------- CẢNH BÁO / RAW BỊ LOẠI ----------------"])
            lines.extend(f"- {warning}" for warning in warnings)
            for row in rejected_rows[:20]:
                flags = ",".join(row.get("quality_flags") or [])
                lines.append(
                    f"- {row.get('from', '-')} -> {row.get('to', '-')} | "
                    f"epoch {row.get('observation_epoch', '-')} | {flags} | "
                    f"lệch vector {number(row.get('vector_deviation_from_edge_m'), 3)} m"
                )
            if len(rejected_rows) > 20:
                lines.append(
                    f"- ... và {len(rejected_rows) - 20} raw bị loại khác "
                    "(xem hồ sơ audit)."
                )

        lines.extend([
            "",
            "Ghi chú: Mỗi cạnh chỉ dùng một baseline trung bình có trọng số trong solver.",
            "Raw AGRICA chi tiết không in trong báo cáo này; xem JSON/XLSX audit khi cần truy vết.",
        ])
        return "\n".join(lines) + "\n"

    def _write_adjustment_reports(self, project_id: int, timestamp: int, data: dict) -> dict:
        """Write the report files referenced by the GNSS adjustment interface."""
        import os

        report_dir = os.path.join(os.path.dirname(__file__), "static", "adjustments")
        os.makedirs(report_dir, exist_ok=True)
        audit_name = f"gnss_adjustment_{project_id}_{timestamp}.json"
        audit_path = os.path.join(report_dir, audit_name)
        try:
            with open(audit_path, "w", encoding="utf-8") as report_file:
                json.dump(data, report_file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Error saving GNSS adjustment JSON %s: %s", audit_path, exc, exc_info=True)
            raise
        if not os.path.isfile(audit_path) or os.path.getsize(audit_path) == 0:
            raise OSError(f"Adjustment JSON was not created correctly: {audit_path}")
        logger.info("GNSS adjustment JSON written: %s (%s bytes)", audit_path, os.path.getsize(audit_path))

        excel_path = self._append_adjustment_to_excel(project_id, timestamp, data, "")
        if not excel_path:
            raise OSError("Adjustment Excel exporter did not return an output path")
        excel_url = f"/static/adjustments/{os.path.basename(excel_path)}"
        return {
            "report_file_url": excel_url,
            "audit_json_url": f"/static/adjustments/{audit_name}",
            "excel_report_url": excel_url,
        }

    async def _handle_round_robin_adjustment_result(self, project_id: int, adjustment: dict):
        """Always persist audit reports; publish coordinates only after quality PASS."""
        current_timestamp = int(time.time())
        try:
            report_urls = self._write_adjustment_reports(project_id, current_timestamp, adjustment)
        except Exception as exc:
            message = f"Bình sai đã tính xong nhưng không thể xuất JSON/XLSX: {exc}"
            logger.error("Project %s: %s", project_id, message, exc_info=True)
            await self._handle_round_robin_adjustment_error(project_id, message)
            return
        adjustment.update(report_urls)
        quality_gate = adjustment.get("quality_gate") or {}
        if not bool(quality_gate.get("passed")):
            reasons = "; ".join(quality_gate.get("reasons") or [])
            message = (
                "Bình sai đã tạo hồ sơ audit nhưng không đạt quality gate; "
                "không lưu/publish tọa độ chính thức. "
                f"{reasons or 'quality gate failed'}"
            )
            self.adjustment_phase[project_id] = "FAILED_QUALITY_GATE"
            self.adjustment_message[project_id] = message
            self.adjustment_results[project_id] = adjustment
            await manager.broadcast({
                "type": "gnss_adjustment_progress",
                "project_id": project_id,
                "phase": "FAILED_QUALITY_GATE",
                "message": message,
                "timestamp": current_timestamp,
                "data": adjustment,
            })
            return
        interpretation_status = str(
            quality_gate.get("interpretation_status") or "PASS"
        )
        completed_message = (
            "Connected GNSS network adjustment completed with diagnostic warnings."
            if interpretation_status == "PASS_WITH_WARNINGS" else
            "Connected GNSS network adjustment completed."
        )
        self.adjustment_phase[project_id] = "COMPLETED"
        self.adjustment_message[project_id] = completed_message
        self.adjustment_results[project_id] = adjustment

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
            "message": completed_message,
            "timestamp": current_timestamp,
            # The UI may not currently be viewing one of the adjusted stations,
            # so publish the downloadable result on the project-level event too.
            "data": adjustment,
        })

    async def _handle_round_robin_adjustment_error(self, project_id: int, message: str):
        self.adjustment_phase[project_id] = "ERROR"
        self.adjustment_message[project_id] = message
        self.adjustment_results.pop(project_id, None)
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": project_id,
            "phase": "ERROR",
            "message": message,
        })

    async def _handle_round_robin_progress(self, project_id: int, message: str):
        self.adjustment_message[project_id] = message
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
                            seed_progress_parts = []
                            for cluster_status in seed_status.get("clusters") or ():
                                rolling_by_station = (
                                    cluster_status.get("rolling_stability_by_station") or {}
                                )
                                open_by_station = (
                                    cluster_status.get("solver_window_open_by_station") or {}
                                )
                                count_by_station = (
                                    cluster_status.get("solver_sample_counts_by_station") or {}
                                )
                                duration_by_station = (
                                    cluster_status.get("solver_durations_by_station_seconds") or {}
                                )
                                warmup_count_by_station = (
                                    cluster_status.get("sample_counts_by_station") or {}
                                )
                                warmup_duration_by_station = (
                                    cluster_status.get("durations_by_station_seconds") or {}
                                )
                                reset_by_station = (
                                    cluster_status.get("solver_window_reset_counts_by_station") or {}
                                )
                                drift_by_station = (
                                    cluster_status.get("solver_drift_failure_counts_by_station") or {}
                                )
                                for waiting_station_id in (
                                    cluster_status.get("warming_station_ids") or ()
                                ):
                                    rolling = (
                                        rolling_by_station.get(waiting_station_id)
                                        or rolling_by_station.get(str(waiting_station_id))
                                        or {}
                                    )
                                    delta = rolling.get("delta_neu_m")
                                    if delta and len(delta) == 3:
                                        delta_text = (
                                            "dN/E/U="
                                            f"{float(delta[0]) * 1000:.1f}/"
                                            f"{float(delta[1]) * 1000:.1f}/"
                                            f"{float(delta[2]) * 1000:.1f}mm"
                                        )
                                    else:
                                        delta_text = (
                                            f"waiting for two {seed_status.get('stability_window_seconds', 10)}s windows"
                                        )
                                    is_open = bool(
                                        open_by_station.get(waiting_station_id)
                                        or open_by_station.get(str(waiting_station_id))
                                    )
                                    if is_open:
                                        state_text = (
                                            "solver="
                                            f"{int(count_by_station.get(waiting_station_id, count_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                            f"{int(seed_status.get('solver_min_distinct_epochs') or 0)} epochs, "
                                            f"{int(duration_by_station.get(waiting_station_id, duration_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                            f"{int(seed_status.get('solver_min_duration_seconds') or 0)}s"
                                        )
                                    else:
                                        state_text = (
                                            "fixed-base warm-up="
                                            f"{int(warmup_count_by_station.get(waiting_station_id, warmup_count_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                            f"{int(seed_status.get('seed_warmup_min_distinct_epochs') or 0)} epochs, "
                                            f"{int(warmup_duration_by_station.get(waiting_station_id, warmup_duration_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                            f"{int(seed_status.get('seed_warmup_min_duration_seconds') or 0)}s"
                                        )
                                    reset_count = int(
                                        reset_by_station.get(
                                            waiting_station_id,
                                            reset_by_station.get(str(waiting_station_id), 0),
                                        ) or 0
                                    )
                                    drift_count = int(
                                        drift_by_station.get(
                                            waiting_station_id,
                                            drift_by_station.get(str(waiting_station_id), 0),
                                        ) or 0
                                    )
                                    seed_progress_parts.append(
                                        f"ID {waiting_station_id}: {state_text}, {delta_text}, "
                                        f"resets={reset_count}, rolling-advisory-strikes={drift_count}"
                                    )
                            if seed_status.get("stability_timeout"):
                                phase = "ERROR"
                                await self._handle_round_robin_adjustment_error(
                                    proj_id,
                                    (
                                        "Fixed-base baselines did not produce a complete "
                                        "time-based stable solver window within "
                                        f"{seed_status['stability_timeout_seconds']}s. "
                                        "No network solution was published. Last station state: "
                                        f"{' | '.join(seed_progress_parts) or 'no rolling diagnostics'}"
                                    ),
                                )
                        diagnostic = self.round_robin_manager.get_last_ingest_diagnostic(proj_id)
                        if diagnostic:
                            if seed_status:
                                diagnostic = {**diagnostic, "seed_status": seed_status}
                            if seed_status and (
                                seed_status["missing_station_ids"]
                                or seed_status.get("warming_station_ids")
                            ):
                                waiting_parts = []
                                if seed_status["missing_station_ids"]:
                                    silent_ids = seed_status.get("silent_station_ids") or []
                                    invalid_fix_ids = seed_status.get("invalid_fix_station_ids") or []
                                    if silent_ids:
                                        waiting_parts.append(
                                            "no AGRICA station IDs "
                                            f"{silent_ids}"
                                        )
                                    if invalid_fix_ids:
                                        position_type_parts = []
                                        for item in seed_status.get("clusters") or ():
                                            position_types = (
                                                item.get("latest_position_type_by_station") or {}
                                            )
                                            for invalid_station_id in invalid_fix_ids:
                                                value = position_types.get(
                                                    invalid_station_id,
                                                    position_types.get(str(invalid_station_id)),
                                                )
                                                if value is not None:
                                                    position_type_parts.append(
                                                        f"ID {invalid_station_id}=type {value}"
                                                    )
                                        waiting_parts.append(
                                            "AGRICA not RTK Fixed: "
                                            + (", ".join(dict.fromkeys(position_type_parts))
                                               or str(invalid_fix_ids))
                                        )
                                if seed_status.get("warming_station_ids"):
                                    waiting_parts.append(
                                        " | ".join(seed_progress_parts)
                                        or "stations still building a stable seed window "
                                        f"{seed_status['warming_station_ids']}"
                                    )
                                diagnostic = {
                                    **diagnostic,
                                    "message": (
                                        f"{diagnostic['message']} "
                                        f"Offline discovery {seed_status['step_count']}/{seed_status['max_steps']}; "
                                        f"waiting for {'; '.join(waiting_parts)}."
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
                                    else (
                                        "All selected rovers completed the fixed-base seed window "
                                        f"({self.round_robin_manager.SEED_SOLVER_MIN_DURATION_SECONDS}s "
                                        "stationary solver data each). Starting Round-Robin."
                                    )
                                ),
                            })
                            # The Round-Robin manager has already identified and locked
                            # the actual primary/backup fixed-base service from AGRICA.
                            # Never stop the persisted primary mountpoint here: it may be
                            # offline while a backup station is feeding that mountpoint.
                            # The manager snapshots, sleeps and restores the selected
                            # CORS service atomically inside start_cycle().
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
