# backend/processors/gnss_processor.py
import asyncio
import re
import calendar
import numpy as np
import math
import logging
import time
from collections import deque
from typing import Optional, Dict, Any

from app.modules.geodetic import VN2000Converter, DatumParams, parse_vn2000_central_meridian, normalize_vn2000_l0_value

logger = logging.getLogger(__name__)

A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84**2
# Derived displacement/peak values from the previous runtime state were allowed
# to accumulate from overlapping noise windows.  Bump the checkpoint version so
# the first process restart rebuilds that derived state from fresh observations.
GNSS_RUNTIME_STATE_VERSION = 2
GNSS_RUNTIME_STATE_SAVE_INTERVAL_S = 15.0

def haversine_2d(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a_val = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
    return R * c

class GNSSVelocityProcessor:
    """
    Processor ổn định: nhận GNGGA → tính ENU position → tính velocity qua cửa sổ trượt.
    Tích hợp chuyển đổi tọa độ VN2000 (NEH).
    """
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

    def mark_reference_changed(self, timestamp: float = None, source: str = None):
        """Signal that CORS base / datum reference changed; allows tracking reacquire within time window."""
        self._reference_changed_at = timestamp or time.time()
        self._reference_change_source = source
        self._schedule_runtime_state_save(force=True)
        logger.info(f"[{self._log_prefix()}] Reference frame change marked (source: {source})")

    def is_reference_changed_recently(self, current_ts: float, window_s: float = 300.0) -> bool:
        """Check if a reference change occurred within window_s seconds."""
        changed_at = getattr(self, '_reference_changed_at', None)
        if changed_at is None:
            return False
        delta_s = current_ts - changed_at
        return 0.0 <= delta_s <= window_s

    @staticmethod
    def _normalize_epoch_timestamp(value) -> Optional[float]:
        try:
            timestamp = float(value)
            if not math.isfinite(timestamp):
                return None
            return timestamp / 1000.0 if timestamp > 1e11 else timestamp
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validated_tracking_offset(value):
        offset = np.asarray(value, dtype=float)
        if (
            offset.shape != (3,)
            or not np.all(np.isfinite(offset))
            or np.linalg.norm(offset[:2]) > 2.0
            or abs(offset[2]) > 10.0
        ):
            raise ValueError(f"invalid persisted tracking offset: {offset}")
        return offset

    def _runtime_state_key(self) -> str:
        return f"gnss_runtime_state:{self.device_id}"

    def _runtime_origin_identity(self):
        origin = getattr(self, "origin", None)
        locked_at = self._normalize_epoch_timestamp(getattr(self, "_origin_locked_at", None))
        origin_record_id = getattr(self, "_origin_record_id", None)
        if not origin or locked_at is None or origin_record_id is None:
            return None
        try:
            identity = {
                "id": int(origin_record_id),
                "locked_at": int(locked_at),
                "lat": float(origin["lat"]),
                "lon": float(origin["lon"]),
                "h": float(origin["h"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        return identity if all(math.isfinite(identity[key]) for key in ("lat", "lon", "h")) else None

    @staticmethod
    def _validated_runtime_vector(value, name):
        vector = np.asarray(value, dtype=float)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)) or np.max(np.abs(vector)) > 1_000_000.0:
            raise ValueError(f"invalid {name}: {vector}")
        return vector

    def _runtime_state_snapshot(self):
        identity = self._runtime_origin_identity()
        history = getattr(self, "history", None)
        if identity is None or not history:
            return None
        last = history[-1]
        if not isinstance(last, dict) or "ts" not in last or "pos_enu" not in last:
            return None
        last_ts = self._normalize_epoch_timestamp(last["ts"])
        if last_ts is None:
            return None
        try:
            last_position = self._validated_runtime_vector(last["pos_enu"], "last trusted ENU")
            displacement = self._validated_runtime_vector(
                getattr(self, "disp_enu_state", np.zeros(3, dtype=float)),
                "displacement ENU",
            )
            tracking_offset = self._validated_tracking_offset(
                getattr(self, "tracking_offset_enu", np.zeros(3, dtype=float))
            )
        except (TypeError, ValueError):
            return None

        candidates = []
        for candidate in list(getattr(self, "reacquire_candidates", ()))[:10]:
            try:
                candidate_ts = self._normalize_epoch_timestamp(candidate["ts"])
                candidate_position = self._validated_runtime_vector(candidate["pos_enu"], "quarantine ENU")
                if candidate_ts is None:
                    continue
                candidates.append({
                    "ts": candidate_ts,
                    "pos_enu": candidate_position.tolist(),
                    "fix_quality": int(candidate.get("fix_quality", self.min_fix_quality)),
                })
            except (KeyError, TypeError, ValueError):
                continue

        shift_started_at = self._normalize_epoch_timestamp(getattr(self, "_shift_started_at", None))
        quarantine = (
            {"started_at": shift_started_at, "candidates": candidates}
            if candidates and shift_started_at is not None else None
        )
        reference_changed_at = self._normalize_epoch_timestamp(getattr(self, "_reference_changed_at", None))
        last_handled_event = self._normalize_epoch_timestamp(
            getattr(self, "_last_handled_reference_event_ts", None)
        )
        peak_mm = float(getattr(self, "peak_displacement_mm", 0.0))
        if not math.isfinite(peak_mm):
            return None
        reference_source = getattr(self, "_reference_change_source", None)
        if reference_source is not None and not isinstance(reference_source, str):
            reference_source = str(reference_source)
        return {
            "version": GNSS_RUNTIME_STATE_VERSION,
            "origin": identity,
            "tracking_offset_enu": tracking_offset.tolist(),
            "last_trusted": {"gga_timestamp": last_ts, "pos_enu": last_position.tolist()},
            "displacement": {
                "enu": displacement.tolist(),
                "ready": bool(getattr(self, "disp_state_ready", False)),
                "peak_mm": max(0.0, peak_mm),
            },
            "last_reacquire_ts": self._normalize_epoch_timestamp(
                getattr(self, "_last_reacquire_ts", 0.0)
            ) or 0.0,
            "reference_event": {
                "changed_at": reference_changed_at,
                "source": reference_source,
                "last_handled_at": last_handled_event,
            },
            "quarantine": quarantine,
            "updated_at": int(time.time()),
        }

    def _restore_runtime_state(self, value) -> bool:
        """Restore only a checkpoint tied to this exact immutable origin and offset."""
        self._needs_boot_anchor = True
        try:
            if not isinstance(value, dict) or value.get("version") != GNSS_RUNTIME_STATE_VERSION:
                return False
            expected_origin = self._runtime_origin_identity()
            stored_origin = value.get("origin")
            if expected_origin is None or not isinstance(stored_origin, dict):
                return False
            if int(stored_origin.get("locked_at")) != expected_origin["locked_at"]:
                return False
            if int(stored_origin.get("id")) != expected_origin["id"]:
                return False
            for key, tolerance in (("lat", 1e-10), ("lon", 1e-10), ("h", 1e-4)):
                if not math.isclose(
                    float(stored_origin.get(key)), expected_origin[key], rel_tol=0.0, abs_tol=tolerance
                ):
                    return False

            stored_offset = self._validated_tracking_offset(value.get("tracking_offset_enu"))
            current_offset = self._validated_tracking_offset(
                getattr(self, "tracking_offset_enu", np.zeros(3, dtype=float))
            )
            if not np.allclose(stored_offset, current_offset, rtol=0.0, atol=1e-7):
                return False

            trusted = value.get("last_trusted")
            displacement = value.get("displacement")
            if not isinstance(trusted, dict) or not isinstance(displacement, dict):
                return False
            trusted_ts = self._normalize_epoch_timestamp(trusted.get("gga_timestamp"))
            trusted_position = self._validated_runtime_vector(trusted.get("pos_enu"), "last trusted ENU")
            displacement_position = self._validated_runtime_vector(displacement.get("enu"), "displacement ENU")
            displacement_ready = displacement.get("ready")
            peak_mm = float(displacement.get("peak_mm"))
            if (
                trusted_ts is None or trusted_ts <= 0.0
                or not isinstance(displacement_ready, bool)
                or not math.isfinite(peak_mm) or peak_mm < 0.0
            ):
                return False

            last_reacquire_ts = self._normalize_epoch_timestamp(value.get("last_reacquire_ts", 0.0))
            if last_reacquire_ts is None or last_reacquire_ts < 0.0:
                return False
            reference_event = value.get("reference_event") or {}
            if not isinstance(reference_event, dict):
                return False
            reference_changed_at = self._normalize_epoch_timestamp(reference_event.get("changed_at"))
            last_handled_event = self._normalize_epoch_timestamp(reference_event.get("last_handled_at"))
            reference_source = reference_event.get("source")
            if reference_source is not None and not isinstance(reference_source, str):
                return False

            restored_candidates = []
            quarantine = value.get("quarantine")
            shift_started_at = None
            if quarantine is not None:
                if not isinstance(quarantine, dict) or not isinstance(quarantine.get("candidates"), list):
                    return False
                shift_started_at = self._normalize_epoch_timestamp(quarantine.get("started_at"))
                if shift_started_at is None or shift_started_at < trusted_ts:
                    return False
                for candidate in quarantine["candidates"][-10:]:
                    if not isinstance(candidate, dict):
                        return False
                    candidate_ts = self._normalize_epoch_timestamp(candidate.get("ts"))
                    candidate_position = self._validated_runtime_vector(
                        candidate.get("pos_enu"), "quarantine ENU"
                    )
                    fix_quality = int(candidate.get("fix_quality"))
                    if candidate_ts is None or candidate_ts <= trusted_ts:
                        return False
                    restored_candidates.append({
                        "ts": candidate_ts,
                        "pos_enu": candidate_position,
                        "fix_quality": fix_quality,
                    })
                if not restored_candidates:
                    return False

            self.history.clear()
            self.history.append({"ts": trusted_ts, "pos_enu": trusted_position})
            self.reacquire_candidates.clear()
            self.reacquire_candidates.extend(restored_candidates)
            self.disp_enu_state = displacement_position
            self.disp_state_ready = displacement_ready
            self.peak_displacement_mm = peak_mm
            self._last_reacquire_ts = last_reacquire_ts
            self._reference_changed_at = reference_changed_at
            self._reference_change_source = reference_source
            self._last_handled_reference_event_ts = last_handled_event
            self._shift_started_at = shift_started_at
            self._consecutive_rejects = len(restored_candidates)
            self._quarantine_checkpointed = bool(restored_candidates)
            self._needs_boot_anchor = False
            return True
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    async def _async_save_runtime_state(self, snapshot) -> bool:
        if snapshot is None:
            return False
        try:
            from app.models.config import GlobalConfig
            from sqlalchemy import select

            async with self.db_session_factory() as db:
                result = await db.execute(select(GlobalConfig).where(GlobalConfig.key == self._runtime_state_key()))
                existing = result.scalar_one_or_none()
                now = int(time.time())
                if existing:
                    existing.value = snapshot
                    existing.updated_at = now
                    existing.updated_by = "gnss_processor"
                else:
                    db.add(GlobalConfig(
                        key=self._runtime_state_key(),
                        value=snapshot,
                        updated_at=now,
                        updated_by="gnss_processor",
                    ))
                await db.commit()
            return True
        except Exception as exc:
            logger.error(f"[{self._log_prefix()}] Failed to persist GNSS runtime state: {exc}")
            return False

    async def _runtime_state_save_loop(self):
        try:
            while getattr(self, "_runtime_state_dirty", False):
                self._runtime_state_dirty = False
                snapshot = self._runtime_state_pending_snapshot
                offset = self._runtime_state_pending_offset
                self._runtime_state_pending_snapshot = None
                self._runtime_state_pending_offset = None
                if offset is not None and not await self._async_save_tracking_offset(offset):
                    continue
                await self._async_save_runtime_state(snapshot)
        finally:
            self._runtime_state_save_task = None

    def _schedule_runtime_state_save(self, *, force=False, persist_tracking_offset=False):
        if not getattr(self, "db_session_factory", None):
            return
        now = time.monotonic()
        last = getattr(self, "_last_runtime_state_schedule_monotonic", 0.0)
        if not force and now - last < GNSS_RUNTIME_STATE_SAVE_INTERVAL_S:
            return
        snapshot = self._runtime_state_snapshot()
        if snapshot is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._last_runtime_state_schedule_monotonic = now
        self._runtime_state_pending_snapshot = snapshot
        if persist_tracking_offset:
            self._runtime_state_pending_offset = np.asarray(self.tracking_offset_enu, dtype=float).copy()
        self._runtime_state_dirty = True
        task = getattr(self, "_runtime_state_save_task", None)
        if task is None or task.done():
            self._runtime_state_save_task = loop.create_task(self._runtime_state_save_loop())

    def _integrity_config(self, station_config: Dict) -> Dict[str, float]:
        config = (station_config or {}).get("GnssIntegrity") or (station_config or {}).get("gnss_integrity") or {}

        def number(name, default, minimum):
            try:
                return max(float(config.get(name, default)), minimum)
            except (TypeError, ValueError):
                return default

        return {
            "process_max_hdop": number("process_max_hdop", 2.0, 0.1),
            "process_min_sats": int(number("process_min_sats", 10, 1)),
            "origin_max_gap_s": number("origin_max_gap_s", 2.0, 0.1),
            "reference_event_alignment_s": number("reference_event_alignment_s", 30.0, 1.0),
            "reference_transition_samples": max(6, min(int(number("reference_transition_samples", 6, 1)), 10)),
            "reacquire_max_spread_xy_m": number("reacquire_max_spread_xy_m", 0.03, 0.001),
            "reacquire_max_spread_u_m": number("reacquire_max_spread_u_m", 0.05, 0.001),
        }

    def _reference_event(self, station_config: Dict):
        config = station_config or {}
        events = [
            (config.get("reference_change_timestamp"), "reference_change_timestamp"),
            (config.get("cors_failover_timestamp"), "cors_failover_timestamp"),
            (config.get("allow_tracking_reacquire_timestamp"), "allow_tracking_reacquire_timestamp"),
            (getattr(self, "_reference_changed_at", None), getattr(self, "_reference_change_source", "local")),
        ]
        valid = [
            (timestamp, source)
            for value, source in events
            if (timestamp := self._normalize_epoch_timestamp(value)) is not None
        ]
        return max(valid, default=(None, None), key=lambda event: event[0])

    def _consume_reference_event(self, event_ts: float):
        self._last_handled_reference_event_ts = event_ts
        if self._normalize_epoch_timestamp(getattr(self, "_reference_changed_at", None)) == event_ts:
            self._reference_changed_at = None
            self._reference_change_source = None
        self._schedule_runtime_state_save(force=True)

    @staticmethod
    def _shift_data(
        tracking_shift,
        candidate_xy_spread: float,
        candidate_u_spread: float,
        duration_s: float,
        reference_event_verified: bool,
        possible_ground_movement: bool,
        reference_event_ts: float = None,
        shift_started_at: float = None,
    ) -> Dict[str, Any]:
        shift = np.asarray(tracking_shift, dtype=float)
        return {
            "integrity_state": "UNVERIFIED_POSITION_SHIFT",
            "position_quality_reliable": not possible_ground_movement,
            "shift_e_m": float(shift[0]),
            "shift_n_m": float(shift[1]),
            "shift_u_m": float(shift[2]),
            "shift_2d_m": float(np.hypot(shift[0], shift[1])),
            "shift_3d_m": float(np.linalg.norm(shift)),
            "spread_xy_m": float(candidate_xy_spread),
            "spread_u_m": float(candidate_u_spread),
            "duration_s": float(duration_s),
            "reference_event_verified": bool(reference_event_verified),
            "possible_ground_movement": bool(possible_ground_movement),
            "reference_event_timestamp": reference_event_ts,
            "shift_started_at": shift_started_at,
        }

    def _handle_reference_transition(self, ts, pos_enu, fix_quality, station_config, raw_payload):
        """Quarantine post-reference samples before they can affect tracking history."""
        integrity_cfg = self._integrity_config(station_config)
        transition = getattr(self, "_reference_transition", None)
        event_ts, event_source = self._reference_event(station_config)

        if transition is None:
            if (
                event_ts is None
                or event_ts == getattr(self, "_last_handled_reference_event_ts", None)
                or not self.history
                or not 0.0 <= ts - event_ts <= integrity_cfg["reference_event_alignment_s"]
            ):
                return None
            transition = {
                "event_ts": event_ts,
                "event_source": event_source,
                "started_at": ts,
                "pre_position": self.history[-1]["pos_enu"].copy(),
                "candidates": deque(maxlen=integrity_cfg["reference_transition_samples"]),
            }
            self._reference_transition = transition
            logger.info(
                f"[{self._log_prefix()}] Reference transition started from {event_source}; "
                "quarantining post-event FIXED samples"
            )

        transition["candidates"].append({"ts": ts, "pos_enu": pos_enu.copy()})
        candidate_count = len(transition["candidates"])
        target_count = transition["candidates"].maxlen
        if candidate_count < target_count:
            return {
                "type": "gnss_status",
                "status": "REFERENCE_TRANSITION",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "raw_payload": raw_payload,
                "data": {
                    "integrity_state": "REFERENCE_TRANSITION",
                    "candidate_count": candidate_count,
                    "candidate_target": target_count,
                    "reference_event_verified": True,
                    "reference_event_timestamp": transition["event_ts"],
                },
                "message": f"Reference transition: quarantining FIXED samples {candidate_count}/{target_count}",
            }

        candidates = list(transition["candidates"])
        positions = np.array([candidate["pos_enu"] for candidate in candidates], dtype=float)
        center = np.median(positions, axis=0)
        xy_spread = float(np.max(np.linalg.norm(positions[:, :2] - center[:2], axis=1)))
        u_spread = float(np.max(np.abs(positions[:, 2] - center[2])))
        tracking_shift = center - transition["pre_position"]
        duration_s = ts - transition["started_at"]
        stable = (
            xy_spread <= integrity_cfg["reacquire_max_spread_xy_m"]
            and u_spread <= integrity_cfg["reacquire_max_spread_u_m"]
        )
        offset_too_large = bool(np.hypot(*tracking_shift[:2]) > 0.5 or abs(tracking_shift[2]) > 1.0)
        proposed_offset = getattr(self, "tracking_offset_enu", np.zeros(3, dtype=float)) + tracking_shift
        accumulated_too_much = bool(np.linalg.norm(proposed_offset) > 2.0)
        in_cooldown = bool(ts - getattr(self, "_last_reacquire_ts", 0.0) < 300.0)
        data = self._shift_data(
            tracking_shift, xy_spread, u_spread, duration_s, True,
            not (stable and not offset_too_large and not accumulated_too_much and not in_cooldown),
            transition["event_ts"], transition["started_at"],
        )
        self._reference_transition = None
        self._consume_reference_event(transition["event_ts"])

        if stable and not offset_too_large and not accumulated_too_much and not in_cooldown:
            data["integrity_state"] = "TRACKING_REACQUIRED"
            data["position_quality_reliable"] = True
            self.tracking_offset_enu = proposed_offset
            self._last_reacquire_ts = ts
            self.history.clear()
            self.history.extend({
                "ts": candidate["ts"],
                "pos_enu": candidate["pos_enu"] - tracking_shift,
            } for candidate in candidates)
            self.reacquire_candidates.clear()
            self._consecutive_rejects = 0
            self._quarantine_checkpointed = False
            self._schedule_runtime_state_save(force=True, persist_tracking_offset=True)
            return {
                "type": "gnss_status",
                "status": "TRACKING_REACQUIRED",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "raw_payload": raw_payload,
                "data": data,
                "message": "Verified reference shift compensated; locked displacement preserved",
            }

        return {
            "type": "gnss_status",
            "status": "UNVERIFIED_POSITION_SHIFT",
            "fix_quality": fix_quality,
            "fix_mode": self._fix_mode(fix_quality),
            "raw_payload": raw_payload,
            "data": data,
            "message": "Reference transition was not stable enough to compensate; last trusted position preserved",
        }

    def set_context(self, context_label: str):
        if context_label:
            self.context_label = context_label

    def _log_prefix(self) -> str:
        return f"GNSS-{self.device_id} {self.context_label}"

    def reset_origin(self):
        """Origins are immutable once locked; only pre-lock candidates may be reset."""
        if self.origin is not None or self.state == "ORIGIN_LOCKED":
            logger.warning(
                f"[{self._log_prefix()}] Origin reset refused: locked monitoring origins are immutable"
            )
            return False
        self.origin = None
        self.origin_candidates = []
        self.state = "AWAITING_CANDIDATES"
        self.history = deque(maxlen=max(self.filter_window_size + 1, 1200))
        self.reacquire_candidates = deque(maxlen=10)
        self._velocity_confirmation_history = deque(maxlen=120)
        self.last_significant_motion_ts = 0.0
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False
        self.peak_displacement_mm = 0.0
        self.tracking_offset_enu = np.zeros(3, dtype=float)
        self._last_reacquire_ts = 0.0
        self._needs_boot_anchor = True
        self._quarantine_checkpointed = False
        self._runtime_state_save_task = None
        self._runtime_state_dirty = False
        self._runtime_state_pending_snapshot = None
        self._runtime_state_pending_offset = None
        self._last_runtime_state_schedule_monotonic = 0.0
        self._last_handled_reference_event_ts = None
        self._reference_transition = None
        self._last_origin_candidate_ts = None
        self._origin_locked_at = None
        self._origin_record_id = None
        self.last_process_time = 0
        logger.info(f"🔄 [GNSS] Origin reset for device {self.device_id}")
        return True

    def _update_last_data_time(self, timestamp: int):
        self.last_process_time = timestamp

    def _fix_mode(self, fix_quality: int) -> str:
        # NMEA GGA fix quality mapping for UI/log readability
        mapping = {
            0: "INVALID",
            1: "GPS_SINGLE_NO_RTK",
            2: "DGPS_FLOAT",
            4: "RTK_FIXED",
            5: "RTK_FLOAT",
            7: "MANUAL_INPUT_MODE"
        }
        return mapping.get(fix_quality, "UNKNOWN")

    @staticmethod
    def _gga_epoch_seconds(gga_time: str, received_ts: float) -> Optional[float]:
        """Resolve GGA hhmmss.s to the UTC day nearest the server receive time."""
        try:
            raw = float(gga_time)
            hours = int(raw // 10000)
            minutes = int((raw % 10000) // 100)
            seconds = raw % 100
            if hours > 23 or minutes > 59 or seconds >= 60:
                return None
            now = time.gmtime(received_ts)
            midnight = calendar.timegm((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0))
            same_day = midnight + hours * 3600 + minutes * 60 + seconds
            return min((same_day - 86400, same_day, same_day + 86400), key=lambda ts: abs(ts - received_ts))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _verify_nmea_checksum(sentence: str) -> bool:
        """Validate NMEA XOR checksum if present (*XX). Returns True if valid or if no checksum field."""
        if not sentence or '*' not in sentence:
            return True
        try:
            body, chk = sentence.rsplit('*', 1)
            if '$' in body:
                body = body[body.find('$') + 1:]
            chk_str = chk.strip()[:2]
            if len(chk_str) < 2 or not all(c in '0123456789ABCDEFabcdef' for c in chk_str):
                return False
            expected = int(chk_str, 16)
            computed = 0
            for char in body:
                computed ^= ord(char)
            return computed == expected
        except (ValueError, IndexError):
            return False

    @staticmethod
    def _robust_velocity_estimate(samples):
        """Theil-Sen velocity and robust residual scatter for accepted ENU samples."""
        times = np.array([float(sample['ts']) for sample in samples], dtype=float)
        positions = np.array([sample['pos_enu'] for sample in samples], dtype=float)
        slopes = []
        for i in range(len(samples) - 1):
            dt = times[i + 1:] - times[i]
            valid = dt > 0.01
            if np.any(valid):
                slopes.extend((positions[i + 1:][valid] - positions[i]) / dt[valid, None])
        if not slopes:
            return None
        velocity = np.median(np.asarray(slopes, dtype=float), axis=0)
        centered_t = times - times[-1]
        intercept = np.median(positions - centered_t[:, None] * velocity, axis=0)
        residuals = positions - (intercept + centered_t[:, None] * velocity)
        residual_3d = np.linalg.norm(residuals, axis=1)
        residual_rms_m = float(np.sqrt(np.mean(residual_3d ** 2)))
        time_sxx = float(np.sum((times - np.mean(times)) ** 2))
        uncertainty_mm_s = (
            float(residual_rms_m / math.sqrt(time_sxx) * 1000.0)
            if time_sxx > 0.0 else float('inf')
        )
        return {
            'velocity': velocity,
            'residual_rms_mm': residual_rms_m * 1000.0,
            'residual_mad_mm': float(np.median(np.abs(residual_3d - np.median(residual_3d))) * 1000.0),
            'uncertainty_mm_s': uncertainty_mm_s,
            'confidence_95_mm_s': uncertainty_mm_s * 1.96,
            'sample_count': int(len(samples)),
            'duration_s': float(times[-1] - times[0]),
        }

    def _update_velocity_confirmation(
        self,
        timestamp: float,
        velocity_m_s: np.ndarray,
        statistically_significant: bool,
        reliable: bool,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Confirm movement from independent, directionally consistent windows.

        ``velocity_m_s`` remains the measured robust estimate.  This gate only
        decides whether it is safe to call the estimate ground movement.  A
        rolling window produces highly correlated estimates, so accepting every
        epoch would count the same samples repeatedly.  Evidence is therefore
        sampled at least once per velocity window.
        """
        config = config if isinstance(config, dict) else {}
        try:
            required_samples = max(
                int(config.get('velocity_confirmation_samples', 3)),
                2,
            )
        except (TypeError, ValueError):
            required_samples = 3
        try:
            required_duration_s = max(
                float(config.get('velocity_confirmation_duration_s', 30.0)),
                5.0,
            )
        except (TypeError, ValueError):
            required_duration_s = 30.0
        try:
            direction_threshold = min(
                max(float(config.get('velocity_confirmation_direction_cosine', 0.70)), 0.0),
                1.0,
            )
        except (TypeError, ValueError):
            direction_threshold = 0.70
        try:
            minimum_gap_s = max(
                float(config.get('velocity_confirmation_min_gap_s', 15.0)),
                1.0,
            )
        except (TypeError, ValueError):
            minimum_gap_s = 15.0
        try:
            max_gap_s = max(
                float(config.get(
                    'velocity_confirmation_max_gap_s',
                    max(required_duration_s, minimum_gap_s * 2.0),
                )),
                minimum_gap_s,
            )
        except (TypeError, ValueError):
            max_gap_s = max(required_duration_s, minimum_gap_s * 2.0)

        evidence = getattr(self, '_velocity_confirmation_history', None)
        if not isinstance(evidence, deque):
            evidence = deque(maxlen=120)
            self._velocity_confirmation_history = evidence

        def empty_result() -> Dict[str, Any]:
            self.last_significant_motion_ts = 0.0
            return {
                'confirmed': False,
                'sample_count': 0,
                'duration_s': 0.0,
                'direction_cosine': None,
                'accepted_sample': False,
                'required_samples': required_samples,
                'required_duration_s': required_duration_s,
                'minimum_gap_s': minimum_gap_s,
            }

        def current_result(accepted_sample: bool) -> Dict[str, Any]:
            if not evidence:
                return empty_result()
            reference = np.asarray(evidence[0]['velocity'], dtype=float)
            reference_norm = float(np.linalg.norm(reference))
            direction_cosine = min(
                float(np.dot(reference, item['velocity']) / (
                    reference_norm * float(np.linalg.norm(item['velocity']))
                ))
                for item in evidence
            )
            duration_s = max(0.0, ts - float(evidence[0]['ts']))
            confirmed = bool(
                len(evidence) >= required_samples
                and duration_s >= required_duration_s
                and direction_cosine >= direction_threshold
            )
            self.last_significant_motion_ts = float(evidence[0]['ts']) if confirmed else 0.0
            return {
                'confirmed': confirmed,
                'sample_count': len(evidence),
                'duration_s': duration_s,
                'direction_cosine': direction_cosine,
                'accepted_sample': accepted_sample,
                'required_samples': required_samples,
                'required_duration_s': required_duration_s,
                'minimum_gap_s': minimum_gap_s,
            }

        try:
            ts = float(timestamp)
            vector = np.asarray(velocity_m_s, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            evidence.clear()
            return empty_result()

        if (
            not math.isfinite(ts)
            or vector.size != 3
            or not np.all(np.isfinite(vector))
            or np.linalg.norm(vector) <= 0.0
            or not statistically_significant
            or not reliable
        ):
            evidence.clear()
            return empty_result()

        if evidence:
            previous = evidence[-1]
            gap_s = ts - float(previous['ts'])
            previous_vector = np.asarray(previous['velocity'], dtype=float)
            previous_norm = float(np.linalg.norm(previous_vector))
            vector_norm = float(np.linalg.norm(vector))
            cosine = float(np.dot(previous_vector, vector) / (previous_norm * vector_norm))
            if gap_s <= 0.0 or gap_s > max_gap_s or cosine < direction_threshold:
                evidence.clear()
            elif gap_s < minimum_gap_s:
                # The current rolling velocity window overlaps the previous
                # evidence window.  Keep the streak, but do not count another
                # copy of the same observations.
                return current_result(False)

        evidence.append({'ts': ts, 'velocity': vector.copy()})
        horizon_s = max(
            required_duration_s * 2.0,
            minimum_gap_s * max(required_samples + 1, 2),
            60.0,
        )
        cutoff_ts = ts - horizon_s
        while len(evidence) > 1 and float(evidence[0]['ts']) < cutoff_ts:
            evidence.popleft()
        return current_result(True)

    def _schedule_load_origin(self):
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                self._initialization_task = loop.create_task(self._async_load_origin_task())
            except RuntimeError:
                logger.warning(f"⚠️ Device {self.device_id}: Init outside event loop, origin will be collected manually.")
                self._initialization_complete = True
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Error scheduling DB load: {e}")
            self._initialization_complete = True

    async def _async_load_origin_task(self):
        try:
            from app.models.config import GlobalConfig, GNSSOrigin
            from sqlalchemy import select

            runtime_state = None
            async with self.db_session_factory() as db:
                try:
                    result = await db.execute(
                        select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                    )
                    origin_record = result.scalar_one_or_none()
                except Exception as col_err:
                    # Nếu DB chưa kịp migrate cột tracking_offset, query các cột cơ bản
                    logger.warning(f"⚠️ Device {self.device_id}: Direct model select failed ({col_err}), attempting basic column select")
                    result = await db.execute(
                        select(
                            GNSSOrigin.lat, GNSSOrigin.lon, GNSSOrigin.h,
                            GNSSOrigin.rotation_matrix, GNSSOrigin.ecef_origin,
                            GNSSOrigin.locked_at, GNSSOrigin.id,
                        ).where(GNSSOrigin.device_id == self.device_id)
                    )
                    row = result.first()
                    if row:
                        origin_record = type('SimpleOrigin', (), {
                            'lat': row[0], 'lon': row[1], 'h': row[2],
                            'rotation_matrix': row[3], 'ecef_origin': row[4],
                            'locked_at': row[5],
                            'id': row[6],
                            'tracking_offset': None
                        })()
                    else:
                        origin_record = None

                try:
                    runtime_result = await db.execute(
                        select(GlobalConfig).where(GlobalConfig.key == self._runtime_state_key())
                    )
                    runtime_record = runtime_result.scalar_one_or_none()
                    runtime_state = runtime_record.value if runtime_record else None
                except Exception as runtime_err:
                    logger.warning(
                        f"[{self._log_prefix()}] GNSS runtime checkpoint unavailable: {runtime_err}"
                    )
            
            if origin_record:
                # Validate dữ liệu trước khi dùng
                if origin_record.rotation_matrix and origin_record.ecef_origin:
                    self.origin = {
                        'lat': origin_record.lat,
                        'lon': origin_record.lon,
                        'h': origin_record.h,
                        'R': np.array(origin_record.rotation_matrix),
                        'ecef': np.array(origin_record.ecef_origin)
                    }
                    self._origin_locked_at = getattr(origin_record, 'locked_at', None)
                    self._origin_record_id = getattr(origin_record, 'id', None)
                    if getattr(origin_record, 'tracking_offset', None):
                        try:
                            self.tracking_offset_enu = self._validated_tracking_offset(origin_record.tracking_offset)
                            logger.info(f"✅ [ASYNC LOAD] Loaded tracking offset for device {self.device_id}: {self.tracking_offset_enu}")
                        except Exception as ex:
                            logger.warning(f"⚠️ Device {self.device_id}: Ignored unsafe tracking offset: {ex}")
                    self.state = "ORIGIN_LOCKED"
                    if self._restore_runtime_state(runtime_state):
                        logger.info(
                            f"✅ [ASYNC LOAD] Restored GNSS safety checkpoint for device {self.device_id}"
                        )
                    else:
                        self._needs_boot_anchor = True
                        logger.warning(
                            f"[{self._log_prefix()}] No matching GNSS safety checkpoint; "
                            "first FIXED sample will be checked against the locked zero-ENU baseline"
                        )
                    logger.info(f"✅ [ASYNC LOAD] Loaded origin for device {self.device_id}: ({origin_record.lat}, {origin_record.lon})")
                else:
                    logger.warning(f"⚠️ Device {self.device_id}: Found origin record but matrix data is missing.")
            
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Failed to load origin from DB: {repr(e)}")
        finally:
            self._initialization_complete = True

    async def _save_origin_to_db(self):
        """✅ Lưu origin vào DB và đồng bộ vào Station Config"""
        try:
            from app.models.config import GNSSOrigin, Station
            from sqlalchemy import select, update
            from app.websocket import manager  # WebSocket manager
            
            async with self.db_session_factory() as db:
                # 1. Cập nhật bảng GNSSOrigin (dành cho Processor)
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                existing = result.scalar_one_or_none()
                
                rot_matrix = self.origin['R'].tolist() if hasattr(self.origin['R'], 'tolist') else self.origin['R']
                ecef_origin = self.origin['ecef'].tolist() if hasattr(self.origin['ecef'], 'tolist') else self.origin['ecef']
                tracking_offset_list = self.tracking_offset_enu.tolist() if hasattr(self.tracking_offset_enu, 'tolist') else list(self.tracking_offset_enu)

                is_new_origin = False
                if existing:
                    # A monitoring origin is a permanent reference. Never overwrite it
                    # from a later collection/race/restart.
                    self.origin = {
                        'lat': existing.lat,
                        'lon': existing.lon,
                        'h': existing.h,
                        'R': np.array(existing.rotation_matrix),
                        'ecef': np.array(existing.ecef_origin),
                    }
                    self._origin_locked_at = existing.locked_at
                    self._origin_record_id = existing.id
                    if getattr(existing, 'tracking_offset', None) and np.all(self.tracking_offset_enu == 0.0):
                        try:
                            self.tracking_offset_enu = self._validated_tracking_offset(existing.tracking_offset)
                        except Exception as ex:
                            logger.warning(f"⚠️ Device {self.device_id}: Ignored unsafe tracking offset: {ex}")
                    self.state = "ORIGIN_LOCKED"
                    logger.warning(
                        f"[{self._log_prefix()}] Existing locked origin preserved; candidate origin discarded"
                    )
                else:
                    is_new_origin = True
                    locked_at = int(time.time())
                    self._origin_locked_at = locked_at
                    new_origin = GNSSOrigin(
                        device_id=self.device_id,
                        lat=self.origin['lat'],
                        lon=self.origin['lon'],
                        h=self.origin['h'],
                        locked_at=locked_at,
                        spread_meters=0.0,
                        num_points=len(self.origin_candidates),
                        rotation_matrix=rot_matrix,
                        ecef_origin=ecef_origin,
                        tracking_offset=tracking_offset_list
                    )
                    db.add(new_origin)
                    await db.flush()
                    self._origin_record_id = new_origin.id
                
                # 2. ✅ Đồng bộ ngược vào Station.config['gnss_origin'] (dành cho UI Admin)
                # Tìm station_id từ device_id
                from app.models.config import Device
                dev_res = await db.execute(select(Device.station_id).where(Device.id == self.device_id))
                station_id = dev_res.scalar_one_or_none()
                
                if station_id and is_new_origin:
                    st_res = await db.execute(select(Station).where(Station.id == station_id))
                    station = st_res.scalar_one_or_none()
                    if station:
                        import copy
                        from sqlalchemy.orm.attributes import flag_modified
                        new_config = copy.deepcopy(station.config) if station.config else {}
                        new_config['gnss_origin'] = {
                            'lat': self.origin['lat'],
                            'lon': self.origin['lon'],
                            'h': self.origin['h'],
                            'locked_at': int(time.time())
                        }
                        station.config = new_config
                        flag_modified(station, 'config')
                        logger.info(f"🔄 Synced origin to Station {station_id} config")

                await db.commit()
                if is_new_origin:
                    logger.info(f"💾 Saved NEW origin for device {self.device_id} to DB (first-time lock)")

                # 3. ✅ Phát tín hiệu WebSocket để UI tự động cập nhật số mới
                if station_id:
                    await manager.broadcast({
                        "type": "origin_locked_event",
                        "station_id": station_id,
                        "sensor_type": "gnss",
                        "data": {
                            'lat': self.origin['lat'],
                            'lon': self.origin['lon'],
                            'h': self.origin['h']
                        }
                    })
                
        except Exception as e:
            logger.error(f"❌ Error saving origin to DB: {e}", exc_info=True)

    async def _async_save_tracking_offset(self, offset=None):
        """Persist current tracking_offset to DB without modifying origin coordinates."""
        try:
            from app.models.config import GNSSOrigin
            from sqlalchemy import select
            
            offset_value = np.asarray(
                self.tracking_offset_enu if offset is None else offset,
                dtype=float,
            )

            async with self.db_session_factory() as db:
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.tracking_offset = offset_value.tolist()
                    await db.commit()
                    logger.info(f"💾 Persisted updated tracking offset for device {self.device_id} to DB: {offset_value}")
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Error persisting tracking offset for device {self.device_id}: {e}")
            return False

    async def recalibrate_tracking_offset(
        self,
        *,
        station_id: Optional[int] = None,
        minimum_samples: int = 61,
        minimum_duration_s: float = 60.0,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
    ):
        """Collect a fresh stable FIXED window and re-zero displacement.

        During quarantine, samples are deliberately excluded from ``history``.
        A manual calibration therefore uses a short-lived capture buffer filled
        by ``_handle_processing`` while this method is waiting.
        """
        if self.state != "ORIGIN_LOCKED" or self.origin is None:
            raise ValueError("GNSS origin is not locked")
        if getattr(self, "_offset_calibration_in_progress", False):
            raise ValueError("GNSS offset calibration is already in progress")

        minimum_samples = max(2, int(minimum_samples))
        minimum_duration_s = max(0.0, float(minimum_duration_s))
        timeout_s = max(minimum_duration_s, float(timeout_s))
        poll_interval_s = max(0.01, float(poll_interval_s))
        started_after_ts = float(self.history[-1]["ts"]) if self.history else -math.inf
        old_offset = self.tracking_offset_enu.copy()
        capture_buffer = getattr(self, "_offset_calibration_samples", None)
        if capture_buffer is None:
            capture_buffer = deque(maxlen=600)
            self._offset_calibration_samples = capture_buffer
        capture_buffer.clear()
        deadline = asyncio.get_running_loop().time() + timeout_s
        self._offset_calibration_in_progress = True
        last_progress_second = -1
        used_capture_samples = False
        try:
            while True:
                captured_samples = list(capture_buffer)
                used_capture_samples = bool(captured_samples)
                samples = captured_samples or [
                    sample for sample in self.history
                    if float(sample["ts"]) > started_after_ts
                ]
                duration_s = (
                    float(samples[-1]["ts"] - samples[0]["ts"])
                    if len(samples) >= 2
                    else 0.0
                )
                progress_second = int(min(duration_s, minimum_duration_s))
                if progress_second != last_progress_second:
                    last_progress_second = progress_second
                    progress = {
                        "type": "gnss_offset_calibration_progress",
                        "station_id": station_id,
                        "device_id": self.device_id,
                        "data": {
                            "phase": "collecting",
                            "sample_count": len(samples),
                            "minimum_samples": minimum_samples,
                            "duration_s": round(duration_s, 1),
                            "minimum_duration_s": minimum_duration_s,
                            "remaining_s": max(0.0, minimum_duration_s - duration_s),
                        },
                    }
                    logger.info(
                        "[GNSS CALIBRATION] device=%s station=%s samples=%s/%s duration=%.1fs/%.1fs",
                        self.device_id,
                        station_id,
                        len(samples),
                        minimum_samples,
                        duration_s,
                        minimum_duration_s,
                    )
                    try:
                        from app.websocket import manager
                        await manager.broadcast(progress)
                    except Exception as exc:
                        logger.debug("GNSS calibration progress broadcast failed: %s", exc)
                if (
                    len(samples) >= minimum_samples
                    and duration_s >= minimum_duration_s
                ):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise ValueError(
                        "Timed out collecting fresh RTK FIXED samples "
                        f"({len(samples)}/{minimum_samples} samples, "
                        f"{duration_s:.1f}/{minimum_duration_s:.1f}s)"
                    )
                await asyncio.sleep(poll_interval_s)
        finally:
            self._offset_calibration_in_progress = False
            capture_buffer.clear()

        if not np.allclose(self.tracking_offset_enu, old_offset):
            raise ValueError("GNSS tracking reference changed during calibration; retry")

        positions = np.asarray([sample["pos_enu"] for sample in samples], dtype=float)
        center = np.median(positions, axis=0)
        residuals = positions - center
        spread_2d_m = float(np.max(np.linalg.norm(residuals[:, :2], axis=1)))
        spread_u_m = float(np.max(np.abs(residuals[:, 2])))
        config = self._integrity_config({})
        if (
            spread_2d_m > float(config["reacquire_max_spread_xy_m"])
            or spread_u_m > float(config["reacquire_max_spread_u_m"])
        ):
            raise ValueError(
                "RTK FIXED samples are not stable enough "
                f"(2D spread {spread_2d_m * 1000:.1f}mm, "
                f"vertical spread {spread_u_m * 1000:.1f}mm)"
            )

        proposed_offset = self._validated_tracking_offset(old_offset + center)
        if not await self._async_save_tracking_offset(proposed_offset):
            raise RuntimeError("Could not persist GNSS tracking offset")

        self.tracking_offset_enu = proposed_offset
        if used_capture_samples:
            # Quarantined samples never entered trusted history. Replace the
            # stale pre-shift anchor with their re-zeroed window so the first
            # post-calibration FIXED sample is accepted instead of creating a
            # synthetic jump back from ``-center``.
            self.history.clear()
            self.history.extend({
                "ts": sample["ts"],
                "pos_enu": np.asarray(sample["pos_enu"], dtype=float) - center,
            } for sample in samples)
        else:
            for sample in self.history:
                sample["pos_enu"] = np.asarray(sample["pos_enu"], dtype=float) - center

        calibrated_positions = np.asarray(
            [sample["pos_enu"] for sample in samples],
            dtype=float,
        )
        try:
            from app.websocket import manager
            completion_message = {
                "type": "gnss_offset_calibration_progress",
                "station_id": station_id,
                "device_id": self.device_id,
                "data": {
                    "phase": "complete",
                    "sample_count": len(samples),
                    "duration_s": round(duration_s, 1),
                    "remaining_s": 0.0,
                },
            }
            # Do not hold the HTTP calibration response on a stale browser socket.
            asyncio.create_task(manager.broadcast(completion_message))
        except Exception as exc:
            logger.debug("GNSS calibration completion broadcast failed: %s", exc)
        # Keep the newest measured residual; never synthesize a zero payload.
        self.disp_enu_state = calibrated_positions[-1].copy()
        self.disp_state_ready = True
        self._velocity_confirmation_history = deque(maxlen=120)
        self.last_significant_motion_ts = 0.0
        self.peak_displacement_mm = float(np.linalg.norm(self.disp_enu_state[:2]) * 1000.0)
        self._reference_transition = None
        self._consecutive_rejects = 0
        self.reacquire_candidates.clear()
        self._quarantine_checkpointed = False
        self._schedule_runtime_state_save(force=True)
        runtime_save_task = getattr(self, "_runtime_state_save_task", None)
        if runtime_save_task is not None:
            await asyncio.shield(runtime_save_task)

        return {
            "device_id": self.device_id,
            "sample_count": len(samples),
            "duration_s": duration_s,
            "spread_2d_mm": spread_2d_m * 1000.0,
            "spread_u_mm": spread_u_m * 1000.0,
            "shift_e_m": float(center[0]),
            "shift_n_m": float(center[1]),
            "shift_u_m": float(center[2]),
            "old_tracking_offset": old_offset.tolist(),
            "new_tracking_offset": proposed_offset.tolist(),
            "new_tracking_offset_2d_mm": float(
                np.linalg.norm(proposed_offset[:2]) * 1000.0
            ),
            "origin_unchanged": True,
        }

    def process_gngga(self, raw_payload: str, station_config: Dict = None) -> Optional[Dict[str, Any]]:
        status_type = 'origin_status' if self.state == "AWAITING_CANDIDATES" else 'gnss_status'
        if not getattr(self, "_initialization_complete", True):
            return {
                "type": status_type,
                "status": "INITIALIZING",
                "fix_quality": None,
                "fix_mode": "UNKNOWN",
                "message": "Waiting for persisted GNSS origin and safety checkpoint"
            }
        try:
            # Extract câu GGA từ bất kỳ vị trí nào trong string.
            # Lấy trọn vẹn câu GGA để validate checksum chính xác (không strip *XX)
            gga_match = re.search(r'\$G[NP]GGA,[^\r\n]+', raw_payload or '')
            if not gga_match:
                return {
                    "type": status_type,
                    "status": "NO_DATA",
                    "fix_quality": None,
                    "fix_mode": "UNKNOWN",
                    "message": "No GGA sentence found in payload"
                }

            payload = gga_match.group(0).strip()
            # Cắt gọn phần sau checksum nếu có byte rác
            if '*' in payload:
                star_idx = payload.find('*')
                payload = payload[:star_idx + 3]

            # Verify NMEA checksum if present
            if '*' in payload and not self._verify_nmea_checksum(payload):
                return {
                    "type": status_type,
                    "status": "CHECKSUM_FAILED",
                    "fix_quality": None,
                    "fix_mode": "UNKNOWN",
                    "message": "NMEA checksum verification failed"
                }

            parts = payload.split(',')
            if len(parts) < 10:
                return {
                    "type": status_type,
                    "status": "NO_DATA",
                    "fix_quality": None,
                    "fix_mode": "UNKNOWN",
                    "message": "Incomplete GGA sentence"
                }

            # lat/lon trống thường là mất tín hiệu/antenna issue -> NO_DATA, không phải INVALID.
            if not parts[2] or not parts[4]:
                return {
                    "type": status_type,
                    "status": "NO_DATA",
                    "fix_quality": int(parts[6]) if parts[6] else None,
                    "fix_mode": "UNKNOWN",
                    "message": "GGA has empty coordinate fields"
                }

            fix_quality = int(parts[6]) if parts[6] else 0
            
            if self.state == "AWAITING_CANDIDATES":
                return self._handle_origin_collection(payload, fix_quality, station_config)
            elif self.state == "ORIGIN_LOCKED":
                return self._handle_processing(payload, fix_quality, station_config, raw_payload)
            
            return None

        except Exception as e:
            logger.debug(f"GNSS payload parse skipped: {e}")
            return {
                "type": status_type,
                "status": "NO_DATA",
                "fix_quality": None,
                "fix_mode": "UNKNOWN",
                "message": "Failed to parse GGA payload"
            }

    def _handle_origin_collection(self, gngga_string, fix_quality, station_config: Dict = None):
        # Origin candidates must be one uninterrupted RTK-quality acquisition epoch.
        required_fix = getattr(self, "min_fix_quality", 4)
        if fix_quality != required_fix:
            self.stats['low_quality_rejected'] += 1
            self.origin_candidates.clear()
            self._last_origin_candidate_ts = None
            return {
                "type": "origin_status",
                "status": "WAITING_FOR_QUALITY",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "message": f"Waiting required fix={required_fix}, current={fix_quality} ({self._fix_mode(fix_quality)})"
            }

        point = self._parse_gngga(gngga_string)
        if not point: return None

        # Filter poor satellite geometry from immutable origin candidates
        integrity_cfg = self._integrity_config(station_config)
        ORIGIN_MAX_HDOP = integrity_cfg["process_max_hdop"]
        ORIGIN_MIN_SATS = integrity_cfg["process_min_sats"]
        if point.get('hdop', 99.9) > ORIGIN_MAX_HDOP or point.get('num_sats', 0) < ORIGIN_MIN_SATS:
            self.origin_candidates.clear()
            self._last_origin_candidate_ts = None
            return {
                "type": "origin_status",
                "status": "AWAITING_ORIGIN",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "raw_payload": gngga_string,
                "message": f"Waiting for quality baseline (HDOP={point.get('hdop')} max {ORIGIN_MAX_HDOP}, Sats={point.get('num_sats')} min {ORIGIN_MIN_SATS})"
            }

        candidate_ts = point.get("gga_timestamp") or point.get("received_timestamp") or time.time()
        max_gap_s = integrity_cfg["origin_max_gap_s"]
        last_candidate_ts = getattr(self, "_last_origin_candidate_ts", None)
        if last_candidate_ts is not None and (
            candidate_ts <= last_candidate_ts or candidate_ts - last_candidate_ts > max_gap_s
        ):
            self.origin_candidates.clear()
            logger.info(
                f"[{self._log_prefix()}] Origin candidate epoch reset after {candidate_ts - last_candidate_ts:.1f}s gap"
            )
        self._last_origin_candidate_ts = candidate_ts
        self.origin_candidates.append(point['wgs'])
        
        if len(self.origin_candidates) >= self.required_points:
            lats = [p['lat'] for p in self.origin_candidates]
            lons = [p['lon'] for p in self.origin_candidates]
            hs = [p['h'] for p in self.origin_candidates]
            
            center_lat = float(np.median(lats))
            center_lon = float(np.median(lons))
            center_h = float(np.median(hs))
            
            max_dist_xy = max(
                haversine_2d(center_lat, center_lon, p['lat'], p['lon']) 
                for p in self.origin_candidates
            )
            max_dist_u = max(
                abs(p['h'] - center_h)
                for p in self.origin_candidates
            )

            max_xy = getattr(self, 'origin_max_xy_spread_m', getattr(self, 'max_spread_m', 0.5))
            max_u = getattr(self, 'origin_max_u_spread_m', 1.0)

            if max_dist_xy <= max_xy and max_dist_u <= max_u:
                self.origin = {
                    'lat': center_lat, 
                    'lon': center_lon, 
                    'h': center_h, 
                    'R': self._get_rotation_matrix(center_lat, center_lon),
                    'ecef': self._gngga_to_ecef(center_lat, center_lon, center_h)
                }
                self.state = "ORIGIN_LOCKED"
                self._needs_boot_anchor = True
                logger.info(
                    f"ORIGIN LOCKED (Device {self.device_id}): ({center_lat:.6f}, {center_lon:.6f}, {center_h:.3f}m), "
                    f"Spread XY: {max_dist_xy:.3f}m (max={max_xy}m), U: {max_dist_u:.3f}m (max={max_u}m)"
                )
                
                # ✅ Save Async
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._save_origin_to_db())
                except RuntimeError:
                    logger.warning("Cannot save origin: No running event loop")
                
                return {
                    "type": "origin_locked",
                    "data": {
                        'lat': float(center_lat),
                        'lon': float(center_lon),
                        'h': float(center_h)
                    }
                }
            else:
                self.origin_candidates.clear()
                self._last_origin_candidate_ts = None
                self.stats['origin_resets'] += 1
                return {
                    "type": "origin_reset",
                    "message": f"Spread too high (XY={max_dist_xy:.3f}m > {max_xy}m, U={max_dist_u:.3f}m > {max_u}m)"
                }
        
        return {
            "type": "origin_collecting",
            "count": len(self.origin_candidates),
            "target": self.required_points
        }

    def _handle_processing(self, gngga_string, fix_quality, station_config: Dict = None, raw_payload: str = None):
        # Millimetre-level monitoring must use RTK FIXED exclusively. FLOAT and all
        # other modes are status-only and cannot mutate measurement state.
        required_fix = getattr(self, "min_fix_quality", 4)
        if fix_quality != required_fix:
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "gnss_status",
                "status": "UNTRUSTED_FIX",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "message": f"Measurement rejected: fix={required_fix} required, current={fix_quality} ({self._fix_mode(fix_quality)})"
            }
        
        # Flag: only RTK FIXED is trusted for alerting analysis
        is_trusted_fix = True

        point = self._parse_gngga(gngga_string)
        if not point:
            return None

        integrity_cfg = self._integrity_config(station_config)
        if (
            point.get("hdop", 99.9) > integrity_cfg["process_max_hdop"]
            or point.get("num_sats", 0) < integrity_cfg["process_min_sats"]
        ):
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "gnss_status",
                "status": "UNTRUSTED_GEOMETRY",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "raw_payload": raw_payload or gngga_string,
                "data": {
                    "integrity_state": "UNTRUSTED_GEOMETRY",
                    "position_quality_reliable": False,
                    "hdop": point.get("hdop"),
                    "num_sats": point.get("num_sats"),
                    "max_hdop": integrity_cfg["process_max_hdop"],
                    "min_sats": integrity_cfg["process_min_sats"],
                },
                "message": "Measurement rejected: RTK FIXED geometry below monitoring threshold",
            }

        received_ts = time.time()
        ts = point.get('gga_timestamp') or received_ts
        ecef_coords = self._gngga_to_ecef(
            point['wgs']['lat'],
            point['wgs']['lon'],
            point['wgs']['h']
        )
        pos_enu_raw = self.origin['R'] @ (ecef_coords - self.origin['ecef'])
        if not np.all(np.isfinite(pos_enu_raw)):
            logger.warning(f"Non-finite ENU position rejected (device {self.device_id})")
            return None

        # Subtract tracking_offset_enu so that the reacquired baseline reference is applied to every incoming sample
        pos_enu = pos_enu_raw - getattr(self, 'tracking_offset_enu', np.zeros(3, dtype=float))

        # Never let the first post-restart fix silently become the trusted baseline.
        # A persisted checkpoint is preferred; zero ENU is the conservative fallback.
        if getattr(self, "_needs_boot_anchor", False):
            if not self.history:
                self.history.append({
                    "ts": ts - 1.0,
                    "pos_enu": np.zeros(3, dtype=float),
                })
            self._needs_boot_anchor = False

        reference_result = self._handle_reference_transition(
            ts, pos_enu, fix_quality, station_config, raw_payload or gngga_string,
        )
        if reference_result is not None:
            return reference_result

        # Keep a bounded, non-persisted capture window for the explicit manual
        # calibration action. This includes FIXED samples that the integrity
        # gate will quarantine below, so a shifted cluster can be recalibrated
        # instead of waiting forever for accepted history to appear.
        if getattr(self, "_offset_calibration_in_progress", False):
            capture_buffer = getattr(self, "_offset_calibration_samples", None)
            if capture_buffer is not None:
                capture_buffer.append({
                    "ts": float(ts),
                    "pos_enu": np.asarray(pos_enu, dtype=float).copy(),
                })

        self.history.append({
            'ts': ts,
            'pos_enu': pos_enu,
        })

        if len(self.history) < 2:
            return None

        p_new = self.history[-1]
        p_old = self.history[-2]
        dt = p_new['ts'] - p_old['ts']

        if dt < 0.01:
            self.history.pop()
            return {
                "type": "gnss_status",
                "status": "NON_MONOTONIC_GGA_TIME",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "message": f"Measurement rejected: non-increasing GGA time (dt={dt:.3f}s)"
            }

        v_enu_raw = (p_new['pos_enu'] - p_old['pos_enu']) / dt
        if not np.all(np.isfinite(v_enu_raw)):
            logger.warning(f"Non-finite raw velocity rejected (device {self.device_id})")
            self.history.pop()
            return None

        # ── Spike rejection with cascade-break ──
        # Compare new sample against last accepted sample.
        step_2d_m = float(np.hypot(v_enu_raw[0], v_enu_raw[1]) * dt)
        step_u_m = float(abs(v_enu_raw[2]) * dt)

        # If dt is too large (stale reference), the comparison is meaningless.
        # Do not force-accept a bad fix just because rejects are consecutive:
        # that would silently move the accepted trajectory away from the locked origin.
        if not hasattr(self, '_consecutive_rejects'):
            self._consecutive_rejects = 0
        if not hasattr(self, '_last_stale_reject_log_ts'):
            self._last_stale_reject_log_ts = 0.0
        if not hasattr(self, '_last_bad_fix_log_ts'):
            self._last_bad_fix_log_ts = 0.0

        # Dynamic step limits based on fix quality
        current_max_2d = self.max_step_distance_m if is_trusted_fix else self.max_step_distance_m * 0.5
        current_max_u = self.max_step_vertical_m if is_trusted_fix else self.max_step_vertical_m * 0.5

        is_spike = step_2d_m > current_max_2d or step_u_m > current_max_u
        stale_reference = dt > 60.0

        if is_spike:
            quarantine_started = not self.reacquire_candidates
            if quarantine_started:
                self._shift_started_at = ts
                self._quarantine_checkpointed = False
            self._consecutive_rejects += 1
            self.stats['spike_rejected'] += 1
            self.history.pop()
            self.reacquire_candidates.append({
                'ts': ts,
                'pos_enu': pos_enu,
                'fix_quality': fix_quality,
            })
            self._schedule_runtime_state_save(force=quarantine_started)

            persistent_offset = False
            candidate_offset_2d_m = None
            candidate_offset_u_m = None
            shift_data = None
            if len(self.reacquire_candidates) >= 6:
                candidate_positions = np.array([c['pos_enu'] for c in self.reacquire_candidates], dtype=float)
                candidate_center = np.median(candidate_positions, axis=0)
                candidate_xy_spread = float(np.max(np.linalg.norm(candidate_positions[:, :2] - candidate_center[:2], axis=1)))
                candidate_u_spread = float(np.max(np.abs(candidate_positions[:, 2] - candidate_center[2])))
                candidate_offset_2d_m = float(np.linalg.norm(candidate_center[:2] - p_old['pos_enu'][:2]))
                candidate_offset_u_m = float(abs(candidate_center[2] - p_old['pos_enu'][2]))
                persistent_offset = bool(
                    candidate_xy_spread <= integrity_cfg["reacquire_max_spread_xy_m"]
                    and candidate_u_spread <= integrity_cfg["reacquire_max_spread_u_m"]
                )
                persistent_shift_duration_s = ts - getattr(self, "_shift_started_at", ts)
                persistent_shift_duration_ok = persistent_shift_duration_s >= 60.0

                # ── Guard: reject reacquire for unrealistic offsets ──
                # A real tracking shift (e.g. GNSS base station switchover) is
                # typically < 0.5 m horizontal and < 1.0 m vertical. Offsets of
                # 3+ metres are systematic datum/geoid issues that must NOT be
                # absorbed — doing so creates an infinite reacquire loop.
                REACQUIRE_MAX_OFFSET_2D_M = 0.5
                REACQUIRE_MAX_OFFSET_U_M = 1.0
                # Maximum accumulated tracking offset before we stop absorbing.
                TRACKING_OFFSET_CAP_M = 2.0
                # Minimum interval between successive reacquires to prevent cycling.
                REACQUIRE_COOLDOWN_S = 300.0  # 5 minutes

                offset_too_large = bool(
                    candidate_offset_2d_m > REACQUIRE_MAX_OFFSET_2D_M
                    or candidate_offset_u_m > REACQUIRE_MAX_OFFSET_U_M
                )
                current_tracking_offset = getattr(self, 'tracking_offset_enu', np.zeros(3, dtype=float))
                tracking_shift = candidate_center - p_old['pos_enu']
                proposed_tracking_offset = current_tracking_offset + tracking_shift
                accumulated_too_much = bool(
                    np.linalg.norm(proposed_tracking_offset) > TRACKING_OFFSET_CAP_M
                )
                last_reacquire_ts = getattr(self, '_last_reacquire_ts', 0.0)
                in_cooldown = bool(ts - last_reacquire_ts < REACQUIRE_COOLDOWN_S)

                ref_ts, _ = self._reference_event(station_config)
                event_aligned = bool(
                    ref_ts is not None
                    and 0.0 <= getattr(self, "_shift_started_at", ts) - ref_ts
                    <= integrity_cfg["reference_event_alignment_s"]
                )

                # Reacquire compensation requires the event to align with shift onset,
                # not merely to be recent when the stable cluster is confirmed.
                reacquire_allowed = bool(
                    event_aligned
                    or getattr(self, "allow_auto_reacquire", False)
                )
                shift_data = self._shift_data(
                    tracking_shift, candidate_xy_spread, candidate_u_spread,
                    persistent_shift_duration_s, event_aligned, not reacquire_allowed,
                    ref_ts, getattr(self, "_shift_started_at", ts),
                )

                if (
                    persistent_offset
                    and persistent_shift_duration_ok
                    and not offset_too_large
                    and not accumulated_too_much
                    and not in_cooldown
                    and reacquire_allowed
                ):
                    shift_data["integrity_state"] = "TRACKING_REACQUIRED"
                    shift_data["position_quality_reliable"] = True
                    self.tracking_offset_enu = proposed_tracking_offset
                    self._last_reacquire_ts = ts
                    # Consume the reference change event once successfully absorbed
                    self._reference_changed_at = None
                    self._reference_change_source = None
                    self._last_handled_reference_event_ts = ref_ts
                    self.history.clear()
                    self.history.extend({
                        'ts': candidate['ts'],
                        'pos_enu': candidate['pos_enu'] - tracking_shift,
                    } for candidate in self.reacquire_candidates)
                    self.reacquire_candidates.clear()
                    self._consecutive_rejects = 0
                    self._quarantine_checkpointed = False
                    logger.info(
                        f"[{self._log_prefix()}] Tracking reacquired after verified reference shift (duration={persistent_shift_duration_s:.1f}s): "
                        f"offset2d={candidate_offset_2d_m:.3f}m, offsetU={candidate_offset_u_m:.3f}m. "
                        "Locked origin and last accepted displacement preserved."
                    )
                    self._schedule_runtime_state_save(force=True, persist_tracking_offset=True)

                    return {
                        "type": "gnss_status",
                        "status": "TRACKING_REACQUIRED",
                        "fix_quality": fix_quality,
                        "fix_mode": self._fix_mode(fix_quality),
                        "raw_payload": raw_payload or gngga_string,
                        "data": self._shift_data(
                            tracking_shift, candidate_xy_spread, candidate_u_spread,
                            persistent_shift_duration_s, event_aligned, False,
                            ref_ts, getattr(self, "_shift_started_at", ts),
                        ),
                        "message": "Stable RTK FIXED tracking reacquired after verified reference shift"
                    }

                if persistent_offset and persistent_shift_duration_ok and (offset_too_large or accumulated_too_much or in_cooldown or not reacquire_allowed):
                    if not getattr(self, "_quarantine_checkpointed", False):
                        self._quarantine_checkpointed = True
                        self._schedule_runtime_state_save(force=True)
                    # Log why reacquire was refused (only once per 60s to reduce spam).
                    if not hasattr(self, '_last_reacquire_refused_log_ts'):
                        self._last_reacquire_refused_log_ts = 0.0
                    if (ts - self._last_reacquire_refused_log_ts) >= 60.0:
                        self._last_reacquire_refused_log_ts = ts
                        reasons = []
                        if offset_too_large:
                            reasons.append(f"offset too large (2d={candidate_offset_2d_m:.3f}m max={REACQUIRE_MAX_OFFSET_2D_M}m, U={candidate_offset_u_m:.3f}m max={REACQUIRE_MAX_OFFSET_U_M}m)")
                        if accumulated_too_much:
                            reasons.append(f"proposed tracking offset {np.linalg.norm(proposed_tracking_offset):.3f}m exceeds cap {TRACKING_OFFSET_CAP_M}m")
                        if in_cooldown:
                            reasons.append(f"cooldown active ({ts - last_reacquire_ts:.0f}s < {REACQUIRE_COOLDOWN_S:.0f}s)")
                        if not reacquire_allowed:
                            reasons.append("reference change not confirmed; possible real ground movement")
                        logger.warning(
                            f"[{self._log_prefix()}] Reacquire REFUSED: {'; '.join(reasons)}. "
                            "Origin and displacement remain frozen at last accepted values."
                        )

                if persistent_offset and (ts - self._last_bad_fix_log_ts) >= 30.0:
                    logger.warning(
                        f"[{self._log_prefix()}] Persistent shifted GNSS cluster quarantined: "
                        f"offset2d={candidate_offset_2d_m:.3f}m, offsetU={candidate_offset_u_m:.3f}m, "
                        f"spread2d={candidate_xy_spread:.3f}m, spreadU={candidate_u_spread:.3f}m. "
                        "Tracking and displacement remain at the last accepted FIXED position."
                    )

            if (ts - self._last_bad_fix_log_ts) >= 30.0:
                self._last_bad_fix_log_ts = ts
                logger.warning(
                    f"[{self._log_prefix()}] Bad fix rejected (#{self._consecutive_rejects}): "
                    f"step2d={step_2d_m:.3f}m (max={current_max_2d}m), "
                    f"stepU={step_u_m:.3f}m (max={current_max_u}m), quality={fix_quality}"
                )

            if stale_reference and (ts - self._last_stale_reject_log_ts) >= 30.0:
                self._last_stale_reject_log_ts = ts
                logger.warning(
                    f"[{self._log_prefix()}] Stale reference after reject: dt={dt:.1f}s. "
                    "Keeping locked origin and last accepted displacement; waiting for a stable fix."
                )
            return {
                "type": "gnss_status",
                "status": "UNVERIFIED_POSITION_SHIFT" if persistent_offset else "INVALID_DATA",
                "sub_status": "UNVERIFIED_POSITION_SHIFT" if persistent_offset else "UNSTABLE_FIX",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "raw_payload": raw_payload or gngga_string,
                "data": shift_data,
                "message": (
                    f"Unverified shifted FIXED cluster: offset2d={candidate_offset_2d_m:.3f}m "
                    f"offsetU={candidate_offset_u_m:.3f}m; last trusted position preserved"
                    if persistent_offset else
                    f"Velocity skipped: rejected jump step2d={step_2d_m:.3f}m "
                    f"stepU={step_u_m:.3f}m from last accepted fix"
                )
            }

        # Good sample accepted — reset consecutive reject counter
        quarantine_cleared = bool(self.reacquire_candidates)
        self._consecutive_rejects = 0
        self._shift_started_at = None
        self.reacquire_candidates.clear()
        self._quarantine_checkpointed = False
        self._schedule_runtime_state_save(force=quarantine_cleared)

        gnss_alert_cfg = (station_config or {}).get("GnssAlerting", {}) if isinstance(station_config, dict) else {}
        try:
            velocity_window_seconds = max(float(gnss_alert_cfg.get("velocity_window_seconds", 15.0)), 4.0)
        except Exception:
            velocity_window_seconds = 15.0
        try:
            velocity_min_samples = max(int(gnss_alert_cfg.get("velocity_min_samples", 5)), 3)
        except Exception:
            velocity_min_samples = 5
        try:
            velocity_min_duration_s = max(float(gnss_alert_cfg.get("velocity_min_duration_s", 4.0)), 1.0)
        except Exception:
            velocity_min_duration_s = 4.0
        try:
            velocity_max_residual_mm = max(float(gnss_alert_cfg.get("velocity_max_residual_mm", 50.0)), 1.0)
        except Exception:
            velocity_max_residual_mm = 50.0

        history_for_velocity = [
            sample for sample in self.history
            if sample['ts'] >= (self.history[-1]['ts'] - velocity_window_seconds)
        ]
        velocity_duration = (
            history_for_velocity[-1]['ts'] - history_for_velocity[0]['ts']
            if len(history_for_velocity) >= 2 else 0.0
        )
        if len(history_for_velocity) < velocity_min_samples or velocity_duration < velocity_min_duration_s:
            return {
                "type": "gnss_status",
                "status": "VELOCITY_WARMUP",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "audit": False,
                "message": (
                    f"Collecting RTK FIXED velocity window: {len(history_for_velocity)}/{velocity_min_samples} "
                    f"samples, {velocity_duration:.1f}/{velocity_min_duration_s:.1f}s"
                )
            }

        velocity_estimate = self._robust_velocity_estimate(history_for_velocity)
        if not velocity_estimate or not np.all(np.isfinite(velocity_estimate['velocity'])):
            logger.warning(f"Robust velocity estimate failed (device {self.device_id})")
            return None

        # Never clip the observation. Keep the estimate intact and expose quality flags.
        v_enu_stable = np.array(velocity_estimate['velocity'], dtype=float, copy=True)
        velocity_reliable = velocity_estimate['residual_rms_mm'] <= velocity_max_residual_mm
        try:
            flag_xy_mm_s = float(gnss_alert_cfg.get("velocity_soft_limit_xy_mm_s", 1.0))
        except Exception:
            flag_xy_mm_s = 1.0
        try:
            flag_z_mm_s = float(gnss_alert_cfg.get("velocity_soft_limit_z_mm_s", 15.0))
        except Exception:
            flag_z_mm_s = 15.0
        velocity_out_of_range = bool(
            abs(v_enu_stable[0] * 1000.0) > flag_xy_mm_s
            or abs(v_enu_stable[1] * 1000.0) > flag_xy_mm_s
            or abs(v_enu_stable[2] * 1000.0) > flag_z_mm_s
        )
        estimated_speed_3d_mm_s = float(np.linalg.norm(v_enu_stable) * 1000.0)
        try:
            velocity_min_sigma = max(
                float(gnss_alert_cfg.get('velocity_min_sigma', 3.0)),
                1.0,
            )
        except (TypeError, ValueError):
            velocity_min_sigma = 3.0
        velocity_uncertainty_mm_s = float(velocity_estimate['uncertainty_mm_s'])
        velocity_detection_threshold_mm_s = max(
            velocity_min_sigma * velocity_uncertainty_mm_s
            if math.isfinite(velocity_uncertainty_mm_s) else float('inf'),
            0.15,  # conservative RTK FIXED floor; this is not the movement value
        )
        velocity_z_score = (
            estimated_speed_3d_mm_s / velocity_uncertainty_mm_s
            if math.isfinite(velocity_uncertainty_mm_s) and velocity_uncertainty_mm_s > 0.0
            else 0.0
        )
        velocity_significant = bool(
            math.isfinite(velocity_detection_threshold_mm_s)
            and estimated_speed_3d_mm_s >= velocity_detection_threshold_mm_s
        )
        confirmation_cfg = dict(gnss_alert_cfg)
        # Confirmation samples must represent independent velocity windows;
        # otherwise a 1 Hz stream counts the same 15 s window many times.
        confirmation_cfg.setdefault('velocity_confirmation_min_gap_s', velocity_window_seconds)
        velocity_confirmation = self._update_velocity_confirmation(
            ts,
            v_enu_stable,
            velocity_significant,
            velocity_reliable,
            confirmation_cfg,
        )
        self.v_enu_state = v_enu_stable.copy()
        self.v_state_ready = True

        # Parse VN2000 parameters from config if present.
        # Accept both keys for backward compatibility:
        # - vn2000 (new)
        # - vn2000_params (legacy from older admin UI payload)
        forwarding_cfg = (station_config or {}).get('gnss_rtk_forwarding', {})
        forwarding_enabled = forwarding_cfg.get('enabled', False)

        n_vn, e_vn, h_vn = None, None, None
        
        custom_datum = DatumParams()
        if forwarding_enabled:
            vn_cfg = (station_config or {}).get("vn2000") or (station_config or {}).get("vn2000_params") or {}
            if vn_cfg and vn_cfg.get("enabled"):
                try:
                    l0_deg, _ = normalize_vn2000_l0_value(vn_cfg.get("l0_deg", 105.0))
                    if vn_cfg.get("l0_raw") or str(vn_cfg.get("l0_input_format", "")).startswith("deg_min"):
                        l0_deg, _ = parse_vn2000_central_meridian(vn_cfg.get("l0_raw", l0_deg), default=l0_deg)

                    custom_datum = DatumParams(
                        dx=float(vn_cfg.get("dx", 191.90441429)),
                        dy=float(vn_cfg.get("dy", 39.30318279)),
                        dz=float(vn_cfg.get("dz", 111.45032835)),
                        rx=float(vn_cfg.get("rx", 0.00928836)),
                        ry=float(vn_cfg.get("ry", -0.01975479)),
                        rz=float(vn_cfg.get("rz", 0.00427372)),
                        k=float(vn_cfg.get("k", 0.999999747093722)),
                        l0_deg=l0_deg,
                        k0=float(vn_cfg.get("k0", 0.9999)),
                        false_e=float(vn_cfg.get("false_e", 500000.0)),
                        false_n=float(vn_cfg.get("false_n", 0.0)),
                        res_b=float(vn_cfg.get("res_b", 0.0)),
                        res_l=float(vn_cfg.get("res_l", 0.0)),
                        res_h=float(vn_cfg.get("res_h", 0.0)),
                        res_n=float(vn_cfg.get("res_n", 0.0)),
                        res_e=float(vn_cfg.get("res_e", 0.0)),
                        res_h_shift=float(vn_cfg.get("res_h_shift", 0.0))
                    )
                except Exception as e:
                    logger.error(f"Error parsing VN2000 custom params for device {self.device_id}: {e}")

        # Calculate VN2000 NEH
        if forwarding_enabled:
            n_vn, e_vn, h_vn = VN2000Converter.wgs84_to_vn2000(
                point['wgs']['lat'], point['wgs']['lon'], point['wgs']['h'],
                custom_params=custom_datum
            )

        speed_2d = float(np.hypot(v_enu_stable[0], v_enu_stable[1]))
        # Commit net displacement only after a stable time window. Once committed,
        # hold it inside the measured noise floor unless statistically significant
        # motion (or its short settling tail) is present. This eliminates the old
        # repeating ramps caused by rolling-median membership changes.
        try:
            displacement_window_s = max(float(gnss_alert_cfg.get("displacement_window_seconds", 30.0)), 10.0)
        except Exception:
            displacement_window_s = 30.0
        try:
            displacement_min_samples = max(int(gnss_alert_cfg.get("displacement_min_samples", 15)), 5)
        except Exception:
            displacement_min_samples = 15
        try:
            displacement_min_duration_s = max(float(gnss_alert_cfg.get("displacement_min_duration_s", 15.0)), 4.0)
        except Exception:
            displacement_min_duration_s = 15.0
        try:
            displacement_noise_floor_min_mm = max(float(gnss_alert_cfg.get("displacement_noise_floor_min_mm", 2.0)), 0.5)
        except Exception:
            displacement_noise_floor_min_mm = 2.0
        try:
            displacement_stationary_speed_mm_s = max(
                float(gnss_alert_cfg.get("displacement_stationary_speed_mm_s", 0.3)),
                0.0,
            )
        except Exception:
            displacement_stationary_speed_mm_s = 0.3
        displacement_history = [
            sample for sample in self.history
            if sample['ts'] >= (self.history[-1]['ts'] - displacement_window_s)
        ]
        displacement_duration_s = (
            displacement_history[-1]['ts'] - displacement_history[0]['ts']
            if len(displacement_history) >= 2 else 0.0
        )
        if (
            len(displacement_history) < displacement_min_samples
            or displacement_duration_s < displacement_min_duration_s
        ):
            return {
                "type": "gnss_status",
                "status": "DISPLACEMENT_WARMUP",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "audit": False,
                "message": (
                    f"Collecting stable displacement window: {len(displacement_history)}/{displacement_min_samples} "
                    f"samples, {displacement_duration_s:.1f}/{displacement_min_duration_s:.1f}s"
                )
            }

        displacement_positions = np.array([sample['pos_enu'] for sample in displacement_history], dtype=float)
        displacement_candidate = np.median(displacement_positions, axis=0)
        residual_3d_mm = (
            np.linalg.norm(displacement_positions - displacement_candidate, axis=1) * 1000.0
        )
        residual_median_mm = float(np.median(residual_3d_mm))
        residual_mad_mm = float(np.median(np.abs(residual_3d_mm - residual_median_mm)))
        displacement_noise_floor_mm = max(
            displacement_noise_floor_min_mm,
            residual_median_mm + 1.4826 * residual_mad_mm,
        )
        displacement_uncertainty_mm = max(
            displacement_noise_floor_min_mm / math.sqrt(len(displacement_history)),
            1.4826 * residual_mad_mm / math.sqrt(len(displacement_history)),
        )

        try:
            displacement_change_sigma = max(
                float(gnss_alert_cfg.get("displacement_change_sigma", 3.0)),
                1.0,
            )
        except (TypeError, ValueError):
            displacement_change_sigma = 3.0

        displacement_updated = False
        candidate_step_mm = None
        measured_speed_3d_mm_s = estimated_speed_3d_mm_s
        displacement_change_threshold_mm = max(
            displacement_noise_floor_mm * displacement_change_sigma,
            displacement_uncertainty_mm * displacement_change_sigma,
            displacement_noise_floor_min_mm,
        )
        if not self.disp_state_ready:
            # Publish the real displacement from the locked origin after the
            # first stable window; stationary gating only controls later drift.
            self.disp_enu_state = displacement_candidate.copy()
            self.disp_state_ready = True
            displacement_updated = True
        else:
            # Compare the new position candidate with the last accepted
            # position.  Cumulative peak/alpha updates are deliberately not
            # used as movement evidence.
            candidate_step_mm = float(
                np.linalg.norm(displacement_candidate - self.disp_enu_state) * 1000.0
            )
        position_change_significant = bool(
            self.disp_state_ready
            and candidate_step_mm is not None
            and candidate_step_mm >= displacement_change_threshold_mm
            and measured_speed_3d_mm_s >= displacement_stationary_speed_mm_s
        )
        motion_confirmed = bool(
            velocity_confirmation['confirmed'] and position_change_significant
        )
        if (
            self.disp_state_ready
            and motion_confirmed
            and velocity_confirmation.get('accepted_sample', True)
        ):
            # The median candidate is already the robust position estimate for
            # this window.  Commit it only at an independent confirmation
            # epoch, so a stationary multipath drift cannot ramp the state.
            self.disp_enu_state = displacement_candidate.copy()
            displacement_updated = True

        # Keep the raw speed and uncertainty visible even when the movement
        # decision is negative.  The public confirmation flag combines the
        # independent velocity evidence with the position-change test.
        movement_confirmed = motion_confirmed

        total_displacement_m = float(np.linalg.norm(self.disp_enu_state[:2]))
        total_displacement_3d_m = float(np.linalg.norm(self.disp_enu_state))
        self.peak_displacement_mm = max(
            float(getattr(self, 'peak_displacement_mm', 0.0)),
            total_displacement_m * 1000.0,
        )

        # ── Unit conversions ──────────────────────────────────────────
        # ALL displacement outputs unified to CM (centimeters).
        # pos_e/n/u = ENU displacement from origin (cm)
        # Use filtered state (self.disp_enu_state) for consistency across all fields
        f_pos_e_cm = float(self.disp_enu_state[0] * 100.0)
        f_pos_n_cm = float(self.disp_enu_state[1] * 100.0)
        f_pos_u_cm = float(self.disp_enu_state[2] * 100.0)

        total_displacement_mm = total_displacement_m * 1000.0
        total_displacement_3d_mm = total_displacement_3d_m * 1000.0
        # Tách riêng 2D (mặt bằng) và Vertical (cao độ) để người dùng dễ đánh giá
        total_displacement_2d_mm = float(np.hypot(self.disp_enu_state[0], self.disp_enu_state[1]) * 1000.0)
        vertical_displacement_mm = float(abs(self.disp_enu_state[2]) * 1000.0)
        
        # Velocity in mm/s and mm/min
        v_e_mm_s = float(v_enu_stable[0] * 1000.0)
        v_n_mm_s = float(v_enu_stable[1] * 1000.0)
        v_u_mm_s = float(v_enu_stable[2] * 1000.0)
        raw_v_e_mm_s = float(v_enu_raw[0] * 1000.0)
        raw_v_n_mm_s = float(v_enu_raw[1] * 1000.0)
        raw_v_u_mm_s = float(v_enu_raw[2] * 1000.0)
        raw_speed_2d_mm_s = float(np.hypot(v_enu_raw[0], v_enu_raw[1]) * 1000.0)
        
        # Zero-clamping removed as per user request to allow values to jump continuously

        self.stats['total_processed'] += 1

        result_data = {
            'raw_gngga': gngga_string,
            'raw_payload': raw_payload or gngga_string,
            'gga_utc': point.get('gga_utc'),
            'gga_timestamp': point.get('gga_timestamp'),
            'received_timestamp': point.get('received_timestamp'),
            'raw_lat': point['wgs']['lat'],
            'raw_lon': point['wgs']['lon'],
            'raw_h': point['wgs']['h'],
            'lat': point['wgs']['lat'],
            'lon': point['wgs']['lon'],
            'h': point['wgs']['h'],
            'raw_pos_e': float(pos_enu_raw[0] * 100.0),
            'raw_pos_n': float(pos_enu_raw[1] * 100.0),
            'raw_pos_u': float(pos_enu_raw[2] * 100.0),
            'candidate_pos_e': float(displacement_candidate[0] * 100.0),
            'candidate_pos_n': float(displacement_candidate[1] * 100.0),
            'candidate_pos_u': float(displacement_candidate[2] * 100.0),
            'candidate_horizontal_displacement_mm': float(np.hypot(displacement_candidate[0], displacement_candidate[1]) * 1000.0),
            'candidate_vertical_displacement_mm': float(abs(displacement_candidate[2]) * 1000.0),
            'candidate_displacement_3d_mm': float(np.linalg.norm(displacement_candidate) * 1000.0),
            'pos_e': f_pos_e_cm,
            'pos_n': f_pos_n_cm,
            'pos_u': f_pos_u_cm,
            'tracking_offset_e_m': float(getattr(self, 'tracking_offset_enu', np.zeros(3))[0]),
            'tracking_offset_n_m': float(getattr(self, 'tracking_offset_enu', np.zeros(3))[1]),
            'tracking_offset_u_m': float(getattr(self, 'tracking_offset_enu', np.zeros(3))[2]),
            'total_displacement_mm': total_displacement_mm,
            'horizontal_displacement_mm': total_displacement_2d_mm,
            'vertical_displacement_mm': vertical_displacement_mm,
            'displacement_3d_mm': total_displacement_3d_mm,
            'peak_displacement_mm': self.peak_displacement_mm,
            'displacement_updated': displacement_updated,
            'displacement_window_duration_s': displacement_duration_s,
            'displacement_sample_count': len(displacement_history),
            'displacement_noise_floor_mm': displacement_noise_floor_mm,
            'displacement_uncertainty_mm': displacement_uncertainty_mm,
            'candidate_step_displacement_mm': candidate_step_mm,
            'displacement_change_threshold_mm': displacement_change_threshold_mm,
            'position_change_significant': position_change_significant,
            'vel_e': v_e_mm_s,
            'vel_n': v_n_mm_s,
            'vel_u': v_u_mm_s,
            'speed_2d': speed_2d,
            'speed_2d_mm_s': float(speed_2d * 1000),
            'raw_vel_e_mm_s': raw_v_e_mm_s,
            'raw_vel_n_mm_s': raw_v_n_mm_s,
            'raw_vel_u_mm_s': raw_v_u_mm_s,
            'raw_speed_2d_mm_s': raw_speed_2d_mm_s,
            'velocity_method': 'theil_sen_enu',
            'velocity_sample_count': velocity_estimate['sample_count'],
            'velocity_window_duration_s': velocity_estimate['duration_s'],
            'velocity_residual_rms_mm': velocity_estimate['residual_rms_mm'],
            'velocity_residual_mad_mm': velocity_estimate['residual_mad_mm'],
            'velocity_uncertainty_mm_s': velocity_estimate['uncertainty_mm_s'],
            'velocity_confidence_95_mm_s': velocity_estimate['confidence_95_mm_s'],
            'velocity_detection_threshold_mm_s': velocity_detection_threshold_mm_s,
            'velocity_z_score': velocity_z_score,
            'velocity_min_sigma': velocity_min_sigma,
            'velocity_reliable': velocity_reliable,
            # Keep the public movement flag conservative. The raw statistical
            # result is exposed separately for diagnostics, so a stationary
            # multipath spike cannot look like confirmed movement in logs/API.
            'velocity_significant': movement_confirmed,
            'velocity_statistically_significant': velocity_significant,
            'velocity_persistent': velocity_confirmation['confirmed'],
            'velocity_confirmed': movement_confirmed,
            'velocity_confirmation_sample_count': velocity_confirmation['sample_count'],
            'velocity_confirmation_duration_s': velocity_confirmation['duration_s'],
            'velocity_confirmation_direction_cosine': velocity_confirmation['direction_cosine'],
            'velocity_confirmation_accepted_sample': velocity_confirmation.get('accepted_sample', False),
            'velocity_confirmation_min_gap_s': velocity_confirmation.get('minimum_gap_s'),
            'velocity_confirmation_required_samples': velocity_confirmation['required_samples'],
            'velocity_confirmation_required_duration_s': velocity_confirmation['required_duration_s'],
            'velocity_out_of_range': velocity_out_of_range,
            'fix_quality': point['fix_quality'],
            'fix_mode': self._fix_mode(point['fix_quality']),
            'num_sats': point['num_sats'],
            'hdop': point['hdop'],
            'integrity': {
                'integrity_state': 'TRACKING_NORMAL',
                'position_quality_reliable': True,
                'hdop': point['hdop'],
                'num_sats': point['num_sats'],
            },
        }

        if forwarding_enabled and n_vn is not None:
            # Chuyển Origin sang VN2000 để nhất quán với lat/lon/h nếu đang dùng VN2000
            result_data.update({
                'vn2000_n': n_vn,
                'vn2000_e': e_vn,
                'vn2000_h': h_vn,
                'forwarding_data': {
                    'type': forwarding_cfg.get('gnss_code', 'gnss_processed'),
                    # Preserve the original forward contract: server receive epoch.
                    'timestamp': int(received_ts),
                    'data': {
                        'lat': n_vn,
                        'lon': e_vn,
                        'h': h_vn,
                        'pos_e': f_pos_e_cm,
                        'pos_n': f_pos_n_cm,
                        'pos_u': f_pos_u_cm,
                        'total_displacement_mm': total_displacement_mm,
                        'speed_2d_mm_s': float(speed_2d * 1000),
                        'fix_quality': point['fix_quality'],
                        'fix_mode': self._fix_mode(point['fix_quality']),
                        'num_sats': point['num_sats'],
                        'hdop': point['hdop'],
                        'origin_lat': float(self.origin['lat']),
                        'origin_lon': float(self.origin['lon']),
                        'origin_h': float(self.origin['h']),
                        'adv_x': n_vn,
                        'adv_y': e_vn,
                        'adv_h': h_vn,
                        'adv_dx': f_pos_e_cm,
                        'adv_dy': f_pos_n_cm,
                        'adv_dh': f_pos_u_cm,
                        'adv_vdx': float(v_e_mm_s * 60.0),
                        'adv_vdy': float(v_n_mm_s * 60.0),
                        'adv_vdh': float(v_u_mm_s * 60.0)
                    }
                },
                'adv_x': n_vn,
                'adv_y': e_vn,
                'adv_h': h_vn,
                'adv_dx': f_pos_e_cm,
                'adv_dy': f_pos_n_cm,
                'adv_dh': f_pos_u_cm,
                'adv_vdx': float(v_e_mm_s * 60.0),
                'adv_vdy': float(v_n_mm_s * 60.0),
                'adv_vdh': float(v_u_mm_s * 60.0),
            })

        return {
            'type': 'gnss_processed',
            'timestamp': int(received_ts),
            'is_trusted_fix': is_trusted_fix,  # Only True for RTK FIXED (4)
            'data': result_data
        }

    def _parse_gngga(self, gngga_string):
        try:
            parts = gngga_string.split(',')
            if len(parts) < 10: return None
                
            lat_str, lon_str = parts[2], parts[4]
            lat_dir, lon_dir = parts[3].upper() if parts[3] else '', parts[5].upper() if parts[5] else ''
            
            if not lat_str or not lon_str: return None
            if lat_dir not in ('N', 'S') or lon_dir not in ('E', 'W'): return None

            # Persisted origins and ECEF use ellipsoidal height.
            if len(parts) <= 9 or not parts[9]:
                return None
            try:
                altitude_msl = float(parts[9])
            except (ValueError, TypeError):
                return None

            # Check geoid separation (field 11): if missing or empty, reject to prevent 30m+ false jump
            if len(parts) <= 11 or not parts[11]:
                return None
            try:
                geoid_sep = float(parts[11])
            except (ValueError, TypeError):
                return None

            h = altitude_msl + geoid_sep
            
            try:
                lat_deg = int(lat_str[:2])
                lat_min = float(lat_str[2:])
                lon_deg = int(lon_str[:3])
                lon_min = float(lon_str[3:])
            except (ValueError, IndexError):
                return None

            if not (0.0 <= lat_min < 60.0 and 0.0 <= lon_min < 60.0):
                return None

            lat = float(lat_deg) + lat_min / 60.0
            if lat_dir == 'S': lat = -lat
            
            lon = float(lon_deg) + lon_min / 60.0
            if lon_dir == 'W': lon = -lon

            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                return None
                
            received_ts = time.time()
            gga_timestamp = self._gga_epoch_seconds(parts[1], received_ts) if parts[1] else None
            return {
                'wgs': {'lat': lat, 'lon': lon, 'h': h},
                'gga_utc': parts[1] if parts[1] else None,
                'gga_timestamp': gga_timestamp,
                'received_timestamp': received_ts,
                'fix_quality': int(parts[6]) if parts[6] else 0, 
                'num_sats': int(parts[7]) if parts[7] else 0, 
                'hdop': float(parts[8]) if parts[8] else 99.9
            }
        except (ValueError, IndexError):
            return None

    def _gngga_to_ecef(self, lat, lon, h):
        lat_rad, lon_rad = math.radians(lat), math.radians(lon)
        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        
        N = A_WGS84 / math.sqrt(1 - E2_WGS84 * sin_lat**2)
        X = (N + h) * cos_lat * math.cos(lon_rad)
        Y = (N + h) * cos_lat * math.sin(lon_rad)
        Z = (N * (1 - E2_WGS84) + h) * sin_lat
        return np.array([X, Y, Z])

    def _get_rotation_matrix(self, lat0, lon0):
        lat0_rad, lon0_rad = math.radians(lat0), math.radians(lon0)
        sl0, cl0 = math.sin(lon0_rad), math.cos(lon0_rad)
        sf0, cf0 = math.sin(lat0_rad), math.cos(lat0_rad)
        return np.array([
            [-sl0, cl0, 0],
            [-sf0 * cl0, -sf0 * sl0, cf0],
            [cf0 * cl0, cf0 * sl0, sf0]
        ])

    def get_stats(self):
        return self.stats.copy()
