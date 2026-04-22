# backend/processors/gnss_processor.py
import re
import numpy as np
import math
import logging
import time
from collections import deque
from typing import Optional, Dict, Any

from app.modules.geodetic import VN2000Converter, DatumParams

logger = logging.getLogger(__name__)

A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84**2

def haversine_3d(lat1, lon1, h1, lat2, lon2, h2):
    R = 6371000
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a_val = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
    distance_2d = R * c
    return math.sqrt(distance_2d**2 + (h2 - h1)**2)

class GNSSVelocityProcessor:
    """
    Processor ổn định: nhận GNGGA → tính ENU position → tính velocity qua cửa sổ trượt.
    Tích hợp chuyển đổi tọa độ VN2000 (NEH).
    """
    def __init__(
        self,
        device_id: int,
        db_session_factory,
        required_points=5,
        max_spread_m=5.0,
        filter_window_size=30,
        min_fix_quality=4,
        # Sanity gate: reject fix nếu thiết bị claim nhảy > X mét trong 1 sample.
        max_step_distance_m=3.0,
        # Vertical jump gate (U-axis) to reject unrealistic altitude spikes.
        max_step_vertical_m=0.6,
    ):
        self.device_id = device_id
        self.db_session_factory = db_session_factory
        self.required_points = 60  # Increased for stability (approx 1 min at 1Hz)
        self.max_spread_m = max_spread_m
        self.min_fix_quality = min_fix_quality
        self.filter_window_size = filter_window_size
        self.max_step_distance_m = float(max_step_distance_m)
        self.max_step_vertical_m = float(max_step_vertical_m)

        # State
        self.state = "AWAITING_CANDIDATES"
        self.origin = None
        self.origin_candidates = []

        # history giữ filter_window_size + 1 mẫu để tính median window
        self.history = deque(maxlen=filter_window_size + 1)
        # Output velocity state to suppress frame-to-frame jumps without forcing zero.
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        # Stable displacement state for UI/log (reduce "standing still but jumping total").
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False

        self.stats = {
            'total_processed': 0,
            'low_quality_rejected': 0,
            'origin_resets': 0,
            'spike_rejected': 0,
        }

        self._schedule_load_origin()
        logger.info(
            f"GNSS Processor init for device {device_id}: "
            f"fix_required={min_fix_quality}, window={filter_window_size}, "
            f"max_step={self.max_step_distance_m}m"
        )

    def reset_origin(self):
        """Manually reset the origin calculation."""
        self.origin = None
        self.origin_candidates = []
        self.state = "AWAITING_CANDIDATES"
        self.history = deque(maxlen=self.filter_window_size + 1)
        self.v_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.v_state_ready = False
        self.disp_enu_state = np.array([0.0, 0.0, 0.0], dtype=float)
        self.disp_state_ready = False
        self.last_process_time = 0
        logger.info(f"🔄 [GNSS] Origin reset for device {self.device_id}")

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
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                origin_record = result.scalar_one_or_none()
            
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
                    self.state = "ORIGIN_LOCKED"
                    logger.info(f"✅ [ASYNC LOAD] Loaded origin for device {self.device_id}: ({origin_record.lat}, {origin_record.lon})")
                else:
                    logger.warning(f"⚠️ Device {self.device_id}: Found origin record but matrix data is missing.")
            
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Failed to load origin from DB: {repr(e)}")

    async def _save_origin_to_db(self):
        """✅ Lưu origin vào DB"""
        try:
            from app.models.config import GNSSOrigin
            from sqlalchemy import select
            
            async with self.db_session_factory() as db:
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                existing = result.scalar_one_or_none()
                
                # Convert numpy array to list for JSON serialization
                rot_matrix = self.origin['R'].tolist() if hasattr(self.origin['R'], 'tolist') else self.origin['R']
                ecef_origin = self.origin['ecef'].tolist() if hasattr(self.origin['ecef'], 'tolist') else self.origin['ecef']

                if existing:
                    existing.lat = self.origin['lat']
                    existing.lon = self.origin['lon']
                    existing.h = self.origin['h']
                    existing.locked_at = int(time.time())
                    existing.rotation_matrix = rot_matrix
                    existing.ecef_origin = ecef_origin
                else:
                    new_origin = GNSSOrigin(
                        device_id=self.device_id,
                        lat=self.origin['lat'],
                        lon=self.origin['lon'],
                        h=self.origin['h'],
                        locked_at=int(time.time()),
                        spread_meters=0.0,
                        num_points=len(self.origin_candidates),
                        rotation_matrix=rot_matrix,
                        ecef_origin=ecef_origin
                    )
                    db.add(new_origin)
                
                await db.commit()
                logger.info(f"💾 Saved new origin for device {self.device_id} to DB")
                
        except Exception as e:
            logger.error(f"❌ Error saving origin to DB: {e}")

    def process_gngga(self, raw_payload: str, station_config: Dict = None) -> Optional[Dict[str, Any]]:
        status_type = 'origin_status' if self.state == "AWAITING_CANDIDATES" else 'gnss_status'
        try:
            # Extract câu GGA từ bất kỳ vị trí nào trong string.
            # Chịu được wrapper text (bytearray repr, prefix bytes, v.v.)
            gga_match = re.search(r'\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?', raw_payload or '')
            if not gga_match:
                return {
                    "type": status_type,
                    "status": "NO_DATA",
                    "fix_quality": None,
                    "fix_mode": "UNKNOWN",
                    "message": "No GGA sentence found in payload"
                }

            payload = gga_match.group(0).strip()
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
                return self._handle_origin_collection(payload, fix_quality)
            elif self.state == "ORIGIN_LOCKED":
                return self._handle_processing(payload, fix_quality, station_config)
            
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

    def _handle_origin_collection(self, gngga_string, fix_quality):
        # Chỉ lock origin khi RTK FIXED (fix=4)
        if fix_quality != 4:
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "origin_status",
                "status": "WAITING_FOR_QUALITY",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "message": f"Waiting RTK FIXED (fix=4), current={fix_quality} ({self._fix_mode(fix_quality)})"
            }

        point = self._parse_gngga(gngga_string)
        if not point: return None
        
        self.origin_candidates.append(point['wgs'])
        
        if len(self.origin_candidates) >= self.required_points:
            lats = [p['lat'] for p in self.origin_candidates]
            lons = [p['lon'] for p in self.origin_candidates]
            hs = [p['h'] for p in self.origin_candidates]
            
            center_lat = np.mean(lats)
            center_lon = np.mean(lons)
            center_h = np.mean(hs)
            
            max_dist = max(
                haversine_3d(center_lat, center_lon, center_h, p['lat'], p['lon'], p['h']) 
                for p in self.origin_candidates
            )

            if max_dist <= self.max_spread_m:
                self.origin = {
                    'lat': center_lat, 
                    'lon': center_lon, 
                    'h': center_h, 
                    'R': self._get_rotation_matrix(center_lat, center_lon),
                    'ecef': self._gngga_to_ecef(center_lat, center_lon, center_h)
                }
                self.state = "ORIGIN_LOCKED"
                logger.info(f"ORIGIN LOCKED (Device {self.device_id}): ({center_lat:.6f}, {center_lon:.6f}), Spread: {max_dist:.3f}m")
                
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
                self.stats['origin_resets'] += 1
                return {
                    "type": "origin_reset",
                    "message": f"Spread too high ({max_dist:.2f}m > {self.max_spread_m}m)"
                }
        
        return {
            "type": "origin_collecting",
            "count": len(self.origin_candidates),
            "target": self.required_points
        }

    def _handle_processing(self, gngga_string, fix_quality, station_config: Dict = None):
        # Chỉ tính vận tốc/displacement khi RTK FIXED (fix=4)
        if fix_quality != self.min_fix_quality:
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "gnss_status",
                "status": "UNTRUSTED_FIX",
                "fix_quality": fix_quality,
                "fix_mode": self._fix_mode(fix_quality),
                "message": f"Velocity skipped: need fix={self.min_fix_quality} (RTK FIXED), current={fix_quality}"
            }

        point = self._parse_gngga(gngga_string)
        if not point:
            return None

        ts = time.time()
        ecef_coords = self._gngga_to_ecef(
            point['wgs']['lat'],
            point['wgs']['lon'],
            point['wgs']['h']
        )
        pos_enu = self.origin['R'] @ (ecef_coords - self.origin['ecef'])
        if not np.all(np.isfinite(pos_enu)):
            logger.warning(f"Non-finite ENU position rejected (device {self.device_id})")
            return None

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
            return None

        v_enu_raw = (p_new['pos_enu'] - p_old['pos_enu']) / dt
        if not np.all(np.isfinite(v_enu_raw)):
            logger.warning(f"Non-finite raw velocity rejected (device {self.device_id})")
            self.history.pop()
            return None

        # Sanity gate: reject fix vật lý không thể xảy ra (bad RTK fix, multipath)
        # Dùng displacement (mét) chứ không phải tốc độ để độc lập với sample rate.
        step_2d_m = float(np.hypot(v_enu_raw[0], v_enu_raw[1]) * dt)
        step_u_m = float(abs(v_enu_raw[2]) * dt)
        if step_2d_m > self.max_step_distance_m or step_u_m > self.max_step_vertical_m:
            self.stats['spike_rejected'] += 1
            self.history.pop()  # pop bad fix ra khỏi window trước khi nó nhiễm median
            logger.warning(
                f"[GNSS-{self.device_id}] Bad fix rejected: step2d={step_2d_m:.3f}m (max={self.max_step_distance_m}m), "
                f"stepU={step_u_m:.3f}m (max={self.max_step_vertical_m}m), dt={dt:.3f}s | "
                f"pos_old=[{p_old['pos_enu'][0]:.3f}, {p_old['pos_enu'][1]:.3f}, {p_old['pos_enu'][2]:.3f}]m -> "
                f"pos_new=[{p_new['pos_enu'][0]:.3f}, {p_new['pos_enu'][1]:.3f}, {p_new['pos_enu'][2]:.3f}]m | "
                f"wgs=[{point['wgs']['lat']:.6f}, {point['wgs']['lon']:.6f}, {point['wgs']['h']:.3f}]"
            )
            return None

        # Stable window smoothing:
        # - đủ cửa sổ chuẩn: dùng full window
        # - giai đoạn đầu: dùng first->last của toàn bộ history để tránh giật raw velocity
        if len(self.history) >= 3:
            p_end = self.history[-1]
            p_start = self.history[0]
            dt_window = p_end['ts'] - p_start['ts']
            if dt_window > 0.1:
                v_enu_filtered = (p_end['pos_enu'] - p_start['pos_enu']) / dt_window
            else:
                v_enu_filtered = v_enu_raw
        else:
            v_enu_filtered = v_enu_raw

        if not np.all(np.isfinite(v_enu_filtered)):
            logger.warning(f"Non-finite filtered velocity rejected (device {self.device_id})")
            self.history.pop()
            return None

        # Kinematic smoother: giữ dấu và dao động nhỏ, nhưng chặn cú nhảy vận tốc phi lý.
        gnss_alert_cfg = (station_config or {}).get("GnssAlerting", {}) if isinstance(station_config, dict) else {}
        try:
            max_xy_mm_s = float(gnss_alert_cfg.get("velocity_soft_limit_xy_mm_s", 6.0))
        except Exception:
            max_xy_mm_s = 6.0
        try:
            max_z_mm_s = float(gnss_alert_cfg.get("velocity_soft_limit_z_mm_s", 15.0))
        except Exception:
            max_z_mm_s = 15.0
        try:
            accel_xy_mm_s2 = float(gnss_alert_cfg.get("velocity_accel_limit_xy_mm_s2", 1.0))
        except Exception:
            accel_xy_mm_s2 = 1.0
        try:
            accel_z_mm_s2 = float(gnss_alert_cfg.get("velocity_accel_limit_z_mm_s2", 3.0))
        except Exception:
            accel_z_mm_s2 = 3.0
        try:
            tau_seconds = float(gnss_alert_cfg.get("velocity_smoothing_tau_s", 8.0))
        except Exception:
            tau_seconds = 8.0

        hard_cap = np.array([
            max(max_xy_mm_s, 0.5) / 1000.0,
            max(max_xy_mm_s, 0.5) / 1000.0,
            max(max_z_mm_s, 1.0) / 1000.0,
        ], dtype=float)
        v_target = np.clip(np.array(v_enu_filtered, dtype=float, copy=True), -hard_cap, hard_cap)

        if not self.v_state_ready:
            self.v_enu_state = v_target
            self.v_state_ready = True
        else:
            max_dv = np.array([
                max(accel_xy_mm_s2, 0.1) / 1000.0 * dt,
                max(accel_xy_mm_s2, 0.1) / 1000.0 * dt,
                max(accel_z_mm_s2, 0.2) / 1000.0 * dt,
            ], dtype=float)
            dv = np.clip(v_target - self.v_enu_state, -max_dv, max_dv)
            v_rate_limited = self.v_enu_state + dv

            alpha = dt / (max(tau_seconds, 0.1) + dt)
            self.v_enu_state = (1.0 - alpha) * self.v_enu_state + alpha * v_rate_limited

        v_enu_stable = self.v_enu_state.copy()

        # Parse VN2000 parameters from config if present.
        # Accept both keys for backward compatibility:
        # - vn2000 (new)
        # - vn2000_params (legacy from older admin UI payload)
        custom_datum = DatumParams()
        vn_cfg = (station_config or {}).get("vn2000") or (station_config or {}).get("vn2000_params") or {}
        if vn_cfg and vn_cfg.get("enabled"):
            try:
                custom_datum = DatumParams(
                    dx=float(vn_cfg.get("dx", 191.90441429)),
                    dy=float(vn_cfg.get("dy", 39.30318279)),
                    dz=float(vn_cfg.get("dz", 111.45032835)),
                    rx=float(vn_cfg.get("rx", 0.00928836)),
                    ry=float(vn_cfg.get("ry", -0.01975479)),
                    rz=float(vn_cfg.get("rz", 0.00427372)),
                    k=float(vn_cfg.get("k", 0.999999747093722)),
                    l0_deg=float(vn_cfg.get("l0_deg", 105.0)),
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
        n_vn, e_vn, h_vn = VN2000Converter.wgs84_to_vn2000(
            point['wgs']['lat'], point['wgs']['lon'], point['wgs']['h'],
            custom_params=custom_datum
        )

        speed_2d = float(np.hypot(v_enu_stable[0], v_enu_stable[1]))
        # 4.3 Robust displacement:
        # Use median(center) of the recent ENU window to suppress outliers, then apply
        # a small EMA so "total displacement" does not jump while the station is still.
        recent_history = list(self.history)[-30:] if len(self.history) >= 2 else list(self.history)
        if recent_history:
            enu_arr = np.array([p['pos_enu'] for p in recent_history], dtype=float)
            med_enu = np.median(enu_arr, axis=0)

            try:
                disp_tau = float(gnss_alert_cfg.get("displacement_smoothing_tau_s", 12.0))
            except Exception:
                disp_tau = 12.0

            if not self.disp_state_ready:
                self.disp_enu_state = med_enu
                self.disp_state_ready = True
            else:
                alpha_disp = dt / (max(disp_tau, 0.1) + dt)
                self.disp_enu_state = (1.0 - alpha_disp) * self.disp_enu_state + alpha_disp * med_enu

            total_displacement_m = float(np.linalg.norm(self.disp_enu_state))
        else:
            total_displacement_m = float(np.linalg.norm(pos_enu))

        # ── Unit conversions ──────────────────────────────────────────
        # ALL displacement outputs unified to CM (centimeters).
        # pos_e/n/u  = adv_dx/dy/dh = ENU displacement from origin (cm)
        # adv_vdx/vdy/vdh → mm/phút (velocity, m/s × 60000)
        # total_displacement_mm → mm
        # speed_2d_mm_s → mm/s
        pos_e_cm = float(pos_enu[0] * 100.0)
        pos_n_cm = float(pos_enu[1] * 100.0)
        pos_u_cm = float(pos_enu[2] * 100.0)

        total_displacement_mm = total_displacement_m * 1000.0

        self.stats['total_processed'] += 1

        return {
            'type': 'gnss_processed',
            'timestamp': int(ts),
            'data': {
                'lat': point['wgs']['lat'],
                'lon': point['wgs']['lon'],
                'h': point['wgs']['h'],
                # ENU displacement from origin (cm)
                'pos_e': pos_e_cm,
                'pos_n': pos_n_cm,
                'pos_u': pos_u_cm,
                'total_displacement_mm': total_displacement_mm,
                'vel_e': float(v_enu_stable[0]),
                'vel_n': float(v_enu_stable[1]),
                'vel_u': float(v_enu_stable[2]),
                'speed_2d': speed_2d,
                'speed_2d_mm_s': float(speed_2d * 1000),
                'fix_quality': point['fix_quality'],
                'fix_mode': self._fix_mode(point['fix_quality']),
                'num_sats': point['num_sats'],
                'hdop': point['hdop'],
                # VN2000 absolute position (m)
                'vn2000_n': n_vn,
                'vn2000_e': e_vn,
                'vn2000_h': h_vn,
                # Forwarding payload for external MQTT (all displacement in cm)
                'forwarding_data': {
                    'type': 'gnss_processed',
                    'timestamp': int(ts),
                    'data': {
                        'lat': n_vn,
                        'lon': e_vn,
                        'h': h_vn,
                        'pos_e': pos_e_cm,
                        'pos_n': pos_n_cm,
                        'pos_u': pos_u_cm,
                        'total_displacement_mm': total_displacement_mm,
                        'speed_2d_mm_s': float(speed_2d * 1000),
                        'fix_quality': point['fix_quality'],
                        'fix_mode': self._fix_mode(point['fix_quality']),
                        'num_sats': point['num_sats'],
                        'hdop': point['hdop'],
                        'adv_x': n_vn,
                        'adv_y': e_vn,
                        'adv_h': h_vn,
                        'adv_dx': pos_e_cm,
                        'adv_dy': pos_n_cm,
                        'adv_dh': pos_u_cm,
                        'adv_vdx': float(v_enu_stable[0] * 60000),
                        'adv_vdy': float(v_enu_stable[1] * 60000),
                        'adv_vdh': float(v_enu_stable[2] * 60000)
                    }
                },
                # UI keys – adv_x/y/h = VN2000 (m), adv_dx/dy/dh = ENU displacement (cm)
                'adv_x': n_vn,
                'adv_y': e_vn,
                'adv_h': h_vn,
                'adv_dx': pos_e_cm,
                'adv_dy': pos_n_cm,
                'adv_dh': pos_u_cm,
                'adv_vdx': float(v_enu_stable[0] * 60000),
                'adv_vdy': float(v_enu_stable[1] * 60000),
                'adv_vdh': float(v_enu_stable[2] * 60000),
            }
        }

    def _parse_gngga(self, gngga_string):
        try:
            parts = gngga_string.split(',')
            if len(parts) < 10: return None
                
            lat_str, lon_str = parts[2], parts[4]
            lat_dir, lon_dir = parts[3], parts[5]
            
            if not lat_str or not lon_str: return None

            # NMEA GGA field 9 is orthometric height (MSL), not ellipsoidal height.
            # VN2000 conversion expects ellipsoidal h, so use: h = altitude_msl + geoid_separation.
            altitude_msl = float(parts[9]) if parts[9] else 0.0
            geoid_sep = float(parts[11]) if len(parts) > 11 and parts[11] else 0.0
            h = altitude_msl + geoid_sep
            
            lat = float(lat_str[:2]) + float(lat_str[2:]) / 60.0
            if lat_dir == 'S': lat = -lat
            
            lon = float(lon_str[:3]) + float(lon_str[3:]) / 60.0
            if lon_dir == 'W': lon = -lon
                
            return {
                'wgs': {'lat': lat, 'lon': lon, 'h': h},
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
