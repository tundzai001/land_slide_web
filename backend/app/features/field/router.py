"""Field feature routes composed from focused modules."""

from fastapi import APIRouter

from .pi_devices import router as pi_devices_router
from .siren import router as siren_router

router = APIRouter()
router.include_router(pi_devices_router)
router.include_router(siren_router)
