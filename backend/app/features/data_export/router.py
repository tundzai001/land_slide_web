"""Data-export routes composed by export subject."""

from fastapi import APIRouter

from .database.router import router as database_export_router
from .reports.adjustment.router import router as adjustment_report_router
from .reports.station import router as station_report_router

router = APIRouter()
router.include_router(database_export_router)
router.include_router(adjustment_report_router)
router.include_router(station_report_router)
