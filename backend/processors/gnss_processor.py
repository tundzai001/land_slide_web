import numpy as np
import math
import logging
import time
from collections import deque
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# --- Hằng số WGS-84 ---
A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84**2

def haversine_3d(lat1, lon1, h1, lat2, lon2, h2):
    """Tính khoảng cách 3D giữa 2 điểm WGS84"""
    R = 6371000
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a_val = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a_val), math.sqrt(1 - a_val))
    distance_2d = R * c
    return math.sqrt(distance_2d**2 + (h2 - h1)**2)

class GNSSVelocityProcessor:
    def __init__(self, required_points=5, max_spread_m=5.0, filter_window_size=5, min_fix_quality=4):
        self.state = "AWAITING_CANDIDATES"  # AWAITING_CANDIDATES | ORIGIN_LOCKED
        self.origin = None
        self.origin_candidates = []
        
        # Cấu hình
        self.required_points = required_points
        self.max_spread_m = max_spread_m
        self.min_fix_quality = min_fix_quality
        self.filter_window_size = filter_window_size
        
        # Bộ nhớ đệm
        self.history = deque(maxlen=filter_window_size + 1)
        
        # Thống kê
        self.stats = {
            'total_processed': 0,
            'low_quality_rejected': 0,
            'origin_resets': 0
        }
        
        logger.info(f"GNSS Processor init: Waiting for {self.required_points} points (Fix>={self.min_fix_quality})")

    def process_gngga(self, raw_payload: str) -> Optional[Dict[str, Any]]:
        """
        Điểm vào chính: Nhận chuỗi GNGGA -> Trả về Dict dữ liệu đã xử lý
        """
        try:
            parts = raw_payload.split(',')
            if len(parts) < 10 or not parts[2] or not parts[4]:
                return None

            # Parse Fix Quality
            fix_quality = int(parts[6]) if parts[6] else 0
            
            # Máy trạng thái
            if self.state == "AWAITING_CANDIDATES":
                return self._handle_origin_collection(raw_payload, fix_quality)
            elif self.state == "ORIGIN_LOCKED":
                return self._handle_processing(raw_payload, fix_quality)
            
            return None

        except Exception as e:
            logger.error(f"Error processing GNGGA: {e}")
            return None

    def get_stats(self):
        return self.stats.copy()

    # ================= INTERNAL METHODS =================

    def _parse_gngga(self, gngga_string):
        """Phân tích chuỗi GNGGA thành dictionary"""
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

    def _handle_origin_collection(self, gngga_string, fix_quality):
        """Logic thu thập điểm để khóa gốc (Origin)"""
        # 1. Kiểm tra chất lượng tín hiệu
        if fix_quality < self.min_fix_quality:
            self.stats['low_quality_rejected'] += 1
            return {
                "type": "origin_status",
                "status": "WAITING_FOR_QUALITY",
                "message": f"Low quality fix ({fix_quality} < {self.min_fix_quality})"
            }

        point = self._parse_gngga(gngga_string)
        if not point: return None
        
        # 2. Thêm vào danh sách ứng viên
        self.origin_candidates.append(point['wgs'])
        
        # 3. Nếu đủ điểm, tính toán độ phân tán
        if len(self.origin_candidates) >= self.required_points:
            lats = [p['lat'] for p in self.origin_candidates]
            lons = [p['lon'] for p in self.origin_candidates]
            hs = [p['h'] for p in self.origin_candidates]
            
            center_lat = np.mean(lats)
            center_lon = np.mean(lons)
            center_h = np.mean(hs)
            
            # Tính khoảng cách xa nhất từ tâm
            max_dist = max(
                haversine_3d(center_lat, center_lon, center_h, p['lat'], p['lon'], p['h']) 
                for p in self.origin_candidates
            )

            # 4. Quyết định Khóa hay Reset
            if max_dist <= self.max_spread_m:
                self.origin = {
                    'lat': center_lat, 
                    'lon': center_lon, 
                    'h': center_h, 
                    'R': self._get_rotation_matrix(center_lat, center_lon),
                    'ecef': self._gngga_to_ecef(center_lat, center_lon, center_h)  
                }
                self.state = "ORIGIN_LOCKED"
                logger.info(f"ORIGIN LOCKED: ({center_lat:.6f}, {center_lon:.6f}), Spread: {max_dist:.3f}m")
                
                return {
                    "type": "origin_locked",
                    "data": self.origin
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
        """Tính toán vận tốc và chuyển dịch khi đã có gốc"""
        # 1. Lọc nhiễu cơ bản
        if fix_quality < self.min_fix_quality:
            self.stats['low_quality_rejected'] += 1
            return None # Bỏ qua điểm nhiễu để tránh làm sai lệch biểu đồ

        point = self._parse_gngga(gngga_string)
        if not point: return None

        ts = time.time()
        ecef_coords = self._gngga_to_ecef(
            point['wgs']['lat'], 
            point['wgs']['lon'], 
            point['wgs']['h']
        )
        
        # 2. Lưu vào lịch sử để tính vận tốc
        self.history.append({
            'ts': ts, 
            'ecef': ecef_coords, 
            'wgs': point['wgs']
        })

        if len(self.history) < 2: return None

        # 3. Tính toán vận tốc tức thời (Raw)
        p_new = self.history[-1]
        p_old = self.history[-2]
        dt = p_new['ts'] - p_old['ts']
        
        if dt < 0.01: return None # Tránh chia cho 0 hoặc duplicate packets
            
        v_ecef_raw = (p_new['ecef'] - p_old['ecef']) / dt
        v_enu_raw = self.origin['R'] @ v_ecef_raw

        # 4. Lọc trung bình trượt (Moving Average) cho vận tốc
        if len(self.history) >= self.filter_window_size:
            velocities_enu = []
            # Duyệt qua cửa sổ lịch sử để tính vector vận tốc trung bình
            for i in range(1, len(self.history)):
                p1 = self.history[i]
                p0 = self.history[i-1]
                idt = p1['ts'] - p0['ts']
                if idt >= 0.01:  
                    iv_ecef = (p1['ecef'] - p0['ecef']) / idt
                    velocities_enu.append(self.origin['R'] @ iv_ecef)
            
            # Tính trung bình vector
            v_enu_filtered = np.mean(velocities_enu, axis=0) if velocities_enu else v_enu_raw
        else:
            v_enu_filtered = v_enu_raw

        # 5. Tính vị trí tương đối so với gốc (Displacement)
        pos_enu = self.origin['R'] @ (ecef_coords - self.origin['ecef'])
        
        self.stats['total_processed'] += 1
        
        # 6. Trả về kết quả sạch (Dict)
        return {
            'type': 'gnss_processed',
            'timestamp': int(ts),
            'data': {
                'lat': point['wgs']['lat'], 
                'lon': point['wgs']['lon'], 
                'h': point['wgs']['h'],
                
                # Vị trí tương đối (m)
                'pos_e': float(pos_enu[0]), 
                'pos_n': float(pos_enu[1]), 
                'pos_u': float(pos_enu[2]),
                
                # Vận tốc (m/s)
                'vel_e': float(v_enu_filtered[0]), 
                'vel_n': float(v_enu_filtered[1]), 
                'vel_u': float(v_enu_filtered[2]),
                'speed_2d': float(np.sqrt(v_enu_filtered[0]**2 + v_enu_filtered[1]**2)),
                
                # Metadata
                'fix_quality': point['fix_quality'], 
                'num_sats': point['num_sats'], 
                'hdop': point['hdop']
            }
        }

    # ================= MATH HELPERS =================

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