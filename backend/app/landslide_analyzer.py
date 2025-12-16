# backend/app/landslide_analyzer.py
import logging
import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class LandslideAnalyzer:
    """
    Bộ não phân tích rủi ro.
    Nhận dữ liệu đã qua xử lý (Clean Data) và Cấu hình trạm (Station Config).
    Trả về Cảnh báo (Alert) nếu vượt ngưỡng.
    """

    # --- HELPER: Lấy config an toàn ---
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
        """
        Phân tích xu hướng chuyển dịch dài hạn (30 ngày, 90 ngày, 1 năm...)
        
        Returns:
            {
                "status": "success" | "insufficient_data",
                "analysis": {
                    "total_displacement_mm": float,
                    "velocity_mm_year": float,
                    "velocity_mm_day": float,
                    "classification": str,
                    "trend": "accelerating" | "stable" | "decelerating",
                    "duration_days": float
                },
                "risk_level": "LOW" | "MEDIUM" | "HIGH" | "EXTREME",
                "warning_message": str
            }
        """
        try:
            # 1. Kiểm tra dữ liệu đầu vào
            if not historical_data or len(historical_data) < 2:
                return {
                    "status": "insufficient_data",
                    "message": f"Cần ít nhất 2 điểm dữ liệu để phân tích. Hiện có: {len(historical_data)}"
                }

            # 2. Sắp xếp theo thời gian
            sorted_data = sorted(historical_data, key=lambda x: x['timestamp'])
            
            # 3. Lấy điểm đầu và cuối
            first_point = sorted_data[0]
            last_point = sorted_data[-1]
            
            # 4. Tính thời gian (duration)
            time_diff_seconds = last_point['timestamp'] - first_point['timestamp']
            duration_days = time_diff_seconds / 86400
            
            if duration_days < 0.1:  # Ít hơn 2.4 giờ
                return {
                    "status": "insufficient_data",
                    "message": f"Khoảng thời gian quá ngắn: {duration_days:.2f} ngày"
                }

            # 5. Tính tổng chuyển dịch 3D
            first_data = first_point['data']
            last_data = last_point['data']
            
            # Vector chuyển dịch
            delta_e = last_data.get('pos_e', 0) - first_data.get('pos_e', 0)
            delta_n = last_data.get('pos_n', 0) - first_data.get('pos_n', 0)
            delta_u = last_data.get('pos_u', 0) - first_data.get('pos_u', 0)
            
            # Tổng chuyển dịch (m)
            total_displacement_m = math.sqrt(delta_e**2 + delta_n**2 + delta_u**2)
            total_displacement_mm = total_displacement_m * 1000

            # 6. Tính vận tốc trung bình
            velocity_m_per_day = total_displacement_m / duration_days
            velocity_mm_per_day = velocity_m_per_day * 1000
            velocity_mm_per_year = velocity_mm_per_day * 365
            velocity_mm_per_second = velocity_m_per_day / 86400 * 1000

            # 7. Phân loại theo Cruden & Varnes (Extended)
            classification = self._classify_velocity_extended(
                velocity_mm_per_second, 
                velocity_mm_per_day,
                velocity_mm_per_year,
                config
            )

            # 8. Phân tích xu hướng (Trend Detection)
            trend = self._detect_trend(sorted_data)

            # 9. Đánh giá rủi ro
            risk_level, warning_message = self._assess_long_term_risk(
                velocity_mm_per_year,
                classification,
                trend,
                config
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
            return {
                "status": "error",
                "message": f"Lỗi phân tích: {str(e)}"
            }

    def _classify_velocity_extended(
        self,
        velocity_mm_s: float,
        velocity_mm_day: float, 
        velocity_mm_year: float,
        config: Dict
    ) -> str:
        """
        Phân loại vận tốc theo Cruden & Varnes với đơn vị mở rộng
        Hỗ trợ: mm/s, mm/day, mm/year
        """
        # Lấy bảng phân loại từ config (nếu có)
        classification_table = config.get('GNSS_Classification', [])
        
        if not classification_table:
            # Bảng mặc định mở rộng
            classification_table = [
                {"name": "Extremely Rapid", "mm_s": 5000, "mm_day": 432000000, "mm_year": 157680000000, "desc": "> 5 m/s"},
                {"name": "Very Rapid", "mm_s": 50, "mm_day": 4320000, "mm_year": 1576800000, "desc": "3 m/min to 5 m/s"},
                {"name": "Rapid", "mm_s": 0.5, "mm_day": 43200, "mm_year": 15768000, "desc": "1.8 m/h to 3 m/min"},
                {"name": "Moderate", "mm_s": 0.0006, "mm_day": 51.84, "mm_year": 18921.6, "desc": "13 mm/mo to 1.8 m/h"},
                {"name": "Slow", "mm_s": 0.00005, "mm_day": 4.32, "mm_year": 1576.8, "desc": "1.6 m/y to 13 mm/mo"},
                {"name": "Very Slow", "mm_s": 0.000001, "mm_day": 0.0864, "mm_year": 31.536, "desc": "16 mm/y to 1.6 m/y"},
                {"name": "Extremely Slow", "mm_s": 0, "mm_day": 0, "mm_year": 0, "desc": "< 16 mm/y"}
            ]
        
        # Sort từ nhanh xuống chậm
        sorted_classes = sorted(
            classification_table,
            key=lambda x: x.get('mm_year', x.get('mm_s', 0) * 31536000),
            reverse=True
        )
        
        # Tìm class phù hợp (ưu tiên mm/year cho phân tích dài hạn)
        for cls in sorted_classes:
            threshold_year = cls.get('mm_year', cls.get('mm_s', 0) * 31536000)
            
            if velocity_mm_year >= threshold_year:
                return cls.get('name', 'Unknown')
        
        return "Stable"

    def _detect_trend(self, sorted_data: List[Dict]) -> str:
        """
        Phát hiện xu hướng: tăng tốc, ổn định, giảm tốc
        Sử dụng linear regression đơn giản trên vận tốc
        """
        if len(sorted_data) < 5:
            return "stable"
        
        try:
            # Lấy vận tốc 2D từ các điểm
            velocities = [
                point['data'].get('speed_2d', 0) 
                for point in sorted_data 
                if 'speed_2d' in point['data']
            ]
            
            if len(velocities) < 5:
                return "stable"
            
            # Linear regression
            x = np.arange(len(velocities))
            y = np.array(velocities)
            
            # Tính slope
            slope = np.polyfit(x, y, 1)[0]
            
            # Ngưỡng phân loại (có thể điều chỉnh)
            if slope > 0.0001:  # Tăng > 0.1 mm/s mỗi điểm
                return "accelerating"
            elif slope < -0.0001:  # Giảm
                return "decelerating"
            else:
                return "stable"
                
        except Exception as e:
            logger.error(f"Error detecting trend: {e}")
            return "stable"

    def _assess_long_term_risk(
        self,
        velocity_mm_year: float,
        classification: str,
        trend: str,
        config: Dict
    ) -> tuple:
        """
        Đánh giá mức độ rủi ro dựa trên vận tốc và xu hướng
        
        Returns:
            (risk_level, warning_message)
        """
        # Ngưỡng cảnh báo (mm/year)
        threshold_high = 1000  # 1 m/year
        threshold_medium = 100  # 10 cm/year
        
        # Điều chỉnh theo trend
        if trend == "accelerating":
            # Nếu đang tăng tốc, giảm ngưỡng cảnh báo
            threshold_high *= 0.8
            threshold_medium *= 0.8
        
        # Quyết định mức độ
        if velocity_mm_year > threshold_high:
            return "EXTREME", f"⚠️ NGUY HIỂM: Vận tốc {velocity_mm_year:.1f} mm/năm ({classification}), {trend}"
        elif velocity_mm_year > threshold_medium:
            return "HIGH", f"⚠️ Cao: Vận tốc {velocity_mm_year:.1f} mm/năm ({classification}), {trend}"
        elif velocity_mm_year > 16:  # Ngưỡng "Very Slow"
            return "MEDIUM", f"⚠️ Trung bình: Vận tốc {velocity_mm_year:.1f} mm/năm ({classification}), {trend}"
        else:
            return "LOW", f"✅ Thấp: Vận tốc {velocity_mm_year:.1f} mm/năm ({classification}), {trend}"

    # =========================================================================
    # 1. PHÂN TÍCH GNSS (Chuyển dịch & Vận tốc)
    # =========================================================================
    def analyze_gnss_displacement(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        """
        Phân tích dữ liệu GNSS.
        - Kiểm tra tổng chuyển dịch (Displacement) so với gốc.
        - Phân loại vận tốc theo Cruden & Varnes.
        """
        if not recent_data:
            return None
        
        try:
            # Lấy dữ liệu mới nhất
            latest_point = recent_data[-1]['data']
            
            # 1. Kiểm tra Tổng chuyển dịch (Displacement)
            pos_e = latest_point.get('pos_e', 0.0)
            pos_n = latest_point.get('pos_n', 0.0)
            pos_u = latest_point.get('pos_u', 0.0)
            
            total_displacement_m = math.sqrt(pos_e**2 + pos_n**2 + pos_u**2)
            
            # Lấy ngưỡng cảnh báo
            thresh_warn = self._get_cfg(config, 'Water', 'warning_threshold', 0.15)
            thresh_crit = self._get_cfg(config, 'Water', 'critical_threshold', 0.30)

            # 2. Phân loại vận tốc
            velocity_ms = latest_point.get('speed_2d', 0.0)
            velocity_class = self._classify_cruden_varnes(velocity_ms, config)

            # 3. Quyết định mức độ cảnh báo
            level = "INFO"
            message = f"ℹ️ Chuyển dịch: {total_displacement_m*100:.1f}cm | Tốc độ: {velocity_class}"
            category = "displacement"

            if total_displacement_m >= thresh_crit:
                level = "CRITICAL"
                message = f"🚨 NGUY HIỂM: Chuyển dịch {total_displacement_m*100:.1f}cm (> {thresh_crit*100}cm)! ({velocity_class})"
            elif total_displacement_m >= thresh_warn:
                level = "WARNING"
                message = f"⚠️ CẢNH BÁO: Chuyển dịch {total_displacement_m*100:.1f}cm (> {thresh_warn*100}cm)"
            
            if level in ["WARNING", "CRITICAL"]:
                return {
                    "level": level,
                    "category": category,
                    "message": message,
                    "details": {
                        "displacement_m": total_displacement_m,
                        "velocity_ms": velocity_ms,
                        "class": velocity_class
                    }
                }
            return None

        except Exception as e:
            logger.error(f"Error analyzing GNSS for station {station_id}: {e}")
            return None

    def _classify_cruden_varnes(self, velocity_ms: float, config: Dict) -> str:
        """Helper phân loại tốc độ trượt đất"""
        default_classes = [
            {"name": "Extremely Rapid", "min": 5.0},
            {"name": "Very Rapid", "min": 0.05},
            {"name": "Rapid", "min": 0.0005},
            {"name": "Moderate", "min": 2.1e-7},
            {"name": "Slow", "min": 1.6e-9},
            {"name": "Very Slow", "min": 5e-10},
            {"name": "Extremely Slow", "min": 0.0}
        ]
        
        classes = config.get('GNSS_Classification', default_classes)
        
        try:
            sorted_classes = sorted(
                classes, 
                key=lambda x: x.get('min', x.get('mm_giay', 0)/1000.0), 
                reverse=True
            )
            
            for cls in sorted_classes:
                threshold = cls.get('min', 0)
                if 'mm_giay' in cls:
                    threshold = cls['mm_giay'] / 1000.0
                
                if velocity_ms >= threshold:
                    return cls.get('name', 'Unknown')
        except Exception:
            return "Unknown"
            
        return "Stable"

    # =========================================================================
    # 2. PHÂN TÍCH MƯA (Rainfall)
    # =========================================================================
    def analyze_rainfall(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        past_72h_data: List[Dict[str, Any]],
        config: Dict
    ) -> Optional[Dict]:
        if not recent_data: return None

        try:
            watch = self._get_cfg(config, 'RainAlerting', 'rain_intensity_watch_threshold', 10.0)
            warning = self._get_cfg(config, 'RainAlerting', 'rain_intensity_warning_threshold', 25.0)
            critical = self._get_cfg(config, 'RainAlerting', 'rain_intensity_critical_threshold', 50.0)

            latest = recent_data[-1]['data']
            intensity = latest.get('intensity_mm_h', 0.0)

            level = "INFO"
            message = ""

            if intensity >= critical:
                level = "CRITICAL"
                message = f"🌧️ MƯA CỰC LỚN: {intensity:.1f} mm/h (> {critical})"
            elif intensity >= warning:
                level = "WARNING"
                message = f"🌧️ Mưa lớn: {intensity:.1f} mm/h (> {warning})"
            elif intensity >= watch:
                level = "INFO"
                message = f"💧 Mưa đáng chú ý: {intensity:.1f} mm/h"
            
            if level in ["WARNING", "CRITICAL"]:
                return {
                    "level": level,
                    "category": "rainfall",
                    "message": message,
                    "details": {"intensity": intensity}
                }
            return None

        except Exception as e:
            logger.error(f"Error analyzing rain: {e}")
            return None

    # =========================================================================
    # 3. PHÂN TÍCH IMU
    # =========================================================================
    def analyze_tilt(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        if not recent_data: return None

        try:
            latest = recent_data[-1]['data']
            
            total_accel = latest.get('total_accel', 0.0)
            shock_thresh = self._get_cfg(config, 'ImuAlerting', 'shock_threshold_ms2', 20.0) 
            
            roll = abs(latest.get('roll', 0.0))
            pitch = abs(latest.get('pitch', 0.0))
            max_tilt = max(roll, pitch)
            tilt_thresh = 30.0

            level = "INFO"
            message = ""

            if total_accel > shock_thresh:
                level = "CRITICAL"
                message = f"💥 PHÁT HIỆN VA ĐẬP MẠNH: {total_accel:.1f} m/s²"
            elif max_tilt > tilt_thresh:
                level = "WARNING"
                message = f"📐 NGHIÊNG BẤT THƯỜNG: {max_tilt:.1f}° (> {tilt_thresh}°)"

            if level in ["WARNING", "CRITICAL"]:
                return {
                    "level": level,
                    "category": "imu_tilt_shock",
                    "message": message,
                    "details": {"accel": total_accel, "tilt": max_tilt}
                }
            return None

        except Exception as e:
            logger.error(f"Error analyzing IMU: {e}")
            return None

    # =========================================================================
    # 4. PHÂN TÍCH MỰC NƯỚC
    # =========================================================================
    def analyze_water_level(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        if not recent_data: return None
        try:
            latest = recent_data[-1]['data']
            water_level = latest.get('water_level', 0.0)
            
            warn = self._get_cfg(config, 'water', 'warning_level', 999.0)
            crit = self._get_cfg(config, 'water', 'critical_level', 999.0)
            
            level = "INFO"
            message = ""
            
            if water_level >= crit:
                level = "CRITICAL"
                message = f"🌊 LŨ LỚN: {water_level}m (> {crit}m)"
            elif water_level >= warn:
                level = "WARNING"
                message = f"🌊 Nước dâng cao: {water_level}m (> {warn}m)"
                
            if level in ["WARNING", "CRITICAL"]:
                return {
                    "level": level,
                    "category": "water_level",
                    "message": message,
                    "details": {"water_level": water_level}
                }
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing Water: {e}")
            return None

    # =========================================================================
    # 5. TỔNG HỢP ĐÁNH GIÁ RỦI RO
    # =========================================================================
    def generate_combined_risk_assessment(
        self, 
        station_id: int, 
        gnss_alert: Optional[Dict], 
        rain_alert: Optional[Dict], 
        water_alert: Optional[Dict], 
        imu_alert: Optional[Dict]
    ) -> Dict:
        alerts = [a for a in [gnss_alert, rain_alert, water_alert, imu_alert] if a]
        
        crit_count = sum(1 for a in alerts if a['level'] == 'CRITICAL')
        warn_count = sum(1 for a in alerts if a['level'] == 'WARNING')
        
        if crit_count >= 1:
            risk = "EXTREME"
            rec = "🚨 CẢNH BÁO ĐỎ: Nguy hiểm! Sơ tán/Kiểm tra ngay."
        elif warn_count >= 2:
            risk = "HIGH"
            rec = "⚠️ Cảnh báo cao: Nhiều chỉ số vượt ngưỡng."
        elif warn_count == 1:
            risk = "MEDIUM"
            rec = "⚠️ Cảnh báo: Có chỉ số bất thường."
        else:
            risk = "LOW"
            rec = "✅ Trạng thái bình thường."
            
        return {
            "overall_risk": risk,
            "active_alerts": alerts,
            "recommendation": rec
        }