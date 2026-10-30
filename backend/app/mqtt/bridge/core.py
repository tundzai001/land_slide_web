"""MQTT bridge construction and process-wide runtime state."""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict

import paho.mqtt.client as mqtt

from app.config import settings
from app.infrastructure.ingest_spool import IngestSpool
from processors.landslide_analyzer import LandslideAnalyzer

try:
    from backend.processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
except ModuleNotFoundError:
    from processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager

logger = logging.getLogger(__name__)


class MQTTBridgeCore:
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
        self.client.on_connect_fail = self.on_connect_fail
        
        # Topic management
        self.topic_map: Dict[tuple, Dict[str, Any]] = {}  # Key: (broker_key, topic)
        self.processors_cache: Dict[str, Any] = {}
        self.adjustment_phase: Dict[int, str] = {}  # {project_id: "IDLE" | "COLLECTING_BASELINE" | "FREE_NETWORK"}
        self.adjustment_message: Dict[int, str] = {}
        self.adjustment_results: Dict[int, dict] = {}
        self.active_adjustment_clusters: Dict[int, list] = {}  # {project_id: [[station_id, ...], ...]}
        self.adjustment_run_contexts: Dict[int, dict] = {}
        self.adjustment_cluster_results: Dict[int, Dict[int, dict]] = defaultdict(dict)
        # Khởi tạo RoundRobin Manager, trỏ Caster Host về cùng địa chỉ với MQTT Broker (thường chung server)
        ntrip_hosts = [
            host.strip()
            for host in settings.NTRIP_HOSTS.split(",")
            if host.strip()
        ]
        ntrip_hosts = list(dict.fromkeys(ntrip_hosts))
        if not ntrip_hosts:
            ntrip_hosts = [settings.MQTT_BROKER]
        primary_ntrip_host = ntrip_hosts[0]
        self.round_robin_manager = RoundRobinAdjustmentManager(
            self.client,
            caster_host=primary_ntrip_host,
            caster_hosts=ntrip_hosts,
            caster_port=settings.NTRIP_PORT,
            source_host=primary_ntrip_host,
            source_port=settings.NTRIP_PORT,
            control_password=settings.NTRIP_PASSWORD,
            source_password=settings.NTRIP_PASSWORD,
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
            reference_change_callback=self._handle_gnss_reference_change,
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
        self._latest_cache_buffer: dict = {}    # {(station_id, sensor_type): newest row}
        self._buffer_lock = asyncio.Lock()
        self._sensor_db_lock = asyncio.Lock()
        self._ingest_spool = IngestSpool()
        self._ingest_spool_ids = set()
        self._ingest_metrics = {
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
        self._flush_interval: int = 5  # giây – flush mỗi 5 giây 1 lần
        self._diag_last_log_ts = defaultdict(int)
        # Coalesce best-effort latest-value work. Fragmented GNSS/AGRICA can
        # create several pipeline tasks per second for one station; one DB
        # transaction per fragment can exhaust the connection pool.
        self._alert_suppression_last_attempt = defaultdict(float)
        self._alert_suppression_interval_seconds = 5.0

        self.loop = None
        self._stopping = False
        self._background_tasks = set()
        self._threadsafe_futures = set()
