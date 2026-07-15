import math
import unittest
from types import SimpleNamespace

from backend.processors.round_robin_manager import (
    RoundRobinAdjustmentManager,
    _aggregate_parallel_baselines,
    _build_fundamental_loops,
)


def baseline(start, end, observed, adjusted=None):
    adjusted = observed if adjusted is None else adjusted
    return {
        "from": start,
        "to": end,
        "observed_xyz": observed,
        "adjusted_xyz": adjusted,
        "observed_length": math.sqrt(sum(value * value for value in observed)),
    }


class FundamentalLoopReportTests(unittest.TestCase):
    def test_triangle_reports_observed_and_adjusted_closure(self):
        baselines = [
            baseline("BASE", "A", (1.0, 0.0, 0.0)),
            baseline("BASE", "B", (1.0, 1.0, 0.0)),
            baseline("A", "B", (0.0, 1.01, 0.0), (0.0, 1.0, 0.0)),
        ]

        loops = _build_fundamental_loops(baselines)

        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["points"], ["A", "B", "BASE", "A"])
        self.assertAlmostEqual(loops[0]["observed_closure"], 0.01, places=12)
        self.assertAlmostEqual(loops[0]["adjusted_closure"], 0.0, places=12)

    def test_parallel_baselines_do_not_form_a_geometric_loop(self):
        baselines = [
            baseline("BASE", "A", (2.0, 3.0, 4.0)),
            baseline("BASE", "A", (2.1, 3.0, 4.0), (2.0, 3.0, 4.0)),
        ]

        loops = _build_fundamental_loops(baselines)

        self.assertEqual(loops, [])

    def test_tree_network_has_no_loop(self):
        self.assertEqual(
            _build_fundamental_loops([
                baseline("BASE", "A", (1.0, 0.0, 0.0)),
                baseline("A", "B", (0.0, 1.0, 0.0)),
            ]),
            [],
        )

    def test_twelve_rover_loop_count_scales_with_actual_cross_edges(self):
        rover_names = [f"Rover_{index}" for index in range(1, 13)]
        base_edges = [
            baseline("BASE", rover_name, (float(index), 0.0, 0.0))
            for index, rover_name in enumerate(rover_names, start=1)
        ]
        minimum_connected_cross_edges = [
            baseline(rover_names[index], rover_names[index + 1], (1.0, 0.0, 0.0))
            for index in range(len(rover_names) - 1)
        ]

        baselines = base_edges + minimum_connected_cross_edges
        self.assertEqual(len(_build_fundamental_loops(baselines)), 11)

        baselines.append(baseline("Rover_1", "Rover_3", (2.0, 0.0, 0.0)))
        self.assertEqual(len(_build_fundamental_loops(baselines)), 12)

        complete_cross_edges = [
            baseline(rover_names[left], rover_names[right], (float(right - left), 0.0, 0.0))
            for left in range(len(rover_names))
            for right in range(left + 1, len(rover_names))
        ]
        self.assertEqual(len(_build_fundamental_loops(base_edges + complete_cross_edges)), 66)


class AveragedBaselineReportTests(unittest.TestCase):
    def test_repeated_and_reverse_edges_become_one_arithmetic_mean(self):
        rows = [
            {
                **baseline("BASE", "A", (2.0, 4.0, 6.0)),
                "residual_xyz": (0.1, 0.2, 0.3),
                "standard_deviation_xyz": (0.01, 0.02, 0.03),
                "velocity_up_std": 2.0,
            },
            {
                **baseline("A", "BASE", (-4.0, -6.0, -8.0)),
                "residual_xyz": (-0.3, -0.4, -0.5),
                "standard_deviation_xyz": (0.03, 0.04, 0.05),
                "velocity_up_std": 4.0,
            },
        ]

        averaged = _aggregate_parallel_baselines(rows)

        self.assertEqual(len(averaged), 1)
        self.assertEqual((averaged[0]["from"], averaged[0]["to"]), ("BASE", "A"))
        self.assertEqual(averaged[0]["observation_count"], 2)
        self.assertEqual(averaged[0]["observed_xyz"], (3.0, 5.0, 7.0))
        for actual, expected in zip(averaged[0]["residual_xyz"], (0.2, 0.3, 0.4)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(averaged[0]["standard_deviation_xyz"], (0.02, 0.03, 0.04))
        self.assertEqual(averaged[0]["velocity_up_std"], 3.0)

    def test_repeated_triangle_produces_three_edges_and_one_loop(self):
        rows = []
        for offset in (0.0, 0.01, -0.01):
            rows.extend([
                baseline("BASE", "A", (1.0 + offset, 0.0, 0.0)),
                baseline("BASE", "B", (1.0, 1.0 + offset, 0.0)),
                baseline("A", "B", (-offset, 1.0, 0.0)),
            ])
        for row in rows:
            row["residual_xyz"] = (0.0, 0.0, 0.0)
            row["standard_deviation_xyz"] = (0.01, 0.01, 0.01)

        averaged = _aggregate_parallel_baselines(rows)
        loops = _build_fundamental_loops(averaged)

        self.assertEqual(len(averaged), 3)
        self.assertTrue(all(row["observation_count"] == 3 for row in averaged))
        self.assertEqual(len(loops), 1)


class BaseIdentityValidationTests(unittest.TestCase):
    def setUp(self):
        self.manager = RoundRobinAdjustmentManager(SimpleNamespace(publish=lambda *_args: None))
        self.cluster = {
            "stations": [1, 2],
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }
        self.manager.rover_llh_cache["S1"] = {
            "lat": 21.001,
            "lon": 105.0,
            "alt": 11.0,
        }

    def test_fixed_base_measurement_is_rejected_during_temporary_base_window(self):
        observation = SimpleNamespace(rover_name="S2", base_llh=(21.0, 105.0, 10.0))
        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )
        self.assertFalse(accepted)
        self.assertIn("correction source has not switched", diagnostic)

    def test_temporary_base_measurement_is_accepted_when_reported_llh_matches(self):
        observation = SimpleNamespace(rover_name="S2", base_llh=(21.001001, 105.0, 11.0))
        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )
        self.assertTrue(accepted)
        self.assertIn("verified base S1", diagnostic)

    def test_geoid_sized_height_difference_does_not_reject_same_base(self):
        observation = SimpleNamespace(
            rover_name="S2",
            base_llh=(21.001001, 105.0, 42.65),
        )
        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )
        self.assertTrue(accepted)
        self.assertIn("height delta 31.65 m", diagnostic)

    def test_fixed_base_uses_config_when_agrica_base_coordinate_is_missing(self):
        observation = SimpleNamespace(rover_name="S2", base_llh=(0.0, 0.0, 0.0))

        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "BASE", observation
        )

        self.assertTrue(accepted)
        self.assertIn("using configured fixed BASE", diagnostic)

    def test_temporary_base_still_rejects_missing_base_coordinate(self):
        observation = SimpleNamespace(rover_name="S2", base_llh=(0.0, 0.0, 0.0))

        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )

        self.assertFalse(accepted)
        self.assertIn("no usable base_llh", diagnostic)

    def test_temporary_base_accepts_missing_base_coordinate_when_vector_matches(self):
        self.manager.rover_llh_cache["S1"] = {
            "lat": 21.001,
            "lon": 105.0,
            "alt": 10.0,
        }
        observation = SimpleNamespace(
            rover_name="S2",
            base_llh=(0.0, 0.0, 0.0),
            rover_llh=(21.002, 105.0, 10.0),
            baseline_neu=(111.3195, 0.0, 0.0),
        )

        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )

        self.assertTrue(accepted)
        self.assertIn("baseline vector matches temporary base S1", diagnostic)

    def test_temporary_base_rejects_vector_that_still_matches_fixed_base(self):
        self.manager.rover_llh_cache["S1"] = {
            "lat": 21.001,
            "lon": 105.0,
            "alt": 10.0,
        }
        observation = SimpleNamespace(
            rover_name="S2",
            base_llh=(0.0, 0.0, 0.0),
            rover_llh=(21.002, 105.0, 10.0),
            baseline_neu=(222.639, 0.0, 0.0),
        )

        accepted, diagnostic = self.manager._observation_matches_active_base(
            self.cluster, "S1", observation
        )

        self.assertFalse(accepted)
        self.assertIn("fixed-BASE error=", diagnostic)

    def test_fragment_buffers_are_cleared_at_base_transition(self):
        self.manager._agrica_fragment_buffers[(9, 1)] = "partial-a"
        self.manager._agrica_fragment_buffers[(9, 2)] = "partial-b"
        self.manager._clear_cluster_fragment_buffers(9, self.cluster)
        self.assertNotIn((9, 1), self.manager._agrica_fragment_buffers)
        self.assertNotIn((9, 2), self.manager._agrica_fragment_buffers)


if __name__ == "__main__":
    unittest.main()
