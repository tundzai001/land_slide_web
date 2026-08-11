"""GNSS adjustment audit, Excel, and human-readable report generation."""
import json
import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class AdjustmentReportMixin:
    def _append_raw_gnss_to_excel(self, station_id: int, timestamp: int, raw_payload: str):
        import os
        import openpyxl
        import datetime

        file_dir = os.path.join(str(BACKEND_DIR), "static", "raw_gnss")
        os.makedirs(file_dir, exist_ok=True)
        date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        file_path = os.path.join(file_dir, f"gnss_raw_{station_id}_{date_str}.xlsx")

        if os.path.exists(file_path):
            try:
                wb = openpyxl.load_workbook(file_path)
            except Exception:
                wb = openpyxl.Workbook()
                if "Sheet" in wb.sheetnames: wb.remove(wb["Sheet"])
        else:
            wb = openpyxl.Workbook()
            if "Sheet" in wb.sheetnames: wb.remove(wb["Sheet"])

        if "GGA" not in wb.sheetnames:
            ws_gga = wb.create_sheet("GGA")
            ws_gga.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_gga = wb["GGA"]
            
        if "AGRICA" not in wb.sheetnames:
            ws_agrica = wb.create_sheet("AGRICA")
            ws_agrica.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_agrica = wb["AGRICA"]
            
        if "OTHER" not in wb.sheetnames:
            ws_other = wb.create_sheet("OTHER")
            ws_other.append(["Timestamp", "Time", "Sentence"])
        else:
            ws_other = wb["OTHER"]

        dt_str = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

        for line in raw_payload.splitlines():
            line = line.strip()
            if not line: continue
            if "GGA" in line:
                ws_gga.append([timestamp, dt_str, line])
            elif "AGRICA" in line:
                ws_agrica.append([timestamp, dt_str, line])
            else:
                ws_other.append([timestamp, dt_str, line])
        
        try:
            wb.save(file_path)
        except Exception as e:
            logger.error(f"Error saving raw GNSS excel: {e}")

    def _append_adjustment_audit_to_excel(self, project_id: int, timestamp: int, data: dict, raw_payload: str):
        """Legacy verbose audit workbook retained for backwards reference only."""
        import datetime
        import os

        import openpyxl
        from openpyxl.styles import Font, PatternFill

        file_dir = os.path.join(str(BACKEND_DIR), "static", "adjustments")
        os.makedirs(file_dir, exist_ok=True)
        # One immutable workbook per project/run.  A shared workbook caused
        # sheets from unrelated projects to be appended to the same file.
        file_path = os.path.join(
            file_dir,
            f"gnss_binh_sai_{project_id}_{timestamp}.xlsx",
        )
        try:
            wb = openpyxl.load_workbook(file_path) if os.path.exists(file_path) else openpyxl.Workbook()
        except Exception:
            wb = openpyxl.Workbook()
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])

        dt_obj = datetime.datetime.fromtimestamp(timestamp)
        sheet_name = f"Lan {len(wb.sheetnames) + 1} ({dt_obj:%H-%M-%S})"[:31]
        ws = wb.create_sheet(title=sheet_name)

        def section(title):
            ws.append([])
            ws.append([title])
            cell = ws.cell(ws.max_row, 1)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")

        def header(values):
            ws.append(values)
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="D9EAF7")

        def vector_row(prefix, *values):
            row = list(prefix)
            for value in values:
                row.extend(value) if isinstance(value, (list, tuple)) else row.append(value)
            ws.append(row)

        def relative_precision_text(loop, prefix):
            closure = loop.get(f"{prefix}_closure")
            if closure is not None and abs(float(closure)) < 1e-9:
                return "Khép kín"
            ratio = loop.get(f"{prefix}_relative_precision")
            return f"1/{ratio:.0f}" if ratio else "Không xác định"

        ws.append(["BÁO CÁO BÌNH SAI MẠNG GNSS (HỆ TỌA ĐỘ ECEF XYZ)"])
        ws.cell(1, 1).font = Font(bold=True, size=14)
        ws.append(["Mã dự án", project_id])
        ws.append(["Thời gian bình sai", dt_obj.strftime("%Y-%m-%d %H:%M:%S")])
        ws.append(["Số lượng Rover", data.get("rover_count", 0)])
        ws.append(["Động cơ bình sai", data.get("adjustment_engine", "")])

        baselines = data.get("baselines", [])
        loops = data.get("loops", [])
        section("BẢNG 1: BASELINE TRUNG BÌNH THEO CẶP ĐIỂM")
        header(["STT", "Từ điểm", "Đến điểm", "dX (m)", "dY (m)", "dZ (m)",
                "Std_X TB (m)", "Std_Y TB (m)", "Std_Z TB (m)", "Chiều dài TB (m)",
                "Std vận tốc Up TB (m/s)", "Số trị đo"])
        for index, baseline in enumerate(baselines, 1):
            vector_row([index, baseline.get("from"), baseline.get("to")],
                       baseline.get("observed_xyz") or baseline.get("observed_neu") or (0, 0, 0),
                       baseline.get("standard_deviation_xyz") or (None, None, None),
                       baseline.get("observed_length"), baseline.get("velocity_up_std"),
                       baseline.get("observation_count", 1))

        section("BẢNG 2: VÒNG KHÉP TỪ BASELINE TRUNG BÌNH")
        header(["Vòng", "Các điểm", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
                "Tổng chiều dài (m)", "Độ chính xác tương đối"])
        for loop in loops:
            vector_row([loop.get("loop"), " - ".join(loop.get("points", []))],
                       loop.get("observed_misclosure_xyz") or (0, 0, 0),
                       loop.get("observed_closure"), loop.get("total_length"),
                       relative_precision_text(loop, "observed"))

        section("BẢNG 3: BASELINE TRUNG BÌNH SAU BÌNH SAI")
        header(["STT", "Từ điểm", "Đến điểm", "vX (m)", "vY (m)", "vZ (m)",
                "dX_Adjusted (m)", "dY_Adjusted (m)", "dZ_Adjusted (m)", "Chiều dài (m)",
                "Số trị đo"])
        for index, baseline in enumerate(baselines, 1):
            vector_row([index, baseline.get("from"), baseline.get("to")],
                       baseline.get("residual_xyz") or baseline.get("residual_neu") or (0, 0, 0),
                       baseline.get("adjusted_xyz") or baseline.get("adjusted_neu") or (0, 0, 0),
                       baseline.get("adjusted_length"), baseline.get("observation_count", 1))

        section("BẢNG 4: VÒNG KHÉP SAU BÌNH SAI (ADJUSTED LOOPS)")
        ws.append(["Ghi chú", "Khép bằng 0 là hệ quả của mô hình bình sai, không phải kiểm tra độc lập dữ liệu gốc."])
        header(["Vòng", "Các điểm", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
                "Tổng chiều dài (m)", "Độ chính xác tương đối"])
        for loop in loops:
            vector_row([loop.get("loop"), " - ".join(loop.get("points", []))],
                       loop.get("adjusted_misclosure_xyz") or (0, 0, 0),
                       loop.get("adjusted_closure"), loop.get("total_length"),
                       relative_precision_text(loop, "adjusted"))

        section("BẢNG 5: ĐIỂM KHỐNG CHẾ (CONTROL POINT)")
        header(["Tên điểm", "X (m)", "Y (m)", "Z (m)", "Cố định"])
        base = data.get("base", {})
        base_name = base.get("name") or "BASE"
        base_label = base_name if base_name == "BASE" else f"{base_name} (alias: BASE)"
        vector_row([base_label], base.get("ecef_xyz") or (None, None, None),
                   bool(base.get("fixed", True)))

        section("BẢNG 6: TỌA ĐỘ ĐIỂM SAU BÌNH SAI (ADJUSTED POINTS)")
        header(["Tên Điểm", "Trạm ID", "X_Adjusted (m)", "Y_Adjusted (m)", "Z_Adjusted (m)",
                "dX: Adjusted - baseline mean from control (m)",
                "dY: Adjusted - baseline mean from control (m)",
                "dZ: Adjusted - baseline mean from control (m)",
                "Std_X ECEF tiên nghiệm (m)", "Std_Y ECEF tiên nghiệm (m)",
                "Std_Z ECEF tiên nghiệm (m)", "Std_X ECEF hậu nghiệm (m)",
                "Std_Y ECEF hậu nghiệm (m)", "Std_Z ECEF hậu nghiệm (m)",
                "Std_E ENU tiên nghiệm (m)", "Std_N ENU tiên nghiệm (m)",
                "Std_U ENU tiên nghiệm (m)", "Std_E ENU hậu nghiệm (m)",
                "Std_N ENU hậu nghiệm (m)", "Std_U ENU hậu nghiệm (m)",
                "X_Raw TB hợp lệ (m)", "Y_Raw TB hợp lệ (m)",
                "Z_Raw TB hợp lệ (m)", "Số Raw dùng", "Số Raw bị loại"])
        for point_name, point in data.get("points", {}).items():
            raw = point.get("raw_rover_ecef") or (None, None, None)
            std_enu = point.get("standard_deviation_enu") or (None, None, None)
            posterior_std_enu = point.get("posterior_standard_deviation_enu") or (
                None, None, None
            )
            ws.append([point_name, point.get("station_id"),
                       point.get("adjusted_x", point.get("adjusted_n")),
                       point.get("adjusted_y", point.get("adjusted_e")),
                       point.get("adjusted_z", point.get("adjusted_u")), point.get("dx"),
                       point.get("dy"), point.get("dz"),
                       point.get("std_x_a_priori", point.get("std_x")),
                       point.get("std_y_a_priori", point.get("std_y")),
                       point.get("std_z_a_priori", point.get("std_z")),
                       point.get("std_x_a_posteriori"),
                       point.get("std_y_a_posteriori"),
                       point.get("std_z_a_posteriori"),
                       std_enu[0], std_enu[1], std_enu[2],
                       posterior_std_enu[0], posterior_std_enu[1],
                       posterior_std_enu[2], raw[0], raw[1], raw[2],
                       point.get("raw_rover_ecef_observation_count"),
                       point.get("raw_rover_ecef_rejected_count", 0)])

        section("BẢNG 7: CHỈ TIÊU CHẤT LƯỢNG")
        header(["Chỉ tiêu", "Giá trị"])
        quality = data.get("quality", {})
        for label, key in (("Tổng số raw nhận được", "raw_observation_count"),
                           ("Raw loại do nguồn chưa xác nhận", "unconfirmed_source_excluded_count"),
                           ("Raw loại trong cửa sổ chuyển nguồn/chờ ổn định", "pre_stable_window_excluded_count"),
                           ("Raw loại do cửa sổ ổn định chưa đủ", "insufficient_stable_window_excluded_count"),
                           ("Raw loại do drift quay lại", "unstable_solver_window_excluded_count"),
                           ("Số raw bị loại", "raw_rejected_count"),
                           ("Số raw bị loại do vector nhảy nghiệm", "vector_outlier_count"),
                           ("Số baseline quan sát dùng bình sai", "observation_baseline_count"),
                           ("Số baseline trung bình hiển thị", "averaged_baseline_count"),
                           ("Số phiên quan sát liên tục", "observation_session_count"),
                           ("Số baseline có STD vượt ngưỡng cảnh báo", "baseline_std_warning_count"),
                           ("Tổng raw vượt ngưỡng STD", "baseline_std_raw_warning_count"),
                           ("Số raw bị loại do STD", "baseline_std_rejected_count"),
                           ("Số raw Type 7 bị loại", "position_type_rejected_count"),
                           ("Số ECEF rover không nhất quán với baseline", "raw_ecef_inconsistent_count"),
                           ("Số ECEF rover lệch thuần phương đứng do hệ cao", "raw_ecef_vertical_datum_offset_count"),
                           ("Số cạnh trộn nhiều position type", "mixed_position_type_edge_count"),
                           ("Bậc tự do", "degrees_of_freedom"),
                           ("Variance factor σ₀² = vTPv/f (không thứ nguyên)", "variance_factor"),
                           ("M0 = σ₀ = √(vTPv/f) (không thứ nguyên)", "reference_standard_deviation"),
                           ("Tổng bình phương số dư có trọng số", "weighted_residual_sum"),
                           ("Rank", "rank"), ("Condition number", "condition_number"),
                           ("Số dư chuẩn hóa tiên nghiệm lớn nhất", "max_standardized_residual")):
            ws.append([label, quality.get(key)])
        quality_gate = data.get("quality_gate") or {}
        ws.append(["Quality gate", quality_gate.get("status")])
        ws.append([
            "Quality interpretation",
            quality_gate.get("interpretation_status") or quality_gate.get("status"),
        ])
        for warning in quality_gate.get("diagnostic_warnings") or []:
            ws.append([
                f"Diagnostic warning: {warning.get('code') or 'WARNING'}",
                warning.get("message"),
            ])
        ws.append(["Vòng khép trước bình sai lớn nhất (m, chỉ chẩn đoán)", quality_gate.get("max_pre_adjustment_loop_closure_m")])
        ws.append(["Cho phép publish tọa độ chính thức", bool(data.get("official_publish_allowed"))])
        if quality.get("global_test"):
            global_test = quality["global_test"]
            ws.append(["Kiểm định chất lượng mạng (phía trên)", "Đạt" if global_test.get("passed") else "Không đạt - số dư lớn"])
            ws.append(["Chi-square statistic", global_test.get("statistic")])
            ws.append(["Chi-square upper critical 95%", global_test.get("upper_critical_value")])
            ws.append(["Chi-square upper-tail p-value", global_test.get("p_value")])
            if not global_test.get("passed"):
                ws.append(["Cảnh báo", "Số dư mạng vượt ngưỡng trên; kiểm tra cạnh yếu, ngoại lai và covariance"])
        if quality.get("stochastic_model_test"):
            stochastic_test = quality["stochastic_model_test"]
            ws.append(["Chẩn đoán mô hình trọng số (hai phía)", stochastic_test.get("status")])
            ws.append(["Chi-square calibration lower", stochastic_test.get("lower_critical_value")])
            ws.append(["Chi-square calibration upper", stochastic_test.get("upper_critical_value")])
            if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
                ws.append(["Ghi chú", "Covariance bảo thủ; đây không phải lỗi chất lượng mạng và không thu nhỏ STD theo M0"])
        trusted_subset = quality.get("trusted_subset") or {}
        if trusted_subset:
            for label, key in (
                ("Trusted subset: số baseline đạt ngưỡng STD", "observation_baseline_count"),
                ("Trusted subset: bậc tự do", "degrees_of_freedom"),
                ("Trusted subset: vTPv", "weighted_residual_sum"),
                ("Trusted subset: M0", "reference_standard_deviation"),
            ):
                if trusted_subset.get(key) is not None:
                    ws.append([label, trusted_subset[key]])
            trusted_test = trusted_subset.get("global_test") or {}
            if trusted_test:
                ws.append(["Trusted subset: kiểm định phương sai", "Đạt" if trusted_test.get("passed") else "Không đạt"])
                ws.append(["Trusted subset: chi-square lower", trusted_test.get("lower_critical_value")])
                ws.append(["Trusted subset: chi-square upper", trusted_test.get("upper_critical_value")])
                ws.append(["Trusted subset: p-value", trusted_test.get("p_value")])
        ws.append(["Scale STD điểm công bố", quality.get("published_point_std_scale", "a_priori")])
        ws.append(["Scale số dư chuẩn hóa", quality.get("normalized_residual_scale", "a_priori")])
        ws.append(["Mô hình covariance baseline", quality.get("baseline_covariance_model")])
        ws.append([
            "Chính sách rolling stability",
            json.dumps(quality.get("rolling_stability_policy") or {}, ensure_ascii=False),
        ])
        ws.append(["Ngưỡng cảnh báo STD baseline (m)", quality.get("baseline_std_warning_threshold_m")])
        ws.append(["Dung sai nhất quán ECEF rover/baseline (m)", quality.get("raw_ecef_consistency_tolerance_m")])
        ws.append(["Ngưỡng tách phiên liên tục (s)", quality.get("observation_session_gap_seconds")])
        ws.append(["Đã lập block covariance ECEF 3x3 sau phép quay", bool(quality.get("full_covariance_available"))])
        ws.append(["AGRICA có covariance chéo gốc NE/EU/NU", bool(quality.get("source_cross_covariance_available"))])
        ws.append(["Đã chứng minh trị đo lặp độc lập", bool(quality.get("repeated_observations_independence_verified"))])
        ws.append(["Đã cộng sai số điểm khống chế", bool(quality.get("control_point_uncertainty_included"))])
        if not quality.get("repeated_observations_independence_verified"):
            ws.append(["Cảnh báo", "Mỗi cạnh chỉ vào solver một lần sau khi lấy trung bình có trọng số; kiểm định chi-square giả định các cạnh trung bình độc lập."])
        if not quality.get("control_point_uncertainty_included"):
            ws.append(["Cảnh báo", "STD điểm chỉ là độ chính xác tương đối so với BASE cố định."])
        if quality.get("baseline_std_rejected_count"):
            ws.append(["Cảnh báo", (
                f"Đã loại {quality.get('baseline_std_rejected_count')} raw vượt ngưỡng STD "
                "khỏi solver; cờ chi tiết nằm ở Bảng 8."
            )])
        if quality.get("raw_ecef_inconsistent_count"):
            ws.append(["Cảnh báo", (
                "ECEF rover không nhất quán đã bị loại khỏi Raw TB, nhưng vector baseline "
                "vẫn được giữ để bình sai nếu đạt các điều kiện chất lượng khác."
            )])
        if quality.get("vector_outlier_count"):
            ws.append(["Cảnh báo", (
                f"Đã loại {quality.get('vector_outlier_count')} raw có vector baseline nhảy nghiệm/sai thô "
                "trước khi lấy trung bình cạnh và trước khi bình sai."
            )])
        mixed_threshold = float(
            quality.get("mixed_position_type_warning_threshold_m") or 0.01
        )
        for mixed_edge in quality.get("mixed_position_type_edges") or []:
            separation = float(mixed_edge.get("mean_separation_m") or 0.0)
            if separation < mixed_threshold:
                continue
            ws.append(["Cảnh báo", (
                f"Cạnh {mixed_edge.get('from')} -> {mixed_edge.get('to')} trộn position type "
                f"{'/'.join(map(str, mixed_edge.get('position_types') or []))}; "
                f"trung bình theo loại nghiệm lệch {separation:.4f} m."
            )])
        for filtered_edge in quality.get("position_type_filter_edges") or []:
            ws.append(["Đã lọc", (
                f"Cạnh {filtered_edge.get('from')} -> {filtered_edge.get('to')}: giữ Position Type "
                f"{filtered_edge.get('selected_position_type')}; loại "
                f"{filtered_edge.get('rejected_count')} raw Type "
                f"{'/'.join(map(str, filtered_edge.get('rejected_position_types') or []))}."
            )])

        section("BẢNG 8: RAW PAYLOAD BẰNG CHỨNG")
        evidence = data.get("baseline_observations") or []
        if evidence:
            header(["STT", "Từ điểm", "Đến điểm", "Session", "Epoch",
                    "Position type", "GPS", "BDS", "GLONASS", "GAL", "Diff age (s)",
                    "Baseline_NStd (m)",
                    "Baseline_EStd (m)", "Baseline_UStd (m)", "Std vận tốc Up (m/s)",
                    "Xigema_ECEF_X rover (không dùng trọng số)",
                    "Xigema_ECEF_Y rover (không dùng trọng số)",
                    "Xigema_ECEF_Z rover (không dùng trọng số)",
                    "Sai lệch ECEF rover/baseline (m)", "Lệch vector cạnh (m)",
                    "Ngưỡng lọc vector (m)", "Cờ chất lượng", "vX (m)",
                    "vY (m)", "vZ (m)", "Max |normalized residual|", "Raw AGRICA"])
            for index, observation in enumerate(evidence, 1):
                residual = observation.get("residual_xyz") or (None, None, None)
                normalized = observation.get("standardized_residual") or ()
                max_normalized = max((abs(float(value)) for value in normalized), default=None)
                baseline_std = observation.get("baseline_std_neu") or (None, None, None)
                rover_position_std = observation.get("rover_position_std_ecef") or (None, None, None)
                ws.append([index, observation.get("from"), observation.get("to"),
                           observation.get("session_id"), observation.get("observation_epoch"),
                           observation.get("position_type"), observation.get("gps_satellites"),
                           observation.get("bds_satellites"), observation.get("glonass_satellites"),
                           observation.get("galileo_satellites"), observation.get("diff_age"),
                           baseline_std[0], baseline_std[1], baseline_std[2],
                           observation.get("velocity_up_std"),
                           rover_position_std[0], rover_position_std[1], rover_position_std[2],
                           observation.get("raw_ecef_consistency_error_m"),
                           observation.get("vector_deviation_from_edge_m"),
                           observation.get("vector_outlier_threshold_m"),
                           ", ".join(observation.get("quality_flags") or []),
                           residual[0], residual[1], residual[2],
                           max_normalized, observation.get("raw_payload")])
        else:
            for line in raw_payload.splitlines():
                ws.append([line])
            if not raw_payload.strip():
                ws.append(["Không có raw payload trong kết quả đầu vào"])

        sessions = quality.get("observation_sessions") or []
        section("BẢNG 9: NHÓM PHIÊN QUAN SÁT LIÊN TỤC")
        ws.append(["Ghi chú", (
            "Các epoch 1 Hz trong cùng cạnh đã được gom thành một trị trung bình có trọng số trước solver; "
            "số epoch không được tính là bậc tự do độc lập."
        )])
        header(["Session", "Từ điểm", "Đến điểm", "Epoch đầu", "Epoch cuối", "Số observation"])
        for session in sessions:
            ws.append([
                session.get("session_id"), session.get("from"), session.get("to"),
                session.get("start_epoch"), session.get("end_epoch"),
                session.get("observation_count"),
            ])
        ws.freeze_panes = "A2"
        for column in ws.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 42)
            ws.column_dimensions[column[0].column_letter].width = max(width, 12)
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000"
        try:
            wb.save(file_path)
        except Exception as exc:
            logger.error("Error saving adjustment Excel %s: %s", file_path, exc, exc_info=True)
            raise
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            raise OSError(f"Adjustment Excel was not created correctly: {file_path}")
        logger.info("GNSS adjustment Excel written: %s (%s bytes)", file_path, os.path.getsize(file_path))
        return file_path

    def _append_adjustment_to_excel(
        self,
        project_id: int,
        timestamp: int,
        data: dict,
        raw_payload: str,
    ):
        """Write the compact XLSX handed to users.

        Its main sections intentionally mirror ``slbskqbs.txt``. Every raw
        AGRICA epoch remains available in the visible ``RAW_AUDIT`` worksheet
        and in the JSON artifact for independent recalculation.
        """
        import datetime
        import os

        import openpyxl
        from openpyxl.cell.cell import MergedCell
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        report_dir = os.path.join(str(BACKEND_DIR), "static", "adjustments")
        os.makedirs(report_dir, exist_ok=True)
        file_path = os.path.join(
            report_dir,
            f"gnss_binh_sai_{project_id}_{timestamp}.xlsx",
        )

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Binh sai"
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"

        title_fill = PatternFill("solid", fgColor="0F4C5C")
        section_fill = PatternFill("solid", fgColor="1F6F78")
        header_fill = PatternFill("solid", fgColor="DDEBF7")
        thin_gray = Side(style="thin", color="B7C9CE")
        table_border = Border(bottom=thin_gray)
        # Keep the human-readable report printable through Total_Cov_Inflation.
        # The detailed used/formal cross-covariances remain available in O:T for
        # on-screen audit without shrinking every printed column to illegibility.
        report_max_column = 14

        def append_title(value):
            sheet.append([value])
            row = sheet.max_row
            sheet.merge_cells(
                start_row=row,
                start_column=1,
                end_row=row,
                end_column=report_max_column,
            )
            cell = sheet.cell(row, 1)
            cell.font = Font(bold=True, color="FFFFFF", size=14)
            cell.fill = title_fill
            cell.alignment = Alignment(horizontal="center")

        def append_section(value):
            sheet.append([])
            sheet.append([value])
            row = sheet.max_row
            sheet.merge_cells(
                start_row=row,
                start_column=1,
                end_row=row,
                end_column=report_max_column,
            )
            cell = sheet.cell(row, 1)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = section_fill

        def append_header(values):
            sheet.append(values)
            for cell in sheet[sheet.max_row]:
                if cell.column > len(values):
                    break
                cell.font = Font(bold=True, color="17324D")
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", wrap_text=True)
                cell.border = table_border

        def values3(value):
            value = value or (None, None, None)
            return [value[index] if index < len(value) else None for index in range(3)]

        def covariance_scaling(baseline):
            observation_count = float(baseline.get("observation_count") or 1.0)
            effective_sample_size = float(
                baseline.get("effective_sample_size") or observation_count
            )
            temporal = baseline.get("temporal_inflation_factor")
            if temporal is None:
                temporal = observation_count / max(effective_sample_size, 1.0)
            scatter = baseline.get("scatter_scale_factor")
            if scatter is None:
                scatter = baseline.get("variance_inflation")
            scatter = float(scatter or 1.0)
            temporal = float(temporal)
            total = baseline.get("total_covariance_inflation_factor")
            if total is None:
                total = temporal * scatter
            return temporal, scatter, float(total)

        def loop_ratio(loop):
            ratio = loop.get("observed_relative_precision")
            return f"1/{float(ratio):.0f}" if ratio else "-"

        computed_at = int(data.get("computed_at") or timestamp)
        dt_obj = datetime.datetime.fromtimestamp(computed_at)
        baselines = list(data.get("baselines") or [])
        loops = list(data.get("loops") or [])
        points = data.get("points") or {}
        base = data.get("base") or {}
        quality = data.get("quality") or {}
        base_name = base.get("name") or "BASE"
        base_label = base_name if base_name == "BASE" else f"{base_name} (BASE)"

        append_title("BÁO CÁO BÌNH SAI MẠNG GNSS - ECEF XYZ")
        # Column A is reserved for STT in all detail tables.  Keeping metadata
        # labels in column B prevents long labels from being clipped by the
        # intentionally narrow STT column.
        sheet.append([None, "Dự án", project_id, "Cụm", data.get("cluster_name") or "-"])
        sheet.append([None, "Thời gian", dt_obj.strftime("%Y-%m-%d %H:%M:%S")])
        sheet.append([
            None,
            "BASE cố định",
            base_label,
            "Số rover",
            data.get("rover_count", len(points)),
        ])

        append_section("CALCULATED BASELINES - BASELINE TRUNG BÌNH")
        append_header([
            "STT", "From_Point", "To_Point", "dX (m)", "dY (m)", "dZ (m)",
            "Std_X (m)", "Std_Y (m)", "Std_Z (m)", "Length (m)", "Raw / n_eff",
            "Temporal_Inflation (n/n_eff)", "Scatter_Scale", "Total_Cov_Inflation",
            "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
        ])
        for index, baseline in enumerate(baselines, 1):
            cov = baseline.get("session_covariance_used_xyz")
            formal_cov = baseline.get("formal_covariance_xyz")
            temporal_scale, scatter_scale, total_scale = covariance_scaling(baseline)
            sheet.append([
                index,
                baseline.get("from"),
                baseline.get("to"),
                *values3(baseline.get("observed_xyz") or baseline.get("observed_neu")),
                *values3(baseline.get("standard_deviation_xyz")),
                baseline.get("observed_length"),
                (
                    f"{baseline.get('observation_count', 1)} / "
                    f"{float(baseline.get('effective_sample_size')):.2f}"
                    if baseline.get("effective_sample_size") is not None
                    else baseline.get("observation_count", 1)
                ),
                temporal_scale,
                scatter_scale,
                total_scale,
                cov[0][1] if cov else None,
                cov[0][2] if cov else None,
                cov[1][2] if cov else None,
                formal_cov[0][1] if formal_cov else None,
                formal_cov[0][2] if formal_cov else None,
                formal_cov[1][2] if formal_cov else None,
            ])

        repeatability_baselines = [
            baseline
            for baseline in baselines
            if int(baseline.get("session_count") or 0) >= 2
            and baseline.get("max_session_mean_difference_xyz") is not None
        ]
        if repeatability_baselines:
            append_section("SESSION REPEATABILITY - ĐỘ LẶP GIỮA CÁC PHIÊN")
            sheet.append([
                None,
                "Ghi chú",
                (
                    "Hiệu vector là mean phiên sau trừ mean phiên trước theo hướng cạnh "
                    "ECEF chuẩn hóa; dấu phụ thuộc thứ tự phiên, còn norm không đổi. Đây là "
                    "diagnostic, không phải sai số tọa độ sau bình sai."
                ),
            ])
            repeatability_note_row = sheet.max_row
            sheet.merge_cells(
                start_row=repeatability_note_row,
                start_column=3,
                end_row=repeatability_note_row,
                end_column=report_max_column,
            )
            append_header([
                "STT", "From_Point", "To_Point", "Cặp phiên",
                "ΔX (mm)", "ΔY (mm)", "ΔZ (mm)", "Norm (mm)",
                "Scatter_Scale", "Chẩn đoán",
            ])
            for index, baseline in enumerate(repeatability_baselines, 1):
                difference = values3(
                    baseline.get("max_session_mean_difference_xyz")
                )
                pair = baseline.get("max_session_mean_pair") or ()
                pair_label = " → ".join(str(value) for value in pair) or "-"
                scatter_scale = covariance_scaling(baseline)[1]
                norm_m = float(
                    baseline.get("max_session_mean_separation_m") or 0.0
                )
                sheet.append([
                    index,
                    baseline.get("from"),
                    baseline.get("to"),
                    pair_label,
                    *(float(value) * 1000.0 for value in difference),
                    norm_m * 1000.0,
                    scatter_scale,
                    "CẢNH BÁO" if scatter_scale > 1.5 else "THAM KHẢO",
                ])

        append_section("FOUND LOOPS - VÒNG KHÉP TRƯỚC BÌNH SAI")
        append_header([
            "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
            "Length (m)", "fs/s",
        ])
        for index, loop in enumerate(loops, 1):
            sheet.append([
                index,
                " - ".join(loop.get("points") or []),
                *values3(loop.get("observed_misclosure_xyz")),
                loop.get("observed_closure"),
                loop.get("total_length"),
                loop_ratio(loop),
            ])

        append_section("ADJUSTMENT RESULT - KẾT QUẢ BÌNH SAI")
        append_section("ADJUSTED BASELINES")
        append_header([
            "STT", "From_Point", "To_Point", "vX (m)", "vY (m)", "vZ (m)",
            "Adj_X (m)", "Adj_Y (m)", "Adj_Z (m)", "Length (m)", "Raw / n_eff",
            "Temporal_Inflation (n/n_eff)", "Scatter_Scale", "Total_Cov_Inflation",
            "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
        ])
        for index, baseline in enumerate(baselines, 1):
            cov = baseline.get("session_covariance_used_xyz")
            formal_cov = baseline.get("formal_covariance_xyz")
            temporal_scale, scatter_scale, total_scale = covariance_scaling(baseline)
            sheet.append([
                index,
                baseline.get("from"),
                baseline.get("to"),
                *values3(baseline.get("residual_xyz") or baseline.get("residual_neu")),
                *values3(baseline.get("adjusted_xyz") or baseline.get("adjusted_neu")),
                baseline.get("adjusted_length"),
                (
                    f"{baseline.get('observation_count', 1)} / "
                    f"{float(baseline.get('effective_sample_size')):.2f}"
                    if baseline.get("effective_sample_size") is not None
                    else baseline.get("observation_count", 1)
                ),
                temporal_scale,
                scatter_scale,
                total_scale,
                cov[0][1] if cov else None,
                cov[0][2] if cov else None,
                cov[1][2] if cov else None,
                formal_cov[0][1] if formal_cov else None,
                formal_cov[0][2] if formal_cov else None,
                formal_cov[1][2] if formal_cov else None,
            ])

        append_section("ADJUSTED LOOPS")
        sheet.append([
            None,
            "Ghi chú",
            (
                "Chỉ liệt kê fundamental cycle basis độc lập theo topology; "
                "các vòng phụ thuộc đã được loại. Closure sau bình sai gần 0 "
                "là hệ quả của mô hình, không phải phép kiểm tra độc lập dữ liệu gốc."
            ),
        ])
        loop_note_row = sheet.max_row
        sheet.merge_cells(
            start_row=loop_note_row,
            start_column=3,
            end_row=loop_note_row,
            end_column=report_max_column,
        )
        append_header([
            "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)",
            "Length (m)", "Kết quả",
        ])
        for index, loop in enumerate(loops, 1):
            sheet.append([
                index,
                " - ".join(loop.get("points") or []),
                *values3(loop.get("adjusted_misclosure_xyz")),
                loop.get("adjusted_closure"),
                loop.get("total_length"),
                "Khép kín" if abs(float(loop.get("adjusted_closure") or 0.0)) < 1e-9 else "Kiểm tra",
            ])

        append_section("CONTROL POINT")
        append_header(["STT", "Point_name", "X (m)", "Y (m)", "Z (m)", "Cố định"])
        sheet.append([1, base_label, *values3(base.get("ecef_xyz")), True])

        append_section("ADJUSTED POINTS")
        append_header([
            "STT", "Point_name", "X (m)", "Y (m)", "Z (m)",
            "Std_X a priori (m)", "Std_Y a priori (m)", "Std_Z a priori (m)",
            "Std_X a posteriori (m)", "Std_Y a posteriori (m)",
            "Std_Z a posteriori (m)", "Raw dùng", "Raw loại",
        ])
        for index, (point_name, point) in enumerate(points.items(), 1):
            sheet.append([
                index,
                point_name,
                point.get("adjusted_x", point.get("adjusted_n")),
                point.get("adjusted_y", point.get("adjusted_e")),
                point.get("adjusted_z", point.get("adjusted_u")),
                point.get("std_x_a_priori", point.get("std_x", point.get("std_n"))),
                point.get("std_y_a_priori", point.get("std_y", point.get("std_e"))),
                point.get("std_z_a_priori", point.get("std_z", point.get("std_u"))),
                point.get("std_x_a_posteriori"),
                point.get("std_y_a_posteriori"),
                point.get("std_z_a_posteriori"),
                point.get("raw_rover_ecef_observation_count"),
                point.get("raw_rover_ecef_rejected_count", 0),
            ])

        append_section("REFERENCE STANDARD DEVIATION / QUALITY")
        append_header(["", "Chỉ tiêu", "Giá trị"])
        quality_value_rows = set()
        quality_warning_rows = set()
        quality_rows = [
            ("Raw nhận được", quality.get("raw_observation_count")),
            ("Raw loại do nguồn chưa xác nhận", quality.get("unconfirmed_source_excluded_count")),
            (
                "Raw loại trước cửa sổ ổn định (EXCLUDE_PRE_STABLE_WINDOW)",
                quality.get("pre_stable_window_excluded_count"),
            ),
            (
                "Raw loại sau chuyển seed/source (EXCLUDE_POST_SEED_TRANSITION)",
                quality.get("post_seed_transition_excluded_count"),
            ),
            (
                "Raw loại khi tái bắt giữa rotation (EXCLUDE_INTER_ROTATION_REACQUISITION)",
                quality.get("inter_rotation_reacquisition_excluded_count"),
            ),
            (
                "Raw loại do thời gian thu chưa đạt tối thiểu",
                quality.get("insufficient_duration_excluded_count"),
            ),
            (
                "Raw loại do cửa sổ ổn định chưa đủ",
                quality.get("insufficient_stable_window_excluded_count"),
            ),
            (
                "Raw loại do drift quay lại",
                quality.get("unstable_solver_window_excluded_count"),
            ),
            ("Raw dùng", quality.get("observation_baseline_count")),
            ("Raw bị loại", quality.get("raw_rejected_count")),
            ("Raw vector sai thô", quality.get("vector_outlier_count")),
            ("Raw loại do STD", quality.get("baseline_std_rejected_count")),
            (
                "Raw STD cao giữ bảo thủ nhờ lặp ổn định",
                quality.get("baseline_std_repeatability_fallback_count"),
            ),
            ("Raw loại Type 7", quality.get("position_type_rejected_count")),
            (
                "Raw ECEF lệch thuần phương đứng do hệ cao",
                quality.get("raw_ecef_vertical_datum_offset_count"),
            ),
            ("Số cạnh trung bình", quality.get("averaged_baseline_count", len(baselines))),
            (
                "Chênh mean giữa các phiên lớn nhất (m, diagnostic)",
                quality.get("max_session_mean_separation_m"),
            ),
            ("Số vòng cơ sở", quality.get("fundamental_loop_count")),
            ("Vòng độc lập chỉ rover-rover", quality.get("rover_only_loop_count")),
            ("Vòng độc lập có BASE", quality.get("base_anchored_loop_count")),
            ("Chiều không gian vòng", quality.get("cycle_space_dimension")),
            ("Rank ma trận vòng", quality.get("fundamental_loop_basis_rank")),
            ("Bậc tự do", quality.get("degrees_of_freedom")),
            (
                "Variance factor σ₀² = vTPv / f (không thứ nguyên)",
                quality.get("variance_factor"),
            ),
            (
                "M0 = σ₀ = √(vTPv / f) (không thứ nguyên)",
                quality.get("reference_standard_deviation"),
            ),
            (
                "M0 quy đổi theo quy ước trọng số đơn vị 1 mm (m)",
                quality.get("reference_standard_deviation_m_at_1mm"),
            ),
            ("Rank", quality.get("rank")),
            ("Condition number", quality.get("condition_number")),
            (
                "Số dư chuẩn hóa tiên nghiệm lớn nhất",
                quality.get("max_standardized_residual"),
            ),
        ]
        quality_gate = data.get("quality_gate") or {}
        quality_rows.extend([
            ("Quality gate", quality_gate.get("status")),
            (
                "Quality interpretation",
                quality_gate.get("interpretation_status") or quality_gate.get("status"),
            ),
            ("Vòng khép trước bình sai lớn nhất (m, chỉ chẩn đoán)", quality_gate.get("max_pre_adjustment_loop_closure_m")),
            ("Cho phép publish tọa độ chính thức", bool(data.get("official_publish_allowed"))),
        ])
        global_test = quality.get("global_test") or {}
        stochastic_test = quality.get("stochastic_model_test") or {}
        independent_test = quality.get("independent_epoch_sensitivity") or {}
        ess_edges = quality.get("effective_sample_size_edges") or []
        if ess_edges:
            effective_sizes = [
                float(edge.get("effective_sample_size"))
                for edge in ess_edges
                if edge.get("effective_sample_size") is not None
            ]
            if effective_sizes:
                quality_rows.extend([
                    ("n_eff nhỏ nhất", min(effective_sizes)),
                    ("n_eff lớn nhất", max(effective_sizes)),
                ])
        if global_test:
            quality_rows.extend([
                (
                    "Kiểm định chất lượng mạng",
                    "ĐẠT" if global_test.get("passed") else "KHÔNG ĐẠT - SỐ DƯ LỚN",
                ),
                (
                    "Ngưỡng trên Chi-square 95%",
                    global_test.get("upper_critical_value"),
                ),
                ("Chi-square statistic = vTPv", global_test.get("statistic")),
                (
                    "Kiểm định Chi-square là xấp xỉ",
                    bool(global_test.get("approximate")),
                ),
            ])
        if stochastic_test:
            stochastic_labels = {
                "CONSERVATIVE_WEIGHTS": "TRỌNG SỐ BẢO THỦ",
                "CONSISTENT": "NHẤT QUÁN",
                "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR": "TRỌNG SỐ QUÁ LẠC QUAN / SAI MÔ HÌNH",
            }
            quality_rows.append((
                "Chẩn đoán mô hình trọng số",
                stochastic_labels.get(
                    stochastic_test.get("status"),
                    stochastic_test.get("status"),
                ),
            ))
            quality_rows.extend([
                (
                    "Cận dưới Chi-square hai phía 95%",
                    stochastic_test.get("lower_critical_value"),
                ),
                (
                    "Cận trên Chi-square hai phía 95%",
                    stochastic_test.get("upper_critical_value"),
                ),
            ])
        if independent_test:
            quality_rows.extend([
                (
                    "Chi-square giả định epoch độc lập",
                    "ĐẠT (tham khảo)" if independent_test.get("passed") else "KHÔNG ĐẠT (tham khảo)",
                ),
                ("vTPv giả định độc lập", independent_test.get("weighted_residual_sum")),
                ("M0 giả định độc lập", independent_test.get("reference_standard_deviation")),
            ])
        for label, value in quality_rows:
            if value is not None:
                sheet.append([None, label, value])
                quality_value_rows.add(sheet.max_row)

        quality_notes = []
        if quality.get("raw_exclusion_reason_counts_overlap"):
            quality_notes.append(
                "Các reason loại raw có thể overlap; không cộng các reason count. "
                f"Raw bị loại unique = {int(quality.get('raw_rejected_count') or 0)}."
            )
        if global_test and global_test.get("approximate"):
            quality_notes.append(
                "Covariance nghiệm chính chỉ tính một trị đo độc lập cho mỗi phiên RTK FIXED "
                "liên tục; các epoch 1 Hz trong cùng phiên không được cộng như các trị đo độc lập. "
                "ACF chỉ được lưu để chẩn đoán độ nhạy."
            )
        if quality.get("source_cross_covariance_available") is False:
            quality_notes.append(
                "Kiểm định Chi-square giả định các baseline trung bình độc lập; "
                "covariance chéo giữa các baseline chưa có. Scatter scale cũng được "
                "ước lượng từ chính dữ liệu nên kết luận thống kê là xấp xỉ."
            )
        if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
            quality_notes.append(
                "vTPv thấp hơn cận dưới hai phía: covariance đang bảo thủ. Đây là cảnh báo "
                "hiệu chỉnh mô hình trọng số, không phải lỗi chất lượng mạng và không dùng M0 "
                "để thu nhỏ STD công bố."
            )
        if global_test and not global_test.get("passed"):
            quality_notes.append(
                "vTPv vượt ngưỡng trên một phía 95%: số dư mạng lớn hơn mức covariance cho phép."
            )
        for fallback_edge in (
            quality.get("baseline_std_repeatability_fallback_edges") or []
        ):
            quality_notes.append(
                (
                    f"Giữ bảo thủ cạnh {fallback_edge.get('from')} - "
                    f"{fallback_edge.get('to')}: "
                    f"{fallback_edge.get('observation_count')} epoch RTK Fixed, "
                    f"độ lặp vector lớn nhất "
                    f"{float(fallback_edge.get('max_vector_deviation_m') or 0.0):.4f} m, "
                    f"sai số nhất quán ECEF lớn nhất "
                    f"{float(fallback_edge.get('max_ecef_consistency_error_m') or 0.0):.4f} m; "
                    "vẫn giữ covariance STD cao gốc để không tăng trọng số."
                )
            )
        for quality_note in quality_notes:
            sheet.append([
                None,
                "Ghi chú",
                quality_note,
            ])
            note_row = sheet.max_row
            sheet.merge_cells(
                start_row=note_row,
                start_column=3,
                end_row=note_row,
                end_column=report_max_column,
            )
            quality_warning_rows.add(note_row)

        for mixed_edge in quality.get("mixed_position_type_edges") or []:
            separation = float(mixed_edge.get("mean_separation_m") or 0.0)
            threshold = float(quality.get("mixed_position_type_warning_threshold_m") or 0.01)
            if separation < threshold:
                continue
            sheet.append([
                None,
                "Cảnh báo",
                (
                    f"{mixed_edge.get('from')} -> {mixed_edge.get('to')} trộn position type "
                    f"{'/'.join(map(str, mixed_edge.get('position_types') or []))}; "
                    f"lệch {separation:.4f} m"
                ),
            ])
            warning_row = sheet.max_row
            sheet.merge_cells(
                start_row=warning_row,
                start_column=3,
                end_row=warning_row,
                end_column=report_max_column,
            )
            quality_warning_rows.add(warning_row)

        for filtered_edge in quality.get("position_type_filter_edges") or []:
            sheet.append([
                None,
                "Đã lọc",
                (
                    f"{filtered_edge.get('from')} -> {filtered_edge.get('to')}: giữ Position Type "
                    f"{filtered_edge.get('selected_position_type')}; loại "
                    f"{filtered_edge.get('rejected_count')} raw Type "
                    f"{'/'.join(map(str, filtered_edge.get('rejected_position_types') or []))}."
                ),
            ])
            filter_row = sheet.max_row
            sheet.merge_cells(
                start_row=filter_row,
                start_column=3,
                end_row=filter_row,
                end_column=report_max_column,
            )
            quality_warning_rows.add(filter_row)

        merged_banner_rows = {
            cell_range.min_row
            for cell_range in sheet.merged_cells.ranges
            if (
                cell_range.min_row == cell_range.max_row
                and cell_range.min_col == 1
                and cell_range.max_col == report_max_column
            )
        }
        for row_index, row in enumerate(sheet.iter_rows(), 1):
            populated = any(
                not isinstance(cell, MergedCell) and cell.value is not None
                for cell in row
            )
            for cell in row:
                if isinstance(cell, MergedCell):
                    continue
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000"
                horizontal = cell.alignment.horizontal
                if horizontal is None:
                    if row_index in merged_banner_rows:
                        horizontal = "center" if row_index == 1 else "left"
                    elif row_index in quality_value_rows and cell.column == 3:
                        horizontal = "right" if isinstance(cell.value, (int, float)) else "left"
                    elif cell.column == 1:
                        horizontal = "center"
                    elif cell.column in (2, 3):
                        horizontal = "left"
                    elif isinstance(cell.value, (int, float)):
                        horizontal = "right"
                    else:
                        horizontal = "left"
                cell.alignment = Alignment(
                    horizontal=horizontal,
                    vertical="center",
                    wrap_text=cell.column in (2, 3) or row_index in quality_warning_rows,
                )
                if populated and row_index not in merged_banner_rows:
                    cell.border = table_border

            if row_index == 1:
                sheet.row_dimensions[row_index].height = 26
            elif row_index in quality_warning_rows:
                sheet.row_dimensions[row_index].height = 34
            elif any(
                not isinstance(cell, MergedCell)
                and cell.column in (2, 3)
                and len(str(cell.value or "")) > 34
                for cell in row
            ):
                sheet.row_dimensions[row_index].height = 32

        # Fixed widths keep all table headings on the same vertical guides.
        # Auto-sizing from the merged title or long warnings previously made
        # columns A/B huge and made correctly placed values look shifted.
        main_column_widths = {
            "A": 8,
            "B": 34,
            "C": 18,
            "D": 15,
            "E": 15,
            "F": 15,
            "G": 15,
            "H": 15,
            "I": 15,
            "J": 15,
            "K": 12,
            "L": 22,
            "M": 15,
            "N": 19,
            "O": 16,
            "P": 16,
            "Q": 16,
            "R": 18,
            "S": 18,
            "T": 18,
        }
        for letter, width in main_column_widths.items():
            sheet.column_dimensions[letter].width = width

        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.page_setup.orientation = "landscape"
        sheet.print_area = (
            f"A1:{get_column_letter(report_max_column)}{sheet.max_row}"
        )
        sheet.print_options.horizontalCentered = True
        sheet.page_margins.left = 0.25
        sheet.page_margins.right = 0.25

        # Preserve every source epoch in the same XLSX for independent
        # recalculation. Keep the compact report as the opening sheet while
        # exposing RAW_AUDIT as a normal tab so users can inspect it directly.
        raw_sheet = workbook.create_sheet("RAW_AUDIT")
        sheet.sheet_properties.tabColor = "1F6F78"
        raw_sheet.sheet_properties.tabColor = "D4A017"
        raw_headers = [
            "Raw_STT", "From_Point", "To_Point", "Session", "Effective_Session_ID", "Rotation_ID", "Stable_Window_ID", "Epoch",
            "Position_Type", "Baseline_N (m)", "Baseline_E (m)", "Baseline_U (m)",
            "Std_N_Raw (m)", "Std_E_Raw (m)", "Std_U_Raw (m)",
            "Std_N_Used (m)", "Std_E_Used (m)", "Std_U_Used (m)",
            "Baseline_dX (m)", "Baseline_dY (m)", "Baseline_dZ (m)",
            "Raw_Base_Lat", "Raw_Base_Lon", "Raw_Base_h (m)",
            "Base_Lat", "Base_Lon", "Base_h (m)",
            "Rover_X (m)", "Rover_Y (m)", "Rover_Z (m)",
            "Rover_StdX_Raw (m)", "Rover_StdY_Raw (m)", "Rover_StdZ_Raw (m)",
            "Rover_StdX_Used (m)", "Rover_StdY_Used (m)", "Rover_StdZ_Used (m)",
            "Vector_Deviation (m)", "Vector_Filter_Threshold (m)", "Vector_Filter_Status",
            "ECEF_Consistency_Error (m)",
            "ECEF_Residual_E (m)", "ECEF_Residual_N (m)", "ECEF_Residual_U (m)",
            "Quality_Flags", "Accepted_For_Solver",
            "Raw_AGRICA",
        ]
        raw_sheet.append(raw_headers)
        for cell in raw_sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = title_fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)

        for raw_index, observation in enumerate(
            data.get("baseline_observations") or [],
            1,
        ):
            flags = list(observation.get("quality_flags") or [])
            rejected = any(
                str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                for flag in flags
            )
            raw_sheet.append([
                raw_index,
                observation.get("from"),
                observation.get("to"),
                observation.get("session_id"),
                observation.get("effective_session_id"),
                observation.get("rotation_index"),
                observation.get("stable_window_index"),
                observation.get("observation_epoch"),
                observation.get("position_type"),
                *values3(observation.get("baseline_neu")),
                *values3(
                    observation.get("baseline_std_neu_raw")
                    if "baseline_std_neu_raw" in observation
                    else observation.get("baseline_std_neu")
                ),
                *values3(observation.get("baseline_std_neu")),
                *values3(observation.get("baseline_ecef_xyz")),
                *values3(observation.get("raw_base_llh")),
                *values3(observation.get("base_llh")),
                *values3(observation.get("rover_ecef")),
                *values3(
                    observation.get("rover_position_std_ecef_raw")
                    if "rover_position_std_ecef_raw" in observation
                    else observation.get("rover_position_std_ecef")
                ),
                *values3(observation.get("rover_position_std_ecef")),
                observation.get("vector_deviation_from_edge_m"),
                observation.get("vector_outlier_threshold_m"),
                observation.get("vector_filter_status"),
                observation.get("raw_ecef_consistency_error_m"),
                *values3(observation.get("raw_ecef_consistency_residual_enu_m")),
                ", ".join(flags),
                not rejected,
                observation.get("raw_payload"),
            ])

        raw_sheet.freeze_panes = "A2"
        raw_sheet.auto_filter.ref = raw_sheet.dimensions
        raw_sheet.sheet_view.showGridLines = False
        for row_index, row in enumerate(raw_sheet.iter_rows(), 1):
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "0.000000000"
                cell.alignment = Alignment(
                    horizontal="center" if row_index == 1 else None,
                    vertical="center" if row_index == 1 else "top",
                    wrap_text=row_index == 1,
                )
        for column_index in range(1, raw_sheet.max_column + 1):
            letter = get_column_letter(column_index)
            if column_index == raw_sheet.max_column:
                raw_sheet.column_dimensions[letter].width = 42
                continue
            max_length = max(
                len(str(raw_sheet.cell(row_index, column_index).value or ""))
                for row_index in range(1, min(raw_sheet.max_row, 250) + 1)
            )
            raw_sheet.column_dimensions[letter].width = min(max(max_length + 2, 11), 24)

        # Defensive cleanup: only these two report tabs are valid.  An empty
        # default Sheet/Sheet1 must never sit between the compact result and raw
        # audit, otherwise Excel's tab strip makes RAW_AUDIT look absent.
        for extra_sheet in list(workbook.worksheets):
            if extra_sheet.title not in {"Binh sai", "RAW_AUDIT"}:
                workbook.remove(extra_sheet)
        workbook.active = 0
        workbook.views[0].activeTab = 0
        workbook.views[0].firstSheet = 0
        sheet.sheet_view.tabSelected = True
        raw_sheet.sheet_view.tabSelected = False

        workbook.save(file_path)
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            raise OSError(f"Adjustment Excel was not created correctly: {file_path}")
        logger.info(
            "Compact GNSS adjustment Excel written: %s (%s bytes)",
            file_path,
            os.path.getsize(file_path),
        )
        return file_path

    @staticmethod
    def _format_adjustment_summary_text(project_id: int, timestamp: int, data: dict) -> str:
        """Build the compact user-facing report without raw AGRICA rows."""
        import datetime

        def number(value, decimals=4):
            if value is None:
                return "-"
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not math.isfinite(numeric):
                return "-"
            return f"{numeric:.{decimals}f}"

        def vector(values, decimals=4):
            values = values or (None, None, None)
            return " ".join(
                number(values[index] if index < len(values) else None, decimals)
                for index in range(3)
            )

        def relative_precision(loop):
            try:
                ratio = float(loop.get("observed_relative_precision"))
            except (TypeError, ValueError):
                return "-"
            return f"1/{ratio:.0f}" if math.isfinite(ratio) and ratio > 0 else "-"

        baselines = list(data.get("baselines") or [])
        loops = list(data.get("loops") or [])
        points = data.get("points") or {}
        quality = data.get("quality") or {}
        base = data.get("base") or {}
        raw_rows = list(data.get("baseline_observations") or [])
        rejected_rows = [
            row for row in raw_rows
            if any(
                str(flag).startswith(("REJECTED_", "EXCLUDE_"))
                for flag in (row.get("quality_flags") or [])
            )
        ]

        raw_total = quality.get("raw_observation_count", len(raw_rows))
        raw_rejected = quality.get("raw_rejected_count", len(rejected_rows))
        raw_used = quality.get("observation_baseline_count")
        if raw_used is None and raw_total is not None:
            raw_used = max(0, int(raw_total) - int(raw_rejected or 0))

        computed_at = data.get("computed_at") or timestamp
        dt_obj = datetime.datetime.fromtimestamp(int(computed_at))
        base_name = base.get("name") or "BASE"
        base_alias = base_name if base_name == "BASE" else f"{base_name} (BASE)"

        lines = [
            "================ BÁO CÁO BÌNH SAI GNSS ================",
            f"Dự án: {project_id} | Cụm: {data.get('cluster_name') or '-'}",
            f"Thời gian: {dt_obj:%Y-%m-%d %H:%M:%S}",
            f"BASE cố định: {base_alias}",
            (
                f"Lat/Lon/h: {number(base.get('lat'), 10)} "
                f"{number(base.get('lon'), 10)} {number(base.get('h'), 4)} m"
            ),
            (
                f"Rover: {data.get('rover_count', len(points))} | Raw: {raw_total} | "
                f"Dùng: {raw_used} | Loại: {raw_rejected} | "
                f"Cạnh trung bình: {len(baselines)} | Vòng khép: {len(loops)}"
            ),
            "",
            "---------------- BASELINE TRUNG BÌNH ----------------",
            "STT  Từ           Đến          dX(m) dY(m) dZ(m)  StdX StdY StdZ  Dài(m)  n",
        ]
        for index, baseline in enumerate(baselines, 1):
            observed = baseline.get("observed_xyz") or baseline.get("observed_neu")
            std = baseline.get("standard_deviation_xyz") or (None, None, None)
            lines.append(
                f"{index:<4} {str(baseline.get('from') or '-'):<12} "
                f"{str(baseline.get('to') or '-'):<12} {vector(observed, 4)}  "
                f"{vector(std, 6)}  {number(baseline.get('observed_length'), 3)}  "
                f"{baseline.get('observation_count', 1)}"
            )

        lines.extend([
            "",
            "---------------- VÒNG KHÉP TRƯỚC BÌNH SAI ----------------",
            "STT  Các điểm  fx(m) fy(m) fz(m)  fs(m)  Tổng dài(m)  Tỷ lệ",
        ])
        if loops:
            for index, loop in enumerate(loops, 1):
                closure_vector = loop.get("observed_misclosure_xyz") or (None, None, None)
                lines.append(
                    f"{index:<4} {' - '.join(loop.get('points') or [])}  "
                    f"{vector(closure_vector, 5)}  "
                    f"{number(loop.get('observed_closure'), 5)}  "
                    f"{number(loop.get('total_length'), 3)}  {relative_precision(loop)}"
                )
        else:
            lines.append("Không tìm thấy vòng khép hình học độc lập.")

        lines.extend([
            "",
            "---------------- BASELINE SAU BÌNH SAI ----------------",
            "STT  Từ           Đến          vX(m) vY(m) vZ(m)  dX'(m) dY'(m) dZ'(m)",
        ])
        for index, baseline in enumerate(baselines, 1):
            residual = baseline.get("residual_xyz") or baseline.get("residual_neu")
            adjusted = baseline.get("adjusted_xyz") or baseline.get("adjusted_neu")
            lines.append(
                f"{index:<4} {str(baseline.get('from') or '-'):<12} "
                f"{str(baseline.get('to') or '-'):<12} {vector(residual, 5)}  "
                f"{vector(adjusted, 4)}"
            )

        lines.extend([
            "",
            "---------------- TỌA ĐỘ SAU BÌNH SAI ----------------",
            (
                "Điểm  X(m) Y(m) Z(m)  Std a priori XYZ(m)  "
                "Std a posteriori XYZ(m)  Raw dùng/loại"
            ),
            f"{base_alias}  {vector(base.get('ecef_xyz'), 6)}  CỐ ĐỊNH",
        ])
        for point_name, point in points.items():
            coordinate = (
                point.get("adjusted_x", point.get("adjusted_n")),
                point.get("adjusted_y", point.get("adjusted_e")),
                point.get("adjusted_z", point.get("adjusted_u")),
            )
            point_std = (
                point.get("std_x_a_priori", point.get("std_x")),
                point.get("std_y_a_priori", point.get("std_y")),
                point.get("std_z_a_priori", point.get("std_z")),
            )
            posterior_point_std = (
                point.get("std_x_a_posteriori"),
                point.get("std_y_a_posteriori"),
                point.get("std_z_a_posteriori"),
            )
            point_used = point.get("raw_rover_ecef_observation_count", "-")
            point_rejected = point.get("raw_rover_ecef_rejected_count", 0)
            lines.append(
                f"{point_name}  {vector(coordinate, 6)}  {vector(point_std, 6)}  "
                f"{vector(posterior_point_std, 6)}  "
                f"{point_used}/{point_rejected}"
            )

        global_test = quality.get("global_test") or {}
        stochastic_test = quality.get("stochastic_model_test") or {}
        independent_test = quality.get("independent_epoch_sensitivity") or {}
        lines.extend([
            "",
            "---------------- CHỈ TIÊU BÌNH SAI ----------------",
            (
                f"Số ẩn: {3 * int(data.get('rover_count', len(points)) or 0)} | "
                f"Bậc tự do: {quality.get('degrees_of_freedom', '-')} | "
                f"vTPv theo phiên: {number(quality.get('weighted_residual_sum'), 6)} | "
                f"σ₀²=vTPv/f: {number(quality.get('variance_factor'), 6)} | "
                f"M0=σ₀ (không thứ nguyên): "
                f"{number(quality.get('reference_standard_deviation'), 6)}"
            ),
            (
                "M0 quy đổi với trọng số đơn vị 1 mm: "
                f"{number(quality.get('reference_standard_deviation_m_at_1mm'), 9)} m"
            ),
            (
                f"Vòng độc lập: {quality.get('fundamental_loop_count', '-')} | "
                f"rover-rover: {quality.get('rover_only_loop_count', '-')} | "
                f"có BASE: {quality.get('base_anchored_loop_count', '-')} | "
                f"rank: {quality.get('fundamental_loop_basis_rank', '-')}"
            ),
            "STD hậu nghiệm = M0 × STD tiên nghiệm; cả hai scale được liệt kê ở trên.",
            (
                f"Rank: {quality.get('rank', '-')} | "
                f"Condition number: {number(quality.get('condition_number'), 6)} | "
                f"Max |số dư chuẩn hóa|: "
                f"{number(quality.get('max_standardized_residual'), 4)}"
            ),
        ])
        if global_test:
            chi_square_status = (
                "ĐẠT" if global_test.get("passed") else "KHÔNG ĐẠT - SỐ DƯ LỚN"
            )
            lines.append(
                f"Kiểm định chất lượng mạng (phía trên): {chi_square_status} | "
                f"Statistic: {number(global_test.get('statistic'), 6)} | "
                f"Ngưỡng trên 95%: {number(global_test.get('upper_critical_value'), 6)} | "
                f"p-value phía trên: {number(global_test.get('p_value'), 9)}"
            )
        if stochastic_test:
            stochastic_labels = {
                "CONSERVATIVE_WEIGHTS": "TRỌNG SỐ BẢO THỦ",
                "CONSISTENT": "NHẤT QUÁN",
                "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR": "TRỌNG SỐ QUÁ LẠC QUAN / SAI MÔ HÌNH",
            }
            lines.append(
                "Chẩn đoán mô hình trọng số (hai phía): "
                f"{stochastic_labels.get(stochastic_test.get('status'), stochastic_test.get('status'))} | "
                f"Khoảng kỳ vọng: [{number(stochastic_test.get('lower_critical_value'), 6)}, "
                f"{number(stochastic_test.get('upper_critical_value'), 6)}]"
            )
        if independent_test:
            lines.append(
                "Chi-square giả định epoch độc lập (chỉ phân tích độ nhạy): "
                f"{'ĐẠT' if independent_test.get('passed') else 'KHÔNG ĐẠT'} | "
                f"vTPv: {number(independent_test.get('weighted_residual_sum'), 6)} | "
                f"M0: {number(independent_test.get('reference_standard_deviation'), 6)}"
            )

        warnings = []
        vector_outlier_count = int(quality.get("vector_outlier_count") or 0)
        if vector_outlier_count:
            warnings.append(
                f"Đã loại {vector_outlier_count} raw có vector baseline nhảy nghiệm/sai thô."
            )
        std_warning_count = int(
            quality.get("baseline_std_raw_warning_count")
            or quality.get("baseline_std_warning_count")
            or 0
        )
        if std_warning_count:
            warnings.append(
                f"Đã loại {std_warning_count} raw vượt ngưỡng STD baseline khỏi solver."
            )
        inconsistent_count = int(quality.get("raw_ecef_inconsistent_count") or 0)
        if inconsistent_count:
            warnings.append(
                f"Có {inconsistent_count} tọa độ rover ECEF không nhất quán với baseline."
            )
        mixed_threshold = float(
            quality.get("mixed_position_type_warning_threshold_m") or 0.01
        )
        mixed_position_type_edges = [
            edge for edge in (quality.get("mixed_position_type_edges") or [])
            if float(edge.get("mean_separation_m") or 0.0) >= mixed_threshold
        ]
        for edge in mixed_position_type_edges:
            warnings.append(
                f"Cạnh {edge.get('from')} -> {edge.get('to')} trộn position type "
                f"{'/'.join(map(str, edge.get('position_types') or []))}; "
                f"hai nghiệm lệch {number(edge.get('mean_separation_m'), 4)} m."
            )
        for edge in quality.get("position_type_filter_edges") or []:
            warnings.append(
                f"Cạnh {edge.get('from')} -> {edge.get('to')}: giữ Position Type "
                f"{edge.get('selected_position_type')}, loại {edge.get('rejected_count')} raw "
                f"Type {'/'.join(map(str, edge.get('rejected_position_types') or []))}."
            )
        if global_test and global_test.get("approximate"):
            warnings.append(
                "Chi-square dùng covariance bảo thủ: mỗi phiên RTK FIXED liên tục chỉ có "
                "n_eff=1; ACF chỉ là chẩn đoán trong JSON audit."
            )
        if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
            warnings.append(
                "vTPv thấp hơn cận dưới hai phía: covariance đang bảo thủ; đây không phải lỗi "
                "chất lượng mạng và không thu nhỏ STD công bố theo M0."
            )
        if global_test and not global_test.get("passed"):
            warnings.append(
                "Số dư mạng vượt ngưỡng Chi-square phía trên 95%; cần kiểm tra cạnh yếu, "
                "ngoại lai và covariance."
            )
        if warnings or rejected_rows:
            lines.extend(["", "---------------- CẢNH BÁO / RAW BỊ LOẠI ----------------"])
            lines.extend(f"- {warning}" for warning in warnings)
            for row in rejected_rows[:20]:
                flags = ",".join(row.get("quality_flags") or [])
                lines.append(
                    f"- {row.get('from', '-')} -> {row.get('to', '-')} | "
                    f"epoch {row.get('observation_epoch', '-')} | {flags} | "
                    f"lệch vector {number(row.get('vector_deviation_from_edge_m'), 3)} m"
                )
            if len(rejected_rows) > 20:
                lines.append(
                    f"- ... và {len(rejected_rows) - 20} raw bị loại khác "
                    "(xem hồ sơ audit)."
                )

        lines.extend([
            "",
            "Ghi chú: Mỗi cạnh chỉ dùng một baseline trung bình có trọng số trong solver.",
            "Raw AGRICA chi tiết không in trong báo cáo này; xem JSON/XLSX audit khi cần truy vết.",
        ])
        return "\n".join(lines) + "\n"

    def _write_adjustment_reports(self, project_id: int, timestamp: int, data: dict) -> dict:
        """Write the report files referenced by the GNSS adjustment interface."""
        import os

        report_dir = os.path.join(str(BACKEND_DIR), "static", "adjustments")
        os.makedirs(report_dir, exist_ok=True)
        audit_name = f"gnss_adjustment_{project_id}_{timestamp}.json"
        audit_path = os.path.join(report_dir, audit_name)
        try:
            with open(audit_path, "w", encoding="utf-8") as report_file:
                json.dump(data, report_file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Error saving GNSS adjustment JSON %s: %s", audit_path, exc, exc_info=True)
            raise
        if not os.path.isfile(audit_path) or os.path.getsize(audit_path) == 0:
            raise OSError(f"Adjustment JSON was not created correctly: {audit_path}")
        logger.info("GNSS adjustment JSON written: %s (%s bytes)", audit_path, os.path.getsize(audit_path))

        excel_path = self._append_adjustment_to_excel(project_id, timestamp, data, "")
        if not excel_path:
            raise OSError("Adjustment Excel exporter did not return an output path")
        report_api_prefix = f"/api/admin/gnss/adjustment/reports/{project_id}"
        excel_url = f"{report_api_prefix}/{os.path.basename(excel_path)}"
        return {
            "report_file_url": excel_url,
            "audit_json_url": f"{report_api_prefix}/{audit_name}",
            "excel_report_url": excel_url,
        }
