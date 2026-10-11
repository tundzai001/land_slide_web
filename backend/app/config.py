# backend/app/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

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
    BACKUP_SIGNING_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PRIVATE_AUTHZ_GRACE_SECONDS: int = 300
    AUTH_IDLE_TIMEOUT_SECONDS: int = Field(default=1800, ge=60, le=43200)
    PUBLIC_MONITORING_ENABLED: bool = False
    ENVIRONMENT: str = "production"
    PUBLIC_SITE_URL: str = "https://monitoring.aitogy.com"
    RESCUE_REQUEST_ENABLED: bool = True
    CORS_ORIGINS: str = "https://monitoring.aitogy.com,http://127.0.0.1:8001,http://localhost:8001"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 10
    DB_COMMAND_TIMEOUT_SECONDS: int = 30
    RUN_SCHEMA_BOOTSTRAP: bool = False
    # Backup archives live outside the web root by default on Windows servers.
    BACKUP_DIR: str = ""
    PROJECT_DEM_DIR: str = ""
    OPERATIONS_LOG_RETENTION_DAYS: int = 365
    NTP_SERVER: str = Field(default="pool.ntp.org", min_length=1, max_length=253, pattern=r'^[A-Za-z0-9.-]+$')
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    # The MQTT ingest spool is deliberately local and append-only.  It is a
    # last-resort handoff for a DB outage; normal traffic still drains through
    # the in-process batch buffer.  Deployments with a persistent volume may
    # point this at a dedicated path, while tests can inject a temporary one.
    INGEST_SPOOL_DIR: str = ""
    INGEST_SPOOL_MAX_BYTES: int = 256 * 1024 * 1024
    INGEST_SPOOL_RETRY_SECONDS: float = 5.0
    INGEST_SPOOL_BATCH_SIZE: int = 256
    FILE_CLEANUP_INTERVAL_SECONDS: float = 10.0
    FILE_CLEANUP_LEASE_SECONDS: int = 60
    FILE_CLEANUP_MAX_ATTEMPTS: int = 12

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
    CORS_BASE_STATIONS_TOKEN: str = ""
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

    def validate_security(self):
        if self.ALGORITHM != "HS256":
            raise RuntimeError("Only HS256 is supported for application tokens")
        if self.ENVIRONMENT.lower() == "production":
            if len(self.SECRET_KEY.encode()) < 32 or self.SECRET_KEY == "super_secret_key_change_me_in_production":
                raise RuntimeError("Configure a random SECRET_KEY of at least 32 bytes")
            if "*" in self.cors_origins:
                raise RuntimeError("Production CORS requires explicit origins")
        if not 1 <= self.ACCESS_TOKEN_EXPIRE_MINUTES <= 720:
            raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 720")
        if self.BOOTSTRAP_ADMIN_PASSWORD and (
            len(self.BOOTSTRAP_ADMIN_PASSWORD) < 12
            or len(self.BOOTSTRAP_ADMIN_PASSWORD.encode("utf-8")) > 72
        ):
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be 12+ characters and at most 72 UTF-8 bytes")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()
