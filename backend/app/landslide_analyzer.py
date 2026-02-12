# backend/app/landslide_analyzer.py - FIXED WITH CONFIRMATION COUNTER
import logging
import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)

class LandslideAnalyzer:
    def __init__(self):
        # ✅ Bộ đếm xác nhận cho từng station
        self.alert_counters = defaultdict(lambda: {
            'gnss': {'count': 0, 'last_level': None},
            'rain': {'count': 0, 'last_level': None},
            'water': {'count': 0, 'last_level': None},
            'imu': {'count': 0, 'last_level': None}
        })
        
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

            classification = self._classify_velocity_extended(
                velocity_mm_per_second, 
                velocity_mm_per_day,
                velocity_mm_per_year,
                config
            )

            trend = self._detect_trend(sorted_data)

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
        classification_table = config.get('velocity_classification') or config.get('GNSS_Classification', [])
        
        if not classification_table:
            classification_table = [
                {"name": "Extremely Rapid", "threshold": 5000, "unit": "mm/s"},
                {"name": "Very Rapid", "threshold": 50, "unit": "mm/s"},
                {"name": "Rapid", "threshold": 0.5, "unit": "mm/s"},
                {"name": "Moderate", "threshold": 0.05, "unit": "mm/s"},
                {"name": "Slow", "threshold": 0.00005, "unit": "mm/s"},
                {"name": "Very Slow", "threshold": 0.0000005, "unit": "mm/s"},
                {"name": "Extremely Slow", "threshold": 0, "unit": "mm/s"}
            ]
        
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

        sorted_classes = sorted(normalized_table, key=lambda x: x['threshold_mm_s'], reverse=True)
        
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
        
        if "EXTREMELY RAPID" in cls_upper or "VERY RAPID" in cls_upper:
            return "EXTREME", f"🚨 NGUY HIỂM: Vận tốc rất cao ({classification})"
        
        elif "RAPID" in cls_upper:
            return "HIGH", f"⚠️ Cao: Vận tốc nhanh ({classification})"
        
        elif "MODERATE" in cls_upper:
            return "MEDIUM", f"⚠️ Trung bình: Đất đang trượt ({classification})"
        
        elif "SLOW" in cls_upper or "STABLE" in cls_upper:
            if trend == "accelerating":
                return "MEDIUM", f"⚠️ Chú ý: Đang tăng tốc ({classification})"
            return "LOW", f"✅ Ổn định ({classification})"
            
        else:
            return "LOW", f"Trạng thái: {classification}"

    # =========================================================================
    # 1. PHÂN TÍCH GNSS - ✅ CÓ ĐẾM XÁC NHẬN
    # =========================================================================
    def analyze_gnss_displacement(
        self, 
        station_id: int, 
        recent_data: List[Dict[str, Any]], 
        config: Dict
    ) -> Optional[Dict]:
        
        if not recent_data: return None
        
        try:
            latest = recent_data[-1]['data']
            velocity_ms = latest.get('speed_2d', 0.0) 
            velocity_mms = velocity_ms * 1000.0
            
            # Lấy cấu hình xác nhận
            gnss_config = config.get('GnssAlerting', {})
            confirm_steps = int(gnss_config.get('gnss_confirm_steps', 3))  # Mặc định 3 lần
            safe_streak = int(gnss_config.get('gnss_safe_streak', 5))      # Mặc định 5 lần an toàn
            
            velocity_class = self._classify_velocity_extended(
                velocity_mms,
                velocity_mms * 86400,
                velocity_mms * 31536000,
                config
            )
            
            cls_upper = velocity_class.upper()
            
            # ✅ XÁC ĐỊNH MỨC ĐỘ NGUY HIỂM (chưa gửi alert)
            current_level = "INFO"
            if "EXTREMELY RAPID" in cls_upper:
                current_level = "CRITICAL"
            elif "VERY RAPID" in cls_upper:
                current_level = "CRITICAL"
            elif "RAPID" in cls_upper:
                current_level = "WARNING"
            elif "MODERATE" in cls_upper:
                current_level = "WARNING"
            
            # ✅ LẤY BỘ ĐẾM CỦA TRẠM NÀY
            counter_info = self.alert_counters[station_id]['gnss']
            
            # ✅ LOGIC ĐẾM XÁC NHẬN
            if current_level in ["WARNING", "CRITICAL"]:
                # Nếu level thay đổi → Reset bộ đếm
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    logger.info(f"🔄 [GNSS-{station_id}] Level changed to {current_level}, reset counter to 1")
                    return None  # Chưa đủ → Không gửi
                else:
                    # Level giữ nguyên → Tăng đếm
                    counter_info['count'] += 1
                    logger.info(f"⏳ [GNSS-{station_id}] {current_level} count: {counter_info['count']}/{confirm_steps}")
                    
                    # ✅ CHỈ GỬI ALERT KHI ĐỦ SỐ LẦN XÁC NHẬN
                    if counter_info['count'] >= confirm_steps:
                        logger.warning(f"🚨 [GNSS-{station_id}] ✅ CONFIRMED {current_level} after {confirm_steps} times!")
                        
                        message = f"🚨 CỰC KỲ NGUY HIỂM: {velocity_mms:.2f} mm/s ({velocity_class})" if current_level == "CRITICAL" else f"⚠️ Tốc độ nhanh: {velocity_mms:.4f} mm/s ({velocity_class})"
                        
                        audio_code = "gnss_warning"
                        if current_level == "CRITICAL":
                            audio_code = "gnss_critical"
                        
                        return {
                            "level": current_level,
                            "category": "gnss_velocity",
                            "message": message,
                            "audio_code": audio_code,
                            "details": {
                                "velocity_mm_s": velocity_mms,
                                "classification": velocity_class,
                                "confirmed_after": confirm_steps
                            }
                        }
                    else:
                        return None  # Chưa đủ số lần
            
            else:
                # ✅ AN TOÀN → Đếm ngược để reset
                if counter_info['count'] > 0:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    logger.info(f"✅ [GNSS-{station_id}] Safe reading, decrement to {counter_info['count']}")
                
                # Reset sau khi liên tục an toàn
                if counter_info['count'] == 0:
                    counter_info['last_level'] = None
            
            return None

        except Exception as e:
            logger.error(f"Error analyzing GNSS for station {station_id}: {e}")
            return None

    # =========================================================================
    # 2. PHÂN TÍCH MƯA - ✅ CÓ ĐẾM XÁC NHẬN
    # =========================================================================
    def analyze_rainfall(self, station_id: int, recent_data: List[Dict], past_72h: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            watch = self._get_cfg(config, 'RainAlerting', 'rain_intensity_watch_threshold', 10.0)
            warning = self._get_cfg(config, 'RainAlerting', 'rain_intensity_warning_threshold', 25.0)
            critical = self._get_cfg(config, 'RainAlerting', 'rain_intensity_critical_threshold', 50.0)
            confirm_steps = int(config.get('RainAlerting', {}).get('rain_confirm_steps', 2))  # ✅ Mặc định 2 lần

            intensity = recent_data[-1]['data'].get('intensity_mm_h', 0.0)
            
            current_level = "INFO"
            if intensity >= critical: current_level = "CRITICAL"
            elif intensity >= warning: current_level = "WARNING"
            elif intensity >= watch: current_level = "INFO"
            
            counter_info = self.alert_counters[station_id]['rain']
            
            if current_level in ["WARNING", "CRITICAL"]:
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        logger.warning(f"🌧️ [RAIN-{station_id}] ✅ CONFIRMED {current_level}")
                        audio_code = "rain_warning"
                        if current_level == "CRITICAL":
                            audio_code = "rain_critical"
                        return {"level": current_level, "category": "rainfall", "message": f"Mưa lớn: {intensity:.1f}mm/h", "audio_code": audio_code, "details": {"val": intensity}}
                    return None
            else:
                counter_info['count'] = max(0, counter_info['count'] - 1)
                if counter_info['count'] == 0:
                    counter_info['last_level'] = None
            
            return None
        except Exception:
            return None

    # =========================================================================
    # 3. PHÂN TÍCH MỰC NƯỚC - ✅ CÓ ĐẾM XÁC NHẬN
    # =========================================================================
    def analyze_water_level(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            val = recent_data[-1]['data'].get('water_level', 0.0)
            warn = self._get_cfg(config, 'Water', 'warning_threshold', 999.0)
            crit = self._get_cfg(config, 'Water', 'critical_threshold', 999.0)
            confirm_steps = int(config.get('Water', {}).get('water_confirm_steps', 3))  # ✅ Mặc định 3 lần
            
            current_level = "INFO"
            if val >= crit: current_level = "CRITICAL"
            elif val >= warn: current_level = "WARNING"
            
            counter_info = self.alert_counters[station_id]['water']
            
            if current_level in ["WARNING", "CRITICAL"]:
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        logger.warning(f"💧 [WATER-{station_id}] ✅ CONFIRMED {current_level}")
                        audio_code = "water_warning"
                        if current_level == "CRITICAL":
                            audio_code = "water_critical"
                        return {"level": current_level, "category": "water_level", "message": f"Nước cao: {val:.2f}m", "audio_code": audio_code, "details": {"val": val}}
                    return None
            else:
                counter_info['count'] = max(0, counter_info['count'] - 1)
                if counter_info['count'] == 0:
                    counter_info['last_level'] = None
            
            return None
        except Exception:
            return None

    # =========================================================================
    # 4. PHÂN TÍCH IMU - ✅ CÓ ĐẾM XÁC NHẬN
    # =========================================================================
    def analyze_tilt(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            latest = recent_data[-1]['data']
            accel = latest.get('total_accel', 0.0)
            thresh = self._get_cfg(config, 'ImuAlerting', 'shock_threshold_ms2', 20.0)
            confirm_steps = int(config.get('ImuAlerting', {}).get('imu_confirm_steps', 1))  # ✅ Mặc định 1 lần (shock tức thì)
            
            counter_info = self.alert_counters[station_id]['imu']
            
            if accel > thresh:
                if counter_info['last_level'] != "CRITICAL":
                    counter_info['count'] = 1
                    counter_info['last_level'] = "CRITICAL"
                    if confirm_steps == 1:  # Shock thường báo ngay
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED SHOCK")
                        return {"level": "CRITICAL", "category": "shock", "message": f"Va đập: {accel:.1f} m/s²", "audio_code": "imu_shock", "details": {"val": accel}}
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED SHOCK after {confirm_steps} times")
                        return {"level": "CRITICAL", "category": "shock", "message": f"Va đập: {accel:.1f} m/s²", "audio_code": "imu_shock", "details": {"val": accel}}
                    return None
            else:
                counter_info['count'] = max(0, counter_info['count'] - 1)
                if counter_info['count'] == 0:
                    counter_info['last_level'] = None
            
            return None
        except Exception:
            return None