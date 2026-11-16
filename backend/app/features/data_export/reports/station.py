"""On-demand PDF report for one monitoring station."""

import logging
import time
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....database import get_config_db, get_data_db
from ....models import config as model_config
from ....models import data as model_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

@router.get("/export/station/{station_id}/pdf", responses={404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def export_station_pdf(
    station_id: int,
    config_db: AsyncSession = Depends(get_config_db),
    data_db: AsyncSession = Depends(get_data_db),
):
    """
    Generate a professional PDF report for a station.
    Includes: station info, latest sensor readings, recent alerts, GNSS daily summaries.
    No auth required so guests can also download (station data is public on map).
    """
    try:
        # 1) Get station info
        res = await config_db.execute(
            select(model_config.Station).where(model_config.Station.id == station_id)
        )
        station = res.scalar_one_or_none()
        if not station:
            raise HTTPException(status_code=404, detail="Station not found")

        # 2) Latest sensor cache
        res = await data_db.execute(
            select(model_data.LatestSensorCache)
            .where(model_data.LatestSensorCache.station_id == station_id)
        )
        sensor_cache = res.scalars().all()

        # 3) Recent alerts (last 20)
        res = await data_db.execute(
            select(model_data.Alert)
            .where(model_data.Alert.station_id == station_id)
            .order_by(desc(model_data.Alert.timestamp))
            .limit(20)
        )
        alerts = res.scalars().all()

        # 4) GNSS daily summaries (last 7 days)
        seven_days_ago_ts = int(time.time()) - 7 * 86400
        res = await data_db.execute(
            select(model_data.GnssDailySummary)
            .where(
                model_data.GnssDailySummary.station_id == station_id,
                model_data.GnssDailySummary.day_start_ts >= seven_days_ago_ts
            )
            .order_by(desc(model_data.GnssDailySummary.day_start_ts))
        )
        daily_summaries = res.scalars().all()

        # --- Build PDF with reportlab ---
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                topMargin=20*mm, bottomMargin=15*mm,
                                leftMargin=15*mm, rightMargin=15*mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('TitleCustom', parent=styles['Title'],
                                     fontSize=18, textColor=colors.HexColor('#0d6efd'))
        subtitle_style = ParagraphStyle('Subtitle', parent=styles['Heading2'],
                                        fontSize=13, textColor=colors.HexColor('#1e293b'),
                                        spaceAfter=6)
        normal_style = styles['Normal']

        elements = []

        # Header
        elements.append(Paragraph(f"Landslide Monitor - Station Report", title_style))
        elements.append(Spacer(1, 4*mm))

        # Station info table
        loc = station.location or {}
        last_up = datetime.fromtimestamp(station.last_update).strftime('%Y-%m-%d %H:%M:%S') if station.last_update else 'N/A'
        info_data = [
            ['Station Name', station.name],
            ['Station Code', station.station_code],
            ['Status', station.status or 'N/A'],
            ['Location', f"Lat: {loc.get('lat', 'N/A')}, Lon: {loc.get('lon', 'N/A')}"],
            ['Last Update', last_up],
            ['Report Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ]
        info_table = Table(info_data, colWidths=[45*mm, 120*mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 8*mm))

        # Latest Sensor Readings
        elements.append(Paragraph("Latest Sensor Readings", subtitle_style))
        if sensor_cache:
            sensor_rows = [['Sensor Type', 'Timestamp', 'Key Values']]
            for sc in sensor_cache:
                ts_str = datetime.fromtimestamp(sc.timestamp).strftime('%H:%M:%S %d/%m') if sc.timestamp else '—'
                data_dict = sc.data if isinstance(sc.data, dict) else {}
                # Extract top 3 key-value pairs
                kv_str = ', '.join([f"{k}: {v}" for k, v in list(data_dict.items())[:4]])
                sensor_rows.append([sc.sensor_type.upper(), ts_str, kv_str[:80]])

            s_table = Table(sensor_rows, colWidths=[30*mm, 35*mm, 100*mm])
            s_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(s_table)
        else:
            elements.append(Paragraph("No sensor data available.", normal_style))
        elements.append(Spacer(1, 6*mm))

        # GNSS Daily Summaries
        if daily_summaries:
            elements.append(Paragraph("GNSS Daily Summary (7 days)", subtitle_style))
            gnss_rows = [['Date', 'Displacement (mm)', 'Velocity (mm/day)', 'Risk', 'Classification']]
            for ds in daily_summaries:
                day_str = datetime.fromtimestamp(ds.day_start_ts).strftime('%d/%m/%Y')
                gnss_rows.append([
                    day_str,
                    f"{ds.net_displacement_mm:.3f}",
                    f"{ds.velocity_mm_day:.4f}",
                    ds.risk_level,
                    ds.classification
                ])
            g_table = Table(gnss_rows, colWidths=[28*mm, 35*mm, 35*mm, 30*mm, 37*mm])
            g_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0fdf4')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(g_table)
            elements.append(Spacer(1, 6*mm))

        # Recent Alerts
        if alerts:
            elements.append(Paragraph("Recent Alerts (max 20)", subtitle_style))
            alert_rows = [['Time', 'Level', 'Category', 'Message']]
            for a in alerts[:15]:  # limit rows for PDF space
                a_time = datetime.fromtimestamp(a.timestamp).strftime('%H:%M %d/%m')
                msg = (a.message or '')[:60]
                alert_rows.append([a_time, a.level, a.category, msg])
            a_table = Table(alert_rows, colWidths=[28*mm, 22*mm, 22*mm, 93*mm])
            a_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ef4444')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fef2f2')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(a_table)

        # Build PDF
        doc.build(elements)
        buffer.seek(0)

        import urllib.parse
        safe_name = station.name.replace(' ', '_')
        filename = f"BaoCao_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
        encoded_filename = urllib.parse.quote(filename)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"}
        )

    except HTTPException:
        raise
    except ImportError:
        logger.error("reportlab not installed. Run: pip install reportlab")
        raise HTTPException(status_code=500, detail="Server missing reportlab library. Ask admin to: pip install reportlab")
    except Exception as e:
        logger.error(f"❌ PDF export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
