"""Workbook writer for failed GNSS adjustment exports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def _write_failure_workbook(path, payload: dict[str, Any]) -> None:
    """Write a readable failure report, including captured raw GNSS evidence."""
    context = payload.get("context") or {}
    diagnostics = context.get("diagnostics") or {}
    workbook = Workbook()

    summary = workbook.active
    summary.title = "LOI_BINH_SAI"
    summary.append(["BÁO CÁO BÌNH SAI GNSS THẤT BẠI", None])
    summary.append([
        "Thời gian",
        datetime.fromtimestamp(payload["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
    ])
    summary.append(["Dự án", payload.get("project_code") or payload["project_id"]])
    summary.append(["Cụm", payload.get("cluster_name") or "Không xác định"])
    summary.append(["Nguồn chạy", payload.get("source")])
    summary.append([
        "Giai đoạn",
        context.get("stage") or context.get("phase") or "Không xác định",
    ])
    summary.append(["Loại lỗi", payload["error"]["type"]])
    summary.append(["Lý do", payload["error"]["message"]])
    summary.append([
        "Trạm offline",
        ", ".join(map(str, context.get("skipped_offline_station_ids") or []))
        or "Không ghi nhận",
    ])
    summary.append([
        "Trạm không điều khiển được",
        ", ".join(map(str, context.get("skipped_uncontrollable_station_ids") or []))
        or "Không ghi nhận",
    ])
    summary.append([
        "Hướng xử lý",
        "Kiểm tra RAW_GNSS và CHAN_DOAN; Position Type hợp lệ là 4 hoặc 7.",
    ])
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
    raw_headers = [
        "epoch_ts",
        "station_id",
        "rover",
        "position_type",
        "base",
        "solver_eligible",
        "reason",
        "raw_payload",
    ]
    raw_sheet.append(raw_headers)
    for item in diagnostics.get("raw_gnss") or context.get("raw_gnss") or []:
        raw_sheet.append([item.get(header) for header in raw_headers])
    if raw_sheet.max_row == 1:
        raw_sheet.append([
            None,
            None,
            None,
            None,
            None,
            False,
            "Không nhận được AGRICA trước khi lỗi",
            None,
        ])
    raw_sheet.freeze_panes = "A2"
    raw_sheet.auto_filter.ref = raw_sheet.dimensions
    for cell in raw_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087F5B")
    for column, width in {
        "A": 20,
        "B": 14,
        "C": 22,
        "D": 16,
        "E": 22,
        "F": 18,
        "G": 55,
        "H": 100,
    }.items():
        raw_sheet.column_dimensions[column].width = width

    diagnostic_sheet = workbook.create_sheet("CHAN_DOAN")
    diagnostic_sheet.append(["Mục", "Giá trị"])
    for key, value in sorted(diagnostics.items()):
        if key != "raw_gnss":
            diagnostic_sheet.append([
                key,
                json.dumps(value, ensure_ascii=False, default=str),
            ])
    diagnostic_sheet.column_dimensions["A"].width = 30
    diagnostic_sheet.column_dimensions["B"].width = 110
    for cell in diagnostic_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="344054")
    for row in diagnostic_sheet.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    if not hasattr(path, "write"):
        raise TypeError("GNSS failure workbooks must be written to a download stream")
    workbook.save(path)
