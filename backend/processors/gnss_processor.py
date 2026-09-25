"""GNSS sensor processor facade.

The implementation is grouped by runtime state, reference transitions,
velocity quality, origin persistence, payload processing, and NMEA helpers.
"""

from .gnss.common import (
    A_WGS84,
    E2_WGS84,
    F_WGS84,
    GNSS_RUNTIME_STATE_SAVE_INTERVAL_S,
    GNSS_RUNTIME_STATE_VERSION,
    deque,
    logger,
    np,
    time,
    haversine_2d,
)
from .gnss.nmea import GNSSNmeaMixin
from .gnss.origin import GNSSOriginMixin
from .gnss.processing import GNSSProcessingMixin
from .gnss.reference import GNSSReferenceMixin
from .gnss.runtime import GNSSRuntimeMixin
from .gnss.velocity import GNSSVelocityMixin


class GNSSVelocityProcessor(
    GNSSRuntimeMixin,
    GNSSReferenceMixin,
    GNSSVelocityMixin,
    GNSSOriginMixin,
    GNSSProcessingMixin,
    GNSSNmeaMixin,
):
    def __init__(
        self,
        device_id: int,
        db_session_factory,
        required_points=60,
        max_spread_m=0.5,
        origin_max_u_spread_m=1.0,
        filter_window_size=30,
        min_fix_quality=4,
        # Sanity gate: reject fix nếu thiết bị claim nhảy > X mét trong 1 sample.
        # For RTK Fixed (4), we allow slightly more but still tight.
        # For RTK Float (5), we should be much stricter because it's noisy.
        max_step_distance_m=0.2,
        # Vertical jump gate (U-axis) to reject unrealistic altitude spikes.
        max_step_vertical_m=0.15,
        context_label: str = None,
        allow_auto_reacquire: bool = False,
    ):
        self.device_id = device_id
        self.db_session_factory = db_session_factory
        self.context_label = context_label or f"device_id={device_id}"
        self.required_points = max(int(required_points), 10) if required_points is not None else 60
        self.max_spread_m = float(max_spread_m)
        self.origin_max_xy_spread_m = float(max_spread_m)
        self.origin_max_u_spread_m = float(origin_max_u_spread_m)
        self.min_fix_quality = min_fix_quality
        self.filter_window_size = filter_window_size
        self.max_step_distance_m = float(max_step_distance_m)
        self.max_step_vertical_m = float(max_step_vertical_m)
        self.allow_auto_reacquire = bool(allow_auto_reacquire)
        self._reference_changed_at = None
        self._reference_change_source = None
        self._last_handled_reference_event_ts = None
        self._reference_transition = None
        self._last_origin_candidate_ts = None
        self._origin_locked_at = None
        self._origin_record_id = None

        # State
        self.state = "AWAITING_CANDIDATES"
        self.origin = None
        self.origin_candidates = []

        # history giữ filter_window_size + 1 mẫu để tính median window
        # Retain enough accepted FIXED samples for time-based windows. The old
        # 31-sample deque made the displacement median cycle too quickly.
        self.history = deque(maxlen=max(filter_window_size + 1, 1200))
        self.reacquire_candidates = deque(maxlen=10)
        # A single rolling velocity window can be biased by multipath even
        # while the monument is static. Keep a separate evidence streak for
        # movement confirmation; this never alters the measured velocity.
        self._velocity_confirmation_history = deque(maxlen=120)
        self.last_significant_motion_ts = 0.0
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        # Stable displacement state for UI/log (reduce "standing still but jumping total").
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False
        self.peak_displacement_mm = 0.0
        self.tracking_offset_enu = np.zeros(3, dtype=float)
        self._last_reacquire_ts = 0.0
        self._needs_boot_anchor = True
        self._quarantine_checkpointed = False
        # Do not consume a GGA sample while the immutable origin/checkpoint
        # load is still in flight.  Otherwise a restart can collect a fresh
        # origin before the persisted safety state is restored.
        self._initialization_complete = False
        self._initialization_task = None
        self._runtime_state_save_task = None
        self._runtime_state_dirty = False
        self._runtime_state_pending_snapshot = None
        self._runtime_state_pending_offset = None
        self._last_runtime_state_schedule_monotonic = 0.0
        # Manual offset calibration must be able to collect stable FIXED samples
        # even while the normal integrity gate keeps a shifted cluster quarantined.
        self._offset_calibration_samples = deque(maxlen=600)
        self._offset_calibration_in_progress = False
        self._origin_relock_samples = deque(maxlen=600)
        self._origin_relock_in_progress = False
        self._origin_relock_integrity_config = None

        self.stats = {
            'total_processed': 0,
            'low_quality_rejected': 0,
            'origin_resets': 0,
            'spike_rejected': 0,
        }

        self._schedule_load_origin()
        logger.info(
            f"GNSS Processor init for {self._log_prefix()}: "
            f"fix_required={min_fix_quality}, window={filter_window_size}, "
            f"max_step={self.max_step_distance_m}m, auto_reacquire={self.allow_auto_reacquire}"
        )


__all__ = ["GNSSVelocityProcessor", "haversine_2d"]
