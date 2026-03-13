# backend/app/landslide_analyzer.py - FIXED WITH CONFIRMATION COUNTER
import logging
import math
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
            return float(config.get(section, {}).get(key, default))
        except (ValueError, TypeError, AttributeError):
            return float(default)

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
            
            # Tính displacement ước lượng từ OLS (để hiển thị) thay vì cộng dồn noise
            total_displacement_mm = (velocity_m_per_day * duration_days) * 1000

            # Net displacement (first → last) chỉ dùng để tham khảo
            first_data = first_point['data']
            last_data = last_point['data']
            delta_e = last_data.get('pos_e', 0) - first_data.get('pos_e', 0)
            delta_n = last_data.get('pos_n', 0) - first_data.get('pos_n', 0)
            delta_u = last_data.get('pos_u', 0) - first_data.get('pos_u', 0)
            net_displacement_mm = math.sqrt(delta_e**2 + delta_n**2 + delta_u**2) * 1000

            velocity_mm_per_day = velocity_m_per_day * 1000
            velocity_mm_per_year = velocity_mm_per_day * 365
            velocity_mm_per_second = velocity_mm_per_day / 86400

            classification = self._classify_velocity_extended(
                velocity_mm_per_second,
                velocity_mm_per_day,
                velocity_mm_per_year,
                config
            )

            # --- Bước 4: Trend detection bằng sliding window velocity ---
            trend = self._detect_displacement_trend(sorted_data)

            cls_upper = classification.upper()
            
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

            # --- Bước 4b: Tính toán Khoảng tin cậy OLS (OLS Confidence Interval) ---
            velocity_ci_95 = self._calculate_ols_velocity_ci(sorted_data)

            # --- Bước 4c: Phát hiện CUSUM Change Point ---
            cusum_result = self._detect_cusum_change_points(sorted_data)
            
            if cusum_result['has_change']:
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
            if inverse_velocity.get('predicted_failure'):
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
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_ci_95": round(velocity_ci_95, 2),
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "cusum_change": cusum_result['has_change'],
                    "cusum_message": cusum_result.get('message', ''),
                    "duration_days": round(duration_days, 1),
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
        classification_table = config.get("velocity_classification")
        if not classification_table:
            classification_table = [
                {"name": "Extremely Rapid", "threshold": 5, "unit": "m/s"},      # > 5 m/sec
                {"name": "Very Rapid", "threshold": 3, "unit": "m/min"},      # > 3 m/min (0.05 m/s)
                {"name": "Rapid", "threshold": 1.8, "unit": "m/hr"},       # > 1.8 m/hr (0.5 mm/s)
                {"name": "Moderate", "threshold": 13, "unit": "m/month"},  # > 13 m/month (5x10^-3 mm/s)
                {"name": "Slow", "threshold": 1.6, "unit": "m/year"},      # > 1.6 m/year (5x10^-5 mm/s)
                {"name": "Very Slow", "threshold": 16, "unit": "mm/year"},    # > 16 mm/year (5x10^-7 mm/s)
                {"name": "Extremely Slow", "threshold": 0, "unit": "mm/year"}     # < 16 mm/year
            ]
        
        normalized_table = []
        for cls in classification_table:
            thresh = float(cls.get('threshold', 0))
            unit = cls.get('unit', 'mm/s')
            
            # Chuyển đổi mọi thứ về cùng 1 chuẩn để so sánh (mm/s)
            thresh_mm_s = thresh
            if unit == 'mm/year': thresh_mm_s = thresh / 31536000
            elif unit == 'mm/day': thresh_mm_s = thresh / 86400
            elif unit == 'm/year': thresh_mm_s = (thresh * 1000) / 31536000
            elif unit == 'm/month': thresh_mm_s = (thresh * 1000) / (30 * 86400)
            elif unit == 'm/hr': thresh_mm_s = (thresh * 1000) / 3600
            elif unit == 'm/min': thresh_mm_s = (thresh * 1000) / 60
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
        window_days: float = 30.0
    ) -> Dict[str, Any]:
        """
        Phân tích tương quan giữa lượng mưa tích lũy và dịch chuyển.
        Phương pháp: So sánh daily rainfall vs daily displacement.
        """
        result = {
            "available": False,
            "message": ""
        }

        if not gnss_data or not rain_data or len(gnss_data) < 2 or len(rain_data) < 2:
            result["message"] = "Cần cả dữ liệu GNSS và mưa để phân tích tương quan."
            return result

        try:
            # Aggregate daily displacement
            sorted_gnss = sorted(gnss_data, key=lambda x: x['timestamp'])
            sorted_rain = sorted(rain_data, key=lambda x: x['timestamp'])

            daily_disp = OrderedDict()  # day_key -> cumulative_disp_mm
            cumulative = 0.0
            for i in range(1, len(sorted_gnss)):
                prev = sorted_gnss[i - 1]['data']
                curr = sorted_gnss[i]['data']
                de = curr.get('pos_e', 0) - prev.get('pos_e', 0)
                dn = curr.get('pos_n', 0) - prev.get('pos_n', 0)
                du = curr.get('pos_u', 0) - prev.get('pos_u', 0)
                cumulative += math.sqrt(de**2 + dn**2 + du**2) * 1000
                day_key = datetime.fromtimestamp(sorted_gnss[i]['timestamp']).strftime('%Y-%m-%d')
                daily_disp[day_key] = cumulative

            # Aggregate daily rainfall (tổng mm/ngày)
            daily_rain = OrderedDict()
            for point in sorted_rain:
                day_key = datetime.fromtimestamp(point['timestamp']).strftime('%Y-%m-%d')
                rain_val = point['data'].get('rainfall_mm', point['data'].get('rain_mm', point['data'].get('rainfall', 0)))
                if day_key not in daily_rain:
                    daily_rain[day_key] = 0.0
                daily_rain[day_key] += float(rain_val) if rain_val else 0

            # Tính cumulative rainfall
            cumulative_rain = OrderedDict()
            cum_r = 0.0
            for day, val in daily_rain.items():
                cum_r += val
                cumulative_rain[day] = cum_r

            # Match days
            common_days = sorted(set(daily_disp.keys()) & set(cumulative_rain.keys()))
            if len(common_days) < 5:
                result["message"] = f"Chỉ có {len(common_days)} ngày chung — cần ít nhất 5."
                return result

            disp_values = np.array([daily_disp[d] for d in common_days])
            rain_values = np.array([cumulative_rain[d] for d in common_days])

            # Pearson correlation
            if np.std(disp_values) > 0 and np.std(rain_values) > 0:
                correlation = float(np.corrcoef(disp_values, rain_values)[0, 1])
            else:
                correlation = 0.0

            # Đánh giá mức tương quan
            abs_corr = abs(correlation)
            if abs_corr >= 0.8:
                strength = "Rất mạnh"
                assessment = "Mưa có ảnh hưởng rõ rệt đến dịch chuyển đất."
            elif abs_corr >= 0.6:
                strength = "Mạnh"
                assessment = "Mưa có tương quan đáng kể với dịch chuyển."
            elif abs_corr >= 0.4:
                strength = "Trung bình"
                assessment = "Mưa có ảnh hưởng nhất định đến dịch chuyển."
            elif abs_corr >= 0.2:
                strength = "Yếu"
                assessment = "Tương quan mưa-dịch chuyển yếu."
            else:
                strength = "Không đáng kể"
                assessment = "Mưa không ảnh hưởng rõ đến dịch chuyển trong giai đoạn này."

            # Daily rainfall (non-cumulative) cho chart
            daily_rain_values = [daily_rain.get(d, 0) for d in common_days]

            result["available"] = True
            result["correlation"] = round(correlation, 4)
            result["strength"] = strength
            result["assessment"] = assessment
            result["common_days"] = len(common_days)
            result["time_series"] = {
                "labels": [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in common_days],
                "cumulative_displacement_mm": [round(daily_disp[d], 2) for d in common_days],
                "cumulative_rainfall_mm": [round(cumulative_rain[d], 1) for d in common_days],
                "daily_rainfall_mm": [round(v, 1) for v in daily_rain_values]
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

                # Tính cumulative displacement
                cumulative = 0.0
                for i in range(1, len(window_data)):
                    prev = window_data[i - 1]['data']
                    curr = window_data[i]['data']
                    de = curr.get('pos_e', 0) - prev.get('pos_e', 0)
                    dn = curr.get('pos_n', 0) - prev.get('pos_n', 0)
                    du = curr.get('pos_u', 0) - prev.get('pos_u', 0)
                    cumulative += math.sqrt(de**2 + dn**2 + du**2) * 1000

                duration = (window_data[-1]['timestamp'] - window_data[0]['timestamp']) / 86400.0
                vel_mm_day = cumulative / duration if duration > 0 else 0
                trend = self._detect_displacement_trend(window_data)

                window_results.append({
                    "window_days": interval["type"], 
                    "label": interval["label"],
                    "status": "success",
                    "velocity_mm_day": round(vel_mm_day, 4),
                    "velocity_mm_year": round(vel_mm_day * 365, 2),
                    "displacement_mm": round(cumulative, 2),
                    "data_points": len(window_data),
                    "trend": trend
                })

            acceleration_alert = None
            valid_windows = [w for w in window_results if w['status'] == 'success' and w['velocity_mm_day'] is not None]

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
                    "duration_days": round(duration_days, 1),
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
            
            # ✅ LOGIC ĐẾM XÁC NHẬN
            if current_level in ["WARNING", "CRITICAL"]:
                # Đã confirm level này và chưa về safe hoàn toàn -> không bắn lại.
                if counter_info['latched_level'] == current_level:
                    counter_info['safe_count'] = 0  # Reset safe countdown khi vẫn còn nguy hiểm
                    return None

                # Nếu level thay đổi → Reset bộ đếm
                import time as _time
                now = _time.time()
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
                    return None
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
                    return None
                if counter_info['last_level'] != current_level:
                    counter_info['count'] = 1
                    counter_info['last_level'] = current_level
                    return None
                else:
                    counter_info['count'] += 1
                    if counter_info['count'] >= confirm_steps:
                        counter_info['latched_level'] = current_level
                        counter_info['latched_time'] = time.time()  # Ghi timestamp
                        logger.warning(f"💧 [WATER-{station_id}] ✅ CONFIRMED {current_level}")
                        audio_code = "water_warning"
                        if current_level == "CRITICAL":
                            audio_code = "water_critical"
                        return {"level": current_level, "category": "water_level", "message": f"Nước cao: {val:.2f}m", "audio_code": audio_code, "details": {"val": val}}
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
        except Exception:
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
                    return None
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
        except Exception:
            return None