"""DisplacementAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class DisplacementAnalysisMixin:
    def _check_preliminary_gnss_status(self, latest: dict) -> dict | None:
        latest_status = str(latest.get("status") or "").upper()
        quarantine_statuses = {
            "INITIALIZING", "VELOCITY_WARMUP", "UNVERIFIED_POSITION_SHIFT",
            "PERSISTENT_OFFSET_QUARANTINED", "REJECTED_MEASUREMENT", "UNSTABLE_FIX",
            "REFERENCE_CHANGE_PENDING", "STALE_REFERENCE", "REACQUIRE_REFUSED",
            "INVALID_DATA", "UNTRUSTED_GEOMETRY", "CHECKSUM_FAILED", "NO_DATA",
        }
        if latest_status in quarantine_statuses:
            return {"level": "PENDING", "category": "gnss_velocity", "signal_state": "UNKNOWN", "processor_status": latest_status}
        if latest.get("velocity_reliable") is False:
            return {"level": "PENDING", "category": "gnss_velocity"}
        if "velocity_confirmed" in latest:
            if latest.get("velocity_confirmed") is not True:
                return {"level": "PENDING", "category": "gnss_velocity"}
        elif latest.get("velocity_significant") is False:
            return {"level": "PENDING", "category": "gnss_velocity"}
        return None

    def _determine_motion_suppressed(self, motion_points: list, station_id: int) -> bool:
        if len(motion_points) < 4:
            return False
        step_lengths = []
        for i in range(1, len(motion_points)):
            dx = motion_points[i]["e"] - motion_points[i - 1]["e"]
            dy = motion_points[i]["n"] - motion_points[i - 1]["n"]
            du = motion_points[i].get("u", 0.0) - motion_points[i - 1].get("u", 0.0)
            step_lengths.append(math.sqrt(dx * dx + dy * dy + du * du))
        if len(step_lengths) < 3:
            return False

        first, last = motion_points[0], motion_points[-1]
        de, dn = last["e"] - first["e"], last["n"] - first["n"]
        du = last.get("u", 0.0) - first.get("u", 0.0)
        net_m = math.sqrt(de * de + dn * dn + du * du)
        path_m = float(sum(step_lengths))

        step_arr = np.array(step_lengths, dtype=float)
        median_step = float(np.median(step_arr))
        mad_step = float(np.median(np.abs(step_arr - median_step)))
        noise_envelope_m = max(median_step + 1.4826 * mad_step, 1e-6)
        motion_significance = net_m / noise_envelope_m
        directionality = net_m / max(path_m, 1e-9)

        if motion_significance < max(3.0, math.sqrt(len(step_lengths))) and directionality < 0.5:
            logger.debug(f"[GNSS-{station_id}] Jitter-suppressed: net3D={net_m*1000.0:.2f}mm, path3D={path_m*1000.0:.2f}mm")
            return True
        return False

    def _apply_anti_jitter(self, history: deque, counter_info: dict, current_level: str, station_id: int) -> str:
        if current_level not in ["WARNING", "CRITICAL"] or len(history) < 4:
            return current_level
        motion_points = list(history)
        if counter_info.get("first_detected", 0.0) > 0:
            recent_motion = [p for p in history if p["ts"] >= counter_info["first_detected"]]
            if len(recent_motion) >= 4:
                motion_points = recent_motion
        if self._determine_motion_suppressed(motion_points, station_id):
            return "INFO"
        return current_level

    def _check_already_latched(self, counter_info: dict, current_level: str) -> bool:
        latched_level = str(counter_info.get("latched_level") or "").upper()
        level_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        if latched_level in ("WARNING", "CRITICAL"):
            counter_info["safe_count"] = 0
            if level_rank.get(current_level, 0) <= level_rank.get(latched_level, 0):
                return True
        if counter_info.get("latched_level") == current_level:
            counter_info["safe_count"] = 0
            return True
        return False

    def _build_confirmed_alert(self, current_level: str, station_id: int, vel_mms: float, vel_class: str, req_steps: int, elapsed: float) -> dict:
        logger.warning(f"🚨 [GNSS-{station_id}] ✅ CONFIRMED {current_level} after {req_steps} readings over {elapsed:.1f}s!")
        msg = f"🚨 CỰC KỲ NGUY HIỂM: {vel_mms:.2f} mm/s ({vel_class})" if current_level == "CRITICAL" else f"⚠️ Tốc độ nhanh: {vel_mms:.4f} mm/s ({vel_class})"
        audio = "gnss_critical" if current_level == "CRITICAL" else "gnss_warning"
        return {
            "level": current_level, "category": "gnss_velocity", "message": msg,
            "audio_code": audio,
            "details": {"velocity_mm_s": vel_mms, "classification": vel_class, "confirmed_after": req_steps}
        }

    def _step_danger_confirmation(self, counter_info: dict, current_level: str, crit_steps: int, warn_steps: int, min_seconds: float, vel_mms: float, vel_class: str, station_id: int, now: float) -> dict | None:
        if self._check_already_latched(counter_info, current_level):
            return {"level": "PENDING", "category": "gnss_velocity"}

        req_steps = crit_steps if current_level == "CRITICAL" else warn_steps
        if counter_info.get("last_level") != current_level:
            counter_info["count"] = 1
            counter_info["safe_count"] = 0
            counter_info["last_level"] = current_level
            counter_info["first_detected"] = now
            return None

        counter_info["count"] = min(counter_info["count"] + 1, req_steps)
        elapsed = now - counter_info["first_detected"]
        if counter_info["count"] == req_steps:
            if elapsed < min_seconds:
                counter_info["count"] = req_steps - 1
                return None
            counter_info["latched_level"] = current_level
            counter_info["latched_time"] = now
            return self._build_confirmed_alert(current_level, station_id, vel_mms, vel_class, req_steps, elapsed)
        return None

    def _step_safe_deassertion(self, counter_info: dict, safe_steps: int, station_id: int, now: float) -> dict | None:
        if counter_info.get("latched_level") is not None:
            if now - counter_info.get("latched_time", 0.0) > 900:
                logger.info(f"[GNSS-{station_id}] Latch timeout (>15m) — resetting to INFO")
                counter_info["latched_level"] = None
                counter_info["safe_count"] = 0
                return None
            counter_info["safe_count"] = counter_info.get("safe_count", 0) + 1
            if counter_info["safe_count"] >= safe_steps:
                logger.info(f"✅ [GNSS-{station_id}] Safe confirmed ({counter_info['safe_count']}/{safe_steps}) — resolving alert")
                counter_info["latched_level"] = None
                counter_info["safe_count"] = 0
                counter_info["count"] = 0
                counter_info["last_level"] = None
                return None
            return {"level": "PENDING", "category": "gnss_velocity"}

        counter_info["count"] = max(0, counter_info.get("count", 0) - 1)
        if counter_info["count"] == 0:
            counter_info["last_level"] = None
        return None

    def _level_from_velocity_class(self, vel_class: str) -> str:
        cls_up = vel_class.upper()
        for kw in ("EXTREMELY RAPID", "VERY RAPID", "RAPID"):
            if kw in cls_up:
                return "CRITICAL"
        if "MODERATE" in cls_up:
            return "WARNING"
        return "INFO"

    def _append_gnss_history(self, history: deque, latest: dict, recent_data: list):
        sample_ts = float(recent_data[-1].get("timestamp", 0.0) or 0.0)
        pos_e, pos_n = latest.get("pos_e"), latest.get("pos_n")
        if pos_e is not None and pos_n is not None and sample_ts > 0:
            history.append({"ts": sample_ts, "e": float(pos_e), "n": float(pos_n), "u": float(latest.get("pos_u", 0.0) or 0.0)})

    def analyze_gnss_displacement(
        self,
        station_id: int,
        recent_data: List[Dict[str, Any]],
        config: Dict
    ) -> Optional[Dict]:
        if not recent_data: return None
        try:
            gnss_cfg = config.get("GnssAlerting", {}) if isinstance(config, dict) else {}
            if not self._as_bool(gnss_cfg.get("enabled", True), default=True):
                return None

            latest = recent_data[-1]["data"]
            preliminary = self._check_preliminary_gnss_status(latest)
            if preliminary is not None:
                return preliminary

            velocity_ms = latest.get("speed_2d", 0.0)
            velocity_mms = velocity_ms * 1000.0
            warn_steps = int(gnss_cfg.get("gnss_warning_confirm_steps", gnss_cfg.get("gnss_confirm_steps", 3)))
            crit_steps = int(gnss_cfg.get("gnss_critical_confirm_steps", gnss_cfg.get("gnss_confirm_steps", 2)))
            min_seconds = float(gnss_cfg.get("gnss_confirm_min_seconds", 3.0))
            safe_steps = int(gnss_cfg.get("gnss_safe_confirm_steps", 5))

            vel_class = self._classify_velocity_extended(
                velocity_mms, velocity_mms * 86400, velocity_mms * 31536000, config, station_id=station_id
            )
            current_level = self._level_from_velocity_class(vel_class)

            counter_info = self.alert_counters[station_id]["gnss"]
            counter_info.setdefault("latched_level", None)
            counter_info.setdefault("safe_count", 0)

            history = self.gnss_recent_history[station_id]
            self._append_gnss_history(history, latest, recent_data)

            current_level = self._apply_anti_jitter(history, counter_info, current_level, station_id)
            now = time.time()
            if current_level in ["WARNING", "CRITICAL"]:
                return self._step_danger_confirmation(
                    counter_info, current_level, crit_steps, warn_steps, min_seconds, velocity_mms, vel_class, station_id, now
                )
            return self._step_safe_deassertion(counter_info, safe_steps, station_id, now)
        except Exception as e:
            logger.exception(f"Error analyzing GNSS displacement for station {station_id}: {e}")
            return None
