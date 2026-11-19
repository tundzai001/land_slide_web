"""GNSS adjustment audit, Excel, and human-readable report generation."""

LENGTH_M = "Length (m)"
NOTE_LABEL = "Ghi chú"


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
        """Build the compact XLSX handed to users.

        Its main sections intentionally mirror ``slbskqbs.txt``. Every raw
        AGRICA epoch remains available in the visible ``RAW_AUDIT`` worksheet
        when the caller supplies the evidence for an on-demand export.
        """
        import datetime

        import openpyxl
        from openpyxl.cell.cell import MergedCell
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

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
            "Std_X (m)", "Std_Y (m)", "Std_Z (m)", LENGTH_M, "Raw / n_eff",
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
                NOTE_LABEL,
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
            LENGTH_M, "fs/s",
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
            "Adj_X (m)", "Adj_Y (m)", "Adj_Z (m)", LENGTH_M, "Raw / n_eff",
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
            NOTE_LABEL,
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
            LENGTH_M, "Kết quả",
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
                NOTE_LABEL,
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

        workbook.save(output_stream)
        output_stream.seek(0)
        return output_stream
