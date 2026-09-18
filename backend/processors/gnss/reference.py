"""GNSSReferenceMixin for the GNSS velocity processor."""

from __future__ import annotations

from .common import (
    A_WGS84,
    E2_WGS84,
    F_WGS84,
    GNSS_RUNTIME_STATE_SAVE_INTERVAL_S,
    GNSS_RUNTIME_STATE_VERSION,
    Any,
    Dict,
    Optional,
    asyncio,
    calendar,
    deque,
    logger,
    math,
    np,
    re,
    time,
    DatumParams,
    VN2000Converter,
    normalize_vn2000_l0_value,
    parse_vn2000_central_meridian,
)


class GNSSReferenceMixin:
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
