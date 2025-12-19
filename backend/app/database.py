# backend/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Hàm tạo engine chung cho Postgres
def create_pg_engine(url):
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True, # Tự động kết nối lại nếu bị ngắt
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