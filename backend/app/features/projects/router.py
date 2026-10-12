"""Project routes composed by access scope and responsibility."""

from fastapi import APIRouter

from .admin import (
    create_project,
    delete_project,
    get_project,
    get_projects,
    router as admin_router,
    update_project,
)
from .cors import (
    get_admin_cors_failover_status,
    get_admin_cors_stations,
    router as cors_router,
)
from .public import get_public_projects, router as public_router

router = APIRouter()
router.include_router(public_router)
router.include_router(cors_router)
router.include_router(admin_router)
