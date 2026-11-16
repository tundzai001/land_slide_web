"""TiltAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class TiltAnalysisMixin:
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
        _ = station_id
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
            logger.exception(f"Error in long-term tilt analysis: {e}")
            return {"status": "error", "message": f"Lỗi: {str(e)}"}
