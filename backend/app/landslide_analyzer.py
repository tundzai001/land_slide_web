# backend/app/landslide_analyzer.py - FIXED WITH CONFIRMATION COUNTER
import logging
import math
import time
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict, OrderedDict, deque

logger = logging.getLogger(__name__)

class LandslideAnalyzer:
    def __init__(self):
        # ✅ Bộ đếm xác nhận cho từng station
        self.alert_counters = defaultdict(lambda: {
            'gnss': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'rain': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'water': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None},
            'imu': {'count': 0, 'last_level': None, 'first_detected': 0.0, 'latched_level': None}
        })
        # Lịch sử ngắn hạn để phân biệt trượt thật với jitter GNSS dù fix=4.
        self.gnss_recent_history = defaultdict(lambda: deque(maxlen=120))
        
    def _get_cfg(self, config: Dict, section: str, key: str, default: float) -> float:
        try:
            raw = config.get(section, {}).get(key, default)
            if isinstance(raw, str):
                raw = raw.strip().replace(',', '.')
            return float(raw)
        except (ValueError, TypeError, AttributeError):
            return float(default)

    def _get_gnss_min_reliable_window_days(self, config: Dict) -> float:
        min_hours = self._get_cfg(config, "GnssAlerting", "longterm_min_duration_hours", 1.0)
        return max(min_hours / 24.0, 1.0 / 1440.0)

    def _is_reliable_observation_window(
        self,
        duration_days: float,
        data_points: int,
        min_duration_days: float,
        min_points: int = 3
    ) -> bool:
        return duration_days >= min_duration_days and data_points >= min_points

    def _build_gnss_preliminary_message(
        self,
        duration_days: float,
        data_points: int,
        min_duration_days: float,
        min_points: int = 3
    ) -> str:
        observed_minutes = max(duration_days * 1440.0, 0.0)
        required_minutes = max(min_duration_days * 1440.0, 1.0)
        return (
            f"Chưa đủ thời lượng để kết luận vận tốc GNSS dài hạn: "
            f"cần >= {required_minutes:.0f} phút và >= {min_points} điểm, "
            f"hiện có {observed_minutes:.0f} phút và {data_points} điểm."
        )

    # =========================================================================
    # PHÂN TÍCH DÀI HẠN (Long-term Analysis) - IMPROVED
    # =========================================================================

    def _filter_outliers_iqr(self, data_points: List[Dict], field: str = 'pos_e') -> List[Dict]:
        """Loại bỏ outlier bằng IQR trên trường pos_e/pos_n/pos_u."""
        if len(data_points) < 4:
            return data_points

        values = np.array([p['data'].get(field, 0) for p in data_points])
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        lower = q1 - 3.0 * iqr
        upper = q3 + 3.0 * iqr

        filtered = []
        for i, p in enumerate(data_points):
            v = values[i]
            if lower <= v <= upper:
                filtered.append(p)

        removed = len(data_points) - len(filtered)
        if removed > 0:
            logger.info(f"🧹 Outlier filter ({field}): removed {removed}/{len(data_points)} points")
        return filtered

    def _filter_gnss_quality(self, data_points: List[Dict], min_fix: int = 4) -> List[Dict]:
        """Lọc dữ liệu GNSS theo chất lượng fix (RTK Fixed = 4+)."""
        filtered = [
            p for p in data_points
            if p['data'].get('fix_quality', min_fix) >= min_fix
        ]
        removed = len(data_points) - len(filtered)
        if removed > 0:
            logger.info(f"🛰️ Quality filter: removed {removed}/{len(data_points)} low-quality fixes")
        return filtered if len(filtered) >= 2 else data_points

    def analyze_long_term_velocity(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        config: Dict,
        window_days: float = 30.0
    ) -> Dict[str, Any]:
        try:
            if not historical_data or len(historical_data) < 2:
                return {"status": "insufficient_data", "message": "Cần ít nhất 2 điểm dữ liệu."}

            sorted_data = sorted(historical_data, key=lambda x: x['timestamp'])

            # --- Bước 1: Lọc chất lượng GNSS fix ---
            sorted_data = self._filter_gnss_quality(sorted_data)

            # --- Bước 2: Loại bỏ outlier bằng IQR trên E, N, U ---
            for field in ['pos_e', 'pos_n', 'pos_u']:
                sorted_data = self._filter_outliers_iqr(sorted_data, field)

            if len(sorted_data) < 2:
                return {"status": "insufficient_data", "message": "Không đủ dữ liệu sau khi lọc outlier."}

            first_point = sorted_data[0]
            last_point = sorted_data[-1]

            duration_days = (last_point['timestamp'] - first_point['timestamp']) / 86400.0
            if duration_days <= 0:
                duration_days = 0.00001  # Prevent division by zero

            # --- Bước 3: Tính toán vận tốc bằng OLS Regression (Ordinary Least Squares) ---
            # Trích xuất time và tọa độ
            t_days = np.array([(p['timestamp'] - first_point['timestamp']) / 86400.0 for p in sorted_data])
            pos_e = np.array([p['data'].get('pos_e', 0) for p in sorted_data])
            pos_n = np.array([p['data'].get('pos_n', 0) for p in sorted_data])
            pos_u = np.array([p['data'].get('pos_u', 0) for p in sorted_data])
            
            # Tính slope (vận tốc: m/day) cho từng trục
            # polyfit(x, y, 1) trả về [slope, intercept]
            vel_e_m_day = np.polyfit(t_days, pos_e, 1)[0] if len(t_days) > 1 else 0
            vel_n_m_day = np.polyfit(t_days, pos_n, 1)[0] if len(t_days) > 1 else 0
            vel_u_m_day = np.polyfit(t_days, pos_u, 1)[0] if len(t_days) > 1 else 0
            
            # Vector vận tốc tổng hợp (m/day)
            velocity_m_per_day = math.sqrt(vel_e_m_day**2 + vel_n_m_day**2 + vel_u_m_day**2)

            # Tổng chuyển dịch dài hạn phải bám theo điểm đầu và điểm cuối của cửa sổ,
            # tránh phóng đại do cộng dồn nhiễu giữa các mẫu liên tiếp.
            first_data = first_point['data']
            last_data = last_point['data']
            delta_e = last_data.get('pos_e', 0) - first_data.get('pos_e', 0)
            delta_n = last_data.get('pos_n', 0) - first_data.get('pos_n', 0)
            delta_u = last_data.get('pos_u', 0) - first_data.get('pos_u', 0)
            net_displacement_mm = math.sqrt(delta_e**2 + delta_n**2 + delta_u**2) * 1000
            total_displacement_mm = net_displacement_mm

            regression_displacement_mm = (velocity_m_per_day * duration_days) * 1000

            velocity_mm_per_day = total_displacement_mm / duration_days if duration_days > 0 else 0
            velocity_mm_per_year = velocity_mm_per_day * 365
            velocity_mm_per_second = velocity_mm_per_day / 86400
            regression_velocity_mm_per_day = velocity_m_per_day * 1000
            regression_velocity_mm_per_year = regression_velocity_mm_per_day * 365
            regression_velocity_mm_per_second = regression_velocity_mm_per_day / 86400

            min_reliable_duration_days = self._get_gnss_min_reliable_window_days(config)
            velocity_reliable = self._is_reliable_observation_window(
                duration_days,
                len(sorted_data),
                min_reliable_duration_days
            )
            reliability_message = self._build_gnss_preliminary_message(
                duration_days,
                len(sorted_data),
                min_reliable_duration_days
            )

            classification = self._classify_velocity_extended(
                velocity_mm_per_second,
                velocity_mm_per_day,
                velocity_mm_per_year,
                config
            )

            # --- Bước 4: Trend detection bằng sliding window velocity ---
            trend = self._detect_displacement_trend(sorted_data)

            cls_upper = classification.upper()

            if velocity_reliable:
                if any(c in cls_upper for c in ("EXTREMELY RAPID", "VERY RAPID", "RAPID")):
                    risk_level = "CRITICAL"
                    warning_message = f"🚨 NGUY HIỂM: Vận tốc {classification}"
                elif "MODERATE" in cls_upper:
                    risk_level = "HIGH"
                    warning_message = f"⚠️ CẢNH BÁO: Tăng tốc độ ({classification})"
                elif "SLOW" in cls_upper:
                    risk_level = "MEDIUM"
                    warning_message = f"CẦN THEO DÕI: Vận tốc {classification}"
                else:
                    risk_level = "LOW"
                    warning_message = f"An toàn: Vận tốc {classification}"

                if trend == "accelerating" and risk_level in ("LOW", "MEDIUM"):
                    risk_level = "HIGH"
                    warning_message = f"⚠️ Chú ý: Xu hướng đang tăng tốc mạnh"
            else:
                classification = "Chưa đủ thời lượng"
                risk_level = "INFO"
                warning_message = reliability_message

            # --- Bước 4b: Tính toán Khoảng tin cậy OLS (OLS Confidence Interval) ---
            velocity_ci_95 = self._calculate_ols_velocity_ci(sorted_data)

            # --- Bước 4c: Phát hiện CUSUM Change Point ---
            cusum_result = self._detect_cusum_change_points(sorted_data)
            
            if velocity_reliable and cusum_result['has_change']:
                # Nâng risk level nếu CUSUM phát hiện thay đổi
                if risk_level in ("LOW", "MEDIUM"):
                    risk_level = "HIGH"
                
                cusum_msg = f"⚠️ CUSUM: {cusum_result['message']}"
                if warning_message:
                    warning_message = f"{warning_message} | {cusum_msg}"
                else:
                    warning_message = cusum_msg

            # --- Bước 5: Inverse Velocity Method (Fukuzono) ---
            inverse_velocity = self._inverse_velocity_analysis(sorted_data)

            # Nâng risk nếu Fukuzono dự báo sụp lún gần
            if velocity_reliable and inverse_velocity.get('predicted_failure'):
                days_to_failure = inverse_velocity.get('days_to_failure', 999)
                fukuzono_msg = ""
                if days_to_failure <= 7:
                    risk_level = "EXTREME"
                    fukuzono_msg = f"🚨 FUKUZONO: Dự báo sụp lún trong ~{days_to_failure:.0f} ngày."
                elif days_to_failure <= 30:
                    if risk_level in ("LOW", "MEDIUM"):
                        risk_level = "HIGH"
                    fukuzono_msg = f"⚠️ FUKUZONO: Dự báo sụp lún trong ~{days_to_failure:.0f} ngày."
                
                if fukuzono_msg:
                    warning_message = f"{warning_message} | {fukuzono_msg}" if warning_message else fukuzono_msg

            return {
                "status": "success",
                "analysis": {
                    "total_displacement_mm": round(total_displacement_mm, 2),
                    "net_displacement_mm": round(net_displacement_mm, 2),
                    "regression_displacement_mm": round(regression_displacement_mm, 2),
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_ci_95": round(velocity_ci_95, 2),
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "regression_velocity_mm_year": round(regression_velocity_mm_per_year, 2),
                    "regression_velocity_mm_day": round(regression_velocity_mm_per_day, 4),
                    "regression_velocity_mm_second": round(regression_velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "cusum_change": cusum_result['has_change'],
                    "cusum_message": cusum_result.get('message', ''),
                    "displacement_basis": "first_last_point",
                    "velocity_reliable": velocity_reliable,
                    "reliability_message": reliability_message,
                    "min_reliable_duration_days": round(min_reliable_duration_days, 4),
                    "min_reliable_points": 3,
                    "duration_days": round(duration_days, 4),
                    "data_points_used": len(sorted_data),
                    "start_date": datetime.fromtimestamp(first_point['timestamp']).isoformat(),
                    "end_date": datetime.fromtimestamp(last_point['timestamp']).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning_message,
                "inverse_velocity": inverse_velocity
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
        def _normalize_unit(raw_unit: Any) -> str:
            u = str(raw_unit or 'mm/s').strip().lower().replace(' ', '')
            aliases = {
                'mm/s': 'mm/s', 'mmps': 'mm/s', 'mm/sec': 'mm/s', 'mm/second': 'mm/s', 'mm/giây': 'mm/s',
                'mm/day': 'mm/day', 'mm/d': 'mm/day', 'mm/ngày': 'mm/day',
                'mm/year': 'mm/year', 'mm/y': 'mm/year', 'mm/năm': 'mm/year',
                'm/year': 'm/year', 'm/y': 'm/year', 'm/năm': 'm/year',
                'm/month': 'm/month', 'm/mo': 'm/month', 'm/tháng': 'm/month',
                'm/hr': 'm/hr', 'm/h': 'm/hr', 'm/hour': 'm/hr', 'm/giờ': 'm/hr',
                'm/min': 'm/min', 'm/phút': 'm/min',
                'm/s': 'm/s', 'm/sec': 'm/s', 'm/giây': 'm/s',
                'm/day': 'm/day', 'm/d': 'm/day', 'm/ngày': 'm/day',
                'cm/day': 'cm/day', 'cm/ngày': 'cm/day',
                'cm/year': 'cm/year', 'cm/năm': 'cm/year',
            }
            return aliases.get(u, u)

        def _infer_unit_from_description(desc: str) -> Optional[str]:
            d = str(desc or '').lower().replace(' ', '')
            if not d:
                return None
            if 'mm/year' in d or 'mm/y' in d or 'mm/n' in d:
                return 'mm/year'
            if 'm/year' in d or 'm/y' in d or 'm/n' in d:
                return 'm/year'
            if 'm/month' in d or 'm/mo' in d or 'm/th' in d:
                return 'm/month'
            if 'm/hour' in d or 'm/hr' in d or 'm/h' in d or 'm/gi' in d:
                return 'm/hr'
            if 'm/min' in d or 'm/ph' in d:
                return 'm/min'
            if 'm/s' in d:
                return 'm/s'
            if 'm/day' in d or 'm/ng' in d:
                return 'm/day'
            if 'mm/day' in d or 'mm/ng' in d:
                return 'mm/day'
            return None

        # Bảng Cruden & Varnes chuẩn (hardcoded) — luôn đúng
        _CRUDEN_VARNES_DEFAULT = [
            {"name": "Extremely Rapid", "threshold": 5, "unit": "m/s"},        # > 5 m/s
            {"name": "Very Rapid",      "threshold": 3, "unit": "m/min"},      # > 3 m/min
            {"name": "Rapid",           "threshold": 1.8, "unit": "m/hr"},     # > 1.8 m/hr
            {"name": "Moderate",        "threshold": 13, "unit": "m/month"},   # > 13 m/month
            {"name": "Slow",            "threshold": 1.6, "unit": "m/year"},   # > 1.6 m/year
            {"name": "Very Slow",       "threshold": 16, "unit": "mm/year"},   # > 16 mm/year
            {"name": "Extremely Slow",  "threshold": 0, "unit": "mm/year"}     # < 16 mm/year
        ]

        def _convert_threshold_to_mm_s(thresh: float, unit: str) -> float:
            """Chuyển đổi threshold về mm/s để so sánh thống nhất."""
            if unit == 'mm/year':   return thresh / 31536000
            if unit == 'mm/month':  return thresh / (30 * 86400)
            if unit == 'mm/day':    return thresh / 86400
            if unit == 'm/year':    return (thresh * 1000) / 31536000
            if unit == 'm/month':   return (thresh * 1000) / (30 * 86400)
            if unit == 'm/day':     return (thresh * 1000) / 86400
            if unit == 'm/hr':      return (thresh * 1000) / 3600
            if unit == 'm/min':     return (thresh * 1000) / 60
            if unit == 'm/s':       return thresh * 1000
            if unit == 'cm/day':    return (thresh * 10) / 86400
            if unit == 'cm/year':   return (thresh * 10) / 31536000
            if unit == 'mm/s':      return thresh
            return thresh

        def _normalize_table(table):
            """Chuyển đổi bảng classification thành list {name, threshold_mm_s} chuẩn."""
            normalized = []
            for cls in table:
                thresh_raw = cls.get('threshold', 0)
                if isinstance(thresh_raw, str):
                    thresh_raw = thresh_raw.strip().replace(',', '.')
                try:
                    thresh = float(thresh_raw)
                except (ValueError, TypeError):
                    thresh = 0.0

                unit = _normalize_unit(cls.get('unit', 'mm/s'))
                # Một số bản config cũ bị lưu sai unit='mm/s' cho toàn bộ dải Cruden.
                # Khi đó ưu tiên suy luận lại từ mô tả để tránh phân loại sai nặng.
                if unit == 'mm/s':
                    inferred = _infer_unit_from_description(cls.get('description') or cls.get('desc') or '')
                    if inferred:
                        unit = inferred

                thresh_mm_s = _convert_threshold_to_mm_s(thresh, unit)
                normalized.append({
                    "name": cls.get('name', 'Unknown'),
                    "threshold_mm_s": thresh_mm_s
                })
            return normalized

        def _is_table_sane(normalized: list) -> bool:
            """
            Kiểm tra bảng phân loại có hợp lý không.
            Bảng Cruden & Varnes phải có ít nhất 3 mức khác nhau (> 0)
            và mức cao nhất phải > 0.001 mm/s (nếu không thì thresholds quá nhỏ
            do đổi đơn vị sai) hoặc mức thấp nhất (ngoài 0) phải < 1 mm/s
            (nếu không thì thresholds quá lớn do thiếu đổi đơn vị).
            """
            if len(normalized) < 2:
                return False
            non_zero = [c['threshold_mm_s'] for c in normalized if c['threshold_mm_s'] > 0]
            if len(non_zero) < 2:
                return False
            max_thresh = max(non_zero)
            min_thresh = min(non_zero)
            # Mức nhỏ nhất (>0) phải nhỏ hơn 1 mm/s
            # (16 mm/year ≈ 5e-7 mm/s, bất kỳ giá trị > 1 mm/s
            #  cho mức Very Slow nghĩa là đơn vị bị sai)
            if min_thresh > 1.0:
                return False
            # Mức lớn nhất phải > 0.001 mm/s
            # (Extremely Rapid 5 m/s = 5000 mm/s, nếu < 0.001 thì toàn bộ
            #  bảng bị co lại quá nhỏ)
            if max_thresh < 0.001:
                return False
            return True

        def _classify_from_sorted(sorted_classes, vel_mm_s):
            for cls in sorted_classes:
                if vel_mm_s >= cls['threshold_mm_s']:
                    return cls['name']
            return "Stable"

        # --- Chọn bảng phân loại ---
        classification_table = config.get("velocity_classification")
        normalized_table = _normalize_table(_CRUDEN_VARNES_DEFAULT)

        if classification_table and isinstance(classification_table, list) and len(classification_table) >= 2:
            candidate = _normalize_table(classification_table)
            if _is_table_sane(candidate):
                normalized_table = candidate
            else:
                logger.warning(
                    "⚠️ velocity_classification config không hợp lý (thresholds sai đơn vị?), "
                    "dùng bảng Cruden & Varnes mặc định."
                )

        sorted_classes = sorted(normalized_table, key=lambda x: x['threshold_mm_s'], reverse=True)

        result = _classify_from_sorted(sorted_classes, velocity_mm_s)

        # --- Fallback cuối cùng: nếu vẫn ra Extremely Slow nhưng velocity thực tế lớn ---
        # Dùng velocity_mm_day trực tiếp để phân loại theo thang Cruden & Varnes
        # khi kết quả classification rõ ràng sai so với giá trị vận tốc.
        if result.upper() == "EXTREMELY SLOW" and velocity_mm_day > 0.044:
            # 0.044 mm/day ≈ 16 mm/year — ngưỡng tối thiểu của Very Slow
            # Nếu vận tốc > 16 mm/year mà vẫn Extremely Slow → bảng bị lỗi,
            # phân loại lại trực tiếp bằng bảng mặc định.
            default_normalized = _normalize_table(_CRUDEN_VARNES_DEFAULT)
            default_sorted = sorted(default_normalized, key=lambda x: x['threshold_mm_s'], reverse=True)
            result = _classify_from_sorted(default_sorted, velocity_mm_s)
            if result.upper() == "EXTREMELY SLOW" and velocity_mm_day > 0.044:
                # Vẫn sai? Phân loại trực tiếp theo mm/day
                if velocity_mm_day >= 432000000:       # 5 m/s = 432,000,000 mm/day
                    result = "Extremely Rapid"
                elif velocity_mm_day >= 4320000:       # 3 m/min = 4,320,000 mm/day
                    result = "Very Rapid"
                elif velocity_mm_day >= 43200:         # 1.8 m/hr = 43,200 mm/day
                    result = "Rapid"
                elif velocity_mm_day >= 433.33:        # 13 m/month ≈ 433.33 mm/day
                    result = "Moderate"
                elif velocity_mm_day >= 4.384:         # 1.6 m/year ≈ 4.384 mm/day
                    result = "Slow"
                elif velocity_mm_day >= 0.044:         # 16 mm/year ≈ 0.044 mm/day
                    result = "Very Slow"
                else:
                    result = "Extremely Slow"

        return result

    def _detect_displacement_trend(self, sorted_data: List[Dict], window_size: int = 5) -> str:
        """
        Phát hiện xu hướng bằng sliding window velocity tính từ displacement thực,
        thay vì dùng speed_2d tức thời nhiễu cao.
        """
        if len(sorted_data) < window_size * 2:
            return "stable"
        try:
            # Tính velocity trung bình mỗi window (mm/day)
            window_velocities = []
            for i in range(window_size, len(sorted_data)):
                start = sorted_data[i - window_size]
                end = sorted_data[i]
                dt_days = (end['timestamp'] - start['timestamp']) / 86400.0
                if dt_days < 0.001:
                    continue
                de = end['data'].get('pos_e', 0) - start['data'].get('pos_e', 0)
                dn = end['data'].get('pos_n', 0) - start['data'].get('pos_n', 0)
                du = end['data'].get('pos_u', 0) - start['data'].get('pos_u', 0)
                disp_mm = math.sqrt(de**2 + dn**2 + du**2) * 1000
                vel = disp_mm / dt_days
                window_velocities.append(vel)

            if len(window_velocities) < 5:
                return "stable"

            x = np.arange(len(window_velocities))
            y = np.array(window_velocities)
            # Chuẩn hóa slope theo mean velocity để có ý nghĩa tương đối
            slope = np.polyfit(x, y, 1)[0]
            mean_vel = np.mean(y)
            if mean_vel > 0:
                relative_slope = slope / mean_vel
            else:
                relative_slope = 0

            if relative_slope > 0.01:
                return "accelerating"
            elif relative_slope < -0.01:
                return "decelerating"
            else:
                return "stable"
        except Exception:
            return "stable"

    def _calculate_ols_velocity_ci(self, sorted_data: List[Dict]) -> float:
        """
        Tính khoảng tin cậy 95% cho vận tốc bằng OLS (Ordinary Least Squares).
        Sử dụng Error Propagation (weighted combination) để tính chuẩn sai số của Magnitude.
        """
        if len(sorted_data) < 5:
            return 0.0

        try:
            x = []
            y_e, y_n, y_u = [], [], []
            
            start_ts = sorted_data[0]['timestamp']
            
            for p in sorted_data:
                dt_days = (p['timestamp'] - start_ts) / 86400.0
                x.append(dt_days)
                y_e.append(p['data'].get('pos_e', 0) * 1000) # mm
                y_n.append(p['data'].get('pos_n', 0) * 1000)
                y_u.append(p['data'].get('pos_u', 0) * 1000)
                
            x = np.array(x)
            n = len(x)
            x_mean = np.mean(x)
            denominator = np.sum((x - x_mean)**2)
            
            if denominator == 0: return 0.0

            # Tính toán Slope, SE^2 riêng của từng trục E, N, U
            slopes = {}
            se_squared_dict = {}

            for axis_name, y_arr in zip(['e', 'n', 'u'], [np.array(y_e), np.array(y_n), np.array(y_u)]):
                y_mean = np.mean(y_arr)
                numerator = np.sum((x - x_mean) * (y_arr - y_mean))
                slope = numerator / denominator
                
                y_pred = slope * (x - x_mean) + y_mean
                ssr = np.sum((y_arr - y_pred)**2)
                
                s2 = ssr / (n - 2) if n > 2 else 0
                se_squared = s2 / denominator
                
                slopes[axis_name] = slope
                se_squared_dict[axis_name] = se_squared

            # Tính Velocity Magnitude (v_mag)
            v_mag = math.sqrt(slopes['e']**2 + slopes['n']**2 + slopes['u']**2)

            if v_mag == 0:
                return 0.0

            # Lan truyền sai số (Error Propagation):
            # Variance(v_mag) = Σ ( (∂v_mag / ∂v_i)^2 * Variance(v_i) )
            # ∂v_mag / ∂v_i = v_i / v_mag
            
            se_magnitude_squared = (
                (slopes['e'] / v_mag)**2 * se_squared_dict['e'] +
                (slopes['n'] / v_mag)**2 * se_squared_dict['n'] +
                (slopes['u'] / v_mag)**2 * se_squared_dict['u']
            )
            
            se_magnitude_day = math.sqrt(se_magnitude_squared)
            
            # 95% CI (z ≈ 1.96)
            ci_95_day = 1.96 * se_magnitude_day
            ci_95_year = ci_95_day * 365.25 # mm/year
            
            return round(ci_95_year, 2)
            
        except Exception as e:
            logger.error(f"Error calculating OLS CI: {e}")
            return 0.0

    def _detect_cusum_change_points(self, sorted_data: List[Dict]) -> Dict:
        """
        Thuật toán CUSUM để tìm điểm thay đổi (Change Point) đột ngột.
        """
        if len(sorted_data) < 14:  # Cần ít nhất 2 tuần dữ liệu
            return {"has_change": False, "message": ""}
            
        try:
            displacements = []
            for i in range(1, len(sorted_data)):
                p1 = sorted_data[i]
                p0 = sorted_data[i-1]
                dt_days = (p1['timestamp'] - p0['timestamp']) / 86400.0
                
                if dt_days > 0.001:
                    de = p1['data'].get('pos_e', 0) - p0['data'].get('pos_e', 0)
                    dn = p1['data'].get('pos_n', 0) - p0['data'].get('pos_n', 0)
                    du = p1['data'].get('pos_u', 0) - p0['data'].get('pos_u', 0)
                    disp_mm = math.sqrt(de**2 + dn**2 + du**2) * 1000
                    
                    vel_day = disp_mm / dt_days
                    displacements.append(vel_day)
                    
            if len(displacements) < 10:
                return {"has_change": False, "message": ""}
            
            values = np.array(displacements)
            
            # Baseline tự động: 25% dữ liệu đầu tối thiểu 10 điểm
            baseline_len = max(10, int(len(values) * 0.25))
            if baseline_len > len(values): baseline_len = len(values)
            
            baseline_mean = np.mean(values[:baseline_len])
            baseline_std = np.std(values[:baseline_len])
            if baseline_std < 0.001: 
                baseline_std = 0.001 # Tránh chia 0
            
            z_scores = (values - baseline_mean) / baseline_std
            cusum_positive = np.zeros(len(values) + 1)
            
            k = 0.5 # Allowable slack
            h = 5.0 # Threshold
            
            change_detected_idx = -1
            
            for i in range(len(values)):
                cusum_positive[i+1] = max(0, cusum_positive[i] + z_scores[i] - k)
                if cusum_positive[i+1] > h and change_detected_idx == -1:
                    change_detected_idx = i
                    break
                    
            if change_detected_idx != -1:
                # Lấy ngày xảy ra change point
                change_point = sorted_data[change_detected_idx + 1]
                change_date = datetime.fromtimestamp(change_point['timestamp']).strftime('%d/%m/%Y')
                return {
                    "has_change": True, 
                    "message": f"Phát hiện điểm thay đổi xu hướng độ dốc vào {change_date}"
                }
                
            return {"has_change": False, "message": ""}
            
        except Exception as e:
            logger.error(f"Error in CUSUM: {e}")
            return {"has_change": False, "message": ""}

    def _inverse_velocity_analysis(self, sorted_data: List[Dict], window_days: float = 3.0) -> Dict[str, Any]:
        """
        Phương pháp Inverse Velocity (Fukuzono/Saito) để dự báo thời điểm sụp lún.
        Nếu 1/v giảm tuyến tính về 0, đó là dấu hiệu sắp sụp lún.
        """
        result = {
            "available": False,
            "predicted_failure": False,
            "message": ""
        }

        if len(sorted_data) < 10:
            result["message"] = "Cần ít nhất 10 điểm dữ liệu cho phân tích Inverse Velocity."
            return result

        try:
            # Tính daily velocity (mm/day) bằng sliding window
            window_sec = window_days * 86400
            daily_velocities = []  # (timestamp, velocity_mm_day)

            for i in range(len(sorted_data)):
                # Tìm các điểm trong window trước đó
                t_end = sorted_data[i]['timestamp']
                t_start = t_end - window_sec
                window_points = [p for p in sorted_data if t_start <= p['timestamp'] <= t_end]
                if len(window_points) < 2:
                    continue

                first_wp = window_points[0]
                last_wp = window_points[-1]
                dt_days = (last_wp['timestamp'] - first_wp['timestamp']) / 86400.0
                if dt_days < 0.1:
                    continue

                de = last_wp['data'].get('pos_e', 0) - first_wp['data'].get('pos_e', 0)
                dn = last_wp['data'].get('pos_n', 0) - first_wp['data'].get('pos_n', 0)
                du = last_wp['data'].get('pos_u', 0) - first_wp['data'].get('pos_u', 0)
                disp_mm = math.sqrt(de**2 + dn**2 + du**2) * 1000
                vel = disp_mm / dt_days

                if vel > 0.001:  # Bỏ qua velocity gần 0
                    daily_velocities.append((t_end, vel))

            if len(daily_velocities) < 5:
                result["message"] = "Không đủ dữ liệu velocity > 0 cho Inverse Velocity."
                return result

            # Tính 1/v
            timestamps = np.array([dv[0] for dv in daily_velocities], dtype=float)
            velocities = np.array([dv[1] for dv in daily_velocities])
            inv_velocities = 1.0 / velocities

            # Chuẩn hóa timestamps (ngày từ điểm đầu)
            t0 = timestamps[0]
            t_days = (timestamps - t0) / 86400.0

            # Linear regression trên 1/v
            coeffs = np.polyfit(t_days, inv_velocities, 1)
            slope_inv_v = coeffs[0]
            intercept_inv_v = coeffs[1]

            # Tính R² để đánh giá độ tin cậy
            inv_v_predicted = np.polyval(coeffs, t_days)
            ss_res = np.sum((inv_velocities - inv_v_predicted) ** 2)
            ss_tot = np.sum((inv_velocities - np.mean(inv_velocities)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            result["available"] = True
            result["r_squared"] = round(r_squared, 4)
            result["slope"] = round(slope_inv_v, 6)

            # Time-series cho chart
            result["time_series"] = {
                "labels": [datetime.fromtimestamp(ts).strftime('%d/%m') for ts in timestamps],
                "inverse_velocity": [round(float(iv), 4) for iv in inv_velocities],
                "trend_line": [round(float(v), 4) for v in inv_v_predicted]
            }

            # Nếu slope < 0 (1/v đang giảm) VÀ R² đủ cao → dự báo failure
            if slope_inv_v < -0.0001 and r_squared > 0.6:
                # Thời điểm 1/v = 0: t_failure = -intercept / slope
                t_failure_days = -intercept_inv_v / slope_inv_v
                t_last_days = t_days[-1]
                days_to_failure = t_failure_days - t_last_days

                if 0 < days_to_failure < 365:
                    result["predicted_failure"] = True
                    result["days_to_failure"] = round(days_to_failure, 1)
                    failure_timestamp = timestamps[-1] + days_to_failure * 86400
                    result["predicted_failure_date"] = datetime.fromtimestamp(failure_timestamp).isoformat()
                    result["message"] = f"⚠️ Dự báo sụp lún trong ~{days_to_failure:.0f} ngày (R²={r_squared:.2f})"
                    result["confidence"] = "high" if r_squared > 0.85 else "medium"
                else:
                    result["message"] = "hệ số đang giảm nhưng chưa có dấu hiệu sụt lún trong thời gian sắp tới."
            elif slope_inv_v < 0:
                result["message"] = "hệ số đang giảm nhưng độ tin cậy thấp — cần theo dõi thêm."
            else:
                result["message"] = "Chưa có dấu hiệu sụt lún."

            return result

        except Exception as e:
            logger.error(f"Error in inverse velocity analysis: {e}", exc_info=True)
            result["message"] = f"Lỗi phân tích: {str(e)}"
            return result

    # =========================================================================
    # PHÂN TÍCH TƯƠNG QUAN MƯA - DỊCH CHUYỂN
    # =========================================================================
    def analyze_rainfall_displacement_correlation(
        self,
        gnss_data: List[Dict[str, Any]],
        rain_data: List[Dict[str, Any]],
        window_days: float = 30.0,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Phân tích tương quan LS-RAPID nâng cao (v2).

        Tính năng:
        - Chỉ số mưa hiệu dụng đa thang thời gian (short + long memory).
        - Lag scanning tìm độ trễ mưa → dịch chuyển tốt nhất.
        - Hồi quy tuyến tính LS-RAPID index vs displacement rate.
        - Thống kê mưa & dịch chuyển chi tiết.
        - Phân tích CWD (Cumulative Working-Day rainfall events).
        - Peak rain event detection & displacement response.
        - Sensitivity factor (mm dịch chuyển / mm mưa).
        - Rain acceleration ratio (rain vs dry day displacement).
        - Risk insights tổng hợp.
        """
        result = {
            "available": False,
            "model": "ls_rapid",
            "message": ""
        }

        if not gnss_data or not rain_data or len(gnss_data) < 2 or len(rain_data) < 2:
            result["message"] = "Cần cả dữ liệu GNSS và mưa để phân tích tương quan."
            return result

        try:
            cfg = config or {}
            ls_cfg = cfg.get("LsRapid", {}) if isinstance(cfg, dict) else {}

            short_half_life_days = max(float(ls_cfg.get("short_half_life_days", 1.5)), 0.1)
            long_half_life_days = max(float(ls_cfg.get("long_half_life_days", 7.0)), 0.2)
            short_weight = float(ls_cfg.get("short_weight", 0.7))
            short_weight = min(max(short_weight, 0.0), 1.0)
            max_lag_days = int(ls_cfg.get("max_lag_days", 3))
            max_lag_days = min(max(max_lag_days, 0), 10)

            sorted_gnss = sorted(gnss_data, key=lambda x: x['timestamp'])
            sorted_rain = sorted(rain_data, key=lambda x: x['timestamp'])

            # Lấy một giá trị GNSS đại diện theo ngày (median) để giảm nhiễu.
            gnss_daily_raw = OrderedDict()  # day_key -> {'e':[], 'n':[], 'u':[]}
            for point in sorted_gnss:
                day_key = datetime.fromtimestamp(point['timestamp']).strftime('%Y-%m-%d')
                data = point.get('data', {})
                if day_key not in gnss_daily_raw:
                    gnss_daily_raw[day_key] = {'e': [], 'n': [], 'u': []}
                gnss_daily_raw[day_key]['e'].append(float(data.get('pos_e', 0.0)))
                gnss_daily_raw[day_key]['n'].append(float(data.get('pos_n', 0.0)))
                gnss_daily_raw[day_key]['u'].append(float(data.get('pos_u', 0.0)))

            gnss_daily = OrderedDict()  # day_key -> (e, n, u)
            for day_key, xyz in gnss_daily_raw.items():
                e_med = float(np.median(np.array(xyz['e']))) if xyz['e'] else 0.0
                n_med = float(np.median(np.array(xyz['n']))) if xyz['n'] else 0.0
                u_med = float(np.median(np.array(xyz['u']))) if xyz['u'] else 0.0
                gnss_daily[day_key] = (e_med, n_med, u_med)

            # Aggregate daily rainfall (tổng mm/ngày)
            daily_rain = OrderedDict()
            for point in sorted_rain:
                day_key = datetime.fromtimestamp(point['timestamp']).strftime('%Y-%m-%d')
                rain_val = point['data'].get('rainfall_mm', point['data'].get('rain_mm', point['data'].get('rainfall', 0)))
                if day_key not in daily_rain:
                    daily_rain[day_key] = 0.0
                daily_rain[day_key] += float(rain_val) if rain_val else 0

            # Match days
            common_days = sorted(set(gnss_daily.keys()) & set(daily_rain.keys()))
            if len(common_days) < 7:
                result["message"] = f"Chỉ có {len(common_days)} ngày chung — cần ít nhất 7 cho LS-RAPID."
                return result

            # Chuẩn bị displacement theo ngày
            cumulative_disp = []
            daily_disp_inc = []
            prev_norm = None
            cum_val = 0.0
            first_xyz = None

            for day in common_days:
                e, n, u = gnss_daily[day]
                if first_xyz is None:
                    first_xyz = (e, n, u)
                    cumulative_disp.append(0.0)
                    daily_disp_inc.append(0.0)
                    prev_norm = (e, n, u)
                    continue

                de0 = e - first_xyz[0]
                dn0 = n - first_xyz[1]
                du0 = u - first_xyz[2]
                cumulative_disp.append(math.sqrt(de0**2 + dn0**2 + du0**2) * 1000.0)

                dep = e - prev_norm[0]
                dnp = n - prev_norm[1]
                dup = u - prev_norm[2]
                step_mm = math.sqrt(dep**2 + dnp**2 + dup**2) * 1000.0
                daily_disp_inc.append(step_mm)
                cum_val += step_mm
                prev_norm = (e, n, u)

            # Cumulative displacement theo cách cũ (tổng bước) để giữ tương thích chart cũ
            cumulative_disp_legacy = []
            cum_legacy = 0.0
            for idx, step in enumerate(daily_disp_inc):
                if idx == 0:
                    cumulative_disp_legacy.append(0.0)
                    continue
                cum_legacy += float(step)
                cumulative_disp_legacy.append(cum_legacy)

            rain_arr = np.array([float(daily_rain.get(day, 0.0)) for day in common_days], dtype=float)
            disp_rate_arr = np.array(daily_disp_inc, dtype=float)

            # Effective rainfall (LS-RAPID-style multi-timescale memory)
            decay_short = math.exp(-math.log(2.0) / short_half_life_days)
            decay_long = math.exp(-math.log(2.0) / long_half_life_days)

            rain_eff_short = np.zeros_like(rain_arr)
            rain_eff_long = np.zeros_like(rain_arr)
            for i in range(len(rain_arr)):
                if i == 0:
                    rain_eff_short[i] = rain_arr[i]
                    rain_eff_long[i] = rain_arr[i]
                else:
                    rain_eff_short[i] = rain_arr[i] + decay_short * rain_eff_short[i - 1]
                    rain_eff_long[i] = rain_arr[i] + decay_long * rain_eff_long[i - 1]

            ls_rapid_index = short_weight * rain_eff_short + (1.0 - short_weight) * rain_eff_long

            # Tìm lag tốt nhất: mưa dẫn, dịch chuyển theo sau.
            best_lag = 0
            best_corr = 0.0
            best_pairs = 0
            lag_scan_results = []
            for lag in range(max_lag_days + 1):
                if lag == 0:
                    x = ls_rapid_index
                    y = disp_rate_arr
                else:
                    x = ls_rapid_index[:-lag]
                    y = disp_rate_arr[lag:]

                if len(x) < 5:
                    continue
                if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
                    continue

                corr = float(np.corrcoef(x, y)[0, 1])
                lag_scan_results.append({"lag": lag, "correlation": round(corr, 4), "pairs": int(len(x))})
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag
                    best_pairs = len(x)

            if best_pairs < 5:
                result["message"] = "Biến thiên dữ liệu quá thấp, chưa đủ để ước lượng LS-RAPID tin cậy."
                return result

            # Hồi quy tuyến tính cho cặp lag tốt nhất
            if best_lag == 0:
                x_fit = ls_rapid_index
                y_fit = disp_rate_arr
            else:
                x_fit = ls_rapid_index[:-best_lag]
                y_fit = disp_rate_arr[best_lag:]

            slope, intercept = np.polyfit(x_fit, y_fit, 1)
            y_pred = slope * x_fit + intercept
            ss_res = float(np.sum((y_fit - y_pred) ** 2))
            ss_tot = float(np.sum((y_fit - np.mean(y_fit)) ** 2))
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            correlation = float(best_corr)

            # Đánh giá mức liên hệ
            abs_corr = abs(correlation)
            if abs_corr >= 0.8:
                strength = "Rất mạnh"
                assessment = "LS-RAPID cho thấy mưa có liên hệ rất mạnh với gia tăng dịch chuyển."
            elif abs_corr >= 0.6:
                strength = "Mạnh"
                assessment = "LS-RAPID cho thấy mưa có liên hệ đáng kể với dịch chuyển."
            elif abs_corr >= 0.4:
                strength = "Trung bình"
                assessment = "LS-RAPID ghi nhận ảnh hưởng mức trung bình của mưa lên dịch chuyển."
            elif abs_corr >= 0.2:
                strength = "Yếu"
                assessment = "LS-RAPID ghi nhận liên hệ yếu giữa mưa và dịch chuyển."
            else:
                strength = "Không đáng kể"
                assessment = "LS-RAPID chưa thấy ảnh hưởng rõ của mưa trong giai đoạn này."

            trigger_potential = "LOW"
            if correlation >= 0.6 and slope > 0 and r2 >= 0.3:
                trigger_potential = "HIGH"
            elif correlation >= 0.4 and slope > 0:
                trigger_potential = "MEDIUM"

            # Cumulative rainfall cho chart
            cumulative_rain = []
            rain_cum = 0.0
            for rv in rain_arr:
                rain_cum += float(rv)
                cumulative_rain.append(rain_cum)

            # ================================================================
            # ENHANCED ANALYSIS v2: Rich statistics & risk insights
            # ================================================================

            # --- 1. Rain Statistics ---
            total_rain_mm = float(np.sum(rain_arr))
            max_daily_rain_mm = float(np.max(rain_arr)) if len(rain_arr) > 0 else 0.0
            max_rain_day_idx = int(np.argmax(rain_arr)) if len(rain_arr) > 0 else 0
            max_rain_day_label = common_days[max_rain_day_idx] if max_rain_day_idx < len(common_days) else ""
            rain_days_count = int(np.sum(rain_arr > 0.2))
            avg_rain_on_rainy_days = float(np.mean(rain_arr[rain_arr > 0.2])) if rain_days_count > 0 else 0.0
            dry_days_count = len(common_days) - rain_days_count
            max_ls_rapid_index = float(np.max(ls_rapid_index)) if len(ls_rapid_index) > 0 else 0.0
            mean_ls_rapid_index = float(np.mean(ls_rapid_index)) if len(ls_rapid_index) > 0 else 0.0

            # --- 2. Displacement Statistics ---
            total_disp_mm = float(np.sum(disp_rate_arr))
            max_daily_disp_mm = float(np.max(disp_rate_arr)) if len(disp_rate_arr) > 0 else 0.0
            max_disp_day_idx = int(np.argmax(disp_rate_arr)) if len(disp_rate_arr) > 0 else 0
            max_disp_day_label = common_days[max_disp_day_idx] if max_disp_day_idx < len(common_days) else ""
            avg_daily_disp_mm = float(np.mean(disp_rate_arr)) if len(disp_rate_arr) > 0 else 0.0

            # --- 3. Sensitivity: mm displacement / mm rain ---
            sensitivity_mm_per_mm = 0.0
            if total_rain_mm > 1.0:
                sensitivity_mm_per_mm = total_disp_mm / total_rain_mm

            # --- 4. CWD - Cumulative Working-Day rainfall events ---
            cwd_events = []
            ev_start = None
            ev_rain = 0.0
            ev_days = 0
            for i, day in enumerate(common_days):
                r = float(rain_arr[i])
                if r > 0.2:
                    if ev_start is None:
                        ev_start = day
                    ev_rain += r
                    ev_days += 1
                else:
                    if ev_start is not None and ev_days >= 2:
                        si = common_days.index(ev_start)
                        ev_disp = float(np.sum(disp_rate_arr[si:i]))
                        cwd_events.append({
                            "start": ev_start, "end": common_days[i - 1],
                            "days": ev_days, "total_rain_mm": round(ev_rain, 1),
                            "displacement_mm": round(ev_disp, 2),
                            "avg_intensity": round(ev_rain / ev_days, 1)
                        })
                    ev_start = None
                    ev_rain = 0.0
                    ev_days = 0
            if ev_start is not None and ev_days >= 2:
                si = common_days.index(ev_start)
                ev_disp = float(np.sum(disp_rate_arr[si:]))
                cwd_events.append({
                    "start": ev_start, "end": common_days[-1],
                    "days": ev_days, "total_rain_mm": round(ev_rain, 1),
                    "displacement_mm": round(ev_disp, 2),
                    "avg_intensity": round(ev_rain / ev_days, 1)
                })
            cwd_events.sort(key=lambda e: e["total_rain_mm"], reverse=True)
            top_cwd_events = cwd_events[:5]

            # --- 5. Acceleration during rain vs dry ---
            rain_mask = rain_arr > 0.2
            disp_during_rain = float(np.mean(disp_rate_arr[rain_mask])) if np.any(rain_mask) else 0.0
            disp_during_dry = float(np.mean(disp_rate_arr[~rain_mask])) if np.any(~rain_mask) else 0.0
            rain_accel_ratio = (disp_during_rain / disp_during_dry) if disp_during_dry > 0.001 else 0.0

            # --- 6. Peak rain events (>=20 mm/day) ---
            peak_events = []
            for i, day in enumerate(common_days):
                r = float(rain_arr[i])
                if r >= 20.0:
                    resp_idx = min(i + best_lag, len(disp_rate_arr) - 1)
                    peak_events.append({
                        "date": day, "rain_mm": round(r, 1),
                        "disp_response_mm": round(float(disp_rate_arr[resp_idx]), 2),
                        "ls_rapid_index": round(float(ls_rapid_index[i]), 2)
                    })
            peak_events.sort(key=lambda e: e["rain_mm"], reverse=True)
            top_peak_events = peak_events[:5]

            # --- 7. Risk insights ---
            risk_messages = []
            if trigger_potential == "HIGH":
                risk_messages.append("🚨 Mưa là tác nhân kích hoạt chính — cần cảnh giới khi dự báo mưa lớn.")
            elif trigger_potential == "MEDIUM":
                risk_messages.append("⚠️ Mưa có tác động đáng kể — cần theo dõi khi mưa kéo dài.")
            if rain_accel_ratio > 3.0:
                risk_messages.append(f"⚡ Dịch chuyển ngày mưa nhanh gấp {rain_accel_ratio:.1f}x so với ngày khô.")
            elif rain_accel_ratio > 1.5:
                risk_messages.append(f"📈 Dịch chuyển tăng {rain_accel_ratio:.1f}x trong ngày mưa.")
            if top_cwd_events:
                we = top_cwd_events[0]
                risk_messages.append(
                    f"🌧️ Đợt mưa lớn nhất: {we['days']} ngày ({we['total_rain_mm']}mm) → dịch {we['displacement_mm']}mm."
                )
            if sensitivity_mm_per_mm > 0.01:
                risk_messages.append(f"📊 Độ nhạy: {sensitivity_mm_per_mm:.3f} mm dịch chuyển / mm mưa.")
            combined_risk_message = " | ".join(risk_messages) if risk_messages else assessment

            # ================================================================
            # BUILD RESULT
            # ================================================================
            result["available"] = True
            result["correlation"] = round(correlation, 4)
            result["strength"] = strength
            result["assessment"] = assessment
            result["common_days"] = len(common_days)
            result["lag_days"] = int(best_lag)
            result["r_squared"] = round(float(r2), 4)
            result["slope_mm_day_per_rain_index"] = round(float(slope), 6)
            result["intercept"] = round(float(intercept), 4)
            result["trigger_potential"] = trigger_potential
            result["ls_rapid"] = {
                "short_half_life_days": short_half_life_days,
                "long_half_life_days": long_half_life_days,
                "short_weight": short_weight,
                "max_lag_days": max_lag_days
            }
            result["lag_scan"] = lag_scan_results
            result["rain_stats"] = {
                "total_mm": round(total_rain_mm, 1),
                "max_daily_mm": round(max_daily_rain_mm, 1),
                "max_rain_day": max_rain_day_label,
                "rain_days": rain_days_count,
                "dry_days": dry_days_count,
                "avg_rain_on_rainy_days_mm": round(avg_rain_on_rainy_days, 1),
                "max_ls_rapid_index": round(max_ls_rapid_index, 2),
                "mean_ls_rapid_index": round(mean_ls_rapid_index, 2)
            }
            result["disp_stats"] = {
                "total_mm": round(total_disp_mm, 2),
                "max_daily_mm": round(max_daily_disp_mm, 2),
                "max_disp_day": max_disp_day_label,
                "avg_daily_mm": round(avg_daily_disp_mm, 2),
                "disp_during_rain_mm": round(disp_during_rain, 3),
                "disp_during_dry_mm": round(disp_during_dry, 3),
                "rain_acceleration_ratio": round(rain_accel_ratio, 2)
            }
            result["sensitivity_mm_per_mm"] = round(sensitivity_mm_per_mm, 4)
            result["cwd_events"] = top_cwd_events
            result["peak_rain_events"] = top_peak_events
            result["risk_insights"] = risk_messages
            result["risk_message"] = combined_risk_message

            result["message"] = (
                f"LS-RAPID: r={correlation:.3f}, lag={best_lag} ngày, "
                f"R²={r2:.2f}, trigger={trigger_potential}. "
                f"Tổng mưa: {total_rain_mm:.0f}mm ({rain_days_count} ngày mưa). "
                f"Tổng dịch chuyển: {total_disp_mm:.1f}mm."
            )
            result["time_series"] = {
                "labels": [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in common_days],
                "cumulative_displacement_mm": [round(v, 2) for v in cumulative_disp_legacy],
                "cumulative_rainfall_mm": [round(v, 1) for v in cumulative_rain],
                "daily_rainfall_mm": [round(float(v), 1) for v in rain_arr],
                "daily_displacement_mm": [round(float(v), 2) for v in disp_rate_arr],
                "effective_rainfall_short_mm": [round(float(v), 2) for v in rain_eff_short],
                "effective_rainfall_long_mm": [round(float(v), 2) for v in rain_eff_long],
                "ls_rapid_index": [round(float(v), 2) for v in ls_rapid_index],
                "net_displacement_mm": [round(float(v), 2) for v in cumulative_disp],
                "regression_predicted": [round(float(v), 3) for v in y_pred],
            }

            return result

        except Exception as e:
            logger.error(f"Error in rainfall-displacement correlation: {e}", exc_info=True)
            result["message"] = f"Lỗi: {str(e)}"
            return result

    # =========================================================================
    # PHÂN TÍCH THEO CHU KỲ LỊCH (Day/Week/Month Analysis)
    # =========================================================================
    def analyze_multi_window(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        config: Dict,
        windows: List[int] = None
    ) -> Dict[str, Any]:
        """
        Phân tích trên các chu kỳ lịch sử dụng: Ngày hôm trước, Tuần này (bao nhiêu ngày tính bấy nhiêu),
        Tháng này thay thế cho 'Multi Window' động đơn thuần.
        """
        if not historical_data or len(historical_data) < 2:
            return {"available": False, "message": "Không đủ dữ liệu."}

        try:
            from datetime import timedelta
            sorted_data = sorted(historical_data, key=lambda x: x['timestamp'])
            latest_ts = sorted_data[-1]['timestamp']
            latest_dt = datetime.fromtimestamp(latest_ts)
            min_reliable_duration_days = self._get_gnss_min_reliable_window_days(config)

            # Determine anchors
            # Day: data from 24h ago
            yesterday_start = latest_ts - 86400
            
            # Week: start of current week (Monday) at 00:00:00
            days_since_monday = latest_dt.weekday()
            week_start_dt = latest_dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            week_start_ts = week_start_dt.timestamp()

            # Month: start of current month
            month_start_dt = latest_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_start_ts = month_start_dt.timestamp()

            intervals = [
                {"label": "24h qua", "cutoff": yesterday_start, "type": "day"},
                {"label": f"Tuần này ({days_since_monday + 1}/7 ngày)", "cutoff": week_start_ts, "type": "week"},
                {"label": f"Tháng {latest_dt.month} ({latest_dt.day} ngày)", "cutoff": month_start_ts, "type": "month"}
            ]

            window_results = []
            for interval in intervals:
                cutoff = interval["cutoff"]
                window_data = [p for p in sorted_data if p['timestamp'] >= cutoff]

                if len(window_data) < 2:
                    window_results.append({
                        "window_days": interval["type"],
                        "label": interval["label"],
                        "status": "insufficient_data",
                        "velocity_mm_day": None,
                        "trend": None
                    })
                    continue

                first_window = window_data[0]['data']
                last_window = window_data[-1]['data']
                de = last_window.get('pos_e', 0) - first_window.get('pos_e', 0)
                dn = last_window.get('pos_n', 0) - first_window.get('pos_n', 0)
                du = last_window.get('pos_u', 0) - first_window.get('pos_u', 0)
                net_displacement_mm = math.sqrt(de**2 + dn**2 + du**2) * 1000

                duration = (window_data[-1]['timestamp'] - window_data[0]['timestamp']) / 86400.0
                vel_mm_day = net_displacement_mm / duration if duration > 0 else 0
                trend = self._detect_displacement_trend(window_data)
                velocity_reliable = self._is_reliable_observation_window(
                    duration,
                    len(window_data),
                    min_reliable_duration_days
                )
                reliability_message = self._build_gnss_preliminary_message(
                    duration,
                    len(window_data),
                    min_reliable_duration_days
                )

                window_results.append({
                    "window_days": interval["type"], 
                    "label": interval["label"],
                    "status": "success" if velocity_reliable else "preliminary",
                    "duration_days": round(duration, 4),
                    "velocity_mm_day": round(vel_mm_day, 4),
                    "velocity_mm_year": round(vel_mm_day * 365, 2),
                    "displacement_mm": round(net_displacement_mm, 2),
                    "displacement_basis": "first_last_point",
                    "velocity_reliable": velocity_reliable,
                    "reliability_message": reliability_message,
                    "min_reliable_duration_days": round(min_reliable_duration_days, 4),
                    "min_reliable_points": 3,
                    "data_points": len(window_data),
                    "trend": trend
                })

            acceleration_alert = None
            valid_windows = [
                w for w in window_results
                if w['status'] == 'success' and w['velocity_reliable'] and w['velocity_mm_day'] is not None
            ]

            if len(valid_windows) >= 2:
                short_window = next((w for w in valid_windows if w['window_days'] == 'day'), valid_windows[0])
                long_window = valid_windows[-1]

                if short_window != long_window and long_window['velocity_mm_day'] > 0:
                    ratio = short_window['velocity_mm_day'] / long_window['velocity_mm_day']
                    if ratio > 3.0:
                        acceleration_alert = {
                            "type": "rapid_acceleration",
                            "message": f"⚠️ CẢNH BÁO: Tốc độ hiện tại ({short_window['label']}) gấp {ratio:.1f}x so với xu hướng dài hạn ({long_window['label']})",
                            "ratio": round(ratio, 2)
                        }
                    elif ratio > 1.5:
                        acceleration_alert = {
                            "type": "moderate_acceleration",
                            "message": f"Chú ý: Tốc độ hiện hành đang tăng ({ratio:.1f}x so với {long_window['label']})",
                            "ratio": round(ratio, 2)
                        }

            return {
                "available": True,
                "windows": window_results,
                "acceleration_alert": acceleration_alert
            }

        except Exception as e:
            logger.error(f"Error in calendar interval analysis: {e}", exc_info=True)
            return {"available": False, "message": f"Lỗi: {str(e)}"}



    # =========================================================================
    # PHÂN TÍCH DÀI HẠN GÓC NGHIÊNG IMU
    # =========================================================================
    def analyze_long_term_tilt(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        window_days: float = 30.0
    ) -> Dict[str, Any]:
        """
        Phân tích xu hướng nghiêng dài hạn từ dữ liệu IMU.
        Phát hiện đất dần dần nghiêng theo thời gian.
        """
        try:
            if not historical_data or len(historical_data) < 2:
                return {"status": "insufficient_data", "message": "Cần ít nhất 2 điểm dữ liệu IMU."}

            sorted_data = sorted(historical_data, key=lambda x: x['timestamp'])
            
            # Extract roll/pitch values
            rolls = []
            pitches = []
            timestamps = []
            
            for point in sorted_data:
                data = point.get('data', {})
                roll = data.get('roll', data.get('raw_roll', None))
                pitch = data.get('pitch', data.get('raw_pitch', None))
                if roll is not None and pitch is not None:
                    rolls.append(float(roll))
                    pitches.append(float(pitch))
                    timestamps.append(point['timestamp'])
            
            if len(rolls) < 2:
                return {"status": "insufficient_data", "message": "Không đủ dữ liệu IMU hợp lệ."}
            
            duration_days = (timestamps[-1] - timestamps[0]) / 86400.0
            if duration_days <= 0:
                duration_days = 0.00001  # Prevent div by zero
            
            # --- Tính toán cơ bản ---
            roll_change = rolls[-1] - rolls[0]
            pitch_change = pitches[-1] - pitches[0]
            total_tilt_change = math.sqrt(roll_change**2 + pitch_change**2)
            avg_rate_deg_per_day = total_tilt_change / duration_days if duration_days > 0 else 0
            
            max_roll = max(abs(r) for r in rolls)
            max_pitch = max(abs(p) for p in pitches)
            
            # --- Xu hướng (linear regression trên tổng tilt) ---
            tilts = [math.sqrt(r**2 + p**2) for r, p in zip(rolls, pitches)]
            if len(tilts) >= 5:
                x = np.arange(len(tilts))
                slope = np.polyfit(x, np.array(tilts), 1)[0]
                if slope > 0.001:
                    trend = "accelerating"
                elif slope < -0.001:
                    trend = "decelerating"
                else:
                    trend = "stable"
            else:
                trend = "stable"
            
            # --- Đánh giá rủi ro ---
            if total_tilt_change >= 10.0 or avg_rate_deg_per_day >= 1.0:
                risk_level = "EXTREME"
                warning = f"🚨 NGUY HIỂM: Góc nghiêng thay đổi {total_tilt_change:.1f}° trong {duration_days:.0f} ngày"
            elif total_tilt_change >= 5.0 or avg_rate_deg_per_day >= 0.5:
                risk_level = "HIGH"
                warning = f"⚠️ Cao: Nghiêng {total_tilt_change:.1f}° ({avg_rate_deg_per_day:.2f}°/ngày)"
            elif total_tilt_change >= 2.0 or avg_rate_deg_per_day >= 0.1:
                risk_level = "MEDIUM"
                warning = f"⚠️ Trung bình: Nghiêng dần {total_tilt_change:.1f}°"
            else:
                risk_level = "LOW"
                warning = f"✅ Ổn định: Thay đổi {total_tilt_change:.2f}°"
            
            if trend == "accelerating" and risk_level == "LOW":
                risk_level = "MEDIUM"
                warning = f"⚠️ Chú ý: Tốc độ nghiêng đang tăng ({total_tilt_change:.2f}°)"
            
            # --- Tạo time-series (trung bình theo khoảng thời gian) cho chart ---
            from collections import OrderedDict
            daily_data = OrderedDict()
            
            if window_days < 1/24: fmt = '%H:%M:%S'
            elif window_days <= 1: fmt = '%H:%M'
            elif window_days <= 7: fmt = '%d/%m %H:00'
            else:                  fmt = '%d/%m'
            
            for ts, r, p in zip(timestamps, rolls, pitches):
                day_key = datetime.fromtimestamp(ts).strftime(fmt)
                if day_key not in daily_data:
                    daily_data[day_key] = {'rolls': [], 'pitches': []}
                daily_data[day_key]['rolls'].append(r)
                daily_data[day_key]['pitches'].append(p)
            
            time_series = {
                'raw_timestamps': timestamps,
                'labels': list(daily_data.keys()),
                'rolls': [round(sum(v['rolls']) / len(v['rolls']), 2) for v in daily_data.values()],
                'pitches': [round(sum(v['pitches']) / len(v['pitches']), 2) for v in daily_data.values()]
            }
            
            return {
                "status": "success",
                "analysis": {
                    "total_tilt_change_deg": round(total_tilt_change, 2),
                    "avg_rate_deg_per_day": round(avg_rate_deg_per_day, 4),
                    "max_roll_deg": round(max_roll, 2),
                    "max_pitch_deg": round(max_pitch, 2),
                    "roll_change_deg": round(roll_change, 2),
                    "pitch_change_deg": round(pitch_change, 2),
                    "trend": trend,
                    "duration_days": round(duration_days, 4),
                    "data_points": len(rolls),
                    "start_date": datetime.fromtimestamp(timestamps[0]).isoformat(),
                    "end_date": datetime.fromtimestamp(timestamps[-1]).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning,
                "time_series": time_series
            }
            
        except Exception as e:
            logger.error(f"Error in long-term tilt analysis: {e}", exc_info=True)
            return {"status": "error", "message": f"Lỗi: {str(e)}"}

    # =========================================================================
    # PHÂN TÍCH ĐỒNG THUẬN ĐA CẢM BIẾN (Cross-Sensor Consensus)
    # =========================================================================
    def analyze_cross_sensor_consensus(
        self,
        gnss_result: Dict[str, Any],
        imu_result: Dict[str, Any],
        rain_corr_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Đánh giá mức độ đồng thuận giữa các model cảm biến dài hạn.
        Nguyên tắc: dữ liệu chỉ đáng tin khi nhiều cảm biến cùng chỉ về một
        hướng — GNSS thấy dịch chuyển + IMU thấy góc nghiêng + mưa hỗ trợ.
        Nếu chỉ một cảm biến báo bất thường mà các cảm biến khác flat, rất
        có thể là nhiễu hoặc drift — không đủ cơ sở kết luận.
        """
        try:
            sensors_with_data: List[str] = []
            sensors_alerting: List[str] = []
            sensors_corroborating: List[str] = []
            sensors_conflicting: List[str] = []
            notes: List[str] = []

            # ── GNSS ──────────────────────────────────────────────────────────
            gnss_ok = bool(gnss_result and gnss_result.get("status") == "success")
            gnss_analysis = gnss_result.get("analysis", {}) if gnss_ok else {}
            gnss_reliable = gnss_analysis.get("velocity_reliable", True)
            gnss_trend = gnss_analysis.get("trend", "stable")
            gnss_risk = (gnss_result.get("risk_level", "LOW") or "LOW") if gnss_ok else "LOW"
            gnss_displacement_mm = float(gnss_analysis.get("total_displacement_mm", 0.0))
            gnss_duration_days = float(gnss_analysis.get("duration_days", 0.0))
            gnss_alerting = gnss_ok and gnss_risk not in ("LOW", "INFO")

            if gnss_ok:
                sensors_with_data.append("gnss")
                if gnss_alerting:
                    sensors_alerting.append("gnss")

            # ── IMU ───────────────────────────────────────────────────────────
            imu_ok = bool(imu_result and imu_result.get("status") == "success")
            imu_analysis = imu_result.get("analysis", {}) if imu_ok else {}
            imu_trend = imu_analysis.get("trend", "stable")
            imu_risk = (imu_result.get("risk_level", "LOW") or "LOW") if imu_ok else "LOW"
            imu_tilt_change = float(imu_analysis.get("total_tilt_change_deg", 0.0))
            imu_alerting = imu_ok and imu_risk not in ("LOW",)

            if imu_ok:
                sensors_with_data.append("imu")
                if imu_alerting:
                    sensors_alerting.append("imu")

            # ── Mưa ───────────────────────────────────────────────────────────
            rain_ok = bool(rain_corr_result and rain_corr_result.get("available") is True)
            rain_r = float(rain_corr_result.get("correlation", 0.0)) if rain_ok else 0.0
            rain_supporting = rain_ok and abs(rain_r) >= 0.4

            if rain_ok:
                sensors_with_data.append("rain")

            # ── So sánh xu hướng GNSS vs IMU ─────────────────────────────────
            trend_agreement: Optional[str] = None
            if gnss_ok and imu_ok:
                t1 = gnss_trend or "stable"
                t2 = imu_trend or "stable"
                if t1 == t2:
                    trend_agreement = "full"
                elif (t1 == "accelerating" and t2 == "stable") or (t2 == "accelerating" and t1 == "stable"):
                    trend_agreement = "partial"
                elif {t1, t2} == {"accelerating", "decelerating"}:
                    trend_agreement = "conflict"
                else:
                    trend_agreement = "full"

            both_alerting = gnss_alerting and imu_alerting
            one_alerting = gnss_alerting or imu_alerting

            # ── Quyết định mức đồng thuận ─────────────────────────────────────
            if len(sensors_with_data) == 0:
                consensus_level = "UNAVAILABLE"
                reliability_flag = "UNKNOWN"
                notes.append("Chưa có dữ liệu từ cảm biến nào để đánh giá.")

            elif both_alerting and trend_agreement in ("full", "partial"):
                consensus_level = "STRONG"
                reliability_flag = "HIGH"
                sensors_corroborating = ["gnss", "imu"]
                notes.append(
                    f"GNSS và IMU đồng thuận: GNSS ghi nhận dịch chuyển "
                    f"{gnss_displacement_mm:.1f} mm, IMU ghi nhận nghiêng "
                    f"{imu_tilt_change:.2f}° — cùng xu hướng '{gnss_trend}'."
                )

            elif both_alerting and trend_agreement == "conflict":
                consensus_level = "CONFLICT"
                reliability_flag = "LOW"
                sensors_conflicting = ["gnss", "imu"]
                notes.append(
                    f"GNSS xu hướng '{gnss_trend}' nhưng IMU xu hướng '{imu_trend}'. "
                    f"Hai cảm biến chỉ về hướng khác nhau — hãy kiểm tra lại cài đặt và vị trí."
                )

            elif gnss_alerting and not imu_ok:
                consensus_level = "PARTIAL"
                reliability_flag = "MEDIUM"
                sensors_corroborating = ["gnss"]
                notes.append(
                    f"GNSS ghi nhận dịch chuyển {gnss_displacement_mm:.1f} mm "
                    f"nhưng chưa có dữ liệu IMU để xác nhận."
                )

            elif imu_alerting and not gnss_ok:
                consensus_level = "PARTIAL"
                reliability_flag = "MEDIUM"
                sensors_corroborating = ["imu"]
                notes.append(
                    f"IMU ghi nhận nghiêng {imu_tilt_change:.2f}° "
                    f"nhưng chưa có dữ liệu GNSS để xác nhận dịch chuyển."
                )

            elif one_alerting:
                consensus_level = "PARTIAL"
                reliability_flag = "MEDIUM"
                sensors_corroborating = [s for s in ["gnss", "imu"]
                                         if (s == "gnss" and gnss_alerting) or (s == "imu" and imu_alerting)]
                alerting_name = "GNSS" if gnss_alerting else "IMU"
                other_name = "IMU" if gnss_alerting else "GNSS"
                notes.append(
                    f"{alerting_name} ghi nhận bất thường nhưng {other_name} chưa xác nhận. "
                    f"Cần thêm dữ liệu từ {other_name} để kết luận."
                )

            else:
                consensus_level = "NONE"
                reliability_flag = "STABLE"
                notes.append("Không có cảm biến nào ghi nhận bất thường đáng kể trong giai đoạn này.")

            # ── Ghi chú bổ sung mưa ───────────────────────────────────────────
            if rain_supporting and one_alerting:
                sensors_corroborating.append("rain")
                notes.append(
                    f"Mưa tương quan rõ với dịch chuyển (r={rain_r:.2f} — "
                    f"{rain_corr_result.get('strength', '')}) — có thể là nguyên nhân kích hoạt."
                )
            elif rain_ok and not rain_supporting and one_alerting:
                notes.append(
                    f"Mưa không tương quan rõ (r={rain_r:.2f}) — nguyên nhân có thể không phải mưa."
                )

            # ── Ghi chú độ tin cậy GNSS ───────────────────────────────────────
            if gnss_ok and not gnss_reliable:
                notes.append(
                    f"Lưu ý: Vận tốc GNSS chưa đủ thời lượng quan sát "
                    f"({gnss_duration_days * 1440:.0f} phút). "
                    f"Tổng chuyển dịch đầu-cuối vẫn hợp lệ nhưng vận tốc chỉ mang tính tham khảo."
                )

            summary_vn = {
                "STRONG":      "Đồng thuận mạnh — nhiều cảm biến xác nhận",
                "PARTIAL":     "Đồng thuận một phần — cần thêm dữ liệu để kết luận",
                "CONFLICT":    "Mâu thuẫn cảm biến — hãy kiểm tra lại",
                "NONE":        "Không có bất thường — theo dõi bình thường",
                "UNAVAILABLE": "Chưa có đủ dữ liệu để đánh giá",
            }

            return {
                "available": True,
                "consensus_level": consensus_level,
                "reliability_flag": reliability_flag,
                "summary": summary_vn.get(consensus_level, consensus_level),
                "sensors_with_data": sensors_with_data,
                "sensors_alerting": sensors_alerting,
                "sensors_corroborating": sensors_corroborating,
                "sensors_conflicting": sensors_conflicting,
                "trend_agreement": trend_agreement,
                "rain_supporting": rain_supporting,
                "rain_r": round(rain_r, 3) if rain_ok else None,
                "notes": notes,
            }

        except Exception as e:
            logger.error(f"Error in cross-sensor consensus: {e}", exc_info=True)
            return {"available": False, "message": f"Lỗi: {str(e)}"}

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
            confirm_steps = int(gnss_config.get('gnss_confirm_steps', 3))
            # Dù đủ confirm_steps, phải span ít nhất X giây liên tục.
            # Ngăn data burst 30Hz confirm trong <200ms.
            min_confirm_seconds = float(gnss_config.get('gnss_confirm_min_seconds', 3.0))
            # Số lần an toàn liên tiếp cần đủ để tự động resolve alert đang active.
            safe_confirm_steps = int(gnss_config.get('gnss_safe_confirm_steps', 5))
            
            velocity_class = self._classify_velocity_extended(
                velocity_mms,
                velocity_mms * 86400,
                velocity_mms * 31536000,
                config
            )
            
            cls_upper = velocity_class.upper()
            
            # ✅ XÁC ĐỊNH MỨC ĐỘ NGUY HIỂM (chưa gửi alert)
            current_level = "INFO"
            if "EXTREMELY RAPID" in cls_upper or "VERY RAPID" in cls_upper or "RAPID" in cls_upper:
                current_level = "CRITICAL"
            elif "MODERATE" in cls_upper:
                current_level = "WARNING"
            else:
                current_level = "INFO"
            
            # ✅ LẤY BỘ ĐẾM CỦA TRẠM NÀY
            counter_info = self.alert_counters[station_id]['gnss']
            # Backward-compatible for running workers created before latched_level was added.
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            # Anti-jitter gate tự thích nghi theo noise nền của chính trạm.
            # Không cần set tham số theo từng nơi: nếu chỉ rung quanh 1 điểm,
            # net displacement sẽ nhỏ so với noise envelope và bị hạ về INFO.
            history = self.gnss_recent_history[station_id]
            sample_ts = float(recent_data[-1].get('timestamp', 0.0) or 0.0)
            pos_e = latest.get('pos_e')
            pos_n = latest.get('pos_n')
            if pos_e is not None and pos_n is not None and sample_ts > 0:
                history.append({'ts': sample_ts, 'e': float(pos_e), 'n': float(pos_n)})

            if current_level in ["WARNING", "CRITICAL"] and len(history) >= 4:
                motion_points = list(history)
                if counter_info.get('first_detected', 0.0) > 0:
                    recent_motion = [p for p in history if p['ts'] >= counter_info['first_detected']]
                    if len(recent_motion) >= 4:
                        motion_points = recent_motion

                if len(motion_points) >= 4:
                    step_lengths = []
                    for i in range(1, len(motion_points)):
                        dx = motion_points[i]['e'] - motion_points[i - 1]['e']
                        dy = motion_points[i]['n'] - motion_points[i - 1]['n']
                        step_lengths.append(math.hypot(dx, dy))

                    if len(step_lengths) >= 3:
                        first = motion_points[0]
                        last = motion_points[-1]
                        net_m = math.hypot(last['e'] - first['e'], last['n'] - first['n'])
                        path_m = float(sum(step_lengths))

                        step_array = np.array(step_lengths, dtype=float)
                        median_step = float(np.median(step_array))
                        mad_step = float(np.median(np.abs(step_array - median_step)))
                        noise_envelope_m = max(median_step + 1.4826 * mad_step, 1e-6)
                        motion_significance = net_m / noise_envelope_m
                        directionality = net_m / max(path_m, 1e-9)

                        # Chỉ suppress khi vừa net displacement nhỏ so với noise floor,
                        # vừa quỹ đạo không có hướng rõ ràng.
                        if motion_significance < max(3.0, math.sqrt(len(step_lengths))) and directionality < 0.5:
                            current_level = "INFO"
                            logger.debug(
                                f"[GNSS-{station_id}] Jitter-suppressed: net={net_m*1000.0:.2f}mm, "
                                f"path={path_m*1000.0:.2f}mm, noise={noise_envelope_m*1000.0:.2f}mm, "
                                f"significance={motion_significance:.2f}, directionality={directionality:.2f}"
                            )

            # Dùng chung cho cả nhánh danger và safe (timeout/reset logic).
            import time as _time
            now = _time.time()
            
            # ✅ LOGIC ĐẾM XÁC NHẬN
            if current_level in ["WARNING", "CRITICAL"]:
                latched_level = str(counter_info.get('latched_level') or '').upper()
                level_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

                # Nếu đã latched ở mức nguy hiểm, giữ trạng thái pending cho tới khi thật sự về safe.
                # Tránh trường hợp CRITICAL vừa xuất hiện rồi tụt WARNING làm bridge auto-resolve sai.
                if latched_level in ("WARNING", "CRITICAL"):
                    counter_info['safe_count'] = 0
                    curr_rank = level_rank.get(current_level, 0)
                    latched_rank = level_rank.get(latched_level, 0)

                    # Còn cùng mức hoặc thấp hơn mức latched -> giữ pending, không resolve.
                    if curr_rank <= latched_rank:
                        return {'level': 'PENDING', 'category': 'gnss_velocity'}

                # Đã confirm level này và chưa về safe hoàn toàn -> không bắn lại.
                if counter_info['latched_level'] == current_level:
                    counter_info['safe_count'] = 0  # Reset safe countdown khi vẫn còn nguy hiểm
                    return {'level': 'PENDING', 'category': 'gnss_velocity'}

                # Nếu level thay đổi → Reset bộ đếm
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = current_level
                    counter_info['first_detected'] = now
                    logger.debug(f"[GNSS-{station_id}] Potential {current_level} detected, counting (1/{confirm_steps})")
                    return None
                else:
                    counter_info['count'] += 1

                    # Cap tại confirm_steps để không re-fire
                    if counter_info['count'] > confirm_steps:
                        counter_info['count'] = confirm_steps
                        return None

                    elapsed = now - counter_info['first_detected']
                    logger.debug(
                        f"[GNSS-{station_id}] {current_level} count: {counter_info['count']}/{confirm_steps}, "
                        f"elapsed: {elapsed:.1f}/{min_confirm_seconds}s"
                    )

                    # Phải đủ CẢ HAI: số lần VÀ thời gian tối thiểu
                    if counter_info['count'] == confirm_steps:
                        if elapsed < min_confirm_seconds:
                            logger.debug(
                                f"[GNSS-{station_id}] Count reached but too fast "
                                f"({elapsed:.2f}s < {min_confirm_seconds}s) — waiting"
                            )
                            # Không cap count — cho phép tiếp tục tăng để
                            # khi đủ thời gian sẽ re-check ở lần kế
                            counter_info['count'] = confirm_steps - 1
                            return None
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = now  # Ghi timestamp để tracking timeout
                        logger.warning(f"🚨 [GNSS-{station_id}] ✅ CONFIRMED {current_level} after {confirm_steps} readings over {elapsed:.1f}s!")
                        
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
                # ✅ AN TOÀN → cần đếm xác nhận an toàn trước khi resolve
                if counter_info['latched_level'] is not None:
                    # ⏱️ TIMEOUT CHECK: nếu alert latched > 15 phút mà vẫn safe → reset (xảy ra khi user dismiss)
                    latched_time = counter_info.get('latched_time', now)
                    elapsed_since_latched = now - latched_time
                    if elapsed_since_latched > 900:  # 900s = 15 phút
                        logger.warning(
                            f"🔄 [GNSS-{station_id}] Timeout auto-reset: alert latched {elapsed_since_latched:.0f}s ago, "
                            f"now safe → reset (user likely dismissed alert)"
                        )
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    # Đang có alert đã xác nhận → đếm safe readings
                    counter_info['safe_count'] = counter_info.get('safe_count', 0) + 1
                    logger.debug(
                        f"[GNSS-{station_id}] Safe confirm: {counter_info['safe_count']}/{safe_confirm_steps} "
                        f"(was {counter_info['latched_level']})"
                    )
                    if counter_info['safe_count'] < safe_confirm_steps:
                        # Chưa đủ → giữ trạng thái PENDING, không cho bridge resolve
                        return {'level': 'PENDING'}
                    # Đủ safe_confirm_steps lần an toàn → reset hoàn toàn
                    logger.info(
                        f"✅ [GNSS-{station_id}] Confirmed safe after {counter_info['safe_count']} "
                        f"consecutive safe readings (was {counter_info['latched_level']})"
                    )
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    # Chưa có alert latched, chỉ đếm ngược count thường
                    if counter_info['count'] > 0:
                        counter_info['count'] = max(0, counter_info['count'] - 1)
                        logger.debug(f"[GNSS-{station_id}] Safe reading, counter → {counter_info['count']}/{confirm_steps}")
                    if counter_info['count'] == 0 and counter_info['last_level'] is not None:
                        logger.info(f"✅ [GNSS-{station_id}] Returned to safe after potential {counter_info['last_level']}")
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None

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
            safe_confirm_steps = int(config.get('RainAlerting', {}).get('rain_safe_confirm_steps', 3))

            intensity = recent_data[-1]['data'].get('intensity_mm_h', 0.0)

            current_level = "INFO"
            if intensity >= critical: current_level = "CRITICAL"
            elif intensity >= warning: current_level = "WARNING"
            elif intensity >= watch: current_level = "INFO"

            counter_info = self.alert_counters[station_id]['rain']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': 'rainfall'}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(f"🌧️ [RAIN-{station_id}] ✅ CONFIRMED {current_level}")
                        audio_code = "rain_warning"
                        if current_level == "CRITICAL":
                            audio_code = "rain_critical"
                        return {"level": current_level, "category": "rainfall", "message": f"Mưa lớn: {intensity:.1f}mm/h", "audio_code": audio_code, "details": {"val": intensity}}
                    return None
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [RAIN-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing RAIN for station {station_id}: {e}", exc_info=True)
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
            safe_confirm_steps = int(config.get('Water', {}).get('water_safe_confirm_steps', 3))

            current_level = "INFO"
            if val >= crit: current_level = "CRITICAL"
            elif val >= warn: current_level = "WARNING"

            counter_info = self.alert_counters[station_id]['water']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': 'water_level'}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(
                            f"💧 [WATER-{station_id}] ✅ CONFIRMED {current_level} "
                            f"(value={val:.3f}m, warn={warn:.3f}m, crit={crit:.3f}m)"
                        )
                        audio_code = "water_warning"
                        if current_level == "CRITICAL":
                            audio_code = "water_critical"
                        threshold_ref = crit if current_level == "CRITICAL" else warn
                        return {
                            "level": current_level,
                            "category": "water_level",
                            "message": f"Nước cao: {val:.2f}m (ngưỡng {current_level}: {threshold_ref:.2f}m)",
                            "audio_code": audio_code,
                            "details": {
                                "val": val,
                                "warning_threshold": warn,
                                "critical_threshold": crit,
                            }
                        }
                    return None
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [WATER-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing WATER for station {station_id}: {e}", exc_info=True)
            return None

    # =========================================================================
    # 4. PHÂN TÍCH IMU - GÓC NGHIÊNG & VA ĐẬP - ✅ CÓ ĐẾM XÁC NHẬN
    # =========================================================================
    def analyze_tilt(self, station_id: int, recent_data: List[Dict], config: Dict) -> Optional[Dict]:
        if not recent_data: return None
        try:
            latest = recent_data[-1]['data']
            
            # Góc nghiêng
            roll = latest.get('roll', 0.0)
            pitch = latest.get('pitch', 0.0)
            delta_tilt = math.sqrt(roll**2 + pitch**2)
            
            tilt_warn = self._get_cfg(config, 'ImuAlerting', 'tilt_warning_deg', 5.0)
            tilt_crit = self._get_cfg(config, 'ImuAlerting', 'tilt_critical_deg', 15.0)
            
            # Va đập
            accel = latest.get('total_accel', 0.0)
            shock_thresh = self._get_cfg(config, 'ImuAlerting', 'shock_threshold_ms2', 20.0)
            
            confirm_steps = int(config.get('ImuAlerting', {}).get('imu_confirm_steps', 2))
            safe_confirm_steps = int(config.get('ImuAlerting', {}).get('imu_safe_confirm_steps', 3))

            # Xác định mức nguy hiểm cao nhất hiện tại
            current_level = "INFO"
            alert_category = "tilt"
            alert_msg = ""
            audio_code = ""
            details = {"delta_tilt_deg": delta_tilt}
            
            # 1. Ưu tiên kiểm tra va đập (Shock) -> thường là CRITICAL ngay
            if accel >= shock_thresh:
                current_level = "CRITICAL"
                alert_category = "shock"
                alert_msg = f"Va đập: {accel:.1f} m/s²"
                audio_code = "imu_shock"
                details["shock_ms2"] = accel
                # Shock có thể cần báo ngay lập tức
                confirm_steps = 1 
                
            # 2. Xử lý độ nghiêng (Tilt)
            elif delta_tilt >= tilt_crit:
                current_level = "CRITICAL"
                alert_category = "tilt_critical"
                alert_msg = f"Nghiêng nguy hiểm: {delta_tilt:.1f}°"
                audio_code = "imu_critical"
            elif delta_tilt >= tilt_warn:
                current_level = "WARNING"
                alert_category = "tilt_warning"
                alert_msg = f"Nghiêng nhanh: {delta_tilt:.1f}°"
                audio_code = "imu_warning"
            
            counter_info = self.alert_counters[station_id]['imu']
            if 'latched_level' not in counter_info:
                counter_info['latched_level'] = None
            if 'safe_count' not in counter_info:
                counter_info['safe_count'] = 0

            if current_level in ["WARNING", "CRITICAL"]:
                counter_info['safe_count'] = 0
                if counter_info['latched_level'] == current_level:
                    return {'level': 'PENDING', 'category': alert_category}
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    if counter_info['count'] >= confirm_steps:
                        counter_info['latched_level'] = current_level
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED {current_level} ({alert_category})")
                        return {"level": current_level, "category": alert_category, "message": alert_msg, "audio_code": audio_code, "details": details}
                    else:
                        logger.info(f"⏳ [IMU-{station_id}] WAITING CONFIRMATION {current_level} (1/{confirm_steps})")
                        return {"level": "PENDING", "category": alert_category}
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(f"⚡ [IMU-{station_id}] ✅ CONFIRMED {current_level} ({alert_category}) after {confirm_steps} times")
                        return {"level": current_level, "category": alert_category, "message": alert_msg, "audio_code": audio_code, "details": details}
                    else:
                        logger.info(f"⏳ [IMU-{station_id}] WAITING CONFIRMATION {current_level} ({counter_info['count']}/{confirm_steps})")
                        return {"level": "PENDING", "category": alert_category}
            else:
                if counter_info['latched_level'] is not None:
                    latched_time = counter_info.get('latched_time', time.time())
                    elapsed = time.time() - latched_time
                    if elapsed > 900:  # 15 phút
                        logger.warning(f"🔄 [IMU-{station_id}] Timeout auto-reset: {elapsed:.0f}s latched, now safe")
                        counter_info['count'] = 0
                        counter_info['safe_count'] = 0
                        counter_info['last_level'] = None
                        counter_info['latched_level'] = None
                        return None
                    counter_info['safe_count'] += 1
                    logger.debug(f"[IMU-{station_id}] Safe confirm: {counter_info['safe_count']}/{safe_confirm_steps} (was {counter_info['latched_level']})")
                    if counter_info['safe_count'] < safe_confirm_steps:
                        return {'level': 'PENDING'}
                    logger.info(f"✅ [IMU-{station_id}] Confirmed safe after {counter_info['safe_count']} readings")
                    counter_info['count'] = 0
                    counter_info['safe_count'] = 0
                    counter_info['last_level'] = None
                    counter_info['latched_level'] = None
                else:
                    counter_info['count'] = max(0, counter_info['count'] - 1)
                    if counter_info['count'] == 0:
                        counter_info['last_level'] = None

            return None
        except Exception as e:
            logger.error(f"Error analyzing IMU for station {station_id}: {e}", exc_info=True)
            return None