"""Station feature routes composed from focused modules."""

from fastapi import APIRouter

from .analysis_router import (
    _calculate_station_risk_assessment,
    get_gnss_daily_summary,
    get_gnss_weekly_summary,
    get_long_term_analysis,
    router as analysis_router,
)
from .common import (
    _load_station_runtime_maps,
    _station_detail_adjustment_latest,
    _summarize_station_alerts,
    calculate_station_location,
    is_offline_display_enabled,
)
from .query_router import (
    create_station_in_project,
    get_mqtt_topic_availability,
    get_public_dashboard_summary,
    get_station_detail,
    get_station_history,
    get_stations,
    get_stations_by_project,
    router as query_router,
)

router = APIRouter()
router.include_router(query_router)
router.include_router(analysis_router)
