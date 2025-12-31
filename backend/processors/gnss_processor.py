# backend/processors/gnss_processor.py
import numpy as np
import math
import logging
import time
from collections import deque
from typing import Optional, Dict, Any

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
    def __init__(
        self, 
        device_id: int,
        db_session_factory, 
        required_points=5, 
        max_spread_m=5.0, 
        filter_window_size=5, 
        min_fix_quality=4
    ):
        self.device_id = device_id
        self.db_session_factory = db_session_factory
        
        # Cấu hình
        self.required_points = required_points
        self.max_spread_m = max_spread_m
        self.min_fix_quality = min_fix_quality
        self.filter_window_size = filter_window_size
        
        # State
        self.state = "AWAITING_CANDIDATES" 
        self.origin = None
        self.origin_candidates = []
        
        # Bộ nhớ đệm
        self.history = deque(maxlen=filter_window_size + 1)
        
        # Thống kê
        self.stats = {
            'total_processed': 0,
            'low_quality_rejected': 0,
            'origin_resets': 0
        }
        
        self._schedule_load_origin()
        
        logger.info(f"GNSS Processor init for device {device_id}: State={self.state}")

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

    def process_gngga(self, raw_payload: str) -> Optional[Dict[str, Any]]:
        try:
            parts = raw_payload.split(',')
            if len(parts) < 10 or not parts[2] or not parts[4]:
                return None

            fix_quality = int(parts[6]) if parts[6] else 0
            
            if self.state == "AWAITING_CANDIDATES":
                return self._handle_origin_collection(raw_payload, fix_quality)
            elif self.state == "ORIGIN_LOCKED":
                return self._handle_processing(raw_payload, fix_quality)
            
            return None

        except Exception as e:
            logger.error(f"Error processing GNGGA: {e}")
            return None

    def _handle_origin_collection(self, gngga_string, fix_quality):
        if fix_quality < self.min_fix_quality:
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "origin_status",
                "status": "WAITING_FOR_QUALITY",
                "message": f"Low quality fix ({fix_quality} < {self.min_fix_quality})"
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

    def _handle_processing(self, gngga_string, fix_quality):
        if fix_quality < self.min_fix_quality:
            self.stats['low_quality_rejected'] += 1
            return None

        point = self._parse_gngga(gngga_string)
        if not point: return None

        ts = time.time()
        ecef_coords = self._gngga_to_ecef(
            point['wgs']['lat'], 
            point['wgs']['lon'], 
            point['wgs']['h']
        )
        
        self.history.append({
            'ts': ts, 
            'ecef': ecef_coords, 
            'wgs': point['wgs']
        })

        if len(self.history) < 2: return None

        p_new = self.history[-1]
        p_old = self.history[-2]
        dt = p_new['ts'] - p_old['ts']
        
        if dt < 0.01: return None
            
        v_ecef_raw = (p_new['ecef'] - p_old['ecef']) / dt
        v_enu_raw = self.origin['R'] @ v_ecef_raw

        if len(self.history) >= self.filter_window_size:
            velocities_enu = []
            for i in range(1, len(self.history)):
                p1 = self.history[i]
                p0 = self.history[i-1]
                idt = p1['ts'] - p0['ts']
                if idt >= 0.01:
                    iv_ecef = (p1['ecef'] - p0['ecef']) / idt
                    velocities_enu.append(self.origin['R'] @ iv_ecef)
            
            v_enu_filtered = np.mean(velocities_enu, axis=0) if velocities_enu else v_enu_raw
        else:
            v_enu_filtered = v_enu_raw

        pos_enu = self.origin['R'] @ (ecef_coords - self.origin['ecef'])
        total_displacement_m = float(np.sqrt(pos_enu[0]**2 + pos_enu[1]**2 + pos_enu[2]**2))
        
        self.stats['total_processed'] += 1
        
        return {
            'type': 'gnss_processed',
            'timestamp': int(ts),
            'data': {
                'lat': point['wgs']['lat'], 
                'lon': point['wgs']['lon'], 
                'h': point['wgs']['h'],
                'pos_e': float(pos_enu[0]), 
                'pos_n': float(pos_enu[1]), 
                'pos_u': float(pos_enu[2]),
                'total_displacement_mm': total_displacement_m * 1000,
                'vel_e': float(v_enu_filtered[0]), 
                'vel_n': float(v_enu_filtered[1]), 
                'vel_u': float(v_enu_filtered[2]),
                'speed_2d': float(np.sqrt(v_enu_filtered[0]**2 + v_enu_filtered[1]**2)),
                'speed_2d_mm_s': float(np.sqrt(v_enu_filtered[0]**2 + v_enu_filtered[1]**2) * 1000),
                'fix_quality': point['fix_quality'], 
                'num_sats': point['num_sats'], 
                'hdop': point['hdop']
            }
        }

    def _parse_gngga(self, gngga_string):
        try:
            parts = gngga_string.split(',')
            if len(parts) < 10: return None
                
            lat_str, lon_str = parts[2], parts[4]
            lat_dir, lon_dir = parts[3], parts[5]
            
            if not lat_str or not lon_str: return None

            h = float(parts[9]) if parts[9] else 0.0
            
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