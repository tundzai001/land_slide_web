"""GNSS adjustment audit, Excel, and human-readable report generation."""

import datetime
import json
import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

LENGTH_M = "Length (m)"
NOTE_LABEL = "Ghi chú"


def _values3(value):
    value = value or (None, None, None)
    return [value[index] if index < len(value) else None for index in range(3)]


def _covariance_scaling(baseline):
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


def _loop_ratio(loop):
    ratio = loop.get("observed_relative_precision")
    return f"1/{float(ratio):.0f}" if ratio else "-"


def _append_title(sheet, value, report_max_column, title_fill):
    sheet.append([value])
    row = sheet.max_row
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=report_max_column)
    cell = sheet.cell(row, 1)
    cell.font = Font(bold=True, color="FFFFFF", size=14)
    cell.fill = title_fill
    cell.alignment = Alignment(horizontal="center")


def _append_section(sheet, value, report_max_column, section_fill):
    sheet.append([])
    sheet.append([value])
    row = sheet.max_row
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=report_max_column)
    cell = sheet.cell(row, 1)
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = section_fill


def _append_header(sheet, values, header_fill, table_border):
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        if cell.column > len(values):
            break
        cell.font = Font(bold=True, color="17324D")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = table_border



def _cov_triplets(cov):
    if not cov:
        return None, None, None
    return cov[0][1], cov[0][2], cov[1][2]


def _build_baseline_row(index, baseline, is_adjusted=False):
    temporal_scale, scatter_scale, total_scale = _covariance_scaling(baseline)
    eff_size = baseline.get("effective_sample_size")
    eff_size_str = (
        f"{baseline.get('observation_count', 1)} / {float(eff_size):.2f}"
        if eff_size is not None
        else baseline.get("observation_count", 1)
    )
    cov1 = _cov_triplets(baseline.get("session_covariance_used_xyz"))
    cov2 = _cov_triplets(baseline.get("formal_covariance_xyz"))
    if is_adjusted:
        vec1 = _values3(baseline.get("residual_xyz") or baseline.get("residual_neu"))
        vec2 = _values3(baseline.get("adjusted_xyz") or baseline.get("adjusted_neu"))
        length = baseline.get("adjusted_length")
    else:
        vec1 = _values3(baseline.get("observed_xyz") or baseline.get("observed_neu"))
        vec2 = _values3(baseline.get("standard_deviation_xyz"))
        length = baseline.get("observed_length")
    return [
        index, baseline.get("from"), baseline.get("to"),
        *vec1, *vec2, length, eff_size_str,
        temporal_scale, scatter_scale, total_scale,
        *cov1, *cov2
    ]

def _write_general_info_and_baselines(sheet, project_id: int, timestamp: int, data: dict, report_max_column, title_fill, section_fill, header_fill, table_border):
    computed_at = int(data.get("computed_at") or timestamp)
    dt_obj = datetime.datetime.fromtimestamp(computed_at)
    baselines = list(data.get("baselines") or [])
    points = data.get("points") or {}
    base = data.get("base") or {}
    base_name = base.get("name") or "BASE"
    base_label = base_name if base_name == "BASE" else f"{base_name} (BASE)"

    _append_title(sheet, "BÁO CÁO BÌNH SAI MẠNG GNSS - ECEF XYZ", report_max_column, title_fill)
    sheet.append([None, "Dự án", project_id, "Cụm", data.get("cluster_name") or "-"])
    sheet.append([None, "Thời gian", dt_obj.strftime("%Y-%m-%d %H:%M:%S")])
    sheet.append([None, "BASE cố định", base_label, "Số rover", data.get("rover_count", len(points))])

    _append_section(sheet, "CALCULATED BASELINES - BASELINE TRUNG BÌNH", report_max_column, section_fill)
    _append_header(sheet, [
        "STT", "From_Point", "To_Point", "dX (m)", "dY (m)", "dZ (m)",
        "Std_X (m)", "Std_Y (m)", "Std_Z (m)", LENGTH_M, "Raw / n_eff",
        "Temporal_Inflation (n/n_eff)", "Scatter_Scale", "Total_Cov_Inflation",
        "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
    ], header_fill, table_border)

    for index, baseline in enumerate(baselines, 1):
        sheet.append(_build_baseline_row(index, baseline, is_adjusted=False))
    return base, points, base_label


def _write_repeatability_section(sheet, baselines: list, report_max_column, section_fill, header_fill, table_border):
    repeatability_baselines = [
        baseline for baseline in baselines
        if int(baseline.get("session_count") or 0) >= 2
        and baseline.get("max_session_mean_difference_xyz") is not None
    ]
    if not repeatability_baselines:
        return
    _append_section(sheet, "SESSION REPEATABILITY - ĐỘ LẶP GIỮA CÁC PHIÊN", report_max_column, section_fill)
    sheet.append([
        None, NOTE_LABEL,
        (
            "Hiệu vector là mean phiên sau trừ mean phiên trước theo hướng cạnh "
            "ECEF chuẩn hóa; dấu phụ thuộc thứ tự phiên, còn norm không đổi. Đây là "
            "diagnostic, không phải sai số tọa độ sau bình sai."
        ),
    ])
    note_row = sheet.max_row
    sheet.merge_cells(start_row=note_row, start_column=3, end_row=note_row, end_column=report_max_column)
    _append_header(sheet, [
        "STT", "From_Point", "To_Point", "Cặp phiên",
        "ΔX (mm)", "ΔY (mm)", "ΔZ (mm)", "Norm (mm)",
        "Scatter_Scale", "Chẩn đoán",
    ], header_fill, table_border)
    for index, baseline in enumerate(repeatability_baselines, 1):
        diff = _values3(baseline.get("max_session_mean_difference_xyz"))
        pair = baseline.get("max_session_mean_pair") or ()
        pair_label = " → ".join(str(v) for v in pair) or "-"
        scatter_scale = _covariance_scaling(baseline)[1]
        norm_m = float(baseline.get("max_session_mean_separation_m") or 0.0)
        sheet.append([
            index, baseline.get("from"), baseline.get("to"), pair_label,
            *(float(v) * 1000.0 for v in diff), norm_m * 1000.0,
            scatter_scale, "CẢNH BÁO" if scatter_scale > 1.5 else "THAM KHẢO",
        ])


def _write_loops_section(sheet, loops: list, report_max_column, section_fill, header_fill, table_border):
    _append_section(sheet, "FOUND LOOPS - VÒNG KHÉP TRƯỚC BÌNH SAI", report_max_column, section_fill)
    _append_header(sheet, [
        "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)", LENGTH_M, "fs/s",
    ], header_fill, table_border)
    for index, loop in enumerate(loops, 1):
        sheet.append([
            index, " - ".join(loop.get("points") or []),
            *_values3(loop.get("observed_misclosure_xyz")),
            loop.get("observed_closure"), loop.get("total_length"), _loop_ratio(loop),
        ])


def _write_adjusted_baselines_section(sheet, baselines: list, report_max_column, section_fill, header_fill, table_border):
    _append_section(sheet, "ADJUSTMENT RESULT - KẾT QUẢ BÌNH SAI", report_max_column, section_fill)
    _append_section(sheet, "ADJUSTED BASELINES", report_max_column, section_fill)
    _append_header(sheet, [
        "STT", "From_Point", "To_Point", "vX (m)", "vY (m)", "vZ (m)",
        "Adj_X (m)", "Adj_Y (m)", "Adj_Z (m)", LENGTH_M, "Raw / n_eff",
        "Temporal_Inflation (n/n_eff)", "Scatter_Scale", "Total_Cov_Inflation",
        "Cov_XY", "Cov_XZ", "Cov_YZ", "Formal_Cov_XY", "Formal_Cov_XZ", "Formal_Cov_YZ"
    ], header_fill, table_border)
    for index, baseline in enumerate(baselines, 1):
        sheet.append(_build_baseline_row(index, baseline, is_adjusted=True))


def _write_adjusted_loops_and_points(sheet, loops: list, base: dict, points: dict, base_label: str, report_max_column, section_fill, header_fill, table_border):
    _append_section(sheet, "ADJUSTED LOOPS", report_max_column, section_fill)
    sheet.append([
        None, NOTE_LABEL,
        (
            "Chỉ liệt kê fundamental cycle basis độc lập theo topology; "
            "các vòng phụ thuộc đã được loại. Closure sau bình sai gần 0 "
            "là hệ quả của mô hình, không phải phép kiểm tra độc lập dữ liệu gốc."
        ),
    ])
    note_row = sheet.max_row
    sheet.merge_cells(start_row=note_row, start_column=3, end_row=note_row, end_column=report_max_column)
    _append_header(sheet, [
        "STT", "List of Point", "fx (m)", "fy (m)", "fz (m)", "fs (m)", LENGTH_M, "Kết quả",
    ], header_fill, table_border)
    for index, loop in enumerate(loops, 1):
        sheet.append([
            index, " - ".join(loop.get("points") or []),
            *_values3(loop.get("adjusted_misclosure_xyz")),
            loop.get("adjusted_closure"), loop.get("total_length"),
            "Khép kín" if abs(float(loop.get("adjusted_closure") or 0.0)) < 1e-9 else "Kiểm tra",
        ])

    _append_section(sheet, "CONTROL POINT", report_max_column, section_fill)
    _append_header(sheet, ["STT", "Point_name", "X (m)", "Y (m)", "Z (m)", "Cố định"], header_fill, table_border)
    sheet.append([1, base_label, *_values3(base.get("ecef_xyz")), True])

    _append_section(sheet, "ADJUSTED POINTS", report_max_column, section_fill)
    _append_header(sheet, [
        "STT", "Point_name", "X (m)", "Y (m)", "Z (m)",
        "Std_X a priori (m)", "Std_Y a priori (m)", "Std_Z a priori (m)",
        "Std_X a posteriori (m)", "Std_Y a posteriori (m)",
        "Std_Z a posteriori (m)", "Raw dùng", "Raw loại",
    ], header_fill, table_border)
    for index, (point_name, point) in enumerate(points.items(), 1):
        sheet.append([
            index, point_name,
            point.get("adjusted_x", point.get("adjusted_n")),
            point.get("adjusted_y", point.get("adjusted_e")),
            point.get("adjusted_z", point.get("adjusted_u")),
            point.get("std_x_a_priori", point.get("std_x", point.get("std_n"))),
            point.get("std_y_a_priori", point.get("std_y", point.get("std_e"))),
            point.get("std_z_a_priori", point.get("std_z", point.get("std_u"))),
            point.get("std_x_a_posteriori"), point.get("std_y_a_posteriori"),
            point.get("std_z_a_posteriori"),
            point.get("raw_rover_ecef_observation_count"),
            point.get("raw_rover_ecef_rejected_count", 0),
        ])


def _collect_quality_rows(quality: dict, data: dict, baselines: list) -> list:
    quality_rows = [
        ("Raw nhận được", quality.get("raw_observation_count")),
        ("Raw loại do nguồn chưa xác nhận", quality.get("unconfirmed_source_excluded_count")),
        ("Raw loại trước cửa sổ ổn định (EXCLUDE_PRE_STABLE_WINDOW)", quality.get("pre_stable_window_excluded_count")),
        ("Raw loại sau chuyển seed/source (EXCLUDE_POST_SEED_TRANSITION)", quality.get("post_seed_transition_excluded_count")),
        ("Raw loại khi tái bắt giữa rotation (EXCLUDE_INTER_ROTATION_REACQUISITION)", quality.get("inter_rotation_reacquisition_excluded_count")),
        ("Raw loại do thời gian thu chưa đạt tối thiểu", quality.get("insufficient_duration_excluded_count")),
        ("Raw loại do cửa sổ ổn định chưa đủ", quality.get("insufficient_stable_window_excluded_count")),
        ("Raw loại do drift quay lại", quality.get("unstable_solver_window_excluded_count")),
        ("Raw dùng", quality.get("observation_baseline_count")),
        ("Raw bị loại", quality.get("raw_rejected_count")),
        ("Raw vector sai thô", quality.get("vector_outlier_count")),
        ("Raw loại do STD", quality.get("baseline_std_rejected_count")),
        ("Raw STD cao giữ bảo thủ nhờ lặp ổn định", quality.get("baseline_std_repeatability_fallback_count")),
        ("Raw loại Type 7", quality.get("position_type_rejected_count")),
        ("Raw ECEF lệch thuần phương đứng do hệ cao", quality.get("raw_ecef_vertical_datum_offset_count")),
        ("Số cạnh trung bình", quality.get("averaged_baseline_count", len(baselines))),
        ("Chênh mean giữa các phiên lớn nhất (m, diagnostic)", quality.get("max_session_mean_separation_m")),
        ("Số vòng cơ sở", quality.get("fundamental_loop_count")),
        ("Vòng độc lập chỉ rover-rover", quality.get("rover_only_loop_count")),
        ("Vòng độc lập có BASE", quality.get("base_anchored_loop_count")),
        ("Chiều không gian vòng", quality.get("cycle_space_dimension")),
        ("Rank ma trận vòng", quality.get("fundamental_loop_basis_rank")),
        ("Bậc tự do", quality.get("degrees_of_freedom")),
        ("Variance factor σ₀² = vTPv / f (không thứ nguyên)", quality.get("variance_factor")),
        ("M0 = σ₀ = √(vTPv / f) (không thứ nguyên)", quality.get("reference_standard_deviation")),
        ("M0 quy đổi theo quy ước trọng số đơn vị 1 mm (m)", quality.get("reference_standard_deviation_m_at_1mm")),
        ("Rank", quality.get("rank")),
        ("Condition number", quality.get("condition_number")),
        ("Số dư chuẩn hóa tiên nghiệm lớn nhất", quality.get("max_standardized_residual")),
    ]
    quality_gate = data.get("quality_gate") or {}
    quality_rows.extend([
        ("Quality gate", quality_gate.get("status")),
        ("Quality interpretation", quality_gate.get("interpretation_status") or quality_gate.get("status")),
        ("Vòng khép trước bình sai lớn nhất (m, chỉ chẩn đoán)", quality_gate.get("max_pre_adjustment_loop_closure_m")),
        ("Cho phép publish tọa độ chính thức", bool(data.get("official_publish_allowed"))),
    ])
    quality_rows.extend(_collect_test_rows(quality))
    return quality_rows


def _collect_test_rows(quality: dict) -> list:
    rows = []
    ess_edges = quality.get("effective_sample_size_edges") or []
    if ess_edges:
        effective_sizes = [float(e.get("effective_sample_size")) for e in ess_edges if e.get("effective_sample_size") is not None]
        if effective_sizes:
            rows.extend([("n_eff nhỏ nhất", min(effective_sizes)), ("n_eff lớn nhất", max(effective_sizes))])
    global_test = quality.get("global_test") or {}
    if global_test:
        rows.extend([
            ("Kiểm định chất lượng mạng", "ĐẠT" if global_test.get("passed") else "KHÔNG ĐẠT - SỐ DƯ LỚN"),
            ("Ngưỡng trên Chi-square 95%", global_test.get("upper_critical_value")),
            ("Chi-square statistic = vTPv", global_test.get("statistic")),
            ("Kiểm định Chi-square là xấp xỉ", bool(global_test.get("approximate"))),
        ])
    stochastic_test = quality.get("stochastic_model_test") or {}
    if stochastic_test:
        stochastic_labels = {"CONSERVATIVE_WEIGHTS": "TRỌNG SỐ BẢO THỦ", "CONSISTENT": "NHẤT QUÁN", "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR": "TRỌNG SỐ QUÁ LẠC QUAN / SAI MÔ HÌNH"}
        rows.append(("Chẩn đoán mô hình trọng số", stochastic_labels.get(stochastic_test.get("status"), stochastic_test.get("status"))))
        rows.extend([
            ("Cận dưới Chi-square hai phía 95%", stochastic_test.get("lower_critical_value")),
            ("Cận trên Chi-square hai phía 95%", stochastic_test.get("upper_critical_value")),
        ])
    independent_test = quality.get("independent_epoch_sensitivity") or {}
    if independent_test:
        rows.extend([
            ("Chi-square giả định epoch độc lập", "ĐẠT (tham khảo)" if independent_test.get("passed") else "KHÔNG ĐẠT (tham khảo)"),
            ("vTPv giả định độc lập", independent_test.get("weighted_residual_sum")),
            ("M0 giả định độc lập", independent_test.get("reference_standard_deviation")),
        ])
    return rows


def _collect_quality_notes(quality: dict) -> list[str]:
    notes = []
    if quality.get("raw_exclusion_reason_counts_overlap"):
        notes.append(f"Các reason loại raw có thể overlap; không cộng các reason count. Raw bị loại unique = {int(quality.get('raw_rejected_count') or 0)}.")
    global_test = quality.get("global_test") or {}
    if global_test and global_test.get("approximate"):
        notes.append("Covariance nghiệm chính chỉ tính một trị đo độc lập cho mỗi phiên RTK FIXED liên tục; các epoch 1 Hz trong cùng phiên không được cộng như các trị đo độc lập. ACF chỉ được lưu để chẩn đoán độ nhạy.")
    if quality.get("source_cross_covariance_available") is False:
        notes.append("Kiểm định Chi-square giả định các baseline trung bình độc lập; covariance chéo giữa các baseline chưa có. Scatter scale cũng được ước lượng từ chính dữ liệu nên kết luận thống kê là xấp xỉ.")
    stochastic_test = quality.get("stochastic_model_test") or {}
    if stochastic_test.get("status") == "CONSERVATIVE_WEIGHTS":
        notes.append("vTPv thấp hơn cận dưới hai phía: covariance đang bảo thủ. Đây là cảnh báo hiệu chỉnh mô hình trọng số, không phải lỗi chất lượng mạng và không dùng M0 để thu nhỏ STD công bố.")
    if global_test and not global_test.get("passed"):
        notes.append("vTPv vượt ngưỡng trên một phía 95%: số dư mạng lớn hơn mức covariance cho phép.")
    for fallback_edge in (quality.get("baseline_std_repeatability_fallback_edges") or []):
        notes.append(
            f"Giữ bảo thủ cạnh {fallback_edge.get('from')} - {fallback_edge.get('to')}: {fallback_edge.get('observation_count')} epoch RTK Fixed, "
            f"độ lặp vector lớn nhất {float(fallback_edge.get('max_vector_deviation_m') or 0.0):.4f} m, sai số nhất quán ECEF lớn nhất {float(fallback_edge.get('max_ecef_consistency_error_m') or 0.0):.4f} m; vẫn giữ covariance STD cao gốc để không tăng trọng số."
        )
    return notes


def _write_quality_section(sheet, quality: dict, data: dict, baselines: list, report_max_column, section_fill, header_fill, table_border):
    _append_section(sheet, "REFERENCE STANDARD DEVIATION / QUALITY", report_max_column, section_fill)
    _append_header(sheet, ["", "Chỉ tiêu", "Giá trị"], header_fill, table_border)
    quality_value_rows = set()
    quality_warning_rows = set()

    for label, value in _collect_quality_rows(quality, data, baselines):
        if value is not None:
            sheet.append([None, label, value])
            quality_value_rows.add(sheet.max_row)

    for note in _collect_quality_notes(quality):
        sheet.append([None, NOTE_LABEL, note])
        nr = sheet.max_row
        sheet.merge_cells(start_row=nr, start_column=3, end_row=nr, end_column=report_max_column)
        quality_warning_rows.add(nr)

    for mixed_edge in quality.get("mixed_position_type_edges") or []:
        separation = float(mixed_edge.get("mean_separation_m") or 0.0)
        if separation >= float(quality.get("mixed_position_type_warning_threshold_m") or 0.01):
            sheet.append([None, "Cảnh báo", f"{mixed_edge.get('from')} -> {mixed_edge.get('to')} trộn position type {'/'.join(map(str, mixed_edge.get('position_types') or []))}; lệch {separation:.4f} m"])
            nr = sheet.max_row
            sheet.merge_cells(start_row=nr, start_column=3, end_row=nr, end_column=report_max_column)
            quality_warning_rows.add(nr)

    for filtered_edge in quality.get("position_type_filter_edges") or []:
        sheet.append([None, "Đã lọc", f"{filtered_edge.get('from')} -> {filtered_edge.get('to')}: giữ Position Type {filtered_edge.get('selected_position_type')}; loại {filtered_edge.get('rejected_count')} raw Type {'/'.join(map(str, filtered_edge.get('rejected_position_types') or []))}."])
        nr = sheet.max_row
        sheet.merge_cells(start_row=nr, start_column=3, end_row=nr, end_column=report_max_column)
        quality_warning_rows.add(nr)

    return quality_value_rows, quality_warning_rows


def _resolve_cell_horizontal_align(cell, row_index, merged_banner_rows, quality_value_rows):
    if cell.alignment.horizontal is not None:
        return cell.alignment.horizontal
    if row_index in merged_banner_rows:
        return "center" if row_index == 1 else "left"
    if row_index in quality_value_rows and cell.column == 3:
        return "right" if isinstance(cell.value, (int, float)) else "left"
    if cell.column == 1:
        return "center"
    if cell.column in (2, 3):
        return "left"
    return "right" if isinstance(cell.value, (int, float)) else "left"


def _format_single_cell(cell, row_index, merged_banner_rows, quality_value_rows, quality_warning_rows, populated, table_border):
    if isinstance(cell, MergedCell):
        return
    if isinstance(cell.value, float):
        cell.number_format = "0.000000"
    horizontal = _resolve_cell_horizontal_align(cell, row_index, merged_banner_rows, quality_value_rows)
    wrap = cell.column in (2, 3) or row_index in quality_warning_rows
    cell.alignment = Alignment(horizontal=horizontal, vertical="center", wrap_text=wrap)
    if populated and row_index not in merged_banner_rows:
        cell.border = table_border


def _adjust_row_height(sheet, row_index, row, quality_warning_rows):
    if row_index == 1:
        sheet.row_dimensions[row_index].height = 26
    elif row_index in quality_warning_rows:
        sheet.row_dimensions[row_index].height = 34
    elif any(not isinstance(c, MergedCell) and c.column in (2, 3) and len(str(c.value or "")) > 34 for c in row):
        sheet.row_dimensions[row_index].height = 32


def _format_report_sheet(sheet, report_max_column, table_border, quality_value_rows, quality_warning_rows):
    merged_banner_rows = {
        cell_range.min_row for cell_range in sheet.merged_cells.ranges
        if cell_range.min_row == cell_range.max_row and cell_range.min_col == 1 and cell_range.max_col == report_max_column
    }
    for row_index, row in enumerate(sheet.iter_rows(), 1):
        populated = any(not isinstance(cell, MergedCell) and cell.value is not None for cell in row)
        for cell in row:
            _format_single_cell(cell, row_index, merged_banner_rows, quality_value_rows, quality_warning_rows, populated, table_border)
        _adjust_row_height(sheet, row_index, row, quality_warning_rows)

    main_column_widths = {
        "A": 8, "B": 34, "C": 18, "D": 15, "E": 15, "F": 15, "G": 15, "H": 15,
        "I": 15, "J": 15, "K": 12, "L": 22, "M": 15, "N": 19, "O": 16,
        "P": 16, "Q": 16, "R": 18, "S": 18, "T": 18,
    }
    for letter, width in main_column_widths.items():
        sheet.column_dimensions[letter].width = width

    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_setup.orientation = "landscape"
    sheet.print_area = f"A1:{get_column_letter(report_max_column)}{sheet.max_row}"
    sheet.print_options.horizontalCentered = True
    sheet.page_margins.left = 0.25
    sheet.page_margins.right = 0.25


def _build_raw_observation_row(raw_index, observation):
    flags = list(observation.get("quality_flags") or [])
    rejected = any(str(flag).startswith(("REJECTED_", "EXCLUDE_")) for flag in flags)
    std_neu_raw = observation.get("baseline_std_neu_raw") if "baseline_std_neu_raw" in observation else observation.get("baseline_std_neu")
    rover_std_raw = observation.get("rover_position_std_ecef_raw") if "rover_position_std_ecef_raw" in observation else observation.get("rover_position_std_ecef")
    return [
        raw_index, observation.get("from"), observation.get("to"),
        observation.get("session_id"), observation.get("effective_session_id"),
        observation.get("rotation_index"), observation.get("stable_window_index"),
        observation.get("observation_epoch"), observation.get("position_type"),
        *_values3(observation.get("baseline_neu")),
        *_values3(std_neu_raw),
        *_values3(observation.get("baseline_std_neu")),
        *_values3(observation.get("baseline_ecef_xyz")),
        *_values3(observation.get("raw_base_llh")),
        *_values3(observation.get("base_llh")),
        *_values3(observation.get("rover_ecef")),
        *_values3(rover_std_raw),
        *_values3(observation.get("rover_position_std_ecef")),
        observation.get("vector_deviation_from_edge_m"), observation.get("vector_outlier_threshold_m"),
        observation.get("vector_filter_status"), observation.get("raw_ecef_consistency_error_m"),
        *_values3(observation.get("raw_ecef_consistency_residual_enu_m")),
        ", ".join(flags), not rejected, observation.get("raw_payload"),
    ]


def _format_raw_sheet_cells(raw_sheet):
    raw_sheet.freeze_panes = "A2"
    raw_sheet.auto_filter.ref = raw_sheet.dimensions
    raw_sheet.sheet_view.showGridLines = False
    for row_index, row in enumerate(raw_sheet.iter_rows(), 1):
        is_first = row_index == 1
        for cell in row:
            if isinstance(cell.value, float):
                cell.number_format = "0.000000000"
            cell.alignment = Alignment(
                horizontal="center" if is_first else None,
                vertical="center" if is_first else "top",
                wrap_text=is_first,
            )


def _format_raw_sheet_columns(raw_sheet):
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


def _format_raw_sheet_cells_and_columns(raw_sheet):
    _format_raw_sheet_cells(raw_sheet)
    _format_raw_sheet_columns(raw_sheet)


def _populate_raw_audit_sheet(raw_sheet, data: dict, title_fill):
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

    for raw_index, observation in enumerate(data.get("baseline_observations") or [], 1):
        raw_sheet.append(_build_raw_observation_row(raw_index, observation))

    _format_raw_sheet_cells_and_columns(raw_sheet)


class AdjustmentReportMixin:
    def _append_adjustment_to_excel(
        self,
        project_id: int,
        timestamp: int,
        data: dict,
        _raw_payload: str,
        *,
        output_stream,
    ):
        """Build the compact XLSX handed to users."""
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
        report_max_column = 14

        baselines = list(data.get("baselines") or [])
        loops = list(data.get("loops") or [])
        quality = data.get("quality") or {}

        base, points, base_label = _write_general_info_and_baselines(
            sheet, project_id, timestamp, data, report_max_column,
            title_fill, section_fill, header_fill, table_border
        )
        _write_repeatability_section(sheet, baselines, report_max_column, section_fill, header_fill, table_border)
        _write_loops_section(sheet, loops, report_max_column, section_fill, header_fill, table_border)
        _write_adjusted_baselines_section(sheet, baselines, report_max_column, section_fill, header_fill, table_border)
        _write_adjusted_loops_and_points(sheet, loops, base, points, base_label, report_max_column, section_fill, header_fill, table_border)
        quality_value_rows, quality_warning_rows = _write_quality_section(
            sheet, quality, data, baselines, report_max_column, section_fill, header_fill, table_border
        )
        _format_report_sheet(sheet, report_max_column, table_border, quality_value_rows, quality_warning_rows)

        raw_sheet = workbook.create_sheet("RAW_AUDIT")
        sheet.sheet_properties.tabColor = "1F6F78"
        raw_sheet.sheet_properties.tabColor = "D4A017"
        _populate_raw_audit_sheet(raw_sheet, data, title_fill)

        for extra_sheet in tuple(workbook.worksheets):
            if extra_sheet.title not in {"Binh sai", "RAW_AUDIT"}:
                workbook.remove(extra_sheet)
        workbook.active = 0
        workbook.views[0].activeTab = 0
        workbook.views[0].firstSheet = 0
        sheet.sheet_view.tabSelected = True
        raw_sheet.sheet_view.tabSelected = False

        workbook.save(output_stream)
        output_stream.seek(0)
        return output_stream
