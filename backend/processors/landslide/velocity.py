"""VelocityAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class VelocityAnalysisMixin:
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
                config,
                station_id=station_id
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
                    "window_days": window_days,
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
        _velocity_mm_day: float, 
        _velocity_mm_year: float,
        config: Dict,
        station_id: Optional[int] = None
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
                'mm/min': 'mm/min', 'mm/phút': 'mm/min',
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
            # IMPORTANT: check mm/s BEFORE m/s (because 'mm/s' contains 'm/s')
            if 'mm/s' in d:
                return 'mm/s'
            # Check mm/min before m/min
            if 'mm/min' in d or 'mm/ph' in d:
                return 'mm/min'
            if 'm/min' in d or 'm/ph' in d:
                return 'm/min'
            if 'm/s' in d:
                return 'm/s'
            if 'mm/day' in d or 'mm/ng' in d:
                return 'mm/day'
            if 'm/day' in d or 'm/ng' in d:
                return 'm/day'
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
            if (unit == 'm/min'):     return (thresh * 1000) / 60
            if (unit == 'mm/min'):    return thresh / 60
            if (unit == 'm/s'):       return thresh * 1000
            if unit == 'cm/day':    return (thresh * 10) / 86400
            if unit == 'cm/year':   return (thresh * 10) / 31536000
            if unit == 'mm/s':      return thresh
            return thresh

        def _normalize_table(table):
            """Chuyển đổi bảng classification thành list {name, threshold_mm_s} chuẩn."""
            normalized = []
            for cls in table:
                # Hỗ trợ cả định dạng mới (threshold+unit) và legacy (mm_giay/m_giay).
                if cls.get('threshold') is not None:
                    thresh_raw = cls.get('threshold', 0)
                    unit = _normalize_unit(cls.get('unit', 'mm/s'))
                elif cls.get('mm_giay') is not None:
                    thresh_raw = cls.get('mm_giay', 0)
                    unit = 'mm/s'
                elif cls.get('m_giay') is not None:
                    thresh_raw = cls.get('m_giay', 0)
                    unit = 'm/s'
                else:
                    thresh_raw = 0
                    unit = _normalize_unit(cls.get('unit', 'mm/s'))

                if isinstance(thresh_raw, str):
                    thresh_raw = thresh_raw.strip().replace(',', '.')
                try:
                    thresh = float(thresh_raw)
                except (ValueError, TypeError):
                    thresh = 0.0

                # Một số bản config cũ bị lưu sai unit='mm/s' cho toàn bộ dải Cruden.
                # Khi đó ưu tiên suy luận lại từ mô tả để tránh phân loại sai nặng.
                # Nhưng nếu description cũng cho ra mm/s, tức user cố ý set mm/s → giữ nguyên.
                if unit == 'mm/s':
                    inferred = _infer_unit_from_description(cls.get('description') or cls.get('desc') or '')
                    if inferred and inferred != 'mm/s':
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
                warn_key = station_id if station_id is not None else -1
                now_ts = time.time()
                last_ts = self._velocity_config_warn_last_ts.get(warn_key, 0.0)
                # Chỉ cảnh báo tối đa 1 lần / 10 phút cho mỗi trạm.
                if now_ts - last_ts >= 600:
                    logger.warning(
                        "⚠️ velocity_classification config không hợp lý (thresholds sai đơn vị?), "
                        "dùng bảng Cruden & Varnes mặc định."
                    )
                    self._velocity_config_warn_last_ts[warn_key] = now_ts

        sorted_classes = sorted(normalized_table, key=lambda x: x['threshold_mm_s'], reverse=True)

        result = _classify_from_sorted(sorted_classes, velocity_mm_s)

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
