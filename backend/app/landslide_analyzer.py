# backend/app/landslide_analyzer.py - FIXED VERSION
import logging
import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class LandslideAnalyzer:
    """
    Bộ não phân tích rủi ro.
    Nhận dữ liệu đã qua xử lý (Clean Data) và Cấu hình trạm (Station Config).
    Trả về Cảnh báo (Alert) nếu vượt ngưỡng.
    """

    def _get_cfg(self, config: Dict, section: str, key: str, default: float) -> float:
        try:
            return float(config.get(section, {}).get(key, default))
        except (ValueError, TypeError, AttributeError):
            return float(default)

    # =========================================================================
    # PHÂN TÍCH DÀI HẠN (Long-term Analysis)
    # =========================================================================
    def analyze_long_term_velocity(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        config: Dict,
        window_days: int = 30
    ) -> Dict[str, Any]:
        try:
            if not historical_data or len(historical_data) < 2:
                return {"status": "insufficient_data", "message": "Cần ít nhất 2 điểm dữ liệu."}

            sorted_data = sorted(historical_data, key=lambda x: x['timestamp'])
            first_point = sorted_data[0]
            last_point = sorted_data[-1]
            
            duration_days = (last_point['timestamp'] - first_point['timestamp']) / 86400.0
            if duration_days < 0.1:
                return {"status": "insufficient_data", "message": "Thời gian đo quá ngắn."}

            first_data = first_point['data']
            last_data = last_point['data']
            
            delta_e = last_data.get('pos_e', 0) - first_data.get('pos_e', 0)
            delta_n = last_data.get('pos_n', 0) - first_data.get('pos_n', 0)
            delta_u = last_data.get('pos_u', 0) - first_data.get('pos_u', 0)
            
            total_displacement_m = math.sqrt(delta_e**2 + delta_n**2 + delta_u**2)
            total_displacement_mm = total_displacement_m * 1000

            velocity_m_per_day = total_displacement_m / duration_days
            velocity_mm_per_day = velocity_m_per_day * 1000
            velocity_mm_per_year = velocity_mm_per_day * 365
            velocity_mm_per_second = velocity_m_per_day / 86400 * 1000

            # 1. Phân loại dựa trên Config (Quan trọng)
            classification = self._classify_velocity_extended(
                velocity_mm_per_second, 
                velocity_mm_per_day,
                velocity_mm_per_year,
                config
            )

            trend = self._detect_trend(sorted_data)

            # 2. Đánh giá rủi ro dựa trên Classification (Thay vì hardcode)
            risk_level, warning_message = self._assess_long_term_risk(
                classification,
                trend,
                velocity_mm_per_year
            )

            return {
                "status": "success",
                "analysis": {
                    "total_displacement_mm": round(total_displacement_mm, 2),
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "duration_days": round(duration_days, 1),
                    "start_date": datetime.fromtimestamp(first_point['timestamp']).isoformat(),
                    "end_date": datetime.fromtimestamp(last_point['timestamp']).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning_message
            }

        except Exception as e:
            logger.error(f"Error in long-term analysis: {e}", exc_info=True)
            return {"status": "error", "message": f"Lỗi: {str(e)}"}

    def _classify_velocity_extended(
        self,
        velocity_mm_s: float,
        velocity_mm_day: float, 
        velocity_mm_year: float,
        config: Dict
    ) -> str:
        # Lấy bảng phân loại từ config người dùng
        classification_table = config.get('velocity_classification') or config.get('GNSS_Classification', [])
        
        # Nếu config rỗng, dùng mặc định
        if not classification_table:
            classification_table = [
                {"name": "Extremely Rapid", "threshold": 5000, "unit": "mm/s"},
                {"name": "Very Rapid", "threshold": 50, "unit": "mm/s"},
                {"name": "Rapid", "threshold": 0.5, "unit": "mm/s"},
                {"name": "Moderate", "threshold": 0.05, "unit": "mm/s"}, # ~1.8m/h
                {"name": "Slow", "threshold": 0.00005, "unit": "mm/s"},  # ~13mm/tháng
                {"name": "Very Slow", "threshold": 0.0000005, "unit": "mm/s"},
                {"name": "Extremely Slow", "threshold": 0, "unit": "mm/s"}
            ]
        
        # Chuẩn hóa về mm/s để so sánh
        normalized_table = []
        for cls in classification_table:
            thresh = float(cls.get('threshold', 0))
            unit = cls.get('unit', 'mm/s')
            
            thresh_mm_s = thresh
            if unit == 'mm/year': thresh_mm_s = thresh / 31536000
            elif unit == 'mm/day': thresh_mm_s = thresh / 86400
            elif unit == 'm/s': thresh_mm_s = thresh * 1000
            
            normalized_table.append({
                "name": cls.get('name', 'Unknown'),
                "threshold_mm_s": thresh_mm_s
            })

        # Sort giảm dần
        sorted_classes = sorted(normalized_table, key=lambda x: x['threshold_mm_s'], reverse=True)
        
        # So sánh
        for cls in sorted_classes:
            if velocity_mm_s >= cls['threshold_mm_s']:
                return cls['name']
        
        return "Stable"

    def _detect_trend(self, sorted_data: List[Dict]) -> str:
        if len(sorted_data) < 5: return "stable"
        try:
            velocities = [
                point['data'].get('speed_2d', 0) 
                for point in sorted_data 
                if 'speed_2d' in point['data']
            ]
            if len(velocities) < 5: return "stable"
            
            # Tính độ dốc (slope) của vận tốc
            x = np.arange(len(velocities))
            y = np.array(velocities)
            slope = np.polyfit(x, y, 1)[0]
            
            if slope > 0.0001: return "accelerating"
            elif slope < -0.0001: return "decelerating"
            else: return "stable"
        except Exception:
            return "stable"

    def _assess_long_term_risk(self, classification: str, trend: str, vel_year: float) -> tuple:
        cls_upper = classification.upper()
        
        # Mapping Class -> Risk
        if "EXTREMELY RAPID" in cls_upper or "VERY RAPID" in cls_upper:
            return "EXTREME", f"🚨 NGUY HIỂM: Vận tốc rất cao ({classification})"
        
        elif "RAPID" in cls_upper:
            return "HIGH", f"⚠️ Cao: Vận tốc nhanh ({classification})"
        
        elif "MODERATE" in cls_upper:
            return "MEDIUM", f"⚠️ Trung bình: Đất đang trượt ({classification})"
        
        # Các mức độ thấp hơn
        elif "SLOW" in cls_upper or "STABLE" in cls_upper:
            # Nếu Slow mà đang tăng tốc -> Cảnh báo nhẹ
            if trend == "accelerating":
                return "MEDIUM", f"⚠️ Chú ý: Đang tăng tốc ({classification})"
            return "LOW", f"✅ Ổn định ({classification})"
            
        else:
            # Fallback nếu tên lạ
            return "LOW", f"Trạng thái: {classification}"

    # =========================================================================
    # 1. PHÂN TÍCH GNSS (REALTIME - CHỈ DỰA VÀO VẬN TỐC TỨC THỜI)
    # =========================================================================
    def analyze_gnss_displacement(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        """
        Phân tích dựa trên VẬN TỐC TỨC THỜI (Instantaneous Velocity)
        theo bảng phân cấp Cruden & Varnes người dùng cấu hình.
        """
        if not recent_data: return None
        
        try:
            latest = recent_data[-1]['data']
            
            # 1. Lấy vận tốc tức thời (từ GNSS Processor gửi lên)
            # Đơn vị gốc thường là m/s hoặc mm/s tùy processor, ở đây ta quy về mm/s để chuẩn hóa
            velocity_ms = latest.get('speed_2d', 0.0) 
            velocity_mms = velocity_ms * 1000.0
            
            # 2. Phân loại dựa trên bảng cấu hình Admin
            # Hàm này sẽ lấy tên class: "Extremely Slow", "Rapid", v.v...
            velocity_class = self._classify_velocity_extended(
                velocity_mms,           # mm/s
                velocity_mms * 86400,   # mm/day
                velocity_mms * 31536000,# mm/year
                config
            )
            
            # 3. Ánh xạ từ Tên Class sang Mức độ Cảnh báo (Alert Level)
            level = "INFO"
            message = f"ℹ️ Tốc độ: {velocity_mms:.4f} mm/s ({velocity_class})"
            category = "gnss_velocity"
            
            # Chuyển tên class về chữ hoa để so sánh
            cls_upper = velocity_class.upper()
            
            # --- LOGIC CẢNH BÁO DỰA TRÊN TÊN PHÂN CẤP ---
            if "EXTREMELY RAPID" in cls_upper:
                level = "CRITICAL"
                message = f"🚨 CỰC KỲ NGUY HIỂM: {velocity_mms:.2f} mm/s ({velocity_class})"
            
            elif "VERY RAPID" in cls_upper:
                level = "CRITICAL"
                message = f"🚨 NGUY HIỂM CAO: {velocity_mms:.2f} mm/s ({velocity_class})"
            
            elif "RAPID" in cls_upper:
                level = "WARNING"
                message = f"⚠️ Tốc độ nhanh: {velocity_mms:.4f} mm/s ({velocity_class})"
            
            elif "MODERATE" in cls_upper:
                level = "WARNING"
                message = f"⚠️ Tốc độ trung bình: {velocity_mms:.4f} mm/s ({velocity_class})"
            
            # Các mức độ Slow, Very Slow, Extremely Slow -> INFO (An toàn)
            else:
                level = "INFO"
                message = f"✅ Ổn định: {velocity_mms:.4f} mm/s ({velocity_class})"

            # Chỉ trả về cảnh báo nếu mức độ là WARNING hoặc CRITICAL
            if level in ["WARNING", "CRITICAL"]:
                return {
                    "level": level,
                    "category": category,
                    "message": message,
                    "details": {
                        "velocity_mm_s": velocity_mms,
                        "classification": velocity_class
                    }
                }
            
            # Nếu an toàn, trả về None (không tạo Alert mới)
            return None

        except Exception as e:
            logger.error(f"Error analyzing GNSS Velocity for station {station_id}: {e}")
            return None

    def analyze_rainfall(self, station_id: int, recent_data: List[Dict], past_72h: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            watch = self._get_cfg(config, 'RainAlerting', 'rain_intensity_watch_threshold', 10.0)
            warning = self._get_cfg(config, 'RainAlerting', 'rain_intensity_warning_threshold', 25.0)
            critical = self._get_cfg(config, 'RainAlerting', 'rain_intensity_critical_threshold', 50.0)

            intensity = recent_data[-1]['data'].get('intensity_mm_h', 0.0)
            level = "INFO"
            
            if intensity >= critical: level = "CRITICAL"
            elif intensity >= warning: level = "WARNING"
            elif intensity >= watch: level = "INFO"
            
            if level in ["WARNING", "CRITICAL"]:
                return {"level": level, "category": "rainfall", "message": f"Mưa lớn: {intensity}mm/h", "details": {"val": intensity}}
            return None
        except Exception:
            return None

    def analyze_water_level(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            val = recent_data[-1]['data'].get('water_level', 0.0)
            warn = self._get_cfg(config, 'Water', 'warning_threshold', 999.0)
            crit = self._get_cfg(config, 'Water', 'critical_threshold', 999.0)
            
            level = "INFO"
            if val >= crit: level = "CRITICAL"
            elif val >= warn: level = "WARNING"
            
            if level in ["WARNING", "CRITICAL"]:
                return {"level": level, "category": "water_level", "message": f"Nước cao: {val}m", "details": {"val": val}}
            return None
        except Exception:
            return None

    def analyze_tilt(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            latest = recent_data[-1]['data']
            accel = latest.get('total_accel', 0.0)
            thresh = self._get_cfg(config, 'ImuAlerting', 'shock_threshold_ms2', 20.0)
            
            if accel > thresh:
                return {"level": "CRITICAL", "category": "shock", "message": f"Va đập: {accel:.1f} m/s²", "details": {"val": accel}}
            return None
        except Exception:
            return None