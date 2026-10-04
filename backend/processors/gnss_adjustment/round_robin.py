"""Round-Robin adjustment manager composed from focused processing components."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional
from .geometry import (
    _aggregate_parallel_baselines,
    _build_fundamental_loops,
    _graph_components,
)
from .aicaster import RoundRobinAicasterMixin
from .cors import RoundRobinCorsMixin
from .cycle import RoundRobinCycleMixin
from .observation import RoundRobinObservationMixin
from .receiver import RoundRobinReceiverMixin
from .results import RoundRobinResultsMixin
from .session import _CommandAckWaiter, _SafeRoverRotationSkip, RoundRobinSessionLifecycleMixin
from .statistics import (
    _InformationAccumulator,
    _initial_positive_sequence_ess,
    _rolling_mean_stability,
)

logger = logging.getLogger(__name__)

class RoundRobinAdjustmentManager(
    RoundRobinObservationMixin,
    RoundRobinCorsMixin,
    RoundRobinCycleMixin,
    RoundRobinReceiverMixin,
    RoundRobinResultsMixin,
    RoundRobinAicasterMixin,
    RoundRobinSessionLifecycleMixin,
):
    """Coordinate GNSS adjustment phases without mixing transport and math code."""
    """Collect base-to-rover and rover-to-rover baselines for the existing solver.

    The mathematical adjustment remains in ``gnss_adjustment.solver``.  This
    class only manages the observation lifecycle and provides that solver with
    correctly connected ECEF baselines.
    """

    # A single 1 Hz FIXED epoch only proves that the station is alive. Keep one
    # continuous, source-verified seed session: the initial epochs are useful
    # observations, not a disposable warm-up followed by a second collection.
    SEED_COLLECTION_MIN_DISTINCT_EPOCHS = 20
    SEED_COLLECTION_MIN_DURATION_SECONDS = 15
    SEED_COLLECTION_MAX_STEPS = 20
    # AGRICA arrives at roughly 0.4--0.7 distinct epochs/s in the field. Thirty
    # distinct epochs over at least 30 seconds therefore normally takes about
    # 45--75 seconds of wall time and gives useful temporal coverage without
    # making the old mistake of discarding 20 good epochs and then waiting for
    # another complete 60-second window.
    SEED_SOLVER_MIN_DISTINCT_EPOCHS = 30
    SEED_SOLVER_MIN_DURATION_SECONDS = 30
    SEED_STABILITY_TIMEOUT_SECONDS = 300
    # After the CORS pair has been forced onto one physical receiver, discard
    # the caster/rover handover interval before opening the common seed window.
    FIXED_BASE_HANDOVER_SETTLE_SECONDS = 5
    FIXED_BASE_HANDOVER_VERIFY_SECONDS = 60
    STABILITY_WINDOW_SECONDS = 10
    STABILITY_MIN_SAMPLES_PER_WINDOW = 4
    STABILITY_MAX_SAMPLE_GAP_SECONDS = 5
    STABILITY_HORIZONTAL_COMPONENT_LIMIT_M = 0.003
    STABILITY_UP_COMPONENT_LIMIT_M = 0.005
    STABILITY_HORIZONTAL_STD_LIMIT_M = 0.010
    STABILITY_UP_STD_LIMIT_M = 0.015
    STABILITY_HORIZONTAL_SLOPE_LIMIT_MPS = 0.001
    STABILITY_UP_SLOPE_LIMIT_MPS = 0.002
    STABILITY_EWMA_FAST_TAU_SECONDS = 3.0
    STABILITY_EWMA_SLOW_TAU_SECONDS = 30.0
    STABILITY_HOLD_SECONDS = 10
    # Once a solver window is open, use a wider abort envelope and require
    # repeated receiver epochs outside it. This prevents a 0.1 mm boundary
    # crossing or a repeated UI poll from discarding a full minute of data.
    STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M = 0.008
    STABILITY_ABORT_UP_COMPONENT_LIMIT_M = 0.015
    STABILITY_ABORT_CONSECUTIVE_EPOCHS = 3
    BASE_IDENTITY_TOLERANCE_M = 20.0
    FIXED_BASE_LENGTH_TOLERANCE_M = 20.0
    # This is only a last-resort gross-error barrier. Normal GNSS loop closure
    # should be orders of magnitude smaller; a metre-scale closure means that
    # at least one observation was assigned to the wrong correction source.
    GROSS_LOOP_CLOSURE_MIN_LIMIT_M = 1.0
    GROSS_LOOP_CLOSURE_RELATIVE_LIMIT = 1.0 / 1000.0
    CROSS_BASE_SETTLE_SECONDS = 5
    # A rover that was tracking the stopped fixed source may need well over a
    # minute to reconnect, decode the replacement ephemerides and regain a
    # solver-eligible FIX.  The live Sin Quyen handover showed 45 seconds is
    # too short for the slower receiver, so keep validating source/length for
    # up to two minutes instead of prematurely cycling the base again.
    CROSS_BASE_SWITCH_TIMEOUT_SECONDS = 120
    CROSS_BASE_HANDOVER_MIN_SAMPLES = 5
    CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS = 5
    CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS = 5
    CROSS_BASE_STABLE_COLLECTION_SECONDS = 60
    CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS = 30
    CROSS_BASE_STABLE_MIN_DURATION_SECONDS = 60
    CROSS_BASE_STABILITY_TIMEOUT_SECONDS = 300
    CROSS_BASE_STATUS_POLL_SECONDS = 1
    CROSS_BASE_COLLECTION_ATTEMPTS = 2
    INTER_ROTATION_REACQUIRE_MIN_DISTINCT_EPOCHS = 3
    # If the fixed stream is demonstrably serving another rover while the next
    # candidate remains completely silent, do not burn the full reacquisition
    # timeout on a data-plane-stale receiver.
    INTER_ROTATION_STALE_ROVER_GRACE_SECONDS = 45
    INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
    # A slow receiver can keep publishing transition AGRICA for almost the
    # entire nominal wait and acquire the fixed source a few seconds later.
    # Give recent activity a bounded sliding grace period, but retain a hard
    # ceiling so a permanently stale stream cannot block the rotation forever.
    INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
    INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
    INTER_ROTATION_CLIENT_POLL_SECONDS = 5
    MODE_COMMAND_BURST_COUNT = 6
    UNLOGALL_COMMAND_BURST_COUNT = 3
    GPGGA_COMMAND_BURST_COUNT = 6
    AGRICA_COMMAND_BURST_COUNT = 6
    RTCM_COMMAND_BURST_COUNT = 3
    COMMAND_BURST_INTERVAL_SECONDS = 0.25
    PREFLIGHT_CONNECTION_ATTEMPTS = 2
    ROVER_RESTORE_TRANSPORT_ATTEMPTS = 6
    ROVER_RESTORE_RETRY_SECONDS = 2.0
    RTCM_ROUTE_RECOVERY_ATTEMPTS = 2
    FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS = 15
    FIXED_BASE_MOUNTPOINT_RELEASE_RETRY_SECONDS = 1.0
    OPTIONAL_BASE_RTCM_COMMANDS = (
        "rtcm1077 com2 1",
        "rtcm1127 com2 1",
        "rtcm1087 com2 1",
        "rtcm1097 com2 1",
    )
    def __init__(
        self,
        mqtt_client,
        caster_host: str = "",
        caster_hosts: Optional[List[str]] = None,
        caster_port: int = 2101,
        source_host: Optional[str] = None,
        source_port: int = 2101,
        control_password: str = "12345",
        source_password: str = "12345",
        web_cors_api_base_url: str = "",
        web_cors_api_token: str = "",
        web_cors_api_username: str = "",
        web_cors_api_password: str = "",
        route_start_callback: Optional[Callable[[str, str, int, str, str], Any]] = None,
        route_wait_callback: Optional[Callable[[str, float], Any]] = None,
        route_stop_callback: Optional[Callable[[str], Any]] = None,
        result_callback: Optional[Callable[[int, dict], Any]] = None,
        error_callback: Optional[Callable[[int, str], Any]] = None,
        progress_callback: Optional[Callable[[int, str], Any]] = None,
        reference_change_callback: Optional[Callable[[dict, float, str], Any]] = None,
    ):
        self.mqtt_client = mqtt_client
        self.caster_host = caster_host
        self.caster_hosts = list(dict.fromkeys(
            str(host).strip()
            for host in (caster_hosts or [caster_host])
            if str(host).strip()
        ))
        self.caster_port = caster_port
        self.source_host = source_host or caster_host
        self.source_port = source_port
        self.control_password = control_password
        self.source_password = source_password
        if not web_cors_api_base_url:
            try:
                from app.config import settings as app_settings

                web_cors_api_base_url = app_settings.WEB_CORS_API_BASE_URL
            except Exception:
                web_cors_api_base_url = ""
        self.web_cors_api_base_url = str(web_cors_api_base_url or "").rstrip("/")
        self._web_cors_access_token = str(web_cors_api_token or "").strip()
        self.web_cors_api_username = str(web_cors_api_username or "").strip()
        self.web_cors_api_password = str(web_cors_api_password or "")
        self._cors_fixed_base_snapshots: Dict[tuple[Any, ...], Dict[str, Any]] = {}
        self._cors_failover_last_state: Dict[tuple[Any, ...], str] = {}
        # Failover reconciliation and adjustment seed preparation both change
        # the same physical S1/S2 services.  Keep each topology transition
        # atomic so the scheduler cannot snapshot a half-reconciled pair.
        self._cors_topology_lock = asyncio.Lock()
        self.route_start_callback = route_start_callback
        self.route_wait_callback = route_wait_callback
        self.route_stop_callback = route_stop_callback
        self.result_callback = result_callback
        self.error_callback = error_callback
        self.progress_callback = progress_callback
        self.reference_change_callback = reference_change_callback
        self._last_set_error: Optional[str] = None
        self._last_set_response: Optional[str] = None
        self._last_set_warnings: List[str] = []
        # Paho invokes MQTT callbacks from its own thread while SET commands run
        # in the asyncio event loop.  Protect the short-lived waiter registry so
        # an ACK can safely cross that boundary.
        self._command_ack_lock = threading.Lock()
        self._command_ack_waiters: Dict[str, _CommandAckWaiter] = {}
        self._gnss_stream_health_lock = threading.Lock()
        self._gnss_stream_health: Dict[str, Dict[str, Any]] = {}
        self.running_tasks: Dict[int, asyncio.Task] = {}
        self.rover_llh_cache: Dict[str, Dict[str, float]] = {}
        self._sessions: Dict[int, dict] = {}
        self._last_ingest_diagnostics: Dict[int, dict] = {}
        self._ingest_warning_last_logged: Dict[tuple[int, int, int], float] = {}
        # UM980 AGRICA output can be split across MQTT payloads.  Buffers are
        # isolated per project/station so fragments from different rovers never
        # get concatenated.
        self._agrica_fragment_buffers: Dict[tuple[int, int], str] = {}
