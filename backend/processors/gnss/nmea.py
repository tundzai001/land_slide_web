"""GNSSNmeaMixin for the GNSS velocity processor."""

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


class GNSSNmeaMixin:
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
