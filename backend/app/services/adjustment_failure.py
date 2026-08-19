"""Durable failure artifacts for automatic and in-progress GNSS adjustments."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.services.adjustment_artifacts import VIETNAM_TIMEZONE, adjustment_scope

logger = logging.getLogger(__name__)
ADJUSTMENT_REPORT_DIR = Path(__file__).resolve().parents[2] / "static" / "adjustments"


def _write_failure_workbook(path: Path, payload: dict[str, Any]) -> None:
    """Write a readable failure report, including captured raw GNSS evidence."""

    context = payload.get("context") or {}
    diagnostics = context.get("diagnostics") or {}
    workbook = Workbook()
    summary = workbook.active
    summary.title = "LOI_BINH_SAI"
    summary.append(["BÁO CÁO BÌNH SAI GNSS THẤT BẠI", None])
    summary.append(["Thời gian", datetime.fromtimestamp(payload["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")])
    summary.append(["Dự án", payload.get("project_code") or payload["project_id"]])
    summary.append(["Cụm", payload.get("cluster_name") or "Không xác định"])
    summary.append(["Nguồn chạy", payload.get("source")])
    summary.append(["Giai đoạn", context.get("stage") or context.get("phase") or "Không xác định"])
    summary.append(["Loại lỗi", payload["error"]["type"]])
    summary.append(["Lý do", payload["error"]["message"]])
    summary.append(["Trạm offline", ", ".join(map(str, context.get("skipped_offline_station_ids") or [])) or "Không ghi nhận"])
    summary.append(["Trạm không điều khiển được", ", ".join(map(str, context.get("skipped_uncontrollable_station_ids") or [])) or "Không ghi nhận"])
    summary.append(["Hướng xử lý", "Kiểm tra RAW_GNSS và CHAN_DOAN; Position Type hợp lệ là 4 hoặc 7."])
    summary.merge_cells("A1:B1")
    summary["A1"].font = Font(bold=True, color="FFFFFF", size=14)
    summary["A1"].fill = PatternFill("solid", fgColor="B42318")
    summary["A1"].alignment = Alignment(horizontal="center")
    summary.column_dimensions["A"].width = 29
    summary.column_dimensions["B"].width = 95
    for row in summary.iter_rows(min_row=2):
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    raw_sheet = workbook.create_sheet("RAW_GNSS")
    raw_headers = ["epoch_ts", "station_id", "rover", "position_type", "base", "solver_eligible", "reason", "raw_payload"]
    raw_sheet.append(raw_headers)
    for item in diagnostics.get("raw_gnss") or context.get("raw_gnss") or []:
        raw_sheet.append([item.get(header) for header in raw_headers])
    if raw_sheet.max_row == 1:
        raw_sheet.append([None, None, None, None, None, False, "Không nhận được AGRICA trước khi lỗi", None])
    raw_sheet.freeze_panes = "A2"
    raw_sheet.auto_filter.ref = raw_sheet.dimensions
    for cell in raw_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087F5B")
    for column, width in {"A": 20, "B": 14, "C": 22, "D": 16, "E": 22, "F": 18, "G": 55, "H": 100}.items():
        raw_sheet.column_dimensions[column].width = width

    diagnostic_sheet = workbook.create_sheet("CHAN_DOAN")
    diagnostic_sheet.append(["Mục", "Giá trị"])
    for key, value in sorted(diagnostics.items()):
        if key != "raw_gnss":
            diagnostic_sheet.append([key, json.dumps(value, ensure_ascii=False, default=str)])
    diagnostic_sheet.column_dimensions["A"].width = 30
    diagnostic_sheet.column_dimensions["B"].width = 110
    for cell in diagnostic_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="344054")
    for row in diagnostic_sheet.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    temporary_path = path.with_suffix(".xlsx.tmp")
    workbook.save(temporary_path)
    temporary_path.replace(path)


def write_adjustment_failure_report(
    project_id: int,
    error: Exception | str,
    *,
    source: str,
    context: dict[str, Any] | None = None,
    project_code: str | None = None,
    cluster_name: str | None = None,
) -> dict[str, Any] | None:
    """Atomically write project-scoped JSON and XLSX failure artifacts."""

    timestamp = int(time.time())
    filename_timestamp = int(time.time_ns() // 1_000_000)
    readable_timestamp = (
        datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).strftime("%Y-%m-%d_%H-%M-%S")
        + f"_{filename_timestamp % 1000:03d}"
    )
    error_type = error.__class__.__name__ if isinstance(error, Exception) else "AdjustmentError"
    error_message = str(error).strip()[:4000] or error_type
    report_dir, project_slug, cluster_slug, scoped = adjustment_scope(
        ADJUSTMENT_REPORT_DIR,
        project_id,
        project_code,
        cluster_name,
        run_id=(context or {}).get("run_id"),
        timestamp=timestamp,
    )
    report_name = (
        f"gnss_adjustment_{project_slug}_{cluster_slug}_{readable_timestamp}.json"
        if scoped else f"gnss_adjustment_{int(project_id)}_{filename_timestamp}.json"
    )
    report_path = report_dir / report_name
    excel_name = report_path.with_suffix(".xlsx").name
    excel_path = report_dir / excel_name
    temporary_path = report_path.with_suffix(".json.tmp")
    payload: dict[str, Any] = {
        "status": "failed",
        "phase": "ERROR",
        "source": str(source),
        "project_id": int(project_id),
        "project_code": str(project_code or "") or None,
        "cluster_name": str(cluster_name or "") or None,
        "cluster_index": (context or {}).get("cluster_index"),
        "timestamp": timestamp,
        "error": {"type": error_type, "message": error_message},
        "context": dict(context or {}),
        "audit_json_url": (
            f"/api/admin/gnss/adjustment/reports/"
            f"{report_dir.relative_to(ADJUSTMENT_REPORT_DIR).as_posix()}/{report_name}"
            if scoped else
            f"/api/admin/gnss/adjustment/reports/{int(project_id)}/{report_name}"
        ),
    }
    report_api_prefix = payload["audit_json_url"].rsplit("/", 1)[0]
    payload["excel_report_url"] = f"{report_api_prefix}/{excel_name}"
    payload["report_file_url"] = payload["excel_report_url"]
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        _write_failure_workbook(excel_path, payload)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(report_path)
        logger.error("GNSS adjustment failure reports written: %s, %s", report_path, excel_path)
        return payload
    except Exception:
        logger.exception(
            "Could not persist GNSS adjustment failure report for project %s",
            project_id,
        )
        return None
