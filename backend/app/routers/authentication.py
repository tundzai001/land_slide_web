"""Login and current-session API routes."""
from datetime import timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth, schemas
from ..database import get_auth_db
from ..models import auth as model_auth

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@router.post("/api/auth/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_auth_db)
):
    result = await db.execute(
        select(model_auth.User).where(model_auth.User.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not await auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Check remember_me from form scopes (OAuth2 extra fields)
    remember_me = 'remember_me' in (form_data.scopes or [])
    
    # If remember_me, issue a 30-day token; otherwise use default
    if remember_me:
        expires = timedelta(days=30)
    else:
        expires = None  # Uses default from settings
    
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=expires
    )
    
    logger.info(f"✅ Login successful: {user.username} (remember_me={remember_me})")
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user: model_auth.User = Depends(auth.get_current_user)
):
    permissions = auth.get_user_permissions(current_user)
    user_response = schemas.UserResponse.from_orm(current_user)
    user_response.permissions = permissions
    user_response.assigned_projects = getattr(current_user, 'assigned_projects', []) or []
    return user_response
