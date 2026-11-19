"""RainfallAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class RainfallAnalysisMixin:
    def _aggregate_gnss_and_rain_daily(self, sorted_gnss: list, sorted_rain: list) -> tuple[dict, dict, list]:
        gnss_daily_raw = OrderedDict()
        for point in sorted_gnss:
            day_key = datetime.fromtimestamp(point["timestamp"]).strftime("%Y-%m-%d")
            data = point.get("data", {})
            gnss_daily_raw.setdefault(day_key, {"e": [], "n": [], "u": []})
            gnss_daily_raw[day_key]["e"].append(float(data.get("pos_e", 0.0)))
            gnss_daily_raw[day_key]["n"].append(float(data.get("pos_n", 0.0)))
            gnss_daily_raw[day_key]["u"].append(float(data.get("pos_u", 0.0)))

        gnss_daily = OrderedDict()
        for day_key, xyz in gnss_daily_raw.items():
            e_med = float(np.median(np.array(xyz["e"]))) if xyz["e"] else 0.0
            n_med = float(np.median(np.array(xyz["n"]))) if xyz["n"] else 0.0
            u_med = float(np.median(np.array(xyz["u"]))) if xyz["u"] else 0.0
            gnss_daily[day_key] = (e_med, n_med, u_med)

        daily_rain = OrderedDict()
        for point in sorted_rain:
            day_key = datetime.fromtimestamp(point["timestamp"]).strftime("%Y-%m-%d")
            rain_val = point["data"].get("rainfall_mm", point["data"].get("rain_mm", point["data"].get("rainfall", 0)))
            daily_rain.setdefault(day_key, 0.0)
            daily_rain[day_key] += float(rain_val) if rain_val else 0

        common_days = sorted(set(gnss_daily.keys()) & set(daily_rain.keys()))
        return gnss_daily, daily_rain, common_days

    def _compute_daily_displacements(self, common_days: list, gnss_daily: dict) -> tuple[list, list, list]:
        cumulative_disp, daily_disp_inc = [], []
        first_xyz, prev_norm = None, None
        for day in common_days:
            e, n, u = gnss_daily[day]
            if first_xyz is None:
                first_xyz = (e, n, u)
                cumulative_disp.append(0.0)
                daily_disp_inc.append(0.0)
                prev_norm = (e, n, u)
                continue
            de0, dn0, du0 = e - first_xyz[0], n - first_xyz[1], u - first_xyz[2]
            cumulative_disp.append(math.sqrt(de0**2 + dn0**2 + du0**2) * 1000.0)
            dep, dnp, dup = e - prev_norm[0], n - prev_norm[1], u - prev_norm[2]
            daily_disp_inc.append(math.sqrt(dep**2 + dnp**2 + dup**2) * 1000.0)
            prev_norm = (e, n, u)

        cum_legacy = 0.0
        cumulative_disp_legacy = []
        for idx, step in enumerate(daily_disp_inc):
            if idx > 0:
                cum_legacy += float(step)
            cumulative_disp_legacy.append(cum_legacy)
        return cumulative_disp, daily_disp_inc, cumulative_disp_legacy

    def _compute_slide_model_index(self, rain_arr: np.ndarray, short_half_life: float, long_half_life: float, short_weight: float) -> np.ndarray:
        decay_short = math.exp(-math.log(2.0) / short_half_life)
        decay_long = math.exp(-math.log(2.0) / long_half_life)
        rain_eff_short = np.zeros_like(rain_arr)
        rain_eff_long = np.zeros_like(rain_arr)
        for i in range(len(rain_arr)):
            if i == 0:
                rain_eff_short[i] = rain_arr[i]
                rain_eff_long[i] = rain_arr[i]
            else:
                rain_eff_short[i] = rain_arr[i] + decay_short * rain_eff_short[i - 1]
                rain_eff_long[i] = rain_arr[i] + decay_long * rain_eff_long[i - 1]
        return short_weight * rain_eff_short + (1.0 - short_weight) * rain_eff_long

    def _scan_lag_correlation(self, slide_model_index: np.ndarray, disp_rate_arr: np.ndarray, max_lag_days: int) -> tuple[int, float, int, list]:
        best_lag, best_corr, best_pairs = 0, 0.0, 0
        lag_scan_results = []
        for lag in range(max_lag_days + 1):
            x = slide_model_index if lag == 0 else slide_model_index[:-lag]
            y = disp_rate_arr if lag == 0 else disp_rate_arr[lag:]
            if len(x) < 3 or np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
                continue
            corr = float(np.corrcoef(x, y)[0, 1])
            lag_scan_results.append({"lag": lag, "correlation": round(corr, 4), "pairs": int(len(x))})
            if abs(corr) > abs(best_corr):
                best_corr, best_lag, best_pairs = corr, lag, len(x)
        return best_lag, best_corr, best_pairs, lag_scan_results

    def _assess_correlation_strength(self, correlation: float) -> tuple[str, str]:
        abs_corr = abs(correlation)
        if abs_corr >= 0.8:
            return "Rất mạnh", "Slide model cho thấy mưa có liên hệ rất mạnh với gia tăng dịch chuyển."
        if abs_corr >= 0.6:
            return "Mạnh", "Slide model cho thấy mưa có liên hệ đáng kể với dịch chuyển."
        if abs_corr >= 0.4:
            return "Trung bình", "Slide model ghi nhận ảnh hưởng mức trung bình của mưa lên dịch chuyển."
        if abs_corr >= 0.2:
            return "Yếu", "Slide model ghi nhận liên hệ yếu giữa mưa và dịch chuyển."
        return "Không đáng kể", "Slide model chưa thấy ảnh hưởng rõ của mưa trong giai đoạn này."

    def _fit_lag_regression(self, slide_model_index: np.ndarray, disp_rate_arr: np.ndarray, best_lag: int, best_corr: float):
        x_fit = slide_model_index if best_lag == 0 else slide_model_index[:-best_lag]
        y_fit = disp_rate_arr if best_lag == 0 else disp_rate_arr[best_lag:]
        slope, intercept = np.polyfit(x_fit, y_fit, 1)
        y_pred = slope * x_fit + intercept
        ss_res = float(np.sum((y_fit - y_pred) ** 2))
        ss_tot = float(np.sum((y_fit - np.mean(y_fit)) ** 2))
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        correlation = float(best_corr)
        strength, assessment = self._assess_correlation_strength(correlation)
        trigger_potential = "HIGH" if (correlation >= 0.6 and slope > 0 and r2 >= 0.3) else ("MEDIUM" if (correlation >= 0.4 and slope > 0) else "LOW")
        return slope, intercept, r2, correlation, strength, assessment, trigger_potential

    def _compute_cwd_events(self, common_days: list, rain_arr: np.ndarray, disp_rate_arr: np.ndarray) -> list:
        cwd_events = []
        ev_start, ev_rain, ev_days = None, 0.0, 0
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
                    cwd_events.append({
                        "start": ev_start, "end": common_days[i - 1], "days": ev_days,
                        "total_rain_mm": round(ev_rain, 1), "displacement_mm": round(float(np.sum(disp_rate_arr[si:i])), 2),
                        "avg_intensity": round(ev_rain / ev_days, 1)
                    })
                ev_start, ev_rain, ev_days = None, 0.0, 0
        if ev_start is not None and ev_days >= 2:
            si = common_days.index(ev_start)
            cwd_events.append({
                "start": ev_start, "end": common_days[-1], "days": ev_days,
                "total_rain_mm": round(ev_rain, 1), "displacement_mm": round(float(np.sum(disp_rate_arr[si:])), 2),
                "avg_intensity": round(ev_rain / ev_days, 1)
            })
        cwd_events.sort(key=lambda e: e["total_rain_mm"], reverse=True)
        return cwd_events[:5]

    def _compute_peak_events(self, common_days: list, rain_arr: np.ndarray, disp_rate_arr: np.ndarray, slide_model_index: np.ndarray, best_lag: int) -> list:
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
        return peak_events[:5]

    def _build_risk_messages(self, trigger_potential: str, rain_accel_ratio: float, top_cwd_events: list, sensitivity_mm_per_mm: float, assessment: str) -> tuple[list, str]:
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
            risk_messages.append(f"🌧️ Đợt mưa lớn nhất: {we['days']} ngày ({we['total_rain_mm']}mm) → dịch {we['displacement_mm']}mm.")
        if sensitivity_mm_per_mm > 0.01:
            risk_messages.append(f"📊 Độ nhạy: {sensitivity_mm_per_mm:.3f} mm dịch chuyển / mm mưa.")
        combined_risk_message = " | ".join(risk_messages) if risk_messages else assessment
        return risk_messages, combined_risk_message

    def _build_rainfall_result(
        self, correlation, strength, assessment, common_days, best_lag, r2, slope, intercept,
        trigger_potential, short_half_life_days, long_half_life_days, short_weight, max_lag_days,
        lag_scan_results, total_rain_mm, rain_arr, max_rain_idx, rain_days_count, slide_model_index,
        total_disp_mm, disp_rate_arr, max_disp_idx, disp_during_rain, disp_during_dry,
        rain_accel_ratio, sensitivity_mm_per_mm, top_cwd_events, top_peak_events,
        risk_messages, combined_risk_message
    ) -> dict:
        max_daily_rain = round(float(np.max(rain_arr)), 1) if len(rain_arr) > 0 else 0.0
        max_rain_day = common_days[max_rain_idx] if max_rain_idx < len(common_days) else ""
        avg_rain_rainy = round(float(np.mean(rain_arr[rain_arr > 0.2])), 1) if rain_days_count > 0 else 0.0
        max_slide = round(float(np.max(slide_model_index)), 2) if len(slide_model_index) > 0 else 0.0
        mean_slide = round(float(np.mean(slide_model_index)), 2) if len(slide_model_index) > 0 else 0.0
        max_daily_disp = round(float(np.max(disp_rate_arr)), 2) if len(disp_rate_arr) > 0 else 0.0
        max_disp_day = common_days[max_disp_idx] if max_disp_idx < len(common_days) else ""
        avg_daily_disp = round(float(np.mean(disp_rate_arr)), 2) if len(disp_rate_arr) > 0 else 0.0

        return {
            "available": True, "correlation": round(correlation, 4), "strength": strength,
            "assessment": assessment, "common_days": len(common_days), "lag_days": int(best_lag),
            "r_squared": round(float(r2), 4), "slope_mm_day_per_rain_index": round(float(slope), 6),
            "intercept": round(float(intercept), 4), "trigger_potential": trigger_potential,
            "slide_model": {"short_half_life_days": short_half_life_days, "long_half_life_days": long_half_life_days, "short_weight": short_weight, "max_lag_days": max_lag_days},
            "lag_scan": lag_scan_results,
            "rain_stats": {
                "total_mm": round(total_rain_mm, 1), "max_daily_mm": max_daily_rain,
                "max_rain_day": max_rain_day, "rain_days": rain_days_count,
                "dry_days": len(common_days) - rain_days_count, "avg_rain_on_rainy_days_mm": avg_rain_rainy,
                "max_slide_model_index": max_slide, "mean_slide_model_index": mean_slide,
            },
            "disp_stats": {
                "total_mm": round(total_disp_mm, 2), "max_daily_mm": max_daily_disp,
                "max_disp_day": max_disp_day, "avg_daily_mm": avg_daily_disp,
                "disp_during_rain_mm": round(disp_during_rain, 3), "disp_during_dry_mm": round(disp_during_dry, 3),
                "rain_acceleration_ratio": round(rain_accel_ratio, 2)
            },
            "sensitivity_mm_per_mm": round(sensitivity_mm_per_mm, 4),
            "cwd_events": top_cwd_events, "peak_rain_events": top_peak_events,
            "risk_insights": risk_messages, "risk_message": combined_risk_message,
            "message": f"Slide model: r={correlation:.3f}, lag={best_lag} ngày, R²={r2:.2f}, trigger={trigger_potential}. Tổng mưa: {total_rain_mm:.0f}mm ({rain_days_count} ngày mưa)."
        }

    def analyze_rainfall_displacement_correlation(
        self,
        gnss_data: List[Dict[str, Any]],
        rain_data: List[Dict[str, Any]],
        window_days: float = 30.0,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        _ = window_days
        result = {"available": False, "model": "slide_model", "message": ""}
        if not gnss_data or not rain_data or len(gnss_data) < 2 or len(rain_data) < 2:
            result["message"] = "Cần cả dữ liệu GNSS và mưa để phân tích tương quan."
            return result

        try:
            cfg = config or {}
            ls_cfg = cfg.get("SlideModel", {}) if isinstance(cfg, dict) else {}
            short_half_life_days = max(float(ls_cfg.get("short_half_life_days", 1.5)), 0.1)
            long_half_life_days = max(float(ls_cfg.get("long_half_life_days", 7.0)), 0.2)
            short_weight = min(max(float(ls_cfg.get("short_weight", 0.7)), 0.0), 1.0)
            max_lag_days = min(max(int(ls_cfg.get("max_lag_days", 3)), 0), 10)

            gnss_daily, daily_rain, common_days = self._aggregate_gnss_and_rain_daily(
                sorted(gnss_data, key=lambda x: x["timestamp"]),
                sorted(rain_data, key=lambda x: x["timestamp"])
            )
            if len(common_days) < 3:
                result["message"] = f"Chỉ có {len(common_days)} ngày chung giữa GNSS và mưa — cần ít nhất 3."
                return result

            cum_disp, daily_disp_inc, cum_disp_legacy = self._compute_daily_displacements(common_days, gnss_daily)
            rain_arr = np.array([float(daily_rain.get(day, 0.0)) for day in common_days], dtype=float)
            disp_rate_arr = np.array(daily_disp_inc, dtype=float)

            slide_model_index = self._compute_slide_model_index(rain_arr, short_half_life_days, long_half_life_days, short_weight)
            best_lag, best_corr, best_pairs, lag_scan_results = self._scan_lag_correlation(slide_model_index, disp_rate_arr, max_lag_days)
            if best_pairs < 3:
                result["message"] = f"Biến thiên dữ liệu quá thấp ({best_pairs} cặp hợp lệ), chưa đủ để ước lượng Slide model tin cậy."
                return result

            slope, intercept, r2, correlation, strength, assessment, trigger_potential = self._fit_lag_regression(
                slide_model_index, disp_rate_arr, best_lag, best_corr
            )

            total_rain_mm = float(np.sum(rain_arr))
            total_disp_mm = float(np.sum(disp_rate_arr))
            rain_days_count = int(np.sum(rain_arr > 0.2))
            sensitivity_mm_per_mm = (total_disp_mm / total_rain_mm) if total_rain_mm > 1.0 else 0.0
            top_cwd_events = self._compute_cwd_events(common_days, rain_arr, disp_rate_arr)

            rain_mask = rain_arr > 0.2
            disp_during_rain = float(np.mean(disp_rate_arr[rain_mask])) if np.any(rain_mask) else 0.0
            disp_during_dry = float(np.mean(disp_rate_arr[~rain_mask])) if np.any(~rain_mask) else 0.0
            rain_accel_ratio = (disp_during_rain / disp_during_dry) if disp_during_dry > 0.001 else 0.0

            top_peak_events = self._compute_peak_events(common_days, rain_arr, disp_rate_arr, slide_model_index, best_lag)
            risk_messages, combined_risk_message = self._build_risk_messages(
                trigger_potential, rain_accel_ratio, top_cwd_events, sensitivity_mm_per_mm, assessment
            )

            max_rain_idx = int(np.argmax(rain_arr)) if len(rain_arr) > 0 else 0
            max_disp_idx = int(np.argmax(disp_rate_arr)) if len(disp_rate_arr) > 0 else 0

            result.update(self._build_rainfall_result(
                correlation, strength, assessment, common_days, best_lag, r2, slope, intercept,
                trigger_potential, short_half_life_days, long_half_life_days, short_weight, max_lag_days,
                lag_scan_results, total_rain_mm, rain_arr, max_rain_idx, rain_days_count, slide_model_index,
                total_disp_mm, disp_rate_arr, max_disp_idx, disp_during_rain, disp_during_dry,
                rain_accel_ratio, sensitivity_mm_per_mm, top_cwd_events, top_peak_events,
                risk_messages, combined_risk_message
            ))
            return result
        except Exception as e:
            logger.exception(f"Error in analyze_rainfall_displacement_correlation: {e}")
            result["message"] = f"Lỗi phân tích tương quan: {e}"
            return result
