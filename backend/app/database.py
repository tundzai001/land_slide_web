# backend/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# 1. AUTH DB (Lưu user)
auth_engine = create_async_engine(settings.AUTH_DB_URL, echo=False)
AuthSessionLocal = sessionmaker(auth_engine, class_=AsyncSession, expire_on_commit=False)
BaseAuth = declarative_base()

# 2. CONFIG DB (Lưu cấu hình trạm)
config_engine = create_async_engine(settings.CONFIG_DB_URL, echo=False)
ConfigSessionLocal = sessionmaker(config_engine, class_=AsyncSession, expire_on_commit=False)
BaseConfig = declarative_base()

# 3. DATA DB (Lưu dữ liệu cảm biến & cảnh báo)
data_engine = create_async_engine(settings.DATA_DB_URL, echo=False)
DataSessionLocal = sessionmaker(data_engine, class_=AsyncSession, expire_on_commit=False)
BaseData = declarative_base()

# Dependency Injection cho FastAPI
async def get_auth_db():
    async with AuthSessionLocal() as session:
        yield session

async def get_config_db():
    async with ConfigSessionLocal() as session:
        yield session

async def get_data_db():
    async with DataSessionLocal() as session:
        yield session

# Hàm chung cho các tác vụ không cần phân biệt (nếu code cũ còn dùng)
# Nhưng tốt nhất nên thay thế bằng 3 hàm trên
async def get_db():
    async with ConfigSessionLocal() as session:
        yield session