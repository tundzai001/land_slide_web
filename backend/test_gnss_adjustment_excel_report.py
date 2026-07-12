import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

BACKEND_DIRECTORY = Path(__file__).resolve().parent
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

import mqtt_bridge as mqtt_bridge_module
from mqtt_bridge import MQTTBridge


class GnssAdjustmentExcelReportTests(unittest.TestCase):
    def test_report_uses_averages_apriori_std_tolerance_and_raw_evidence(self):
        data = {
            "rover_count": 1,
            "adjustment_engine": "test",
            "base": {"name": "SinQuyen1", "fixed": True, "ecef_xyz": (1.0, 2.0, 3.0)},
            "baselines": [{
                "from": "BASE",
                "to": "A",
                "observed_xyz": (1.0, 2.0, 3.0),
                "adjusted_xyz": (1.0, 2.0, 3.0),
                "residual_xyz": (0.0, 0.0, 0.0),
                "standard_deviation_xyz": (0.01, 0.02, 0.03),
                "observed_length": 3.741657,
                "adjusted_length": 3.741657,
                "velocity_up_std": 0.01,
                "observation_count": 21,
            }],
            "loops": [{
                "loop": 1,
                "points": ["BASE", "A", "BASE"],
                "observed_misclosure_xyz": (0.001, 0.0, 0.0),
                "observed_closure": 0.001,
                "adjusted_misclosure_xyz": (1e-14, 0.0, 0.0),
                "adjusted_closure": 1e-14,
                "total_length": 7.483314,
                "observed_relative_precision": 7483.314,
                "adjusted_relative_precision": 7.483314e14,
            }],
            "points": {"A": {
                "station_id": 1,
                "adjusted_x": 2.0,
                "adjusted_y": 4.0,
                "adjusted_z": 6.0,
                "dx": 0.0,
                "dy": 0.0,
                "dz": 0.0,
                "std_x": 0.002,
                "std_y": 0.003,
                "std_z": 0.004,
                "standard_deviation_enu": (0.005, 0.006, 0.007),
                "raw_rover_ecef": (2.0, 4.0, 6.0),
            }},
            "quality": {
                "observation_baseline_count": 21,
                "averaged_baseline_count": 1,
                "degrees_of_freedom": 60,
                "variance_factor": 0.25,
                "reference_standard_deviation": 0.5,
                "published_point_std_scale": "a_priori",
                "full_covariance_available": False,
                "repeated_observations_independence_verified": False,
                "control_point_uncertainty_included": False,
                "global_test": {
                    "passed": False,
                    "statistic": 15.0,
                    "lower_critical_value": 40.0,
                    "upper_critical_value": 80.0,
                    "p_value": 0.0,
                },
            },
            "baseline_observations": [{
                "from": "BASE",
                "to": "A",
                "observation_epoch": 1700000000,
                "position_type": 4,
                "gps_satellites": 8,
                "bds_satellites": 16,
                "glonass_satellites": 8,
                "galileo_satellites": 0,
                "diff_age": 0.5,
                "baseline_std_neu": (0.01, 0.02, 0.03),
                "velocity_up_std": 0.01,
                "quality_flags": [],
                "raw_payload": "#AGRICA,TEST*00",
            }],
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_module_path = str(Path(temporary_directory) / "mqtt_bridge.py")
            bridge = MQTTBridge.__new__(MQTTBridge)
            with patch.object(mqtt_bridge_module, "__file__", fake_module_path):
                report_path = bridge._append_adjustment_to_excel(9, 1700000000, data, "")
            workbook = load_workbook(report_path, data_only=True)

        values = [cell.value for row in workbook.active.iter_rows() for cell in row]
        self.assertIn("SinQuyen1 (alias: BASE)", values)
        self.assertIn("Std_X ECEF tiên nghiệm (m)", values)
        self.assertIn("Std_E ENU tiên nghiệm (m)", values)
        self.assertIn("Std vận tốc Up TB (m/s)", values)
        self.assertIn("Baseline_NStd (m)", values)
        self.assertIn("Cờ chất lượng", values)
        self.assertNotIn("Ratio nguồn TB (cần xác minh)", values)
        self.assertNotIn("PDOP", values)
        self.assertIn("Khép kín", values)
        self.assertIn("#AGRICA,TEST*00", values)
        self.assertNotIn("1/748331400000000", values)


if __name__ == "__main__":
    unittest.main()
