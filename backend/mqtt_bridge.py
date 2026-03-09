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

from aes128decrypt import aes128_decrypt_base64

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
        if settings.MQTT_USER:
            self.client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
            
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # Topic management
        self.topic_map: Dict[str, Dict[str, Any]] = {}
        self.processors_cache: Dict[str, Any] = {}
        
        # ✅ THÊM: Save interval tracking (per station per sensor)
        self.last_save_time = defaultdict(lambda: defaultdict(int))  # {station_id: {sensor_type: timestamp}}
        
        self.loop = None

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
                # sẽ thêm hàm giải mã AES ở đoạn này
                decrypted_payload = str(aes128_decrypt_base64(bytearray(payload_str, 'utf-8')))
                
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
            self.client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
            self.client.loop_start()
            self.loop.create_task(self.reload_topics_from_db())
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
                        "config": station.config or {}
                    }

                # Diff subscribe/unsubscribe
                current_topics = set(self.topic_map.keys())
                new_topics = set(new_map.keys())
                for t in new_topics - current_topics: self.client.subscribe(t)
                for t in current_topics - new_topics: self.client.unsubscribe(t)
                self.topic_map = new_map

            except Exception as e:
                logger.error(f"Error reloading topics: {e}")
            await asyncio.sleep(settings.TOPIC_RELOAD_INTERVAL)

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
                        processed_data = processor.process(payload_json)
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
        if alert and alert.get('level') in ['WARNING', 'CRITICAL']:
            is_dangerous = True
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
        else:
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
            
            interval = settings.SAVE_INTERVAL_DEFAULT
            if sensor_type == 'gnss': interval = settings.SAVE_INTERVAL_GNSS
            elif sensor_type == 'imu': interval = settings.SAVE_INTERVAL_IMU
            elif sensor_type == 'rain': interval = settings.SAVE_INTERVAL_RAIN
            elif sensor_type == 'water': interval = settings.SAVE_INTERVAL_WATER
            
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
                 async with ConfigSessionLocal() as db_config:
                    from app.models.config import Device, Station
                    await db_config.execute(
                        Device.__table__.update().where(Device.id == device_id).values(last_data_time=current_timestamp)
                    )
                    await db_config.execute(
                        Station.__table__.update().where(Station.id == station_id).values(last_update=current_timestamp, status="online")
                    )
                    await db_config.commit()

            if save_data_now:
                async with DataSessionLocal() as db_data:
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
                    
                    # === LƯU VÀO DB ===
                    db_data.add(model_data.SensorData(
                        station_id=station_id,  
                        timestamp=current_timestamp,
                        sensor_type=sensor_type,
                        data=processed_data,
                        value_1=val_1,
                        value_2=val_2,
                        value_3=val_3,
                        value_4=val_4,
                        value_5=val_5
                    ))
                    # ✅ CẬP NHẬT LAST SAVE TIME (theo station + sensor_type)
                    self.last_save_time[station_id][sensor_type] = current_timestamp

                    # Chỉ lưu cảnh báo nếu nguy hiểm
                    if is_dangerous:
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
            logger.error(f"❌ DB Error: {e}")