# backend/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Hàm tạo engine chung cho Postgres
def create_pg_engine(url):
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=20,        # Tăng lên 20 để phục vụ nhiều trạm GNSS đồng thời
        max_overflow=40,     # Cho phép tối đa 60 kết nối khi tải cao (10+ trạm * nhiều sensor)
        pool_recycle=1800,
        pool_timeout=60,     # Tăng timeout lên 60s để tránh lỗi khi burst
        pool_use_lifo=True,  # Tái sử dụng kết nối gần nhất (tốt cho cache)
    )

# 1. AUTH DB
auth_engine = create_pg_engine(settings.AUTH_DB_URL)
AuthSessionLocal = sessionmaker(auth_engine, class_=AsyncSession, expire_on_commit=False)
BaseAuth = declarative_base()

# 2. CONFIG DB
config_engine = create_pg_engine(settings.CONFIG_DB_URL)
ConfigSessionLocal = sessionmaker(config_engine, class_=AsyncSession, expire_on_commit=False)
BaseConfig = declarative_base()

# 3. DATA DB
data_engine = create_pg_engine(settings.DATA_DB_URL)
DataSessionLocal = sessionmaker(data_engine, class_=AsyncSession, expire_on_commit=False)
BaseData = declarative_base()

# Aliases cho backward compatibility (sửa lỗi ImportError trong các file cũ)
Base = BaseData
AuthBase = BaseAuth

# Dependency Injection cho FastAPI (Giữ nguyên)
async def get_auth_db():
    async with AuthSessionLocal() as session:
        yield session

async def get_config_db():
    async with ConfigSessionLocal() as session:
        yield session

async def get_data_db():
    async with DataSessionLocal() as session:
        yield session