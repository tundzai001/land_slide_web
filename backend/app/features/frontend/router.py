"""Frontend routes composed from pages and WebSocket delivery."""

from fastapi import APIRouter

from .pages import (
    aitogy_logo,
    favicon_ico,
    get_public_sound,
    read_app,
    read_login,
    read_map,
    read_root,
    robots_txt,
    sitemap_xml,
    router as pages_router,
)
from .websocket import _consume_ws_ticket, router as websocket_router

router = APIRouter()
router.include_router(pages_router)
router.include_router(websocket_router)
