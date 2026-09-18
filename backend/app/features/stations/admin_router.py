"""Station administration routes composed by responsibility."""

from fastapi import APIRouter

from .commands import router as commands_router
from .configuration import router as configuration_router
from .crud import router as crud_router
from .defaults import get_default_station_config
from .origin import router as origin_router

router = APIRouter()
router.include_router(origin_router)
router.include_router(configuration_router)
router.include_router(commands_router)
router.include_router(crud_router)
