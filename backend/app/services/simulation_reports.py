"""On-demand PDF/XLSX/JSON reports built only from persisted run data."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def run_payload(run: Any) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version, "engine_version": run.engine_version,
        "id": run.id, "display_name": run.display_name, "status": run.status,
        "mode": run.mode, "created_by": {"id": run.created_by_user_id, "username": run.created_by_username},
        "project": {"id": run.project_id, "code": run.project_code, "name": run.project_name},
        "station": {"id": run.station_id, "code": run.station_code, "name": run.station_name},
        "seed": run.seed, "duration_seconds": run.sim_duration_seconds,
        "created_at": run.created_at, "started_at": run.started_at, "finished_at": run.finished_at,
        "parameters": run.parameters or {}, "parameter_sources": run.parameter_sources or {},
        "sensor_snapshot": run.sensor_snapshot or {}, "time_series": run.time_series or [],
        "events": run.events or [], "summary": run.summary or {}, "terrain_profile": run.terrain_profile or [],
        "warnings": run.warnings or [], "error": run.error_detail,
        "disclaimer": "Kết quả mô phỏng kịch bản, không phải chứng thư địa kỹ thuật hoặc dự báo đã kiểm định.",
    }


def build_json(run: Any) -> bytes:
    return json.dumps(run_payload(run), ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _sheet_from_rows(workbook: Workbook, title: str, rows: list[list[Any]]) -> Any:
    sheet = workbook.create_sheet(title)
    for row in rows:
        sheet.append(row)
    if rows:
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0F766E")
            cell.alignment = Alignment(horizontal="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    for column in range(1, sheet.max_column + 1):
        width = min(48, max(12, max((len(str(sheet.cell(row, column).value or "")) for row in range(1, sheet.max_row + 1)), default=12) + 2))
        sheet.column_dimensions[get_column_letter(column)].width = width
    return sheet


def build_xlsx(run: Any) -> bytes:
    payload = run_payload(run)
    workbook = Workbook()
    workbook.remove(workbook.active)
    summary_rows = [["Chỉ số", "Giá trị"]] + [[key, value] for key, value in payload["summary"].items()]
    summary_rows += [["Trạng thái lần chạy", payload["status"]], ["Tên", payload["display_name"]], ["Cảnh báo", " | ".join(payload["warnings"])] , ["Lỗi", payload["error"] or ""]]
    _sheet_from_rows(workbook, "Tong_quan", summary_rows)
    _sheet_from_rows(workbook, "Tham_so_dau_vao", [["Tham số", "Giá trị", "Nguồn"]] + [[key, value, payload["parameter_sources"].get(key, "manual")] for key, value in payload["parameters"].items()])
    _sheet_from_rows(workbook, "Du_lieu_tram", [["Loại", "Timestamp", "Online", "Dữ liệu"]] + [[key, value.get("timestamp"), value.get("is_online"), json.dumps(value.get("data", value), ensure_ascii=False)] for key, value in payload["sensor_snapshot"].items()])
    series = payload["time_series"]
    series_headers = list(series[0].keys()) if series else ["time_s"]
    series_sheet = _sheet_from_rows(workbook, "Chuoi_thoi_gian", [series_headers] + [[row.get(key) for key in series_headers] for row in series])
    _sheet_from_rows(workbook, "Su_kien", [["Thời gian (s)", "Trạng thái", "Sự kiện"]] + [[event.get("time_s"), event.get("state"), event.get("label")] for event in payload["events"]])
    _sheet_from_rows(workbook, "Tac_dong", [["Chỉ số", "Giá trị"], ["Nhà ảnh hưởng", payload["summary"].get("houses_affected", 0)], ["Cây ảnh hưởng", payload["summary"].get("trees_affected", 0)], ["Quãng trượt (m)", payload["summary"].get("runout_m", 0)], ["Thể tích (m³)", payload["summary"].get("final_volume_m3", 0)]])
    chart_sheet = workbook.create_sheet("Bieu_do")
    chart_specs = [
        ("FoS theo thời gian", "fos"), ("Mưa tích lũy", "cumulative_rain_mm"),
        ("Áp lực nước lỗ rỗng", "pore_pressure_ratio"), ("Vận tốc khối trượt", "velocity_m_s"),
        ("Quãng đường trượt", "runout_m"), ("Nhà trong vùng ảnh hưởng", "houses_affected"),
    ]
    for index, (title, key) in enumerate(chart_specs):
        if key not in series_headers or len(series) < 2:
            continue
        chart = LineChart()
        chart.title, chart.style, chart.height, chart.width = title, 13, 8, 15
        chart.y_axis.title = key
        chart.x_axis.title = "Thời gian mô phỏng (giây)"
        key_col = series_headers.index(key) + 1
        time_col = series_headers.index("time_s") + 1
        chart.add_data(Reference(series_sheet, min_col=key_col, min_row=1, max_row=len(series) + 1), titles_from_data=True)
        chart.set_categories(Reference(series_sheet, min_col=time_col, min_row=2, max_row=len(series) + 1))
        chart_sheet.add_chart(chart, f"A{1 + index * 16}")
    metadata = [["Trường", "Giá trị"], ["schema_version", payload["schema_version"]], ["engine_version", payload["engine_version"]], ["seed", payload["seed"]], ["disclaimer", payload["disclaimer"]]]
    _sheet_from_rows(workbook, "Metadata", metadata)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("SimulationUnicode", str(path)))
                return "SimulationUnicode"
            except Exception:
                pass
    return "Helvetica"


def build_pdf(run: Any) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    payload, output = run_payload(run), BytesIO()
    font = _pdf_font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("SimulationNormal", parent=styles["BodyText"], fontName=font, fontSize=9, leading=13)
    title = ParagraphStyle("SimulationTitle", parent=styles["Title"], fontName=font, textColor=colors.HexColor("#0F766E"))
    heading = ParagraphStyle("SimulationHeading", parent=styles["Heading2"], fontName=font, textColor=colors.HexColor("#164E63"))
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=payload["display_name"])
    story = [Paragraph("BÁO CÁO MÔ PHỎNG SẠT LỞ", title), Paragraph(payload["display_name"], heading), Spacer(1, 6)]
    status_text = "KHÔNG HOÀN TẤT" if payload["status"] != "completed" else "HOÀN TẤT"
    story += [Paragraph(f"Trạng thái báo cáo: {status_text}", normal), Paragraph(payload["disclaimer"], normal), Spacer(1, 12)]
    summary_data = [["Chỉ số", "Giá trị"]] + [[str(key), str(value)] for key, value in payload["summary"].items()]
    summary_table = Table(summary_data, colWidths=[70 * mm, 100 * mm], repeatRows=1)
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [summary_table, PageBreak(), Paragraph("THAM SỐ VÀ NGUỒN DỮ LIỆU", heading)]
    parameter_data = [["Tham số", "Giá trị", "Nguồn"]] + [[key, str(value), payload["parameter_sources"].get(key, "manual")] for key, value in payload["parameters"].items()]
    parameter_table = Table(parameter_data, colWidths=[55 * mm, 45 * mm, 70 * mm], repeatRows=1)
    parameter_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#164E63")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1"))]))
    story += [parameter_table, Spacer(1, 12), Paragraph("CẢNH BÁO VÀ LỖI", heading)]
    messages = payload["warnings"] or ["Không có cảnh báo dữ liệu."]
    for message in messages:
        story.append(Paragraph(f"• {message}", normal))
    if payload["error"]:
        story.append(Paragraph(f"Lỗi: {payload['error']}", normal))
    series = payload["time_series"]
    story += [PageBreak(), Paragraph("BIỂU ĐỒ DIỄN BIẾN 2D", heading)]
    def line_chart(key: str, label: str) -> Drawing:
        drawing = Drawing(480, 105)
        rows = series[::max(1, len(series) // 180)] if series else []
        values = [float(row.get(key) or 0) for row in rows]
        low, high = (min(values), max(values)) if values else (0.0, 1.0)
        if high <= low:
            high = low + 1.0
        drawing.add(String(0, 91, f"{label}: {low:.2f} – {high:.2f}", fontName=font, fontSize=8, fillColor=colors.HexColor("#334155")))
        drawing.add(Line(0, 8, 470, 8, strokeColor=colors.HexColor("#CBD5E1")))
        points = [(index / max(1, len(values) - 1) * 470, 12 + (value - low) / (high - low) * 70) for index, value in enumerate(values)]
        if len(points) > 1:
            drawing.add(PolyLine(points, strokeColor=colors.HexColor("#0F766E"), strokeWidth=1.5))
        return drawing
    for key, label in [("fos", "FoS"), ("cumulative_rain_mm", "Mưa tích lũy (mm)"), ("pore_pressure_ratio", "Áp lực lỗ rỗng ru"), ("velocity_m_s", "Vận tốc (m/s)"), ("runout_m", "Quãng trượt (m)"), ("houses_affected", "Nhà ảnh hưởng")]:
        story.extend([line_chart(key, label), Spacer(1, 4)])
    profile = payload["terrain_profile"]
    if profile:
        story += [PageBreak(), Paragraph("MẶT CẮT SƯỜN DỐC VÀ MẶT TRƯỢT", heading)]
        drawing = Drawing(480, 210)
        max_elevation = max(float(point.get("elevation_m") or 0) for point in profile) or 1.0
        terrain_points = [(float(point["x_m"]) / 120 * 470, 15 + float(point["elevation_m"]) / max_elevation * 175) for point in profile]
        slip_points = [(float(point["x_m"]) / 120 * 470, 15 + float(point["slip_elevation_m"]) / max_elevation * 175) for point in profile]
        drawing.add(PolyLine(terrain_points, strokeColor=colors.HexColor("#166534"), strokeWidth=2))
        drawing.add(PolyLine(slip_points, strokeColor=colors.HexColor("#B45309"), strokeWidth=1.5, strokeDashArray=[5, 3]))
        drawing.add(String(4, 195, "Địa hình (xanh) · Mặt trượt giả định (cam nét đứt)", fontName=font, fontSize=8))
        story.append(drawing)
    story += [PageBreak(), Paragraph("CHUỖI KẾT QUẢ TIÊU BIỂU", heading)]
    sampled = series[::max(1, len(series) // 24)] if series else []
    result_data = [["t (h)", "FoS", "ru", "v (m/s)", "runout (m)", "state"]] + [[round(row["time_s"] / 3600, 2), row["fos"], row["pore_pressure_ratio"], row["velocity_m_s"], row["runout_m"], row["state"]] for row in sampled]
    result_table = Table(result_data, repeatRows=1)
    result_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1"))]))
    story.append(result_table)
    document.build(story)
    return output.getvalue()
