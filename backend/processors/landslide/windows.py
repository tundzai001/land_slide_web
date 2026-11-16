"""WindowAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class WindowAnalysisMixin:
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
                "station_id": station_id,
                "configured_windows": windows,
                "windows": window_results,
                "acceleration_alert": acceleration_alert
            }

        except Exception as e:
            logger.error(f"Error in calendar interval analysis: {e}", exc_info=True)
            return {"available": False, "message": f"Lỗi: {str(e)}"}
