"""ConsensusAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


class ConsensusAnalysisMixin:
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
