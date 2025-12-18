# backend/app/config.py
from pydantic_settings import BaseSettings
from urllib.parse import quote_plus # Thư viện để xử lý ký tự đặc biệt trong mật khẩu

class Settings(BaseSettings):
    # Cấu hình PostgreSQL
    DB_USER: str = "postgres"
    # Mật khẩu gốc là 'aitogy@aitogy', quote_plus sẽ chuyển nó thành 'aitogy%40aitogy'
    DB_PASSWORD: str = quote_plus("aitogy@aitogy")
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"

    # --- 1. DATABASE URLs (Đã chuyển sang PostgreSQL) ---
    # Cấu trúc: postgresql+asyncpg://user:pass@host:port/dbname
    
    @property
    def AUTH_DB_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/landslide_auth"

    @property
    def CONFIG_DB_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/landslide_config"

    @property
    def DATA_DB_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/landslide_data"
    
    # --- 2. CÁC CẤU HÌNH KHÁC (GIỮ NGUYÊN) ---
    SECRET_KEY: str = "super_secret_key_change_me_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    MQTT_BROKER: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USER: str = ""
    MQTT_PASSWORD: str = ""
    TOPIC_RELOAD_INTERVAL: int = 60

    SAVE_INTERVAL_DEFAULT: int = 60
    SAVE_INTERVAL_GNSS: int = 86400
    SAVE_INTERVAL_RAIN: int = 3600
    SAVE_INTERVAL_WATER: int = 3600
    SAVE_INTERVAL_IMU: int = 2592000

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()