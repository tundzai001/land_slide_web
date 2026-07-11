import math
import unittest
from types import SimpleNamespace

from backend.processors.round_robin_manager import (
    RoundRobinAdjustmentManager,
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

    def test_parallel_baselines_form_two_edge_loop(self):
        baselines = [
            baseline("BASE", "A", (2.0, 3.0, 4.0)),
            baseline("BASE", "A", (2.1, 3.0, 4.0), (2.0, 3.0, 4.0)),
        ]

        loops = _build_fundamental_loops(baselines)

        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["baseline_indices"], [1, 0])
        self.assertAlmostEqual(loops[0]["observed_closure"], 0.1, places=12)
        self.assertAlmostEqual(loops[0]["adjusted_closure"], 0.0, places=12)

    def test_tree_network_has_no_loop(self):
        self.assertEqual(
            _build_fundamental_loops([
                baseline("BASE", "A", (1.0, 0.0, 0.0)),
                baseline("A", "B", (0.0, 1.0, 0.0)),
            ]),
            [],
        )


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

    def test_fragment_buffers_are_cleared_at_base_transition(self):
        self.manager._agrica_fragment_buffers[(9, 1)] = "partial-a"
        self.manager._agrica_fragment_buffers[(9, 2)] = "partial-b"
        self.manager._clear_cluster_fragment_buffers(9, self.cluster)
        self.assertNotIn((9, 1), self.manager._agrica_fragment_buffers)
        self.assertNotIn((9, 2), self.manager._agrica_fragment_buffers)


if __name__ == "__main__":
    unittest.main()
