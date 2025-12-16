# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # --- 1. DATABASE URLs (3 DB riêng biệt) ---
    AUTH_DB_URL: str = "sqlite+aiosqlite:///./db_auth.sqlite"
    CONFIG_DB_URL: str = "sqlite+aiosqlite:///./db_config.sqlite"
    DATA_DB_URL: str = "sqlite+aiosqlite:///./db_sensor_data.sqlite"
    
    # --- 2. SECURITY (JWT) - QUAN TRỌNG ĐỂ FIX LỖI ---
    SECRET_KEY: str = "super_secret_key_change_me_in_production"
    ALGORITHM: str = "HS256"  # ✅ Đây là dòng bị thiếu gây ra lỗi
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 # Thời gian hết hạn token
    
    # --- 3. MQTT CONFIG ---
    MQTT_BROKER: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USER: str = ""
    MQTT_PASSWORD: str = ""
    TOPIC_RELOAD_INTERVAL: int = 60

    # --- 4. DATA SAVING INTERVALS (Giây) ---
    SAVE_INTERVAL_GNSS: int = 86400    # 1 ngày
    SAVE_INTERVAL_ENV: int = 3600      # 1 giờ (Mưa/Nước)
    SAVE_INTERVAL_IMU: int = 2592000   # 1 tháng

    class Config:
        env_file = ".env"
        extra = "ignore" # Bỏ qua các biến thừa trong .env

settings = Settings()