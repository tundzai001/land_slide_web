# ==============================================================================
# == backend/mqtt_bridge.py - MQTT to Database Bridge (FINAL FIXED)           ==
# ==============================================================================

import asyncio
import json
import logging
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt
from sqlalchemy import select
from app.websocket import manager
from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import config as model_config
from app.models import data as model_data
from app.config import settings
from app.landslide_analyzer import LandslideAnalyzer

from processors.gnss_processor import GNSSVelocityProcessor
from processors.water_processor import WaterEngine, RainEngine
from processors.imu_processor import IMUEngine

from .aes128decrypt import aes128_decrypt_base64

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
        self.last_save_time: Dict[str, float] = {}
        
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
                            self.processors_cache[proc_key] = IMUEngine()
                    
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
                    elif sensor_type == 'imu': processed_data = processor.process(payload_json)
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
        if alert and alert.get('level') in ['WARNING', 'CRITICAL']:
            is_dangerous = True
            try:
                await manager.broadcast({
                    "type": "station_status",
                    "station_id": station_id,
                    "risk_level": alert['level']
                })
                logger.warning(f"🚨 [{station_name}] Alert sent: {alert['message']}")
            except Exception as e:
                logger.error(f"❌ WS Alert Error: {e}")
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

        # 3. SAVE TO DB (THROTTLED)
        # Chỉ lưu khi nguy hiểm HOẶC đến chu kỳ lưu
        save_data_now = False

        if is_dangerous:
            save_data_now = True
        else:
            throttle_key = f"{device_id}_{sensor_type}"
            last_saved = self.last_save_time.get(throttle_key, 0)
            
            interval = settings.SAVE_INTERVAL_DEFAULT
            if sensor_type == 'gnss': interval = settings.SAVE_INTERVAL_GNSS
            elif sensor_type == 'imu': interval = settings.SAVE_INTERVAL_IMU
            elif sensor_type == 'rain': interval = settings.SAVE_INTERVAL_RAIN
            elif sensor_type == 'water': interval = settings.SAVE_INTERVAL_WATER
            
            if current_timestamp - last_saved >= interval:
                save_data_now = True

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
                    # Lưu dữ liệu cảm biến
                    db_data.add(model_data.SensorData(
                        station_id=station_id,  
                        timestamp=current_timestamp,
                        sensor_type=sensor_type,
                        data=processed_data,
                        value_1=processed_data.get('speed_2d_mm_s') if sensor_type == 'gnss' else processed_data.get('water_level'),
                        value_2=processed_data.get('total_displacement_mm') if sensor_type == 'gnss' else processed_data.get('intensity_mm_h'),
                    ))
                    self.last_save_time[f"{device_id}_{sensor_type}"] = current_timestamp

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