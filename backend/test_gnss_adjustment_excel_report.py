import sys
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from openpyxl import load_workbook

BACKEND_DIRECTORY = Path(__file__).resolve().parent
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from mqtt_bridge import MQTTBridge


class GnssAdjustmentExcelReportTests(unittest.TestCase):
    def test_user_report_is_one_compact_xlsx_without_raw_payload_rows(self):
        data = {
            "computed_at": 1700000000,
            "cluster_name": "Dam 1",
            "rover_count": 1,
            "adjustment_engine": "test",
            "base": {
                "name": "SinQuyen1",
                "fixed": True,
                "lat": 22.0,
                "lon": 103.0,
                "h": 150.0,
                "ecef_xyz": (1.0, 2.0, 3.0),
            },
            "baselines": [{
                "from": "BASE",
                "to": "Dap1_2",
                "observed_xyz": (211.5967, -95.5708, 285.1738),
                "adjusted_xyz": (211.5960, -95.5710, 285.1740),
                "residual_xyz": (-0.0007, -0.0002, 0.0002),
                "standard_deviation_xyz": (0.01, 0.02, 0.03),
                "observed_length": 367.0,
                "adjusted_length": 367.0,
                "observation_count": 251,
                "effective_sample_size": 12.5,
                "temporal_inflation_factor": 20.08,
                "scatter_scale_factor": 1.5,
                "total_covariance_inflation_factor": 30.12,
                "session_count": 2,
                "max_session_mean_difference_xyz": (0.01, -0.02, 0.03),
                "max_session_mean_separation_m": 0.0374165739,
                "max_session_mean_pair": ("R001", "R002"),
            }],
            "loops": [{
                "loop": 1,
                "points": ["BASE", "Dap1_1", "Dap1_2", "BASE"],
                "observed_misclosure_xyz": (0.001, 0.0, 0.0),
                "observed_closure": 0.001,
                "adjusted_misclosure_xyz": (1e-14, 0.0, 0.0),
                "adjusted_closure": 1e-14,
                "total_length": 700.0,
                "observed_relative_precision": 700000.0,
            }],
            "points": {"Dap1_2": {
                "adjusted_x": -1406000.0,
                "adjusted_y": 5720000.0,
                "adjusted_z": 2439000.0,
                "std_x": 0.01,
                "std_y": 0.02,
                "std_z": 0.03,
                "std_x_a_priori": 0.01,
                "std_y_a_priori": 0.02,
                "std_z_a_priori": 0.03,
                "std_x_a_posteriori": 0.005,
                "std_y_a_posteriori": 0.01,
                "std_z_a_posteriori": 0.015,
                "raw_rover_ecef_observation_count": 251,
                "raw_rover_ecef_rejected_count": 2,
            }},
            "quality": {
                "raw_observation_count": 253,
                "raw_rejected_count": 2,
                "raw_exclusion_reason_counts_overlap": True,
                "post_seed_transition_excluded_count": 3,
                "inter_rotation_reacquisition_excluded_count": 4,
                "observation_baseline_count": 251,
                "vector_outlier_count": 2,
                "baseline_std_rejected_count": 1,
                "baseline_std_repeatability_fallback_count": 3,
                "baseline_std_repeatability_fallback_edges": [{
                    "from": "Dap1_1",
                    "to": "Dap1_2",
                    "observation_count": 3,
                    "max_vector_deviation_m": 0.0113,
                    "max_ecef_consistency_error_m": 0.0137,
                }],
                "position_type_rejected_count": 1,
                "averaged_baseline_count": 1,
                "fundamental_loop_count": 1,
                "cycle_space_dimension": 1,
                "fundamental_loop_basis_rank": 1,
                "rover_only_loop_count": 0,
                "base_anchored_loop_count": 1,
                "degrees_of_freedom": 3,
                "weighted_residual_sum": 0.9,
                "variance_factor": 0.25,
                "reference_standard_deviation": 0.5,
                "reference_standard_deviation_m_at_1mm": 0.0005,
                "rank": 3,
                "condition_number": 2.0,
                "max_standardized_residual": 2.1,
                "max_session_mean_separation_m": 0.0374165739,
                "source_cross_covariance_available": False,
                "mixed_position_type_warning_threshold_m": 0.01,
                "mixed_position_type_edges": [],
                "position_type_filter_edges": [{
                    "from": "BASE",
                    "to": "Dap1_2",
                    "selected_position_type": 4,
                    "rejected_position_types": [7],
                    "rejected_count": 1,
                }],
                "global_test": {
                    "method": "UPPER_TAIL_NETWORK_QUALITY",
                    "passed": True,
                    "applicable": True,
                    "approximate": True,
                    "statistic": 0.9,
                    "upper_critical_value": 7.8147,
                },
                "stochastic_model_test": {
                    "method": "TWO_SIDED_MODEL_CALIBRATION",
                    "status": "CONSERVATIVE_WEIGHTS",
                    "statistic": 0.9,
                    "lower_critical_value": 1.2373,
                    "upper_critical_value": 14.4494,
                },
                "effective_sample_size_edges": [{
                    "from": "BASE",
                    "to": "Dap1_2",
                    "observation_count": 251,
                    "effective_sample_size": 12.5,
                }],
                "independent_epoch_sensitivity": {
                    "passed": True,
                    "weighted_residual_sum": 12.9,
                    "reference_standard_deviation": 0.928,
                },
            },
            "baseline_observations": [{
                "from": "BASE",
                "to": "Dap1_2",
                "observation_epoch": 1784082086,
                "position_type": 4,
                "baseline_neu": (236.9876, 171.4235, -0.4259),
                "baseline_std_neu_raw": (0.0071, 0.0080, 0.0206),
                "baseline_std_neu": (0.0071, 0.0080, 0.0206),
                "baseline_ecef_xyz": (1.0, 2.0, 3.0),
                "raw_base_llh": (21.9, 102.9, 149.0),
                "base_llh": (22.0, 103.0, 150.0),
                "rover_ecef": (-1406000.0, 5720000.0, 2439000.0),
                "rover_position_std_ecef_raw": (0.0, 0.0, 0.0),
                "rover_position_std_ecef": (0.02, 0.02, 0.02),
                "quality_flags": ["REJECTED_VECTOR_OUTLIER"],
                "vector_deviation_from_edge_m": 363.97,
                "raw_payload": "#AGRICA,THIS-MUST-NOT-APPEAR*00",
            }],
        }

        bridge = MQTTBridge.__new__(MQTTBridge)
        urls = bridge._write_adjustment_reports(999999, 1700000000, data)
        report_name = Path(urls["excel_report_url"]).name
        audit_name = Path(urls["audit_json_url"]).name
        report_path = BACKEND_DIRECTORY / "static" / "adjustments" / report_name
        audit_path = BACKEND_DIRECTORY / "static" / "adjustments" / audit_name
        try:
            workbook = load_workbook(report_path, data_only=True)
        finally:
            report_path.unlink(missing_ok=True)
            audit_path.unlink(missing_ok=True)

        self.assertEqual(urls["report_file_url"], urls["excel_report_url"])
        self.assertTrue(
            urls["excel_report_url"].startswith(
                "/api/admin/gnss/adjustment/reports/999999/"
            )
        )
        self.assertTrue(urls["excel_report_url"].endswith(".xlsx"))
        self.assertNotIn("summary_report_url", urls)

        self.assertEqual(workbook.sheetnames, ["Binh sai", "RAW_AUDIT"])
        self.assertEqual(workbook.active.title, "Binh sai")
        sheet = workbook["Binh sai"]
        raw_sheet = workbook["RAW_AUDIT"]
        self.assertEqual(raw_sheet.sheet_state, "visible")
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        raw_values = [cell.value for row in raw_sheet.iter_rows() for cell in row]
        self.assertIn("CALCULATED BASELINES - BASELINE TRUNG BÌNH", values)
        self.assertIn("SESSION REPEATABILITY - ĐỘ LẶP GIỮA CÁC PHIÊN", values)
        self.assertIn("FOUND LOOPS - VÒNG KHÉP TRƯỚC BÌNH SAI", values)
        self.assertIn("ADJUSTED BASELINES", values)
        self.assertIn("ADJUSTED LOOPS", values)
        self.assertIn("CONTROL POINT", values)
        self.assertIn("ADJUSTED POINTS", values)
        self.assertIn("REFERENCE STANDARD DEVIATION / QUALITY", values)
        self.assertIn("Std_X a priori (m)", values)
        self.assertIn("Std_X a posteriori (m)", values)
        self.assertIn(
            "Variance factor σ₀² = vTPv / f (không thứ nguyên)",
            values,
        )
        self.assertIn(
            "M0 = σ₀ = √(vTPv / f) (không thứ nguyên)",
            values,
        )
        self.assertIn("M0 quy đổi theo quy ước trọng số đơn vị 1 mm (m)", values)
        self.assertIn("Vòng độc lập chỉ rover-rover", values)
        self.assertIn("Vòng độc lập có BASE", values)
        self.assertIn(0.0005, values)
        self.assertIn("Khép kín", values)
        self.assertIn("Raw STD cao giữ bảo thủ nhờ lặp ổn định", values)
        self.assertIn("Rank ma trận vòng", values)
        self.assertTrue(any(
            isinstance(value, str)
            and "fundamental cycle basis" in value
            for value in values
        ))
        self.assertTrue(any(
            isinstance(value, str)
            and "Giữ bảo thủ cạnh Dap1_1 - Dap1_2" in value
            for value in values
        ))
        self.assertIn("Raw bị loại", values)
        self.assertIn(
            "Raw loại sau chuyển seed/source (EXCLUDE_POST_SEED_TRANSITION)",
            values,
        )
        self.assertIn(
            "Raw loại khi tái bắt giữa rotation (EXCLUDE_INTER_ROTATION_REACQUISITION)",
            values,
        )
        self.assertIn("Temporal_Inflation (n/n_eff)", values)
        self.assertIn("Scatter_Scale", values)
        self.assertIn("Total_Cov_Inflation", values)
        self.assertIn("Kiểm định chất lượng mạng", values)
        self.assertIn("Chẩn đoán mô hình trọng số", values)
        self.assertIn("TRỌNG SỐ BẢO THỦ", values)
        self.assertIn(2, values)
        self.assertTrue(any(
            isinstance(value, str)
            and "Raw bị loại unique = 2" in value
            for value in values
        ))
        self.assertTrue(any(
            isinstance(value, str)
            and "covariance chéo giữa các baseline chưa có" in value
            for value in values
        ))
        self.assertNotIn("#AGRICA,THIS-MUST-NOT-APPEAR*00", values)
        self.assertNotIn("RAW PAYLOAD BẰNG CHỨNG", values)
        self.assertIn("Baseline_N (m)", raw_values)
        self.assertIn("Std_N_Raw (m)", raw_values)
        self.assertIn("Std_N_Used (m)", raw_values)
        self.assertIn("Rover_StdX_Raw (m)", raw_values)
        self.assertIn("Rover_StdX_Used (m)", raw_values)
        self.assertIn("Raw_Base_Lat", raw_values)
        self.assertIn("Accepted_For_Solver", raw_values)
        self.assertIn("#AGRICA,THIS-MUST-NOT-APPEAR*00", raw_values)
        self.assertIn(False, raw_values)
        self.assertLess(sheet.max_row, 100)
        self.assertEqual(sheet.column_dimensions["A"].width, 8)
        self.assertEqual(sheet.column_dimensions["B"].width, 34)
        self.assertEqual(sheet.column_dimensions["C"].width, 18)
        self.assertEqual(sheet.column_dimensions["D"].width, 15)
        self.assertEqual(sheet.column_dimensions["L"].width, 22)
        self.assertEqual(sheet.page_setup.orientation, "landscape")

        baseline_row = next(
            row
            for row in sheet.iter_rows()
            if row[1].value == "BASE" and row[2].value == "Dap1_2"
        )
        self.assertEqual(baseline_row[0].alignment.horizontal, "center")
        self.assertEqual(baseline_row[1].alignment.horizontal, "left")
        self.assertEqual(baseline_row[2].alignment.horizontal, "left")
        self.assertEqual(baseline_row[3].alignment.horizontal, "right")
        self.assertEqual(baseline_row[3].border.bottom.style, "thin")

        quality_row = next(
            row
            for row in sheet.iter_rows()
            if row[1].value == "Raw nhận được"
        )
        self.assertIsNone(quality_row[0].value)
        self.assertEqual(quality_row[2].value, 253)
        self.assertEqual(quality_row[2].alignment.horizontal, "right")

        point_row = next(
            row
            for row in sheet.iter_rows()
            if row[1].value == "Dap1_2" and row[2].value == -1406000.0
        )
        self.assertEqual(
            tuple(cell.value for cell in point_row[5:11]),
            (0.01, 0.02, 0.03, 0.005, 0.01, 0.015),
        )

        warning_row = next(
            row
            for row in sheet.iter_rows()
            if row[1].value == "Đã lọc"
        )
        self.assertEqual(
            warning_row[2].value,
            "BASE -> Dap1_2: giữ Position Type 4; loại 1 raw Type 7.",
        )
        self.assertGreater(sheet.row_dimensions[warning_row[0].row].height, 30)

        raw_headers = {
            cell.value: cell.column
            for cell in raw_sheet[1]
        }
        self.assertEqual(
            raw_sheet.cell(2, raw_headers["Rover_StdX_Raw (m)"]).value,
            0.0,
        )
        self.assertEqual(
            raw_sheet.cell(2, raw_headers["Rover_StdX_Used (m)"]).value,
            0.02,
        )
        self.assertEqual(
            raw_sheet.cell(2, raw_headers["Raw_Base_Lat"]).value,
            21.9,
        )
        self.assertEqual(
            raw_sheet.cell(2, raw_headers["Base_Lat"]).value,
            22.0,
        )
        self.assertIn("ĐẠT", values)
        self.assertNotIn("KHÔNG ĐẠT - SỐ DƯ LỚN", values)
        self.assertIn("ĐẠT (tham khảo)", values)
        self.assertIn("n_eff nhỏ nhất", values)
        self.assertEqual(baseline_row[10].value, "251 / 12.50")
        self.assertAlmostEqual(baseline_row[11].value, 20.08)
        self.assertAlmostEqual(baseline_row[12].value, 1.5)
        self.assertAlmostEqual(baseline_row[13].value, 30.12)

        repeatability_row = next(
            row
            for row in sheet.iter_rows()
            if row[3].value == "R001 → R002"
        )
        self.assertEqual(repeatability_row[1].value, "BASE")
        self.assertEqual(repeatability_row[2].value, "Dap1_2")
        self.assertAlmostEqual(repeatability_row[4].value, 10.0)
        self.assertAlmostEqual(repeatability_row[5].value, -20.0)
        self.assertAlmostEqual(repeatability_row[6].value, 30.0)
        self.assertAlmostEqual(repeatability_row[7].value, 37.4165739)


class GnssAdjustmentQualityGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_marks_one_fast_list_row_but_keeps_every_station_copy(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        bridge.adjustment_phase = {}
        bridge.adjustment_message = {}
        bridge.adjustment_results = {}
        bridge.adjustment_run_contexts = {
            17: {"project_id": 9, "project_code": "P9", "cluster_index": 2, "cluster_name": "Cụm 3"}
        }
        bridge.adjustment_cluster_results = {9: {}}
        bridge._sensor_buffer = []
        bridge._buffer_lock = asyncio.Lock()
        bridge._write_adjustment_reports = Mock(return_value={})
        bridge._upsert_latest_sensor_cache = AsyncMock()
        adjustment = {
            "points": {"S1": {"station_id": 101}, "S2": {"station_id": 102}},
            "quality_gate": {"passed": True},
        }

        with patch("mqtt_bridge.manager", SimpleNamespace(broadcast=AsyncMock())):
            await bridge._handle_round_robin_adjustment_result(17, adjustment)

        self.assertEqual(len(bridge._sensor_buffer), 2)
        representatives = [row for row in bridge._sensor_buffer if row["adjustment_key"]]
        self.assertEqual(len(representatives), 1)
        self.assertEqual(representatives[0]["adjustment_key"], "run:9:2:17")
        self.assertEqual(representatives[0]["adjustment_project_id"], 9)
        self.assertEqual(representatives[0]["adjustment_cluster_index"], 2)
        self.assertEqual(bridge._upsert_latest_sensor_cache.await_count, 2)

    async def test_failed_quality_gate_writes_audit_but_does_not_publish_coordinates(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        bridge.adjustment_phase = {}
        bridge.adjustment_message = {}
        bridge.adjustment_results = {}
        bridge._sensor_buffer = []
        bridge._buffer_lock = asyncio.Lock()
        bridge._write_adjustment_reports = Mock(return_value={
            "report_file_url": "/audit.xlsx",
            "audit_json_url": "/audit.json",
            "excel_report_url": "/audit.xlsx",
        })
        bridge._upsert_latest_sensor_cache = AsyncMock()
        adjustment = {
            "points": {"S1": {"station_id": 101}},
            "official_publish_allowed": False,
            "quality_gate": {
                "passed": False,
                "status": "FAILED_QUALITY_GATE",
                "reasons": ["pre-adjustment loop closure exceeds 0.003 m"],
            },
        }
        broadcast = AsyncMock()

        with patch("mqtt_bridge.manager", SimpleNamespace(broadcast=broadcast)):
            await bridge._handle_round_robin_adjustment_result(17, adjustment)

        self.assertEqual(bridge.adjustment_phase[17], "FAILED_QUALITY_GATE")
        self.assertIs(
            bridge.adjustment_results[17]["cluster_results"][0],
            adjustment,
        )
        self.assertEqual(bridge._sensor_buffer, [])
        bridge._upsert_latest_sensor_cache.assert_not_awaited()
        bridge._write_adjustment_reports.assert_called_once()
        self.assertEqual(broadcast.await_args.kwargs, {})
        self.assertEqual(
            broadcast.await_args.args[0]["phase"],
            "FAILED_QUALITY_GATE",
        )


if __name__ == "__main__":
    unittest.main()
