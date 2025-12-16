#backend/app/models/auth.py
from sqlalchemy import Column, Integer, String, Boolean
from app.database import BaseAuth

class User(BaseAuth):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String, nullable=True)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)