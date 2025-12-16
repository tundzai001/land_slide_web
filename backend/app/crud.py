# backend/app/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .models import auth as model_auth # Sửa import

async def get_user_by_username(db: AsyncSession, username: str):
    result = await db.execute(select(model_auth.User).where(model_auth.User.username == username))
    return result.scalar_one_or_none()

async def create_user(db: AsyncSession, username: str, hashed_password: str, role: str, full_name: str = None):
    db_user = model_auth.User(
        username=username,
        hashed_password=hashed_password,
        role=role,
        full_name=full_name,
        is_active=True
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user