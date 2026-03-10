# ==============================================================================
# == backend/mqtt_bridge.py - MQTT to Database Bridge (FIXED WITH SAVE INTERVALS) ==
# ==============================================================================

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional
from collections import defaultdict

import paho.mqtt.client as mqtt
from sqlalchemy import select, update, and_, desc
from app.websocket import manager
from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import config as model_config
from app.models import data as model_data
from app.config import settings
from app.landslide_analyzer import LandslideAnalyzer

from processors.gnss_processor import GNSSVelocityProcessor
from processors.water_processor import WaterEngine, RainEngine
from processors.imu_processor import IMUEngine

# from .aes128decrypt import aes128_decrypt_base64

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - BRIDGE - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mqtt_bridge.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MQTTBridge:
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
        self.topic_map: Dict[str, Dict[str, Any]] = {}
        self.processors_cache: Dict[str, Any] = {}
        
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

        self.loop = None

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

        gnss_cfg = dict(cfg.get("GnssAlerting", {}) or {})
        rain_cfg = dict(cfg.get("RainAlerting", {}) or {})
        water_cfg = dict(cfg.get("Water", {}) or {})
        imu_cfg = dict(cfg.get("ImuAlerting", {}) or {})

        gnss_cfg.setdefault("gnss_confirm_steps", self.runtime_confirmation["gnss"])
        rain_cfg.setdefault("rain_confirm_steps", self.runtime_confirmation["rain"])
        water_cfg.setdefault("water_confirm_steps", self.runtime_confirmation["water"])
        imu_cfg.setdefault("imu_confirm_steps", self.runtime_confirmation["imu"])

        cfg["GnssAlerting"] = gnss_cfg
        cfg["RainAlerting"] = rain_cfg
        cfg["Water"] = water_cfg
        cfg["ImuAlerting"] = imu_cfg
        return cfg

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

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("✅ MQTT Connected to Broker.")
            for topic in self.topic_map.keys():
                client.subscribe(topic)
                logger.info(f"   ✓ Subscribed: {topic}")
        else:
            logger.error(f"❌ MQTT Connection failed: rc={rc}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if reason_code != 0:
            logger.warning(f"⚠️ MQTT disconnect: rc={reason_code}. Reconnecting...")
            try:
                client.reconnect()
                logger.info("✅ MQTT Reconnected successfully")
            except Exception as e:
                logger.error(f"❌ Reconnect failed: {e}. Will retry in 5s...")
                if self.loop and self.loop.is_running():
                    self.loop.call_later(5, self._retry_connect)
        else:
            logger.info("✅ MQTT Disconnected gracefully")

    def _retry_connect(self):
        try:
            self.client.reconnect()
            logger.info("✅ MQTT Reconnected after retry")
        except Exception as e:
            logger.error(f"❌ Retry failed: {e}. Next retry in 10s...")
            self.loop.call_later(10, self._retry_connect)

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            try:
                payload_str = msg.payload.decode('utf-8')
                # Bỏ qua giải mã AES theo yêu cầu người dùng
                decrypted_payload = payload_str
                
            except UnicodeDecodeError:
                return # Bỏ qua dữ liệu nhị phân (RTCM)
            
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.process_pipeline(topic, decrypted_payload), 
                    self.loop
                )
        except Exception as e:
            logger.error(f"Error in on_message: {e}")

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

    async def reload_topics_from_db(self):
        logger.info("🔄 Started Topic Auto-Reload Task")
        while True:
            try:
                await self.load_runtime_config_from_db()
                from app.models.config import Device, Station
                from sqlalchemy import select
                
                async with ConfigSessionLocal() as db:
                    result = await db.execute(
                        select(Device, Station)
                        .join(Station, Device.station_id == Station.id)
                        .where(Device.is_active == True)
                    )
                    devices_with_stations = result.all()
                
                new_map = {}
                for device, station in devices_with_stations:
                    if not device.mqtt_topic or device.mqtt_topic.strip() == "": continue
                    
                    topic = device.mqtt_topic
                    sensor_type = device.device_type
                    proc_key = f"device_{device.id}"
                    
                    if proc_key not in self.processors_cache:
                        if device.device_type == 'gnss':
                            self.processors_cache[proc_key] = GNSSVelocityProcessor(device.id, ConfigSessionLocal)
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
                    
                    new_map[topic] = {
                        "device_id": device.id,
                        "device_name": device.name,
                        "station_id": station.id,
                        "station_name": station.name,
                        "type": device.device_type,
                        "processor": self.processors_cache[proc_key],
                        "config": self._apply_runtime_defaults_to_station_config(station.config or {})
                    }

                # Diff subscribe/unsubscribe
                current_topics = set(self.topic_map.keys())
                new_topics = set(new_map.keys())
                for t in new_topics - current_topics: self.client.subscribe(t)
                for t in current_topics - new_topics: self.client.unsubscribe(t)
                self.topic_map = new_map

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
            sensor_batch = list(self._sensor_buffer)
            station_batch = dict(self._station_update_buffer)
            device_batch = dict(self._device_update_buffer)
            self._sensor_buffer.clear()
            self._station_update_buffer.clear()
            self._device_update_buffer.clear()

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
                logger.debug(f"💾 [BATCH CONFIG] {len(station_batch)} stations, {len(device_batch)} devices updated")
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
                db_data.add(model_data.SensorData(**sensor_record))
                # Tìm alert chưa resolve cùng category, cập nhật hoặc tạo mới
                res = await db_data.execute(
                    select(model_data.Alert).where(
                        and_(
                            model_data.Alert.station_id == station_id,
                            model_data.Alert.category == alert['category'],
                            model_data.Alert.is_resolved == False
                        )
                    )
                )
                existing_alert = res.scalar_one_or_none()
                if existing_alert:
                    existing_alert.timestamp = current_timestamp
                    existing_alert.level = alert['level']
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

    async def process_pipeline(self, topic: str, raw_payload: str):
        info = self.topic_map.get(topic)
        if not info: return
            
        device_id = info['device_id']
        station_id = info['station_id']
        station_name = info['station_name']
        sensor_type = info['type']
        processor = info['processor']
        station_config = info['config']
        
        current_timestamp = int(time.time())
        processed_data = None
        
        # 1. PROCESS DATA
        try:
            if sensor_type == 'gnss':
                res = processor.process_gngga(raw_payload)
                if res and res.get('type') == 'gnss_processed':
                    processed_data = res.get('data')
                elif res and res.get('type') == 'origin_locked':
                    logger.info(f"🎯 [{station_name}] GNSS Origin locked")
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

        # 2. ANALYZE
        alert = None
        data_wrapper = [{"timestamp": current_timestamp, "data": processed_data}]
        
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
        if alert and alert.get('level') in ['WARNING', 'CRITICAL']:
            is_dangerous = True
        elif alert and alert.get('level') == 'PENDING':
            is_pending = True
            
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
                    self.client.publish(cmd_topic, cmd_payload, qos=1)
                    logger.warning(f"🔊 [{station_name}] MQTT audio command → {cmd_topic}: {audio_code}")

                logger.warning(f"🚨 [{station_name}] Alert broadcast: {alert['message']}")
            except Exception as e:
                logger.error(f"❌ WS Alert Broadcast Error: {e}")
        elif not is_pending:
            # Nếu AN TOÀN -> Gửi LOW để UI chuyển về màu xanh ngay lập tức
            try:
                await manager.broadcast({
                    "type": "station_status",
                    "station_id": station_id,
                    "risk_level": "LOW"
                })
            except Exception as e:
                logger.error(f"❌ WS Low Status Error: {e}")
                
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
                            logger.info(f"✅ Auto-resolved {res.rowcount} alerts for station {station_id} (sensor: {sensor_type}). Sending stop_siren command...")
                            
                            # Gửi MQTT auto_stop_siren để Pi tắt loa nhưng không bị 'MUTE'
                            cmd_topic = f"landslide/{station_id}/command"
                            cmd_payload = json.dumps({"cmd": "auto_stop_siren", "ts": int(time.time())})
                            self.client.publish(cmd_topic, cmd_payload, qos=1)
            except Exception as e:
                logger.error(f"❌ Error auto-resolving alerts: {e}")

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
            if sensor_type == 'gnss': interval = self.runtime_save_intervals.get('gnss', settings.SAVE_INTERVAL_GNSS)
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

        try:
            if save_data_now:
                # ===== EXTRACT VALUES BASED ON SENSOR TYPE =====
                val_1, val_2, val_3, val_4, val_5 = 0.0, 0.0, 0.0, 0.0, 0.0

                if sensor_type == 'gnss':
                    val_1 = processed_data.get('speed_2d_mm_s', 0.0)
                    val_2 = processed_data.get('total_displacement_mm', 0.0)
                elif sensor_type == 'rain':
                    val_1 = processed_data.get('intensity_mm_h', 0.0)
                    val_2 = processed_data.get('accumulated_mm', 0.0)
                elif sensor_type == 'water':
                    val_1 = processed_data.get('water_level', 0.0)
                    val_2 = processed_data.get('intensity_mm_h', 0.0)
                elif sensor_type == 'imu':
                    val_1 = processed_data.get('roll', 0.0)
                    val_2 = processed_data.get('pitch', 0.0)
                    val_3 = processed_data.get('yaw', 0.0)
                    val_4 = processed_data.get('total_accel', 0.0)
                    val_5 = processed_data.get('battery', 0.0)

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

                if is_dangerous:
                    # ✅ ALERT → Ghi thẳng xuống DB, không qua buffer
                    await self._save_alert_immediate(device_id, station_id, sensor_record, alert, current_timestamp)
                else:
                    # ✅ BÌNH THƯỜNG → Đưa vào buffer, flush theo chu kỳ
                    async with self._buffer_lock:
                        self._sensor_buffer.append(sensor_record)
                        self._station_update_buffer[station_id] = {
                            "status": "online",
                            "last_update": current_timestamp
                        }
                        self._device_update_buffer[device_id] = current_timestamp

        except Exception as e:
            logger.error(f"❌ DB Error: {e}")