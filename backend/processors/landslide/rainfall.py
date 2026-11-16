"""RainfallAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class RainfallAnalysisMixin:
    def analyze_rainfall_displacement_correlation(
        self,
        gnss_data: List[Dict[str, Any]],
        rain_data: List[Dict[str, Any]],
        window_days: float = 30.0,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Phân tích tương quan Slide model nâng cao (v2).

        Tính năng:
        - Chỉ số mưa hiệu dụng đa thang thời gian (short + long memory).
        - Lag scanning tìm độ trễ mưa → dịch chuyển tốt nhất.
        - Hồi quy tuyến tính Slide model index vs displacement rate.
        - Thống kê mưa & dịch chuyển chi tiết.
        - Phân tích CWD (Cumulative Working-Day rainfall events).
        - Peak rain event detection & displacement response.
        - Sensitivity factor (mm dịch chuyển / mm mưa).
        - Rain acceleration ratio (rain vs dry day displacement).
        - Risk insights tổng hợp.
        """
        _ = window_days
        result = {
            "available": False,
            "model": "slide_model",
            "message": ""
        }

        if not gnss_data or not rain_data or len(gnss_data) < 2 or len(rain_data) < 2:
            result["message"] = "Cần cả dữ liệu GNSS và mưa để phân tích tương quan."
            return result

        try:
            cfg = config or {}
            ls_cfg = cfg.get("SlideModel", {}) if isinstance(cfg, dict) else {}

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
            if len(common_days) < 3:
                gnss_days_str = ', '.join(sorted(gnss_daily.keys())[:5])
                rain_days_str = ', '.join(sorted(daily_rain.keys())[:5])
                result["message"] = (
                    f"Chỉ có {len(common_days)} ngày chung giữa GNSS và mưa — cần ít nhất 3. "
                    f"GNSS có {len(gnss_daily)} ngày (vd: {gnss_days_str}). "
                    f"Mưa có {len(daily_rain)} ngày (vd: {rain_days_str})."
                )
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

            # Effective rainfall (Slide model-style multi-timescale memory)
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

            slide_model_index = short_weight * rain_eff_short + (1.0 - short_weight) * rain_eff_long

            # Tìm lag tốt nhất: mưa dẫn, dịch chuyển theo sau.
            best_lag = 0
            best_corr = 0.0
            best_pairs = 0
            lag_scan_results = []
            for lag in range(max_lag_days + 1):
                if lag == 0:
                    x = slide_model_index
                    y = disp_rate_arr
                else:
                    x = slide_model_index[:-lag]
                    y = disp_rate_arr[lag:]

                if len(x) < 3:
                    continue
                if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
                    continue

                corr = float(np.corrcoef(x, y)[0, 1])
                lag_scan_results.append({"lag": lag, "correlation": round(corr, 4), "pairs": int(len(x))})
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag
                    best_pairs = len(x)

            if best_pairs < 3:
                result["message"] = (
                    f"Biến thiên dữ liệu quá thấp ({best_pairs} cặp hợp lệ), "
                    f"chưa đủ để ước lượng Slide model tin cậy."
                )
                return result

            # Hồi quy tuyến tính cho cặp lag tốt nhất
            if best_lag == 0:
                x_fit = slide_model_index
                y_fit = disp_rate_arr
            else:
                x_fit = slide_model_index[:-best_lag]
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
                assessment = "Slide model cho thấy mưa có liên hệ rất mạnh với gia tăng dịch chuyển."
            elif abs_corr >= 0.6:
                strength = "Mạnh"
                assessment = "Slide model cho thấy mưa có liên hệ đáng kể với dịch chuyển."
            elif abs_corr >= 0.4:
                strength = "Trung bình"
                assessment = "Slide model ghi nhận ảnh hưởng mức trung bình của mưa lên dịch chuyển."
            elif abs_corr >= 0.2:
                strength = "Yếu"
                assessment = "Slide model ghi nhận liên hệ yếu giữa mưa và dịch chuyển."
            else:
                strength = "Không đáng kể"
                assessment = "Slide model chưa thấy ảnh hưởng rõ của mưa trong giai đoạn này."

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
            max_slide_model_index = float(np.max(slide_model_index)) if len(slide_model_index) > 0 else 0.0
            mean_slide_model_index = float(np.mean(slide_model_index)) if len(slide_model_index) > 0 else 0.0

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
                        "slide_model_index": round(float(slide_model_index[i]), 2)
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
            result["slide_model"] = {
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
                "max_slide_model_index": round(max_slide_model_index, 2),
                "mean_slide_model_index": round(mean_slide_model_index, 2)
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
                f"Slide model: r={correlation:.3f}, lag={best_lag} ngày, "
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
                "slide_model_index": [round(float(v), 2) for v in slide_model_index],
                "net_displacement_mm": [round(float(v), 2) for v in cumulative_disp],
                "regression_predicted": [round(float(v), 3) for v in y_pred],
            }

            return result

        except Exception as e:
            logger.error(f"Error in rainfall-displacement correlation: {e}", exc_info=True)
            result["message"] = f"Lỗi: {str(e)}"
            return result
