# ==============================================================================
# == backend/mqtt_bridge.py - MQTT to Database Bridge (FIXED)
# ==============================================================================

import asyncio
import json
import logging
import time
import signal
import sys
from typing import Dict, Any, Optional

import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import ConfigSessionLocal, DataSessionLocal
from app.models import config as model_config
from app.models import data as model_data
from app.config import settings
from app.landslide_analyzer import LandslideAnalyzer

from processors.gnss_processor import GNSSVelocityProcessor
from processors.water_processor import WaterEngine, RainEngine
from processors.imu_processor import IMUEngine

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
        logger.info("🚀 Initializing MQTT Bridge...")
        
        # 1. Khởi tạo Analyzer (Bộ não phân tích rủi ro)
        self.analyzer = LandslideAnalyzer()
        
        # 2. Khởi tạo MQTT Client
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings.MQTT_USER:
            self.client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
            
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # 3. Quản lý Topic & Processor
        # topic_map[topic] = {station_id, type, processor, config}
        self.topic_map: Dict[str, Dict[str, Any]] = {}
        
        # Cache processors để giữ trạng thái (history, origin...) qua các lần gọi
        self.processors_cache: Dict[str, Any] = {}
        
        # 4. Quản lý thời gian lưu DB (Throttling)
        # Key: "station_id_sensor_type" -> Value: timestamp lần lưu cuối
        self.last_save_time: Dict[str, float] = {}
        
        # 5. Event loop reference
        self.loop = None

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("✅ MQTT Connected to Broker.")
            # Subscribe lại khi reconnect
            for topic in self.topic_map.keys():
                client.subscribe(topic)
                logger.info(f"   ✓ Subscribed: {topic}")
        else:
            logger.error(f"❌ MQTT Connection failed: rc={rc}")

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning(f"⚠️ Unexpected MQTT disconnect: rc={rc}. Reconnecting...")

    def on_message(self, client, userdata, msg):
        """Callback nhận tin nhắn -> Đẩy vào Event Loop Async"""
        try:
            topic = msg.topic
            payload_str = msg.payload.decode('utf-8')
            
            # Đẩy vào async queue
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.process_pipeline(topic, payload_str), 
                    self.loop
                )
        except Exception as e:
            logger.error(f"Error in on_message: {e}", exc_info=True)

    async def reload_topics_from_db(self):
        """
        Định kỳ đọc DB Config để cập nhật danh sách Topic cần subscribe.
        ✅ FIXED: Đọc topics từ config JSON thay vì attributes trực tiếp
        """
        while True:
            try:
                # Dùng Config DB để đọc danh sách trạm
                async with ConfigSessionLocal() as db:
                    result = await db.execute(select(model_config.Station))
                    stations = result.scalars().all()
                
                new_map = {}
                
                for s in stations:
                    # ✅ FIXED: Đọc topics từ JSON config
                    mqtt_topics = s.config.get('mqtt_topics', {}) if s.config else {}
                    
                    # Helper đăng ký sensor
                    def register(topic, sensor_type):
                        if not topic or topic.strip() == "":
                            return
                        
                        # Key duy nhất cho processor cache (VD: "1_gnss")
                        proc_key = f"{s.id}_{sensor_type}"
                        
                        # Tạo mới hoặc lấy lại processor cũ
                        if proc_key not in self.processors_cache:
                            if sensor_type == 'gnss':
                                self.processors_cache[proc_key] = GNSSVelocityProcessor()
                            elif sensor_type == 'rain':
                                self.processors_cache[proc_key] = RainEngine()
                            elif sensor_type == 'water':
                                self.processors_cache[proc_key] = WaterEngine()
                            elif sensor_type == 'imu':
                                self.processors_cache[proc_key] = IMUEngine()
                        
                        new_map[topic] = {
                            "station_id": s.id,
                            "station_name": s.name,
                            "type": sensor_type,
                            "processor": self.processors_cache[proc_key],
                            "config": s.config or {}
                        }

                    # ✅ FIXED: Đọc từ mqtt_topics trong config
                    if s.has_gnss:
                        register(mqtt_topics.get('gnss'), 'gnss')
                    if s.has_rain:
                        register(mqtt_topics.get('rain'), 'rain')
                    if s.has_water:
                        register(mqtt_topics.get('water'), 'water')
                    if s.has_imu:
                        register(mqtt_topics.get('imu'), 'imu')

                # Xử lý Subscribe/Unsubscribe thay đổi
                current_topics = set(self.topic_map.keys())
                new_topics = set(new_map.keys())
                
                for t in new_topics - current_topics:
                    self.client.subscribe(t)
                    logger.info(f"➕ Subscribed: {t}")
                
                for t in current_topics - new_topics:
                    self.client.unsubscribe(t)
                    logger.info(f"➖ Unsubscribed: {t}")
                
                self.topic_map = new_map
                logger.debug(f"♻️ Topics reloaded. Active: {len(self.topic_map)}")

            except Exception as e:
                logger.error(f"Error reloading topics: {e}", exc_info=True)
            
            # ✅ FIXED: Dùng settings.TOPIC_RELOAD_INTERVAL
            await asyncio.sleep(settings.TOPIC_RELOAD_INTERVAL)

    async def process_pipeline(self, topic: str, raw_payload: str):
        """
        Pipeline xử lý chính:
        1. MQTT -> 2. Processor -> 3. Analyzer -> 4. DB (Có điều kiện)
        """
        # 1. Xác định trạm & sensor
        info = self.topic_map.get(topic)
        if not info:
            logger.debug(f"Unknown topic: {topic}")
            return
            
        station_id = info['station_id']
        station_name = info['station_name']
        sensor_type = info['type']
        processor = info['processor']
        station_config = info['config']
        
        current_timestamp = int(time.time())
        processed_data = None
        
        # 2. XỬ LÝ DỮ LIỆU (Processor)
        try:
            if sensor_type == 'gnss':
                # GNSS Processor nhận raw string (GNGGA)
                res = processor.process_gngga(raw_payload)
                if res and res.get('type') == 'gnss_processed':
                    processed_data = res.get('data')
                elif res and res.get('type') == 'origin_locked':
                    # ✅ NEW: Log khi origin được khóa
                    logger.info(f"🎯 [{station_name}] GNSS Origin locked: {res.get('data')}")
                    return
            else:
                # Các sensor khác nhận JSON Dict
                try:
                    payload_json = json.loads(raw_payload)
                    if sensor_type == 'rain':
                        processed_data = processor.process(payload_json, current_timestamp)
                    elif sensor_type == 'water':
                        processed_data = processor.process(payload_json, current_timestamp)
                    elif sensor_type == 'imu':
                        processed_data = processor.process(payload_json)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error ({sensor_type}): {e}")
                    return
        except Exception as e:
            logger.error(f"Processing error ({sensor_type}): {e}", exc_info=True)
            return

        if not processed_data:
            return

        # 3. PHÂN TÍCH RỦI RO (Analyzer) - Luôn chạy để cảnh báo tức thời
        alert = None
        
        # Tạo list wrapper vì Analyzer nhận list data history
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
            logger.error(f"Analyzer error ({sensor_type}): {e}", exc_info=True)

        # 4. QUYẾT ĐỊNH LƯU DB (Throttling Strategy)
        save_data_now = False
        is_dangerous = False

        # A. Nếu có cảnh báo NGUY HIỂM -> Lưu ngay lập tức
        if alert and alert.get('level') in ['WARNING', 'CRITICAL']:
            save_data_now = True
            is_dangerous = True
            logger.warning(f"🚨 [{station_name}] {sensor_type.upper()}: {alert['message']}")
        
        # B. Nếu không nguy hiểm -> Kiểm tra định kỳ
        else:
            throttle_key = f"{station_id}_{sensor_type}"
            last_saved = self.last_save_time.get(throttle_key, 0)
            
            # ✅ FIXED: Lấy interval từ settings
            interval = settings.SAVE_INTERVAL_DEFAULT
            if sensor_type == 'gnss':
                interval = settings.SAVE_INTERVAL_GNSS
            elif sensor_type == 'imu':
                interval = settings.SAVE_INTERVAL_IMU
            elif sensor_type == 'rain':
                interval = settings.SAVE_INTERVAL_RAIN
            elif sensor_type == 'water':
                interval = settings.SAVE_INTERVAL_WATER
            
            if current_timestamp - last_saved >= interval:
                save_data_now = True

        # 5. THỰC THI LƯU TRỮ
        try:
            # A. Update trạng thái trạm (Online) -> CONFIG DB
            async with ConfigSessionLocal() as db_config:
                await db_config.execute(
                    model_config.Station.__table__.update()
                    .where(model_config.Station.id == station_id)
                    .values(last_update=current_timestamp, status="online")
                )
                await db_config.commit()

            # B. Lưu Dữ liệu & Alert -> DATA DB
            if save_data_now or is_dangerous:
                async with DataSessionLocal() as db_data:
                    # Lưu Sensor Data
                    if save_data_now:
                        db_data.add(model_data.SensorData(
                            station_id=station_id,
                            timestamp=current_timestamp,
                            sensor_type=sensor_type,
                            data=processed_data
                        ))
                        # Cập nhật thời gian lưu
                        self.last_save_time[f"{station_id}_{sensor_type}"] = current_timestamp
                        
                        # Log nhẹ cho periodic save
                        if not is_dangerous:
                            logger.debug(f"💾 [{station_name}] {sensor_type}: Saved")

                    # Lưu Alert History
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
            logger.error(f"❌ DB Error: {e}", exc_info=True)

    def run(self):
        """Khởi chạy Bridge"""
        logger.info("=" * 70)
        logger.info("🚀 Starting MQTT Bridge")
        logger.info(f"   Broker: {settings.MQTT_BROKER}:{settings.MQTT_PORT}")
        logger.info(f"   User: {settings.MQTT_USER or 'anonymous'}")
        logger.info("=" * 70)
        
        try:
            # Setup AsyncIO Loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Connect MQTT
            self.client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
            self.client.loop_start()
            
            # Chạy task reload DB song song
            self.loop.create_task(self.reload_topics_from_db())
            
            logger.info("✅ Bridge is running. Press Ctrl+C to stop.")
            
            # Giữ process chạy
            self.loop.run_forever()
            
        except KeyboardInterrupt:
            logger.info("🛑 Stopping Bridge (KeyboardInterrupt)...")
            self.client.loop_stop()
            self.client.disconnect()
            self.loop.stop()
        except Exception as e:
            logger.critical(f"🔥 Fatal Error: {e}", exc_info=True)
        finally:
            logger.info("✅ Bridge stopped.")

if __name__ == "__main__":
    bridge = MQTTBridge()
    bridge.run()