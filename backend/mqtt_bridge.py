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
from sqlalchemy import select, and_
from app.websocket import manager
from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import config as model_config
from app.models import data as model_data
from app.services.incident_cases import append_event, serialize_case
from app.config import settings
from app.landslide_analyzer import LandslideAnalyzer
from app.mqtt.persistence import MQTTPersistenceMixin
from app.mqtt.transport import MQTTTransportMixin
from app.services import adjustment_failure
from app.services.ingest_spool import IngestSpool

from processors.gnss_processor import GNSSVelocityProcessor
from processors.water_processor import WaterEngine, RainEngine
from processors.imu_processor import IMUEngine
from processors.gnss_adjustment.reporting import AdjustmentReportMixin
try:
    # Prefer the backend package when Uvicorn is launched from repository root;
    # this avoids importing the legacy top-level processors/ copy.
    from backend.processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
except ModuleNotFoundError:
    # backend/server.py runs with backend/ itself as sys.path[0].
    from processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager

# from aes128decrypt import aes128_decrypt_base64  # tạm vô hiệu hoá

logger = logging.getLogger(__name__)

class MQTTBridge(AdjustmentReportMixin, MQTTTransportMixin, MQTTPersistenceMixin):
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

    def _adjustment_run_context(self, run_id: int) -> dict:
        if not hasattr(self, "adjustment_run_contexts"):
            self.adjustment_run_contexts = {}
        if not hasattr(self, "adjustment_cluster_results"):
            self.adjustment_cluster_results = defaultdict(dict)
        context = dict(self.adjustment_run_contexts.get(int(run_id)) or {})
        context.setdefault("run_id", int(run_id))
        context.setdefault("project_id", int(run_id))
        context.setdefault("project_code", "")
        context.setdefault("cluster_name", "Cụm")
        self.adjustment_run_contexts.setdefault(int(run_id), context)
        self.adjustment_cluster_results.setdefault(int(context["project_id"]), {})
        return context

    def _refresh_project_adjustment_state(self, project_id: int) -> tuple[str, dict]:
        contexts = [
            context
            for context in self.adjustment_run_contexts.values()
            if int(context.get("project_id") or 0) == int(project_id)
        ]
        active = [
            context for context in contexts
            if context.get("status") in {"STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
        ]
        if active:
            statuses = {context.get("status") for context in active}
            phase = "PAUSED" if statuses == {"PAUSED"} else (
                "FREE_NETWORK" if "FREE_NETWORK" in statuses else "COLLECTING_BASELINE"
            )
        else:
            terminal = {str(context.get("status") or "") for context in contexts}
            failed = terminal.intersection({"ERROR", "FAILED_QUALITY_GATE"})
            completed = "COMPLETED" in terminal
            phase = "PARTIAL_FAILED" if failed and completed else (
                "FAILED_QUALITY_GATE" if terminal == {"FAILED_QUALITY_GATE"} else (
                    "ERROR" if failed else "COMPLETED"
                )
            )
        self.adjustment_phase[int(project_id)] = phase
        results = self.adjustment_cluster_results.get(int(project_id), {})
        ordered_results = sorted(
            results.values(),
            key=lambda item: (
                item.get("cluster_index") is None,
                int(item.get("cluster_index") or 0),
                str(item.get("cluster_name") or ""),
            ),
        )
        latest = ordered_results[-1] if ordered_results else {}
        summary = {
            **latest,
            "project_id": int(project_id),
            "phase": phase,
            "cluster_results": ordered_results,
        }
        if ordered_results:
            self.adjustment_results[int(project_id)] = summary
        return phase, summary

    async def _handle_round_robin_adjustment_result(self, project_id: int, adjustment: dict):
        """Always persist audit reports; publish coordinates only after quality PASS."""
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(
            adjustment.get("cluster_name")
            or run_context.get("cluster_name")
            or "Cụm"
        )
        adjustment["project_id"] = public_project_id
        adjustment["project_code"] = (
            adjustment.get("project_code") or run_context.get("project_code")
        )
        adjustment["cluster_name"] = cluster_name
        if run_context.get("cluster_index") is not None:
            adjustment["cluster_index"] = int(run_context["cluster_index"])
        adjustment["run_id"] = run_id
        current_timestamp = int(time.time())
        try:
            report_urls = self._write_adjustment_reports(public_project_id, current_timestamp, adjustment)
        except Exception as exc:
            message = f"Bình sai đã tính xong nhưng không thể xuất JSON/XLSX: {exc}"
            logger.error("Project %s run %s: %s", public_project_id, run_id, message, exc_info=True)
            await self._handle_round_robin_adjustment_error(run_id, message)
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
            self.adjustment_phase[run_id] = "FAILED_QUALITY_GATE"
            self.adjustment_message[run_id] = message
            self.adjustment_run_contexts[run_id]["status"] = "FAILED_QUALITY_GATE"
            self.adjustment_cluster_results[public_project_id][run_id] = adjustment
            phase, summary = self._refresh_project_adjustment_state(public_project_id)
            await manager.broadcast({
                "type": "gnss_adjustment_progress",
                "project_id": public_project_id,
                "run_id": run_id,
                "cluster_name": cluster_name,
                "phase": phase,
                "message": f"{cluster_name}: {message}",
                "timestamp": current_timestamp,
                "data": summary,
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
        self.adjustment_phase[run_id] = "COMPLETED"
        self.adjustment_message[run_id] = completed_message
        self.adjustment_run_contexts[run_id]["status"] = "COMPLETED"
        self.adjustment_cluster_results[public_project_id][run_id] = adjustment
        phase, summary = self._refresh_project_adjustment_state(public_project_id)
        self.adjustment_message[public_project_id] = f"{cluster_name}: {completed_message}"

        for point in adjustment.get("points", {}).values():
            station_id = point.get("station_id")
            if not station_id:
                continue
            payload = {
                "station_id": station_id,
                "timestamp": current_timestamp,
                "sensor_type": "gnss_adjusted",
                "ingest_id": self._make_ingest_id(
                    0, station_id, "gnss_adjusted", current_timestamp, adjustment
                ),
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
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": f"{cluster_name}: {completed_message}",
            "timestamp": current_timestamp,
            # The UI may not currently be viewing one of the adjusted stations,
            # so publish the downloadable result on the project-level event too.
            "data": summary,
        })

    async def _handle_round_robin_adjustment_error(self, project_id: int, message: str):
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(run_context.get("cluster_name") or "Cụm")
        diagnostics = self.round_robin_manager.get_adjustment_diagnostics(run_id)
        try:
            await self.round_robin_manager.restore_common_fixed_base_topology(run_id)
        except Exception as restore_exc:
            logger.error(
                "Could not restore fixed-base topology for run %s: %s",
                run_id,
                restore_exc,
                exc_info=True,
            )
            message = f"{message}; topology restore failed: {restore_exc}"
        self.adjustment_phase[run_id] = "ERROR"
        self.adjustment_message[run_id] = message
        if run_id in self.adjustment_run_contexts:
            self.adjustment_run_contexts[run_id]["status"] = "ERROR"
        failure_result = adjustment_failure.write_adjustment_failure_report(
            public_project_id,
            message,
            source="round_robin_runtime",
            project_code=str(run_context.get("project_code") or "") or None,
            cluster_name=cluster_name,
            context={
                "phase": "FREE_NETWORK",
                "run_id": run_id,
                "cluster_index": run_context.get("cluster_index"),
                "diagnostics": diagnostics,
            },
        )
        if failure_result:
            failure_result["run_id"] = run_id
            self.adjustment_cluster_results[public_project_id][run_id] = failure_result
        else:
            self.adjustment_cluster_results[public_project_id].pop(run_id, None)
        phase, summary = self._refresh_project_adjustment_state(public_project_id)
        self.adjustment_message[public_project_id] = f"{cluster_name}: {message}"
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": f"{cluster_name}: {message}",
            "data": summary,
        })

    async def _handle_round_robin_progress(self, project_id: int, message: str):
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(run_context.get("cluster_name") or "Cụm")
        self.adjustment_message[run_id] = message
        phase = str(self.adjustment_phase.get(run_id) or "").upper()
        if phase not in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}:
            # Receiver health preflight runs inside the start request, before the
            # persistent phase is installed. Do not mislabel those messages as
            # FREE_NETWORK/solver work.
            phase = "COLLECTING_BASELINE"
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": f"{cluster_name}: {message}",
        })

    async def process_pipeline(self, info: dict, raw_payload: str):
        if not info: return
        adjustment_only = bool(info.get("_adjustment_only"))
        public_project_id = int(
            info.get("public_project_id")
            or info.get("project_id")
            or info.get("station_id")
            or 0
        )
        if not adjustment_only and info.get("type") == "gnss":
            station_id = int(info.get("station_id") or 0)
            parallel_run_ids = [
                int(run_id)
                for run_id, context in list(self.adjustment_run_contexts.items())
                if int(context.get("project_id") or 0) == public_project_id
                and int(run_id) != public_project_id
                and str(self.adjustment_phase.get(int(run_id)) or "").upper()
                    in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
                and any(
                    station_id in [int(value) for value in cluster.get("stations", [])]
                    for cluster in self.active_adjustment_clusters.get(int(run_id), [])
                )
            ]
            for run_id in parallel_run_ids:
                await self.process_pipeline(
                    {
                        **info,
                        "project_id": run_id,
                        "public_project_id": public_project_id,
                        "_adjustment_only": True,
                    },
                    raw_payload,
                )
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
        if not adjustment_only:
            await self._touch_online_heartbeat(device_id, station_id, current_timestamp)
        
        # 1. PROCESS DATA
        try:
            if sensor_type == 'gnss':
                # AGRICA may arrive as multiple MQTT payloads.  Once a station
                # has sent the #AGRICA prefix, keep feeding its subsequent
                # fragments even though those fragments do not repeat the prefix.
                proj_id = int(info.get("project_id") or info.get("station_id") or 0)
                phase = self.adjustment_phase.get(proj_id)
                if proj_id not in self.round_robin_manager._sessions:
                    phase = None
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
                                    "project_id": public_project_id,
                                    "run_id": proj_id,
                                    "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
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
                                    "project_id": public_project_id,
                                    "run_id": proj_id,
                                    "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
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
                            active_session = (
                                self.round_robin_manager._sessions.get(proj_id) or {}
                            )
                            expected_station_ids = sorted({
                                int(station_id)
                                for cluster in active_session.get("clusters") or ()
                                for station_id in cluster.get("stations") or ()
                            })
                            roster = getattr(self, "adjustment_run_rosters", {}).get(proj_id) or {}
                            roster["participating_station_ids"] = expected_station_ids
                            roster["skipped_seed_station_ids"] = sorted({
                                *roster.get("skipped_seed_station_ids", []),
                                *skipped_station_ids,
                            })
                            if hasattr(self, "adjustment_run_rosters"):
                                self.adjustment_run_rosters[proj_id] = roster
                            self.adjustment_phase[proj_id] = "FREE_NETWORK"
                            if proj_id in self.adjustment_run_contexts:
                                self.adjustment_run_contexts[proj_id]["status"] = "FREE_NETWORK"
                            await manager.broadcast({
                                "type": "gnss_adjustment_progress",
                                "project_id": public_project_id,
                                "run_id": proj_id,
                                "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
                                "phase": "FREE_NETWORK",
                                "expected_station_ids": expected_station_ids,
                                "roster": roster,
                                "message": (
                                    "Skipped offline/degraded station IDs "
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

                if adjustment_only:
                    return

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
                            "raw_payload": res.get('raw_payload', ''),
                            "data": res.get('data'),
                        }
                        
                        if res.get('status') in {
                            'INITIALIZING', 'VELOCITY_WARMUP', 'INVALID_DATA',
                            'UNVERIFIED_POSITION_SHIFT', 'UNTRUSTED_GEOMETRY',
                            'PERSISTENT_OFFSET_QUARANTINED', 'REJECTED_MEASUREMENT',
                            'UNSTABLE_FIX', 'REFERENCE_CHANGE_PENDING',
                            'STALE_REFERENCE', 'REACQUIRE_REFUSED',
                            'CHECKSUM_FAILED', 'NO_DATA',
                        }:
                            # Keep an existing unresolved GNSS alert alive
                            # while the processor is quarantined/warming up;
                            # this is not a safe reading and must not expire
                            # merely because the service restarted.
                            try:
                                await self._touch_active_alert(
                                    station_id,
                                    'gnss_velocity',
                                    current_timestamp,
                                )
                            except Exception as touch_error:
                                logger.error(f"❌ GNSS active-alert refresh failed: {touch_error}")
                            # Immediate buffering for anomalies can be disabled
                            # per station without stopping processing or alerts.
                            if self._is_processing_storage_enabled(station_config):
                                anomaly_record = {
                                    "station_id": station_id,
                                    "timestamp": current_timestamp,
                                    "sensor_type": "gnss_anomaly",
                                    "ingest_id": self._make_ingest_id(
                                        device_id,
                                        station_id,
                                        "gnss_anomaly",
                                        current_timestamp,
                                        status_payload,
                                        raw_payload,
                                    ),
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
                        "ingest_id": self._make_ingest_id(
                            device_id,
                            station_id,
                            sensor_type,
                            current_timestamp,
                            processed_data,
                            raw_payload,
                        ),
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
                    await self._buffer_sensor_record(
                        device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload
                    )
                    await self._flush_write_buffer()
                    logger.info(f"💾 [RESOLVE FLUSH] {station_name} - {sensor_type.upper()} ts={current_timestamp} written immediately")
                else:
                    # ✅ BÌNH THƯỜNG → Đưa vào buffer, flush theo chu kỳ
                    await self._buffer_sensor_record(
                        device_id, station_id, sensor_type, current_timestamp, processed_data, raw_payload
                    )

        except Exception as e:
            logger.error(f"❌ DB Error: {e}")
