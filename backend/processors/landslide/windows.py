"""WindowAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class WindowAnalysisMixin:
    def _build_time_intervals(self, latest_ts: float, latest_dt: datetime) -> list[dict]:
        from datetime import timedelta
        yesterday_start = latest_ts - 86400
        days_since_monday = latest_dt.weekday()
        week_start_dt = latest_dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
        month_start_dt = latest_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return [
            {"label": "24h qua", "cutoff": yesterday_start, "type": "day"},
            {"label": f"Tuần này ({days_since_monday + 1}/7 ngày)", "cutoff": week_start_dt.timestamp(), "type": "week"},
            {"label": f"Tháng {latest_dt.month} ({latest_dt.day} ngày)", "cutoff": month_start_dt.timestamp(), "type": "month"}
        ]

    def _compute_single_window(self, interval: dict, sorted_data: list, min_reliable_duration_days: float) -> dict:
        cutoff = interval["cutoff"]
        window_data = [p for p in sorted_data if p["timestamp"] >= cutoff]
        if len(window_data) < 2:
            return {"window_days": interval["type"], "label": interval["label"], "status": "insufficient_data", "velocity_mm_day": None, "trend": None}

        first_window, last_window = window_data[0]["data"], window_data[-1]["data"]
        de = last_window.get("pos_e", 0) - first_window.get("pos_e", 0)
        dn = last_window.get("pos_n", 0) - first_window.get("pos_n", 0)
        du = last_window.get("pos_u", 0) - first_window.get("pos_u", 0)
        net_displacement_mm = math.sqrt(de**2 + dn**2 + du**2) * 1000

        duration = (window_data[-1]["timestamp"] - window_data[0]["timestamp"]) / 86400.0
        vel_mm_day = net_displacement_mm / duration if duration > 0 else 0
        trend = self._detect_displacement_trend(window_data)
        velocity_reliable = self._is_reliable_observation_window(duration, len(window_data), min_reliable_duration_days)
        reliability_message = self._build_gnss_preliminary_message(duration, len(window_data), min_reliable_duration_days)

        return {
            "window_days": interval["type"], "label": interval["label"],
            "status": "success" if velocity_reliable else "preliminary",
            "duration_days": round(duration, 4), "velocity_mm_day": round(vel_mm_day, 4),
            "velocity_mm_year": round(vel_mm_day * 365, 2), "displacement_mm": round(net_displacement_mm, 2),
            "displacement_basis": "first_last_point", "velocity_reliable": velocity_reliable,
            "reliability_message": reliability_message, "min_reliable_duration_days": round(min_reliable_duration_days, 4),
            "min_reliable_points": 3, "data_points": len(window_data), "trend": trend
        }

    def _check_acceleration_alert(self, window_results: list) -> dict | None:
        valid_windows = [
            w for w in window_results
            if w.get("status") == "success" and w.get("velocity_reliable") and w.get("velocity_mm_day") is not None
        ]
        if len(valid_windows) < 2:
            return None
        short_window = next((w for w in valid_windows if w["window_days"] == "day"), valid_windows[0])
        long_window = valid_windows[-1]
        if short_window != long_window and long_window["velocity_mm_day"] > 0:
            ratio = short_window["velocity_mm_day"] / long_window["velocity_mm_day"]
            if ratio > 3.0:
                return {
                    "type": "rapid_acceleration",
                    "message": f"⚠️ CẢNH BÁO: Tốc độ hiện tại ({short_window['label']}) gấp {ratio:.1f}x so với xu hướng dài hạn ({long_window['label']})",
                    "ratio": round(ratio, 2)
                }
        return None

    def analyze_multi_window(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        config: Dict,
        windows: List[int] = None
    ) -> Dict[str, Any]:
        _ = (station_id, windows)
        if not historical_data or len(historical_data) < 2:
            return {"available": False, "message": "Không đủ dữ liệu."}

        sorted_data = sorted(historical_data, key=lambda x: x["timestamp"])
        latest_ts = sorted_data[-1]["timestamp"]
        latest_dt = datetime.fromtimestamp(latest_ts)
        min_reliable_duration_days = self._get_gnss_min_reliable_window_days(config)

        intervals = self._build_time_intervals(latest_ts, latest_dt)
        window_results = [self._compute_single_window(inv, sorted_data, min_reliable_duration_days) for inv in intervals]
        acceleration_alert = self._check_acceleration_alert(window_results)

        return {
            "available": True,
            "windows": window_results,
            "acceleration_alert": acceleration_alert,
            "analyzed_at": latest_ts
        }
