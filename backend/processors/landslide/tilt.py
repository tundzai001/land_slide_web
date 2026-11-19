"""TiltAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class TiltAnalysisMixin:
    def _extract_imu_roll_pitch(self, sorted_data: list) -> tuple[list, list, list]:
        rolls, pitches, timestamps = [], [], []
        for point in sorted_data:
            data = point.get("data", {})
            roll = data.get("roll", data.get("raw_roll", None))
            pitch = data.get("pitch", data.get("raw_pitch", None))
            if roll is not None and pitch is not None:
                rolls.append(float(roll))
                pitches.append(float(pitch))
                timestamps.append(point["timestamp"])
        return rolls, pitches, timestamps

    def _compute_tilt_trend(self, tilts: list) -> str:
        if len(tilts) < 5:
            return "stable"
        x = np.arange(len(tilts))
        slope = np.polyfit(x, np.array(tilts), 1)[0]
        if slope > 0.001:
            return "accelerating"
        if slope < -0.001:
            return "decelerating"
        return "stable"

    def _evaluate_tilt_risk(self, total_tilt_change: float, avg_rate_deg_per_day: float, duration_days: float, trend: str) -> tuple[str, str]:
        if total_tilt_change >= 10.0 or avg_rate_deg_per_day >= 1.0:
            return "EXTREME", f"🚨 NGUY HIỂM: Góc nghiêng thay đổi {total_tilt_change:.1f}° trong {duration_days:.0f} ngày"
        if total_tilt_change >= 5.0 or avg_rate_deg_per_day >= 0.5:
            return "HIGH", f"⚠️ Cao: Nghiêng {total_tilt_change:.1f}° ({avg_rate_deg_per_day:.2f}°/ngày)"
        if total_tilt_change >= 2.0 or avg_rate_deg_per_day >= 0.1:
            return "MEDIUM", f"⚠️ Trung bình: Nghiêng dần {total_tilt_change:.1f}°"
        if trend == "accelerating":
            return "MEDIUM", f"⚠️ Chú ý: Tốc độ nghiêng đang tăng ({total_tilt_change:.2f}°)"
        return "LOW", f"✅ Ổn định: Thay đổi {total_tilt_change:.2f}°"

    def _build_tilt_time_series(self, timestamps: list, rolls: list, pitches: list, window_days: float) -> dict:
        from collections import OrderedDict
        daily_data = OrderedDict()
        if window_days < 1 / 24:
            fmt = "%H:%M:%S"
        elif window_days <= 1:
            fmt = "%H:%M"
        elif window_days <= 7:
            fmt = "%d/%m %H:00"
        else:
            fmt = "%d/%m"

        for ts, r, p in zip(timestamps, rolls, pitches):
            day_key = datetime.fromtimestamp(ts).strftime(fmt)
            daily_data.setdefault(day_key, {"rolls": [], "pitches": []})
            daily_data[day_key]["rolls"].append(r)
            daily_data[day_key]["pitches"].append(p)

        return {
            "raw_timestamps": timestamps,
            "labels": list(daily_data.keys()),
            "rolls": [round(sum(v["rolls"]) / len(v["rolls"]), 2) for v in daily_data.values()],
            "pitches": [round(sum(v["pitches"]) / len(v["pitches"]), 2) for v in daily_data.values()]
        }

    def analyze_long_term_tilt(
        self,
        station_id: int,
        historical_data: List[Dict[str, Any]],
        window_days: float = 30.0
    ) -> Dict[str, Any]:
        _ = station_id
        try:
            if not historical_data or len(historical_data) < 2:
                return {"status": "insufficient_data", "message": "Cần ít nhất 2 điểm dữ liệu IMU."}

            sorted_data = sorted(historical_data, key=lambda x: x["timestamp"])
            rolls, pitches, timestamps = self._extract_imu_roll_pitch(sorted_data)
            if len(rolls) < 2:
                return {"status": "insufficient_data", "message": "Không đủ dữ liệu IMU hợp lệ."}

            duration_days = max(0.00001, (timestamps[-1] - timestamps[0]) / 86400.0)
            roll_change = rolls[-1] - rolls[0]
            pitch_change = pitches[-1] - pitches[0]
            total_tilt_change = math.sqrt(roll_change**2 + pitch_change**2)
            avg_rate_deg_per_day = total_tilt_change / duration_days if duration_days > 0 else 0
            max_roll = max(abs(r) for r in rolls)
            max_pitch = max(abs(p) for p in pitches)

            tilts = [math.sqrt(r**2 + p**2) for r, p in zip(rolls, pitches)]
            trend = self._compute_tilt_trend(tilts)
            risk_level, warning = self._evaluate_tilt_risk(total_tilt_change, avg_rate_deg_per_day, duration_days, trend)
            time_series = self._build_tilt_time_series(timestamps, rolls, pitches, window_days)

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
                    "risk_level": risk_level,
                    "warning_message": warning,
                    "time_series": time_series,
                    "data_points": len(rolls),
                    "duration_days": round(duration_days, 1)
                }
            }
        except Exception as e:
            logger.exception(f"Error in analyze_long_term_tilt: {e}")
            return {"status": "error", "message": str(e)}
