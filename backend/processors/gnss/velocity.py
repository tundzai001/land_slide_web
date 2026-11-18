"""GNSSVelocityMixin for the GNSS velocity processor."""

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


class GNSSVelocityMixin:
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

    @staticmethod
    def _parse_velocity_confirmation_config(config: dict) -> tuple[int, float, float, float, float]:
        try:
            required_samples = max(int(config.get('velocity_confirmation_samples', 3)), 2)
        except (TypeError, ValueError):
            required_samples = 3
        try:
            required_duration_s = max(float(config.get('velocity_confirmation_duration_s', 30.0)), 5.0)
        except (TypeError, ValueError):
            required_duration_s = 30.0
        try:
            direction_threshold = min(max(float(config.get('velocity_confirmation_direction_cosine', 0.70)), 0.0), 1.0)
        except (TypeError, ValueError):
            direction_threshold = 0.70
        try:
            minimum_gap_s = max(float(config.get('velocity_confirmation_min_gap_s', 15.0)), 1.0)
        except (TypeError, ValueError):
            minimum_gap_s = 15.0
        try:
            max_gap_s = max(float(config.get('velocity_confirmation_max_gap_s', max(required_duration_s, minimum_gap_s * 2.0))), minimum_gap_s)
        except (TypeError, ValueError):
            max_gap_s = max(required_duration_s, minimum_gap_s * 2.0)
        return required_samples, required_duration_s, direction_threshold, minimum_gap_s, max_gap_s

    @staticmethod
    def _is_valid_motion(ts: float, vector: np.ndarray, statistically_significant: bool, reliable: bool) -> bool:
        return bool(
            math.isfinite(ts)
            and vector.size == 3
            and np.all(np.isfinite(vector))
            and np.linalg.norm(vector) > 0.0
            and statistically_significant
            and reliable
        )

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
        (
            required_samples,
            required_duration_s,
            direction_threshold,
            minimum_gap_s,
            max_gap_s,
        ) = self._parse_velocity_confirmation_config(config)

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

        if not self._is_valid_motion(ts, vector, statistically_significant, reliable):
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
