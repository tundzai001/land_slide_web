# backend/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
from .infrastructure.asyncpg_compat import install_asyncpg_tls_fix

install_asyncpg_tls_fix()

# Hàm tạo engine chung cho Postgres
def create_pg_engine(url):
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        # All three engines normally target databases on the same PostgreSQL
        # instance.  The old 20 + 40 configuration allowed 180 concurrent
        # connections in total and could exhaust a default PostgreSQL server
        # during a polling/cache burst.
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=1800,
        # Fail fast enough for HTTP clients to back off instead of retaining a
        # growing queue of one-minute requests while the local DB is unhealthy.
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_use_lifo=True,
        connect_args={
            "timeout": 10,
            "command_timeout": settings.DB_COMMAND_TIMEOUT_SECONDS,
        },
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
