import unittest

from app.features.simulation.engine import calculate_fos, normalize_parameters, run_simulation


class SimulationEngineTests(unittest.TestCase):
    def test_simulation_is_deterministic_and_bounded(self):
        first = run_simulation({"rainfall": 120, "slope_angle": 34}, 3600, 42)
        second = run_simulation({"rainfall": 120, "slope_angle": 34}, 3600, 42)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["time_series"]), 2000)
        self.assertLessEqual(first["summary"]["minimum_fos"], first["summary"]["initial_fos"])

    def test_more_pore_pressure_reduces_fos(self):
        params = normalize_parameters({})
        self.assertLess(calculate_fos(params, 0.5), calculate_fos(params, 0.0))

    def test_zero_rain_drainage_never_adds_water(self):
        result = run_simulation({"rainfall": 0, "pore_pressure_ratio": 0.2}, 3600, 7)
        depths = [row["wetting_depth_m"] for row in result["time_series"]]
        self.assertEqual(depths, sorted(depths, reverse=True))

    def test_parameter_validation_rejects_invalid_threshold_order(self):
        with self.assertRaisesRegex(ValueError, "nguy hiểm"):
            normalize_parameters({"fos_warning": 1.0, "fos_critical": 1.1})


if __name__ == "__main__":
    unittest.main()
