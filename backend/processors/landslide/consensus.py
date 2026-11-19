"""ConsensusAnalysisMixin for cross-sensor landslide analysis."""

from __future__ import annotations

from .helpers import Any, Dict, List, Optional, OrderedDict, datetime, defaultdict, deque, logger, math, np, time


def _extract_gnss_state(gnss_result: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(gnss_result and gnss_result.get("status") == "success")
    analysis = gnss_result.get("analysis", {}) if ok else {}
    risk = (gnss_result.get("risk_level", "LOW") or "LOW") if ok else "LOW"
    return {
        "ok": ok,
        "reliable": analysis.get("velocity_reliable", True),
        "trend": analysis.get("trend", "stable"),
        "risk": risk,
        "displacement_mm": float(analysis.get("total_displacement_mm", 0.0)),
        "duration_days": float(analysis.get("duration_days", 0.0)),
        "alerting": ok and risk not in ("LOW", "INFO"),
    }


def _extract_imu_state(imu_result: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(imu_result and imu_result.get("status") == "success")
    analysis = imu_result.get("analysis", {}) if ok else {}
    risk = (imu_result.get("risk_level", "LOW") or "LOW") if ok else "LOW"
    return {
        "ok": ok,
        "trend": analysis.get("trend", "stable"),
        "risk": risk,
        "tilt_change": float(analysis.get("total_tilt_change_deg", 0.0)),
        "alerting": ok and risk not in ("LOW",),
    }


def _extract_rain_state(rain_corr_result: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(rain_corr_result and rain_corr_result.get("available") is True)
    r = float(rain_corr_result.get("correlation", 0.0)) if ok else 0.0
    return {
        "ok": ok,
        "r": r,
        "supporting": ok and abs(r) >= 0.4,
    }


def _compute_trend_agreement(gnss_ok: bool, imu_ok: bool, t1: str, t2: str) -> Optional[str]:
    if not (gnss_ok and imu_ok):
        return None
    g_tr = t1 or "stable"
    i_tr = t2 or "stable"
    if g_tr == i_tr:
        return "full"
    if (g_tr == "accelerating" and i_tr == "stable") or (g_tr == "stable" and i_tr == "accelerating"):
        return "partial"
    if (g_tr == "accelerating" and i_tr == "decelerating") or (g_tr == "decelerating" and i_tr == "accelerating"):
        return "conflict"
    return "full"


def _decide_alerting_consensus(
    gnss: Dict[str, Any],
    imu: Dict[str, Any],
    trend_agreement: Optional[str]
) -> Optional[tuple[str, str, List[str], List[str], List[str]]]:
    both_alerting = gnss["alerting"] and imu["alerting"]
    if both_alerting and trend_agreement in ("full", "partial"):
        msg = (
            f"GNSS và IMU đồng thuận: GNSS ghi nhận dịch chuyển {gnss['displacement_mm']:.1f} mm, "
            f"IMU ghi nhận nghiêng {imu['tilt_change']:.2f}° — cùng xu hướng '{gnss['trend']}'."
        )
        return "STRONG", "HIGH", ["gnss", "imu"], [], [msg]

    if both_alerting and trend_agreement == "conflict":
        msg = (
            f"GNSS xu hướng '{gnss['trend']}' nhưng IMU xu hướng '{imu['trend']}'. "
            "Hai cảm biến chỉ về hướng khác nhau — hãy kiểm tra lại cài đặt và vị trí."
        )
        return "CONFLICT", "LOW", [], ["gnss", "imu"], [msg]

    if gnss["alerting"] and not imu["ok"]:
        msg = f"GNSS ghi nhận dịch chuyển {gnss['displacement_mm']:.1f} mm nhưng chưa có dữ liệu IMU để xác nhận."
        return "PARTIAL", "MEDIUM", ["gnss"], [], [msg]

    if imu["alerting"] and not gnss["ok"]:
        msg = f"IMU ghi nhận nghiêng {imu['tilt_change']:.2f}° nhưng chưa có dữ liệu GNSS để xác nhận dịch chuyển."
        return "PARTIAL", "MEDIUM", ["imu"], [], [msg]

    return None


def _decide_consensus(
    sensors_with_data: List[str],
    gnss: Dict[str, Any],
    imu: Dict[str, Any],
    trend_agreement: Optional[str],
) -> tuple[str, str, List[str], List[str], List[str]]:
    if not sensors_with_data:
        return "UNAVAILABLE", "UNKNOWN", [], [], ["Chưa có dữ liệu từ cảm biến nào để đánh giá."]

    res = _decide_alerting_consensus(gnss, imu, trend_agreement)
    if res is not None:
        return res

    one_alerting = gnss["alerting"] or imu["alerting"]
    if one_alerting:
        corr = ["gnss"] if gnss["alerting"] else ["imu"]
        alerting_name = "GNSS" if gnss["alerting"] else "IMU"
        other_name = "IMU" if gnss["alerting"] else "GNSS"
        msg = f"{alerting_name} ghi nhận bất thường nhưng {other_name} chưa xác nhận. Cần thêm dữ liệu từ {other_name} để kết luận."
        return "PARTIAL", "MEDIUM", corr, [], [msg]

    return "NONE", "STABLE", [], [], ["Không có cảm biến nào ghi nhận bất thường đáng kể trong giai đoạn này."]


def _append_rain_and_gnss_notes(
    notes: List[str],
    corroborating: List[str],
    rain: Dict[str, Any],
    rain_corr_result: Dict[str, Any],
    gnss: Dict[str, Any],
    one_alerting: bool,
) -> None:
    if rain["supporting"] and one_alerting:
        corroborating.append("rain")
        strength = rain_corr_result.get("strength", "")
        notes.append(f"Mưa tương quan rõ với dịch chuyển (r={rain['r']:.2f} — {strength}) — có thể là nguyên nhân kích hoạt.")
    elif rain["ok"] and not rain["supporting"] and one_alerting:
        notes.append(f"Mưa không tương quan rõ (r={rain['r']:.2f}) — nguyên nhân có thể không phải mưa.")

    if gnss["ok"] and not gnss["reliable"]:
        mins = gnss["duration_days"] * 1440
        notes.append(
            f"Lưu ý: Vận tốc GNSS chưa đủ thời lượng quan sát ({mins:.0f} phút). "
            "Tổng chuyển dịch đầu-cuối vẫn hợp lệ nhưng vận tốc chỉ mang tính tham khảo."
        )


class ConsensusAnalysisMixin:
    def analyze_cross_sensor_consensus(
        self,
        gnss_result: Dict[str, Any],
        imu_result: Dict[str, Any],
        rain_corr_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Đánh giá mức độ đồng thuận giữa các model cảm biến dài hạn.
        """
        try:
            gnss = _extract_gnss_state(gnss_result)
            imu = _extract_imu_state(imu_result)
            rain = _extract_rain_state(rain_corr_result)

            sensors_with_data: List[str] = []
            sensors_alerting: List[str] = []
            if gnss["ok"]:
                sensors_with_data.append("gnss")
                if gnss["alerting"]:
                    sensors_alerting.append("gnss")
            if imu["ok"]:
                sensors_with_data.append("imu")
                if imu["alerting"]:
                    sensors_alerting.append("imu")
            if rain["ok"]:
                sensors_with_data.append("rain")

            trend_agreement = _compute_trend_agreement(gnss["ok"], imu["ok"], gnss["trend"], imu["trend"])
            level, rel, corr, confl, notes = _decide_consensus(sensors_with_data, gnss, imu, trend_agreement)

            one_alerting = gnss["alerting"] or imu["alerting"]
            _append_rain_and_gnss_notes(notes, corr, rain, rain_corr_result, gnss, one_alerting)

            summary_vn = {
                "STRONG": "Đồng thuận mạnh — nhiều cảm biến xác nhận",
                "PARTIAL": "Đồng thuận một phần — cần thêm dữ liệu để kết luận",
                "CONFLICT": "Mâu thuẫn cảm biến — hãy kiểm tra lại",
                "NONE": "Không có bất thường — theo dõi bình thường",
                "UNAVAILABLE": "Chưa có đủ dữ liệu để đánh giá",
            }

            return {
                "available": True,
                "consensus_level": level,
                "reliability_flag": rel,
                "summary": summary_vn.get(level, level),
                "sensors_with_data": sensors_with_data,
                "sensors_alerting": sensors_alerting,
                "sensors_corroborating": corr,
                "sensors_conflicting": confl,
                "trend_agreement": trend_agreement,
                "rain_supporting": rain["supporting"],
                "rain_r": round(rain["r"], 3) if rain["ok"] else None,
                "notes": notes,
            }

        except Exception as e:
            logger.exception(f"Error in cross-sensor consensus: {e}")
            return {"available": False, "message": f"Lỗi: {str(e)}"}
