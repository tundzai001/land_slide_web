import unittest
from types import SimpleNamespace

from app.features.data_export import export_sensor_record


class SensorExportWriterTests(unittest.TestCase):
    def record(self, sensor_type, data=None, **values):
        return SimpleNamespace(
            id=7,
            station_id=11,
            timestamp=1700000000,
            sensor_type=sensor_type,
            data=data or {},
            value_1=values.get("value_1"),
            value_2=values.get("value_2"),
            value_3=values.get("value_3"),
            value_4=values.get("value_4"),
            value_5=values.get("value_5"),
        )

    def test_gnss_audit_keeps_routine_raw_evidence(self):
        result = export_sensor_record(
            self.record(
                "gnss_audit",
                {"raw_gngga": "$GNGGA,raw", "record_kind": "forward"},
            ),
            {"project_code": "P1", "station_code": "CP01"},
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["dataset"], "gnss_audit")
        self.assertIn("raw_gngga", result["headers"])

    def test_each_supported_sensor_uses_its_own_dataset_schema(self):
        results = {
            sensor: export_sensor_record(
                self.record(sensor, {"water_level": 1.2, "roll": 0.4}),
                {"project_code": "P1", "station_code": "CP01"},
            )
            for sensor in ("imu", "rain", "water")
        }

        self.assertEqual(results["imu"]["dataset"], "imu")
        self.assertIn("roll", results["imu"]["headers"])
        self.assertEqual(results["rain"]["dataset"], "rain")
        self.assertIn("rain_mm", results["rain"]["headers"])
        self.assertEqual(results["water"]["dataset"], "water")
        self.assertIn("water_level", results["water"]["headers"])

    def test_unsupported_sensor_is_not_silently_exported(self):
        result = export_sensor_record(
            self.record("new/vendor sensor", {"raw": "value"}),
            {"project_code": "P1", "station_code": "CP01"},
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
