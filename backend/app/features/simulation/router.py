"""Simulation routes composed by responsibility."""

from fastapi import APIRouter

from .exports import export_bundle, export_run, router as export_router
from .runs import (
    create_run,
    evaluate_station,
    get_run,
    list_runs,
    router as run_router,
    rerun,
    stop_run,
)
from .service import recover_interrupted_runs

router = APIRouter()
router.include_router(run_router)
router.include_router(export_router)
