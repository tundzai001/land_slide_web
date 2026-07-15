import sys
import unittest
from pathlib import Path

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
                "raw_rover_ecef_observation_count": 251,
                "raw_rover_ecef_rejected_count": 2,
            }},
            "quality": {
                "raw_observation_count": 253,
                "raw_rejected_count": 2,
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
                "degrees_of_freedom": 3,
                "weighted_residual_sum": 0.9,
                "reference_standard_deviation": 0.5,
                "rank": 3,
                "condition_number": 2.0,
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
        self.assertIn("FOUND LOOPS - VÒNG KHÉP TRƯỚC BÌNH SAI", values)
        self.assertIn("ADJUSTED BASELINES", values)
        self.assertIn("ADJUSTED LOOPS", values)
        self.assertIn("CONTROL POINT", values)
        self.assertIn("ADJUSTED POINTS", values)
        self.assertIn("REFERENCE STANDARD DEVIATION / QUALITY", values)
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
        self.assertIn("Kiểm định chất lượng mạng", values)
        self.assertIn("Chẩn đoán mô hình trọng số", values)
        self.assertIn("TRỌNG SỐ BẢO THỦ", values)
        self.assertIn(2, values)
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
        self.assertLess(sheet.max_row, 80)
        self.assertEqual(sheet.column_dimensions["A"].width, 8)
        self.assertEqual(sheet.column_dimensions["B"].width, 34)
        self.assertEqual(sheet.column_dimensions["C"].width, 18)
        self.assertEqual(sheet.column_dimensions["D"].width, 15)

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


if __name__ == "__main__":
    unittest.main()
