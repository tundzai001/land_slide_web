"""Station command routes composed by command type."""

from fastapi import APIRouter

from .audio import PlayAudioRequest, router as audio_router, send_audio_command
from .ntrip import router as ntrip_router, start_ntrip_route, stop_ntrip_route

router = APIRouter()
router.include_router(audio_router)
router.include_router(ntrip_router)
