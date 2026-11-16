"""Station long-term risk and GNSS rollup query routes."""

import asyncio
import copy
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_config_db, get_data_db
from ...models import config as model_config
from ...models import data as model_data
from ...shared.station_policy import get_offline_threshold
from ..gnss_monitoring.risk import map_gnss_daily_risk
from ..gnss_monitoring.rollup import _utc_day_start

router = APIRouter(tags=["Stations"])
logger = logging.getLogger(__name__)

_LONG_TERM_ANALYSIS_SEMAPHORE = asyncio.Semaphore(2)
_LONG_TERM_ANALYSIS_CACHE: Dict[tuple, tuple[float, Dict[str, Any]]] = {}
_LONG_TERM_ANALYSIS_CACHE_TTL_SECONDS = 30.0

async def _calculate_station_risk_assessment(
    db_data: AsyncSession,
    station_id: int,
    station_config: Optional[Dict[str, Any]] = None
) -> Dict:
    """Build risk assessment while retaining unresolved rows across restarts.

    TTL controls the ``stale`` marker only; resolution remains an explicit
    durable state transition (or a verified recovery signal).
    """
    try:
        now_ts = int(time.time())
        alerting_cfg = (station_config or {}).get("alerting", {}) if station_config else {}
        if alerting_cfg.get("enabled", (station_config or {}).get("alerting_enabled", True)) is False:
            return {"overall_risk": "LOW", "active_alerts": []}

        gnss_offline = get_offline_threshold(station_config or {}, 'gnss')
        rain_offline = get_offline_threshold(station_config or {}, 'rain')
        water_offline = get_offline_threshold(station_config or {}, 'water')
        imu_offline = get_offline_threshold(station_config or {}, 'imu')

        # TTL chỉ gắn nhãn stale. Không được lọc bỏ unresolved alert vì trạng
        # thái này phải tồn tại qua restart cho tới khi có resolve rõ ràng.
        default_ttl = {
            'gnss_velocity': max(90, gnss_offline * 2),
            'rainfall': max(120, rain_offline * 2),
            'water_level': max(120, water_offline * 2),
            'tilt': max(300, imu_offline),
            'tilt_warning': max(300, imu_offline),
            'tilt_critical': max(300, imu_offline),
            'shock': max(300, imu_offline),
        }
        ttl_cfg = (station_config or {}).get('alert_ttl_seconds', {}) if station_config else {}
        alert_ttl = {
            'gnss_velocity': int(ttl_cfg.get('gnss_velocity', default_ttl['gnss_velocity'])),
            'rainfall': int(ttl_cfg.get('rainfall', default_ttl['rainfall'])),
            'water_level': int(ttl_cfg.get('water_level', default_ttl['water_level'])),
            'tilt': int(ttl_cfg.get('tilt', default_ttl['tilt'])),
            'tilt_warning': int(ttl_cfg.get('tilt_warning', default_ttl['tilt_warning'])),
            'tilt_critical': int(ttl_cfg.get('tilt_critical', default_ttl['tilt_critical'])),
            'shock': int(ttl_cfg.get('shock', default_ttl['shock'])),
        }

        result = await db_data.execute(
            select(model_data.Alert).where(
                and_(
                    model_data.Alert.station_id == station_id,
                    model_data.Alert.is_resolved == False
                )
            )
        )
        alerts = result.scalars().all()

        alert_rows = []
        for a in alerts:
            ttl = alert_ttl.get(a.category, 180)
            age_seconds = max(0, now_ts - int(a.timestamp or 0))
            alert_rows.append((a, age_seconds > ttl, age_seconds))

        # Dùng logic max-level giống mqtt_bridge._get_station_active_alert_summary()
        # để WebSocket và REST API trả về cùng giá trị risk_level.
        priority = {
            "EXTREME": 5,
            "CRITICAL": 4,
            "HIGH": 3,
            "WARNING": 2,
            "MEDIUM": 1,
            "LOW": 0,
        }
        overall_risk = "LOW"
        highest_score = -1
        for a, _is_stale, _age_seconds in alert_rows:
            level = str(a.level or "").upper()
            if a.category in ('tilt_warning', 'tilt_critical', 'shock', 'tilt') and level == 'WARNING':
                level = 'CRITICAL'
            score = priority.get(level, 0)
            if score > highest_score:
                overall_risk = level
                highest_score = score

        if overall_risk not in priority:
            overall_risk = "LOW"

        return {
            "overall_risk": overall_risk,
            "active_alerts": [
                {
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "timestamp": a.timestamp,
                    "stale": is_stale,
                    "age_seconds": age_seconds,
                }
                for a, is_stale, age_seconds in alert_rows
            ],
            "stale_alerts": [
                {
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "timestamp": a.timestamp,
                    "stale": True,
                    "age_seconds": age_seconds,
                }
                for a, is_stale, age_seconds in alert_rows
                if is_stale
            ],
            "fresh_alerts": [
                {
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "timestamp": a.timestamp,
                    "stale": False,
                    "age_seconds": age_seconds,
                }
                for a, is_stale, age_seconds in alert_rows
                if not is_stale
            ],
        }
    except Exception as e:
        logger.exception(f"Error calculating risk: {e}")
        return {"overall_risk": "UNKNOWN", "active_alerts": []}


@router.get("/api/stations/{station_id}/long-term-analysis", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 422: {"description": "Unprocessable Entity"}, 500: {"description": "Internal Server Error"}})
async def get_long_term_analysis(
    station_id: int,
    days: float = 30.0,
    include_correlation: bool = False,
    correlation_model: str = "slide_model",
    db_config: AsyncSession = Depends(get_config_db),
    db_data: AsyncSession = Depends(get_data_db)
):
    """
    Phân tích dài hạn cho GNSS displacement + IMU tilt.
    Rainfall correlation chỉ chạy khi include_correlation=True.
    correlation_model hiện hỗ trợ: slide_model.
    + Multi-window analysis + Inverse Velocity (Fukuzono)
    """
    try:
        try:
            days = float(days)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="days must be a number")
        if not math.isfinite(days) or days < (1 / 24) or days > 365:
            raise HTTPException(status_code=422, detail="days must be between 1 hour and 365 days")

        model_key = str(correlation_model or "slide_model").strip().lower()
        if include_correlation and model_key != "slide_model":
            raise HTTPException(status_code=400, detail="Unsupported correlation_model. Use slide_model.")

        cache_key = (int(station_id), round(days, 6), bool(include_correlation), model_key)
        cached = _LONG_TERM_ANALYSIS_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _LONG_TERM_ANALYSIS_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])

        async def _run_analysis(func, **kwargs):
            async with _LONG_TERM_ANALYSIS_SEMAPHORE:
                return await asyncio.to_thread(func, **kwargs)

        def is_gnss_analysis_point(data: dict) -> bool:
            if not isinstance(data, dict):
                return False
            return all(key in data for key in ("pos_e", "pos_n", "pos_u"))

        def _trend_from_velocity_series(values: List[float]) -> str:
            clean = [float(v or 0.0) for v in values]
            if len(clean) < 2:
                return "stable"
            first_v = clean[0]
            last_v = clean[-1]
            if abs(first_v) < 1e-6 and abs(last_v) < 1e-6:
                return "stable"
            if abs(first_v) < 1e-6:
                return "accelerating" if last_v > 0 else "stable"
            ratio = (last_v - first_v) / (abs(first_v) + 1e-6)
            if ratio > 0.1:
                return "accelerating"
            if ratio < -0.1:
                return "decelerating"
            return "stable"

        def _severity(level: str) -> int:
            order = {
                "INFO": 0,
                "LOW": 1,
                "MEDIUM": 2,
                "HIGH": 3,
                "CRITICAL": 4,
                "EXTREME": 5,
            }
            return order.get(str(level or "").upper(), 0)

        def _build_gnss_analysis_from_daily_summaries(
            daily_rows: List[model_data.GnssDailySummary],
            station_cfg: Dict[str, Any]
        ) -> Dict[str, Any]:
            if not daily_rows:
                return {
                    "status": "insufficient_data",
                    "message": "Không có GNSS daily summary trong khoảng thời gian yêu cầu."
                }

            rows = sorted(daily_rows, key=lambda r: int(r.day_start_ts or 0))
            total_displacement_mm = float(sum(float(r.net_displacement_mm or 0.0) for r in rows))
            duration_seconds = int(sum(int(r.duration_seconds or 0) for r in rows))
            duration_days = duration_seconds / 86400.0 if duration_seconds > 0 else float(len(rows))
            if duration_days <= 0:
                duration_days = float(len(rows))

            velocity_mm_per_day = total_displacement_mm / duration_days if duration_days > 0 else 0.0
            velocity_mm_per_second = velocity_mm_per_day / 86400.0
            velocity_mm_per_year = velocity_mm_per_day * 365.0

            classification = analyzer._classify_velocity_extended(
                velocity_mm_per_second,
                velocity_mm_per_day,
                velocity_mm_per_year,
                station_cfg or {}
            )

            min_reliable_duration_days = analyzer._get_gnss_min_reliable_window_days(station_cfg or {})
            data_points_used = int(sum(int(r.sample_count or 0) for r in rows))
            reliability_points = data_points_used if data_points_used > 0 else len(rows)
            velocity_reliable = analyzer._is_reliable_observation_window(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )
            reliability_message = analyzer._build_gnss_preliminary_message(
                duration_days,
                reliability_points,
                min_reliable_duration_days
            )

            trend = _trend_from_velocity_series([float(r.velocity_mm_day or 0.0) for r in rows])
            derived_risk = map_gnss_daily_risk(classification)
            max_row_risk = "LOW"
            for r in rows:
                row_risk = str(r.risk_level or "LOW").upper()
                if _severity(row_risk) > _severity(max_row_risk):
                    max_row_risk = row_risk
            risk_level = max_row_risk if _severity(max_row_risk) >= _severity(derived_risk) else derived_risk

            if risk_level in ("CRITICAL", "EXTREME"):
                warning_message = f"🚨 Cảnh báo cao từ GNSS daily summary ({classification})."
            elif risk_level == "HIGH":
                warning_message = f"⚠️ Cảnh báo: vận tốc có xu hướng tăng ({classification})."
            elif risk_level == "MEDIUM":
                warning_message = f"Cần theo dõi: GNSS có chuyển dịch mức trung bình ({classification})."
            else:
                warning_message = f"An toàn tương đối theo GNSS daily summary ({classification})."

            if not velocity_reliable:
                warning_message = reliability_message
                risk_level = "INFO"

            labels = []
            displacement_series = []
            cumulative_disp = 0.0
            for row in rows:
                labels.append(datetime.fromtimestamp(int(row.day_start_ts)).strftime('%d/%m'))
                cumulative_disp += float(row.net_displacement_mm or 0.0)
                displacement_series.append(round(cumulative_disp, 2))

            return {
                "status": "success",
                "source": "daily_summary_rollup",
                "analysis": {
                    "total_displacement_mm": round(total_displacement_mm, 2),
                    "net_displacement_mm": round(total_displacement_mm, 2),
                    "regression_displacement_mm": round(total_displacement_mm, 2),
                    "velocity_mm_year": round(velocity_mm_per_year, 2),
                    "velocity_ci_95": 0.0,
                    "velocity_mm_day": round(velocity_mm_per_day, 4),
                    "velocity_mm_second": round(velocity_mm_per_second, 6),
                    "regression_velocity_mm_year": round(velocity_mm_per_year, 2),
                    "regression_velocity_mm_day": round(velocity_mm_per_day, 4),
                    "regression_velocity_mm_second": round(velocity_mm_per_second, 6),
                    "classification": classification,
                    "trend": trend,
                    "cusum_change": False,
                    "cusum_message": "Daily summary mode: không chạy CUSUM trên raw sample.",
                    "displacement_basis": "daily_rollup_sum",
                    "velocity_reliable": velocity_reliable,
                    "reliability_message": reliability_message,
                    "min_reliable_duration_days": round(min_reliable_duration_days, 4),
                    "min_reliable_points": 3,
                    "duration_days": round(duration_days, 4),
                    "data_points_used": data_points_used,
                    "summary_days_used": len(rows),
                    "start_date": datetime.fromtimestamp(int(rows[0].day_start_ts)).isoformat(),
                    "end_date": datetime.fromtimestamp(int(rows[-1].day_end_ts)).isoformat()
                },
                "risk_level": risk_level,
                "warning_message": warning_message,
                "inverse_velocity": {
                    "available": False,
                    "message": "Daily summary mode: inverse velocity cần raw GNSS chi tiết."
                },
                "time_series": {
                    "labels": labels,
                    "displacement": displacement_series,
                    "e": [],
                    "n": [],
                    "u": []
                }
            }

        # 1. Lấy config trạm
        station_result = await db_config.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = station_result.scalar_one_or_none()

        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        # Lấy window lớn nhất cho multi-window (tối thiểu = days, mở rộng 90 ngày)
        max_window = max(days, 90)
        cutoff_time = int(time.time() - (max_window * 86400))
        cutoff_requested = int(time.time() - (days * 86400))
        raw_gnss_cutoff = max(cutoff_time, int(time.time() - 86400))

        # 2. Lấy dữ liệu GNSS (mở rộng window cho multi-window)
        gnss_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "gnss",
                    model_data.SensorData.timestamp >= raw_gnss_cutoff
                )
            )
            .order_by(model_data.SensorData.timestamp.desc())
            .limit(10000)
        )
        gnss_data = list(reversed(gnss_result.scalars().all()))

        # 2b. Lấy GNSS daily summary để fallback khi raw đã purge
        daily_summary_result = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_start_ts >= _utc_day_start(cutoff_time),
                    model_data.GnssDailySummary.status == "success"
                )
            )
            .order_by(model_data.GnssDailySummary.day_start_ts.asc())
        )
        daily_gnss_full = daily_summary_result.scalars().all()
        daily_gnss_requested = [
            d for d in daily_gnss_full
            if int(d.day_start_ts or 0) >= _utc_day_start(cutoff_requested)
        ]

        # 3. Lấy dữ liệu IMU
        imu_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "imu",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        imu_data = imu_result.scalars().all()

        # 4. Lấy dữ liệu mưa (cho rainfall-displacement correlation)
        rain_result = await db_data.execute(
            select(model_data.SensorData)
            .where(
                and_(
                    model_data.SensorData.station_id == station_id,
                    model_data.SensorData.sensor_type == "rain",
                    model_data.SensorData.timestamp >= cutoff_requested
                )
            )
            .order_by(model_data.SensorData.timestamp.asc())
        )
        rain_data = rain_result.scalars().all()

        model_key = str(correlation_model or "slide_model").strip().lower()
        result = {
            "station_id": station_id,
            "days": days,
            "correlation_model": model_key
        }

        # Chuyển sang list dict chung
        historical_gnss_full = [
            {"timestamp": d.timestamp, "data": d.data}
            for d in gnss_data
            if is_gnss_analysis_point(d.data)
        ]
        historical_gnss_requested = [p for p in historical_gnss_full if p['timestamp'] >= cutoff_requested]
        if days > 1 and daily_gnss_requested:
            historical_gnss_requested = []
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_gnss_requested) < 2 and len(historical_gnss_full) >= 2 and days <= 1:
            historical_gnss_requested = historical_gnss_full[-20:]

        # 5. Phân tích GNSS (trên window requested)
        if len(historical_gnss_requested) >= 2:
            gnss_analysis = await _run_analysis(analyzer.analyze_long_term_velocity,
                station_id=station_id,
                historical_data=historical_gnss_requested,
                config=station.config or {},
                window_days=days
            )

            # Tạo time-series GNSS (trung bình theo ngày/giờ) cho chart & 3D
            if gnss_analysis.get("status") == "success":
                from collections import OrderedDict
                from datetime import datetime as dt
                daily_gnss = OrderedDict()

                if days < 1/24:    fmt = '%H:%M:%S'
                elif days <= 1:    fmt = '%H:%M'
                elif days <= 7:    fmt = '%d/%m %H:00'
                else:              fmt = '%d/%m'

                first_e, first_n, first_u = None, None, None

                for point in historical_gnss_requested:
                    day_key = dt.fromtimestamp(point['timestamp']).strftime(fmt)
                    data = point['data']

                    disp = data.get('total_displacement_mm', data.get('displacement_mm', 0))
                    e = data.get('pos_e', 0)
                    n = data.get('pos_n', 0)
                    u = data.get('pos_u', 0)

                    if first_e is None:
                        first_e, first_n, first_u = e, n, u

                    if day_key not in daily_gnss:
                        daily_gnss[day_key] = {'disp': [], 'e': [], 'n': [], 'u': []}

                    daily_gnss[day_key]['disp'].append(float(disp))
                    delta_e_mm = (e - first_e) * 1000
                    delta_n_mm = (n - first_n) * 1000
                    delta_u_mm = (u - first_u) * 1000

                    daily_gnss[day_key]['e'].append(delta_e_mm)
                    daily_gnss[day_key]['n'].append(delta_n_mm)
                    daily_gnss[day_key]['u'].append(delta_u_mm)

                gnss_analysis["time_series"] = {
                    "labels": list(daily_gnss.keys()),
                    "displacement": [round(sum(v['disp']) / len(v['disp']), 2) for v in daily_gnss.values()],
                    "e": [round(sum(v['e']) / len(v['e']), 2) for v in daily_gnss.values()],
                    "n": [round(sum(v['n']) / len(v['n']), 2) for v in daily_gnss.values()],
                    "u": [round(sum(v['u']) / len(v['u']), 2) for v in daily_gnss.values()]
                }

            result["gnss"] = gnss_analysis
        elif len(daily_gnss_requested) >= 1:
            result["gnss"] = _build_gnss_analysis_from_daily_summaries(
                daily_rows=daily_gnss_requested,
                station_cfg=station.config or {}
            )
        else:
            result["gnss"] = {
                "status": "insufficient_data",
                "message": f"Không đủ dữ liệu GNSS raw ({len(historical_gnss_requested)} điểm) và chưa có daily summary trong cửa sổ {days} ngày."
            }

        # 6. Phân tích IMU
        historical_imu_full = [{"timestamp": d.timestamp, "data": d.data} for d in imu_data]
        historical_imu_requested = [p for p in historical_imu_full if p['timestamp'] >= cutoff_requested]
        # ✅ FALLBACK: Nếu khoảng thời gian ngắn mà không có đủ dữ liệu, lấy dữ liệu gần nhất
        if len(historical_imu_requested) < 2 and len(historical_imu_full) >= 2 and days <= 1:
            historical_imu_requested = historical_imu_full[-60:]

        if len(historical_imu_requested) >= 2:
            imu_analysis = await _run_analysis(analyzer.analyze_long_term_tilt,
                station_id=station_id,
                historical_data=historical_imu_requested,
                window_days=days
            )

            # Format X-axis for IMU exactly like GNSS
            if imu_analysis.get("status") == "success" and "time_series" in imu_analysis:
                from collections import OrderedDict
                from datetime import datetime as dt
                if days < 1 / 24:
                    fmt = '%H:%M:%S'
                elif days <= 1:
                    fmt = '%H:%M'
                elif days <= 7:
                    fmt = '%d/%m %H:00'
                else:
                    fmt = '%d/%m'

                daily_imu = OrderedDict()
                for ts, r, p in zip(imu_analysis["time_series"]["raw_timestamps"], imu_analysis["time_series"]["rolls"], imu_analysis["time_series"]["pitches"]):
                    day_key = dt.fromtimestamp(ts).strftime(fmt)
                    if day_key not in daily_imu:
                        daily_imu[day_key] = {'rolls': [], 'pitches': []}
                    daily_imu[day_key]['rolls'].append(r)
                    daily_imu[day_key]['pitches'].append(p)

                imu_analysis["time_series"]["labels"] = list(daily_imu.keys())
                imu_analysis["time_series"]["rolls"] = [round(sum(v['rolls']) / len(v['rolls']), 2) for v in daily_imu.values()]
                imu_analysis["time_series"]["pitches"] = [round(sum(v['pitches']) / len(v['pitches']), 2) for v in daily_imu.values()]

            result["imu"] = imu_analysis
        else:
            result["imu"] = {
                "status": "insufficient_data",
                "message": f"Cần ít nhất 2 điểm dữ liệu IMU. Hiện có: {len(historical_imu_requested)}"
            }

        # 7. Phân tích tương quan Mưa - Dịch chuyển (chạy theo yêu cầu)
        if include_correlation:
            if model_key != "slide_model":
                raise HTTPException(status_code=400, detail="Unsupported correlation_model. Use slide_model.")

            # Nếu raw GNSS đã bị purge, dựng pseudo-GNSS từ daily summary
            gnss_for_correlation = historical_gnss_requested
            if len(gnss_for_correlation) < 2 and len(daily_gnss_requested) >= 2:
                logger.info(f"[Slide model] Raw GNSS insufficient ({len(historical_gnss_requested)} pts). "
                            f"Synthesizing from {len(daily_gnss_requested)} daily summaries.")
                cumulative_mm = 0.0
                gnss_for_correlation = []
                for row in sorted(daily_gnss_requested, key=lambda r: int(r.day_start_ts or 0)):
                    ts = int(row.day_start_ts or 0) + 43200  # giữa ngày (12h)
                    cumulative_mm += float(row.net_displacement_mm or 0.0)
                    # Dựng pseudo pos_e = cumulative (m), pos_n=0, pos_u=0
                    gnss_for_correlation.append({
                        "timestamp": ts,
                        "data": {
                            "pos_e": cumulative_mm / 1000.0,
                            "pos_n": 0.0,
                            "pos_u": 0.0
                        }
                    })

            if len(gnss_for_correlation) >= 2 and len(rain_data) >= 2:
                historical_rain = [{"timestamp": d.timestamp, "data": d.data} for d in rain_data]
                rain_correlation = await _run_analysis(analyzer.analyze_rainfall_displacement_correlation,
                    gnss_data=gnss_for_correlation,
                    rain_data=historical_rain,
                    window_days=days,
                    config=station.config or {}
                )
                rain_correlation["model"] = "slide_model"
                result["rainfall_correlation"] = rain_correlation
            else:
                gnss_count = len(gnss_for_correlation)
                rain_count = len(rain_data)
                result["rainfall_correlation"] = {
                    "available": False,
                    "model": "slide_model",
                    "message": f"Cần cả dữ liệu GNSS và mưa để phân tích tương quan. "
                               f"Hiện có: {gnss_count} điểm GNSS, {rain_count} bản ghi mưa."
                }
        else:
            result["rainfall_correlation"] = {
                "available": False,
                "model": "slide_model",
                "message": "Chưa chạy phân tích tương quan Slide model. Nhấn 'Chạy AI Slide model' để thực hiện."
            }

        # 8. Phân tích đa cửa sổ (Multi-Window) - dùng full GNSS data
        if len(historical_gnss_full) >= 2:
            multi_window = await _run_analysis(analyzer.analyze_multi_window,
                station_id=station_id,
                historical_data=historical_gnss_full,
                config=station.config or {},
                windows=[7, 30, 90]
            )
            result["multi_window"] = multi_window
        else:
            result["multi_window"] = {"available": False, "message": "Không đủ dữ liệu."}

        # 9. Overall status
        gnss_ok = result["gnss"].get("status") == "success"
        imu_ok = result["imu"].get("status") == "success"
        multi_window_ok = result.get("multi_window", {}).get("available") is True
        rainfall_ok = result.get("rainfall_correlation", {}).get("available") is True

        if gnss_ok or imu_ok or multi_window_ok or rainfall_ok:
            result["status"] = "success"
        else:
            result["status"] = "insufficient_data"
            result["message"] = "Không đủ dữ liệu GNSS và IMU để phân tích."

        # 10. Cross-sensor consensus — đánh giá đồng thuận giữa các model
        result["cross_sensor_consensus"] = await _run_analysis(analyzer.analyze_cross_sensor_consensus,
            gnss_result=result.get("gnss", {}),
            imu_result=result.get("imu", {}),
            rain_corr_result=result.get("rainfall_correlation", {})
        )

        _LONG_TERM_ANALYSIS_CACHE[cache_key] = (time.monotonic(), copy.deepcopy(result))
        # Bound memory even if many station IDs are probed over time.
        if len(_LONG_TERM_ANALYSIS_CACHE) > 256:
            oldest_key = min(_LONG_TERM_ANALYSIS_CACHE, key=lambda key: _LONG_TERM_ANALYSIS_CACHE[key][0])
            _LONG_TERM_ANALYSIS_CACHE.pop(oldest_key, None)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in long-term analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stations/{station_id}/gnss-daily-summary", responses={500: {"description": "Internal Server Error"}})
async def get_gnss_daily_summary(
    station_id: int,
    limit: int = 30,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo ngày (đã rollup)."""
    try:
        n = max(1, min(int(limit), 365))
        res = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(model_data.GnssDailySummary.station_id == station_id)
            .order_by(model_data.GnssDailySummary.day_start_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "day_start_ts": r.day_start_ts,
                    "day_end_ts": r.day_end_ts,
                    "sample_count": r.sample_count,
                    "duration_seconds": r.duration_seconds,
                    "net_displacement_mm": r.net_displacement_mm,
                    "velocity_mm_day": r.velocity_mm_day,
                    "velocity_mm_second": r.velocity_mm_second,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.exception(f"Error fetching GNSS daily summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stations/{station_id}/gnss-weekly-summary", responses={500: {"description": "Internal Server Error"}})
async def get_gnss_weekly_summary(
    station_id: int,
    limit: int = 12,
    db_data: AsyncSession = Depends(get_data_db)
):
    """Lấy summary GNSS theo tuần (từ 7 daily summaries liên tiếp)."""
    try:
        n = max(1, min(int(limit), 104))
        res = await db_data.execute(
            select(model_data.GnssWeeklySummary)
            .where(model_data.GnssWeeklySummary.station_id == station_id)
            .order_by(model_data.GnssWeeklySummary.week_end_ts.desc())
            .limit(n)
        )
        rows = list(reversed(res.scalars().all()))
        return {
            "station_id": station_id,
            "count": len(rows),
            "items": [
                {
                    "week_start_ts": r.week_start_ts,
                    "week_end_ts": r.week_end_ts,
                    "day_count": r.day_count,
                    "total_displacement_mm": r.total_displacement_mm,
                    "avg_velocity_mm_day": r.avg_velocity_mm_day,
                    "max_velocity_mm_day": r.max_velocity_mm_day,
                    "min_velocity_mm_day": r.min_velocity_mm_day,
                    "classification": r.classification,
                    "risk_level": r.risk_level,
                    "is_safe": r.is_safe,
                    "status": r.status,
                    "message": r.message,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.exception(f"Error fetching GNSS weekly summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


