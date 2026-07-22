"""Daily and weekly GNSS aggregation background workflow."""
import asyncio
import logging
import math
import time

from sqlalchemy import and_, delete, select, text

from .. import config
from ..database import DataSessionLocal
from ..models import data as model_data
from ..runtime import analyzer

logger = logging.getLogger(__name__)

def _utc_day_start(ts: int) -> int:
    return (int(ts) // 86400) * 86400


def _map_gnss_daily_risk(classification: str) -> str:
    cls_upper = str(classification or "").upper()
    if any(c in cls_upper for c in ("EXTREMELY RAPID", "VERY RAPID", "RAPID")):
        return "CRITICAL"
    if "MODERATE" in cls_upper:
        return "HIGH"
    if "SLOW" in cls_upper:
        return "MEDIUM"
    return "LOW"


async def _upsert_gnss_weekly_summary(station_id: int, ending_day_start_ts: int):
    """Tạo summary tuần từ 7 ngày daily gần nhất (liên tiếp) cho station."""
    week_end_ts = ending_day_start_ts + 86400
    async with DataSessionLocal() as db_data:
        res = await db_data.execute(
            select(model_data.GnssDailySummary)
            .where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_end_ts <= week_end_ts,
                    model_data.GnssDailySummary.status == "success"
                )
            )
            .order_by(model_data.GnssDailySummary.day_start_ts.desc())
            .limit(7)
        )
        days = list(reversed(res.scalars().all()))

        if len(days) < 7:
            return

        # Bắt buộc 7 ngày liên tiếp
        for i in range(1, len(days)):
            if days[i].day_start_ts - days[i - 1].day_start_ts != 86400:
                return

        week_start_ts = days[0].day_start_ts
        now_ts = int(time.time())
        total_disp_mm = float(sum(float(d.net_displacement_mm or 0.0) for d in days))
        avg_vel_mm_day = float(sum(float(d.velocity_mm_day or 0.0) for d in days)) / 7.0
        max_vel_mm_day = float(max(float(d.velocity_mm_day or 0.0) for d in days))
        min_vel_mm_day = float(min(float(d.velocity_mm_day or 0.0) for d in days))
        vel_mm_second = avg_vel_mm_day / 86400.0
        vel_mm_year = avg_vel_mm_day * 365.0
        classification = analyzer._classify_velocity_extended(
            vel_mm_second,
            avg_vel_mm_day,
            vel_mm_year,
            {}
        )
        risk_level = _map_gnss_daily_risk(classification)
        is_safe = risk_level in ("LOW", "MEDIUM")

        existing_res = await db_data.execute(
            select(model_data.GnssWeeklySummary).where(
                and_(
                    model_data.GnssWeeklySummary.station_id == station_id,
                    model_data.GnssWeeklySummary.week_start_ts == week_start_ts,
                    model_data.GnssWeeklySummary.week_end_ts == week_end_ts,
                )
            )
        )
        existing = existing_res.scalar_one_or_none()

        if existing:
            existing.day_count = 7
            existing.total_displacement_mm = round(total_disp_mm, 3)
            existing.avg_velocity_mm_day = round(avg_vel_mm_day, 6)
            existing.max_velocity_mm_day = round(max_vel_mm_day, 6)
            existing.min_velocity_mm_day = round(min_vel_mm_day, 6)
            existing.classification = str(classification)
            existing.risk_level = risk_level
            existing.is_safe = is_safe
            existing.status = "success"
            existing.message = "Weekly summary computed from 7 consecutive daily summaries."
            existing.updated_at = now_ts
        else:
            db_data.add(model_data.GnssWeeklySummary(
                station_id=station_id,
                week_start_ts=week_start_ts,
                week_end_ts=week_end_ts,
                day_count=7,
                total_displacement_mm=round(total_disp_mm, 3),
                avg_velocity_mm_day=round(avg_vel_mm_day, 6),
                max_velocity_mm_day=round(max_vel_mm_day, 6),
                min_velocity_mm_day=round(min_vel_mm_day, 6),
                classification=str(classification),
                risk_level=risk_level,
                is_safe=is_safe,
                status="success",
                message="Weekly summary computed from 7 consecutive daily summaries.",
                created_at=now_ts,
                updated_at=now_ts,
            ))

        await db_data.commit()


async def _finalize_gnss_station_day(station_id: int, day_start_ts: int, purge_raw: bool):
    day_end_ts = day_start_ts + 86400
    now_ts = int(time.time())

    async with DataSessionLocal() as db_data:
        existing_res = await db_data.execute(
            select(model_data.GnssDailySummary).where(
                and_(
                    model_data.GnssDailySummary.station_id == station_id,
                    model_data.GnssDailySummary.day_start_ts == day_start_ts,
                )
            )
        )
        existing_summary = existing_res.scalar_one_or_none()

        # Nếu chưa có summary thì tính từ raw trong ngày
        if not existing_summary:
            rows_res = await db_data.execute(
                select(model_data.SensorData)
                .where(
                    and_(
                        model_data.SensorData.station_id == station_id,
                        model_data.SensorData.sensor_type == "gnss",
                        model_data.SensorData.timestamp >= day_start_ts,
                        model_data.SensorData.timestamp < day_end_ts,
                    )
                )
                .order_by(model_data.SensorData.timestamp.asc())
            )
            rows = rows_res.scalars().all()
            valid_points = [
                r for r in rows
                if isinstance(r.data, dict)
                and all(k in r.data for k in ("pos_e", "pos_n", "pos_u"))
            ]

            sample_count = len(valid_points)
            first_ts = int(valid_points[0].timestamp) if sample_count > 0 else None
            last_ts = int(valid_points[-1].timestamp) if sample_count > 0 else None
            duration_seconds = max((last_ts - first_ts), 0) if first_ts and last_ts else 0

            if sample_count >= 2 and duration_seconds > 0:
                first_data = valid_points[0].data
                last_data = valid_points[-1].data
                delta_e = float(last_data.get("pos_e", 0.0)) - float(first_data.get("pos_e", 0.0))
                delta_n = float(last_data.get("pos_n", 0.0)) - float(first_data.get("pos_n", 0.0))
                delta_u = float(last_data.get("pos_u", 0.0)) - float(first_data.get("pos_u", 0.0))
                net_disp_mm = math.sqrt(delta_e ** 2 + delta_n ** 2 + delta_u ** 2) * 1000.0
                duration_days = max(duration_seconds / 86400.0, 1e-6)
                velocity_mm_day = net_disp_mm / duration_days
                velocity_mm_second = velocity_mm_day / 86400.0
                velocity_mm_year = velocity_mm_day * 365.0

                classification = analyzer._classify_velocity_extended(
                    velocity_mm_second,
                    velocity_mm_day,
                    velocity_mm_year,
                    {}
                )
                risk_level = _map_gnss_daily_risk(classification)
                is_safe = risk_level in ("LOW", "MEDIUM")
                status = "success"
                message = "Daily summary computed from raw GNSS records."
            else:
                net_disp_mm = 0.0
                velocity_mm_day = 0.0
                velocity_mm_second = 0.0
                classification = "insufficient_data"
                risk_level = "INFO"
                is_safe = True
                status = "insufficient_data"
                message = "Not enough GNSS points for daily summary."

            db_data.add(model_data.GnssDailySummary(
                station_id=station_id,
                day_start_ts=day_start_ts,
                day_end_ts=day_end_ts,
                sample_count=sample_count,
                first_ts=first_ts,
                last_ts=last_ts,
                duration_seconds=duration_seconds,
                net_displacement_mm=round(float(net_disp_mm), 3),
                velocity_mm_day=round(float(velocity_mm_day), 6),
                velocity_mm_second=round(float(velocity_mm_second), 8),
                classification=str(classification),
                risk_level=risk_level,
                is_safe=is_safe,
                status=status,
                message=message,
                created_at=now_ts,
                updated_at=now_ts,
            ))
            await db_data.commit()

        # Xóa raw GNSS của ngày đã chốt nếu bật purge
        if purge_raw:
            await db_data.execute(
                delete(model_data.SensorData).where(
                    and_(
                        model_data.SensorData.station_id == station_id,
                        model_data.SensorData.sensor_type == "gnss",
                        model_data.SensorData.timestamp >= day_start_ts,
                        model_data.SensorData.timestamp < day_end_ts,
                    )
                )
            )
            await db_data.commit()

    await _upsert_gnss_weekly_summary(station_id, day_start_ts)


async def run_gnss_daily_rollup_daemon():
    """Daemon: chốt GNSS theo ngày rồi rollup tuần từ 7 ngày liên tiếp."""
    interval = max(int(config.settings.GNSS_ROLLUP_INTERVAL_SECONDS), 60)
    purge_raw = bool(config.settings.GNSS_PURGE_RAW_AFTER_DAILY_ROLLUP)
    logger.info(
        f"🔄 GNSS rollup daemon started (interval={interval}s, purge_raw={purge_raw})"
    )

    while True:
        try:
            now_ts = int(time.time())
            today_start = _utc_day_start(now_ts)

            async with DataSessionLocal() as db_data:
                pairs_res = await db_data.execute(text(
                    """
                    SELECT station_id, ((timestamp / 86400) * 86400) AS day_start
                    FROM sensor_data
                    WHERE sensor_type = 'gnss' AND timestamp < :cutoff
                    GROUP BY station_id, ((timestamp / 86400) * 86400)
                    ORDER BY day_start, station_id
                    """
                ), {"cutoff": today_start})
                pairs = [(int(r[0]), int(r[1])) for r in pairs_res.fetchall()]

            for station_id, day_start_ts in pairs:
                await _finalize_gnss_station_day(station_id, day_start_ts, purge_raw)

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("🛑 GNSS rollup daemon cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ GNSS rollup daemon error: {e}", exc_info=True)
            await asyncio.sleep(30)


