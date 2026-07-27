# backend/app/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 1. DATABASE URLs ---
    # Pydantic sẽ tự động đọc giá trị từ file .env khớp với tên biến
    # Nếu không đọc được .env, nó sẽ dùng giá trị mặc định bên phải (dự phòng)
    
    AUTH_DB_URL: str = ""
    CONFIG_DB_URL: str = ""
    DATA_DB_URL: str = ""

    # --- 2. CÁC CẤU HÌNH KHÁC ---
    SECRET_KEY: str = "super_secret_key_change_me_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    MQTT_BROKER: str = ""
    MQTT_PORT: int = 1883
    MQTT_USER: str = "mqttUser"
    MQTT_PASSWORD: str = ""
    TOPIC_RELOAD_INTERVAL: int = 60

    # Shared AICaster endpoints for SOURCE upload, control-table lookup and SET
    # commands. Order is primary -> failover; project-specific stream settings
    # may still select the exact host serving a fixed base.
    NTRIP_HOSTS: str = ""
    NTRIP_PORT: int = 2101
    NTRIP_PASSWORD: str = ""
    # Login/API credentials of the WEB CORS dashboard (cors.aitogy.com).
    # These are not NTRIP/Caster usernames or mountpoint passwords.
    WEB_CORS_API_BASE_URL: str = ""
    CORS_BASE_STATIONS_URL: str = ""
    CORS_BASE_STATIONS_CACHE_TTL_SECONDS: float = 20.0
    CORS_BASE_STATIONS_STALE_TTL_SECONDS: float = 300.0
    CORS_BASE_STATIONS_RETRY_SECONDS: float = 15.0
    GNSS_CORS_FAILOVER_POLL_SECONDS: float = 5.0
    WEB_CORS_API_TOKEN: str = ""
    WEB_CORS_API_USERNAME: str = ""
    WEB_CORS_API_PASSWORD: str = ""

    SAVE_INTERVAL_DEFAULT: int = 60
    SAVE_INTERVAL_GNSS: int = 1
    SAVE_INTERVAL_RAIN: int = 3600
    SAVE_INTERVAL_WATER: int = 3600
    SAVE_INTERVAL_IMU: int = 2592000

    # GNSS rollup/purge workflow: thu thập dày theo giây, chốt ngày/tuần rồi dọn raw.
    GNSS_ROLLUP_INTERVAL_SECONDS: int = 300
    GNSS_PURGE_RAW_AFTER_DAILY_ROLLUP: bool = False

settings = Settings()
