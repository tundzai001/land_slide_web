"""GNSSProcessingMixin for the GNSS velocity processor."""

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


class GNSSProcessingMixin:
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

            if getattr(self, "_origin_relock_in_progress", False):
                self._capture_origin_relock_sample(payload, fix_quality, station_config)
                return None
            
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

    def _capture_origin_relock_sample(self, gngga_string, fix_quality, station_config=None):
        samples = self._origin_relock_samples
        required_fix = getattr(self, "min_fix_quality", 4)
        if fix_quality != required_fix:
            samples.clear()
            self.stats['low_quality_rejected'] += 1
            return

        point = self._parse_gngga(gngga_string)
        if not point:
            samples.clear()
            return

        integrity_cfg = self._integrity_config(station_config)
        self._origin_relock_integrity_config = integrity_cfg
        if (
            point.get("hdop", 99.9) > integrity_cfg["process_max_hdop"]
            or point.get("num_sats", 0) < integrity_cfg["process_min_sats"]
        ):
            samples.clear()
            self.stats['low_quality_rejected'] += 1
            return

        timestamp = point.get("gga_timestamp") or point.get("received_timestamp") or time.time()
        last_timestamp = samples[-1]["ts"] if samples else None
        if last_timestamp is not None and (
            timestamp <= last_timestamp
            or timestamp - last_timestamp > integrity_cfg["origin_max_gap_s"]
        ):
            samples.clear()
        samples.append({"ts": float(timestamp), "wgs": dict(point["wgs"])})

    def _evaluate_origin_candidates(self) -> Optional[dict]:
        if len(self.origin_candidates) < self.required_points:
            return None
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

        self.origin_candidates.clear()
        self._last_origin_candidate_ts = None
        self.stats['origin_resets'] += 1
        return {
            "type": "origin_reset",
            "message": f"Spread too high (XY={max_dist_xy:.3f}m > {max_xy}m, U={max_dist_u:.3f}m > {max_u}m)"
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
        
        eval_res = self._evaluate_origin_candidates()
        if eval_res is not None:
            return eval_res
        
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

        # Dynamic step limits based on fix quality
        current_max_2d = self.max_step_distance_m if is_trusted_fix else self.max_step_distance_m * 0.5
        current_max_u = self.max_step_vertical_m if is_trusted_fix else self.max_step_vertical_m * 0.5

        is_spike = step_2d_m > current_max_2d or step_u_m > current_max_u

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
            refusal_reasons = []
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

                # A stale checkpoint may contain a temporary adjustment-frame
                # position. Recover only a continuous FIXED cluster that returns
                # to the immutable origin; do not compensate or zero its samples.
                tracking_offset = getattr(self, 'tracking_offset_enu', np.zeros(3, dtype=float))
                raw_candidates = candidate_positions + tracking_offset
                old_raw_position = p_old['pos_enu'] + tracking_offset
                candidate_times = [c['ts'] for c in self.reacquire_candidates]
                returned_to_origin = bool(
                    dt > 60.0 and persistent_offset
                    and (np.linalg.norm(old_raw_position[:2]) > 0.03 or abs(old_raw_position[2]) > 0.05)
                    and np.max(np.linalg.norm(raw_candidates[:, :2], axis=1)) <= 0.03
                    and np.max(np.abs(raw_candidates[:, 2])) <= 0.05
                    and np.max(np.diff(candidate_times)) <= integrity_cfg['origin_max_gap_s']
                )
                if returned_to_origin:
                    if getattr(self, '_locked_origin_return_started_at', None) is None:
                        self._locked_origin_return_started_at = ts
                    if ts - self._locked_origin_return_started_at >= 60.0:
                        self.history.clear()
                        self.history.extend({'ts': c['ts'], 'pos_enu': c['pos_enu'].copy()}
                                            for c in self.reacquire_candidates)
                        self.reacquire_candidates.clear()
                        self._velocity_confirmation_history.clear()
                        self.last_significant_motion_ts = 0.0
                        self.v_state_ready = False
                        self.disp_state_ready = False
                        self._consecutive_rejects = 0
                        self._shift_started_at = None
                        self._quarantine_checkpointed = False
                        self._last_reject_log_state = None
                        self._locked_origin_return_started_at = None
                        self._schedule_runtime_state_save(force=True)
                        logger.info("[%s] Monitoring reference recovered after 60s of stable FIXED samples near locked origin; origin and tracking offset unchanged", self._log_prefix())
                        return {
                            'type': 'gnss_status', 'status': 'WARMING_UP',
                            'fix_quality': fix_quality, 'fix_mode': self._fix_mode(fix_quality),
                            'raw_payload': raw_payload or gngga_string,
                            'data': {'integrity_state': 'WARMING_UP', 'position_quality_reliable': False},
                            'message': 'Stable FIXED measurements returned to locked origin; rebuilding monitoring windows',
                        }
                else:
                    self._locked_origin_return_started_at = None

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
                    and (
                        getattr(self, "_last_handled_reference_event_ts", None) is None
                        or ref_ts > self._last_handled_reference_event_ts
                    )
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
                        "data": shift_data,
                        "message": "Stable RTK FIXED tracking reacquired after verified reference shift"
                    }

                if persistent_offset and persistent_shift_duration_ok and (offset_too_large or accumulated_too_much or in_cooldown or not reacquire_allowed):
                    if not getattr(self, "_quarantine_checkpointed", False):
                        self._quarantine_checkpointed = True
                        self._schedule_runtime_state_save(force=True)
                    if offset_too_large:
                        refusal_reasons.append("shift exceeds automatic compensation limits")
                    if accumulated_too_much:
                        refusal_reasons.append("accumulated tracking offset exceeds cap")
                    if in_cooldown:
                        refusal_reasons.append("compensation cooldown active")
                    if not reacquire_allowed:
                        refusal_reasons.append("reference change not confirmed; possible ground movement")

            # Report a new state immediately, then one reminder per five minutes.
            # Receiver timestamps must not control console rate limiting.
            reject_state = "UNVERIFIED_POSITION_SHIFT" if persistent_offset else "UNSTABLE_FIX"
            log_now = time.monotonic()
            if (getattr(self, '_last_reject_log_state', None) != reject_state
                    or log_now - getattr(self, '_last_reject_log_monotonic', 0.0) >= 300.0):
                self._last_reject_log_state = reject_state
                self._last_reject_log_monotonic = log_now
                logger.warning(
                    "[%s] GNSS measurement quarantined: state=%s, rejected=%s, "
                    "step2d=%.3fm (max=%.3fm), stepU=%.3fm (max=%.3fm), "
                    "quality=%s, last_trusted_age=%.1fs. %s. Locked origin and trusted displacement preserved.",
                    self._log_prefix(), reject_state, self._consecutive_rejects,
                    step_2d_m, current_max_2d, step_u_m, current_max_u, fix_quality, dt,
                    "; ".join(refusal_reasons) or "Waiting for verified stable measurements",
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
        self._locked_origin_return_started_at = None
        self._last_reject_log_state = None
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
                    logger.exception(f"Error parsing VN2000 custom params for device {self.device_id}: {e}")

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
