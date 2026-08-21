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

        # State
        self.state = "AWAITING_CANDIDATES"
        self.origin = None
        self.origin_candidates = []

        # history giữ filter_window_size + 1 mẫu để tính median window
        # Retain enough accepted FIXED samples for time-based windows. The old
        # 31-sample deque made the displacement median cycle too quickly.
        self.history = deque(maxlen=max(filter_window_size + 1, 1200))
        self.reacquire_candidates = deque(maxlen=10)
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        # Stable displacement state for UI/log (reduce "standing still but jumping total").
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False
        self.peak_displacement_mm = 0.0
        self.tracking_offset_enu = np.zeros(3, dtype=float)
        self._last_reacquire_ts = 0.0

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
            try:
                import asyncio
                asyncio.get_running_loop().create_task(self._async_save_tracking_offset())
            except RuntimeError:
                pass
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
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False
        self.peak_displacement_mm = 0.0
        self.tracking_offset_enu = np.zeros(3, dtype=float)
        self._last_reacquire_ts = 0.0
        self._last_handled_reference_event_ts = None
        self._reference_transition = None
        self._last_origin_candidate_ts = None
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

    def _schedule_load_origin(self):
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._async_load_origin_task())
            except RuntimeError:
                logger.warning(f"⚠️ Device {self.device_id}: Init outside event loop, origin will be collected manually.")
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Error scheduling DB load: {e}")

    async def _async_load_origin_task(self):
        try:
            from app.models.config import GNSSOrigin
            from sqlalchemy import select
            
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
                            GNSSOrigin.rotation_matrix, GNSSOrigin.ecef_origin
                        ).where(GNSSOrigin.device_id == self.device_id)
                    )
                    row = result.first()
                    if row:
                        origin_record = type('SimpleOrigin', (), {
                            'lat': row[0], 'lon': row[1], 'h': row[2],
                            'rotation_matrix': row[3], 'ecef_origin': row[4],
                            'tracking_offset': None
                        })()
                    else:
                        origin_record = None
            
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
                    if getattr(origin_record, 'tracking_offset', None):
                        try:
                            self.tracking_offset_enu = self._validated_tracking_offset(origin_record.tracking_offset)
                            logger.info(f"✅ [ASYNC LOAD] Loaded tracking offset for device {self.device_id}: {self.tracking_offset_enu}")
                        except Exception as ex:
                            logger.warning(f"⚠️ Device {self.device_id}: Ignored unsafe tracking offset: {ex}")
                    self.state = "ORIGIN_LOCKED"
                    logger.info(f"✅ [ASYNC LOAD] Loaded origin for device {self.device_id}: ({origin_record.lat}, {origin_record.lon})")
                else:
                    logger.warning(f"⚠️ Device {self.device_id}: Found origin record but matrix data is missing.")
            
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Failed to load origin from DB: {repr(e)}")

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
                    new_origin = GNSSOrigin(
                        device_id=self.device_id,
                        lat=self.origin['lat'],
                        lon=self.origin['lon'],
                        h=self.origin['h'],
                        locked_at=int(time.time()),
                        spread_meters=0.0,
                        num_points=len(self.origin_candidates),
                        rotation_matrix=rot_matrix,
                        ecef_origin=ecef_origin,
                        tracking_offset=tracking_offset_list
                    )
                    db.add(new_origin)
                
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
        minimum_samples: int = 60,
        minimum_duration_s: float = 60.0,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
    ):
        """Collect a fresh stable FIXED window and re-zero displacement."""
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
        deadline = asyncio.get_running_loop().time() + timeout_s
        self._offset_calibration_in_progress = True
        last_progress_second = -1
        try:
            while True:
                samples = [
                    sample
                    for sample in self.history
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
        self.peak_displacement_mm = float(np.linalg.norm(self.disp_enu_state[:2]) * 1000.0)
        self._reference_transition = None
        self._consecutive_rejects = 0
        self.reacquire_candidates.clear()

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

        reference_result = self._handle_reference_transition(
            ts, pos_enu, fix_quality, station_config, raw_payload or gngga_string,
        )
        if reference_result is not None:
            return reference_result

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
            if not self.reacquire_candidates:
                self._shift_started_at = ts
            self._consecutive_rejects += 1
            self.stats['spike_rejected'] += 1
            self.history.pop()
            self.reacquire_candidates.append({
                'ts': ts,
                'pos_enu': pos_enu,
                'fix_quality': fix_quality,
            })

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
                    logger.info(
                        f"[{self._log_prefix()}] Tracking reacquired after verified reference shift (duration={persistent_shift_duration_s:.1f}s): "
                        f"offset2d={candidate_offset_2d_m:.3f}m, offsetU={candidate_offset_u_m:.3f}m. "
                        "Locked origin and last accepted displacement preserved."
                    )
                    try:
                        import asyncio
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._async_save_tracking_offset())
                    except RuntimeError:
                        pass

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
        self._consecutive_rejects = 0
        self._shift_started_at = None
        self.reacquire_candidates.clear()

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
        velocity_noise_threshold_mm_s = max(
            velocity_estimate['confidence_95_mm_s'],
            0.15  # 0.15 mm/s baseline sensor noise floor for RTK FIXED
        )
        velocity_significant = bool(
            estimated_speed_3d_mm_s > velocity_noise_threshold_mm_s
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

        displacement_updated = False
        horizontal_speed_mm_s = speed_2d * 1000.0
        motion_confirmed = horizontal_speed_mm_s > displacement_stationary_speed_mm_s
        if not self.disp_state_ready:
            # Publish the real displacement from the locked origin after the
            # first stable window; stationary gating only controls later drift.
            self.disp_enu_state = displacement_candidate.copy()
            self.disp_state_ready = True
            displacement_updated = True
        else:
            # Advance published displacement only after motion clears the
            # stationary-speed gate and moves beyond the measured noise floor.
            candidate_step_mm = float(
                np.linalg.norm(displacement_candidate - self.disp_enu_state) * 1000.0
            )
            if motion_confirmed and candidate_step_mm > displacement_noise_floor_mm:
                alpha = 0.15
                self.disp_enu_state = (
                    (1.0 - alpha) * self.disp_enu_state
                    + alpha * displacement_candidate
                )
                displacement_updated = True

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
            'velocity_reliable': velocity_reliable,
            'velocity_significant': velocity_significant,
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
