# backend/app/config.py
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # --- 1. DATABASE URLs ---
    # Pydantic sẽ tự động đọc giá trị từ file .env khớp với tên biến
    # Nếu không đọc được .env, nó sẽ dùng giá trị mặc định bên phải (dự phòng)
    
    AUTH_DB_URL: str = "postgresql+asyncpg://postgres:password@127.0.0.1:5432/landslide_auth"
    CONFIG_DB_URL: str = "postgresql+asyncpg://postgres:password@127.0.0.1:5432/landslide_config"
    DATA_DB_URL: str = "postgresql+asyncpg://postgres:password@127.0.0.1:5432/landslide_data"

    # --- 2. CÁC CẤU HÌNH KHÁC ---
    SECRET_KEY: str = "super_secret_key_change_me_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    MQTT_BROKER: str = "aitogy.asia"
    MQTT_PORT: int = 1883
    MQTT_USER: str = "mqttUser"
    MQTT_PASSWORD: str = ""
    TOPIC_RELOAD_INTERVAL: int = 60

    # AICaster uses a control/tunnel port for /clienttable and SET, while an
    # NTRIP SOURCE normally connects to the caster's NTRIP port.  Keeping the
    # two endpoints separate prevents Round-Robin from sending SOURCE requests
    # to the SET control socket.
    NTRIP_CONTROL_HOST: str = ""
    NTRIP_CONTROL_HOSTS: str = "aitogy.com.vn,aitogy.click"
    NTRIP_CONTROL_PORT: int = 2101
    NTRIP_CONTROL_PASSWORD: str = "12345"
    NTRIP_SOURCE_HOST: str = "aitogy.click"
    NTRIP_SOURCE_PORT: int = 2101
    NTRIP_SOURCE_PASSWORD: str = "12345"

    SAVE_INTERVAL_DEFAULT: int = 60
    SAVE_INTERVAL_GNSS: int = 1
    SAVE_INTERVAL_RAIN: int = 3600
    SAVE_INTERVAL_WATER: int = 3600
    SAVE_INTERVAL_IMU: int = 2592000

    # GNSS rollup/purge workflow: thu thập dày theo giây, chốt ngày/tuần rồi dọn raw.
    GNSS_ROLLUP_INTERVAL_SECONDS: int = 300
    GNSS_PURGE_RAW_AFTER_DAILY_ROLLUP: bool = False

    class Config:
        # Chỉ định đường dẫn tuyệt đối tới file .env để chạy ổn định trên IIS
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"

settings = Settings()
