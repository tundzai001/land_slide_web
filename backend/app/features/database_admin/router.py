"""Database administration routes composed by operation type."""

from fastapi import APIRouter

from .read_router import (
    _device_runtime_state,
    admin_get_sensor_data,
    router as read_router,
)
from .write_router import router as write_router

router = APIRouter()
router.include_router(read_router)
router.include_router(write_router)
