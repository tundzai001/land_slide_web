from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gnss_adjustment import Baseline, Network, NetworkError, Point, adjust_network, read_network


ROOT = Path(__file__).resolve().parents[3]


class LegacyDatasetTests(unittest.TestCase):
    def test_slbs1_exact_csharp_compatibility_mode(self) -> None:
        result = adjust_network(
            read_network(ROOT / "Dataset" / "slbs1.txt"), csharp_compatible=True
        )
        points = {point.name: point for point in result.points}

        # Values printed by Dataset/slbskqbs.txt.
        self.assertEqual(tuple(round(value, 3) for value in points["p1"].coordinate),
                         (2331343.319, 580551.563, 17.472))
        self.assertEqual(tuple(round(value, 3) for value in points["p3"].coordinate),
                         (2331089.379, 581271.517, 26.929))
        self.assertEqual(tuple(round(value, 3) for value in points["p4"].coordinate),
                         (2331857.014, 579582.056, 26.983))
        self.assertEqual(tuple(round(value, 3) for value in points["p1"].standard_deviation),
                         (0.009, 0.006, 0.016))
        self.assertIsNotNone(result.csharp_reference_standard_deviation)
        assert result.csharp_reference_standard_deviation is not None
        self.assertEqual(round(result.csharp_reference_standard_deviation, 3), 0.040)
        expected_adjusted = (
            (-251.929, -373.435, 10.451),
            (-253.940, 719.953, 9.457),
            (513.695, -969.507, 9.511),
            (-2.011, 1093.389, -0.994),
            (765.624, -596.072, -0.940),
            (767.635, -1689.460, 0.054),
        )
        expected_residuals = (
            (0.000, -0.003, -0.003),
            (0.000, 0.011, -0.003),
            (-0.001, -0.008, 0.007),
            (0.001, 0.006, -0.009),
            (-0.001, -0.010, 0.009),
            (0.001, 0.018, -0.016),
        )
        for baseline, adjusted, residual in zip(
            result.baselines, expected_adjusted, expected_residuals, strict=True
        ):
            self.assertEqual(tuple(round(value, 3) for value in baseline.adjusted), adjusted)
            self.assertEqual(tuple(round(value, 3) for value in baseline.residual), residual)

    def test_slbs1_standard_mode_adjusted_coordinates(self) -> None:
        result = adjust_network(read_network(ROOT / "Dataset" / "slbs1.txt"))
        points = {point.name: point for point in result.points}

        self.assertEqual(result.rank, 9)
        self.assertEqual(result.degrees_of_freedom, 9)
        self.assertAlmostEqual(points["p1"].coordinate[0], 2331343.3187, places=4)
        self.assertAlmostEqual(points["p1"].coordinate[1], 580551.56325, places=5)
        self.assertAlmostEqual(points["p3"].coordinate[2], 26.9294, places=4)
        self.assertAlmostEqual(points["p4"].coordinate[0], 2331857.0142, places=4)
        self.assertIsNotNone(result.global_test)
        assert result.global_test is not None
        self.assertFalse(result.global_test.passed)
        self.assertGreater(len(result.residual_flags), 0)

class SolverTests(unittest.TestCase):
    def test_weighted_mean_and_full_covariance(self) -> None:
        network = Network.from_items(
            [Point("A", (0, 0, 0), fixed=True), Point("B", (9, 0, 0))],
            [
                Baseline("A", "B", (10, 2, 3), standard_deviation=(0.1, 0.1, 0.1)),
                Baseline(
                    "A",
                    "B",
                    (10.2, 2, 3),
                    covariance=((0.04, 0, 0), (0, 0.04, 0), (0, 0, 0.04)),
                ),
            ],
        )
        result = adjust_network(network)
        point_b = next(point for point in result.points if point.name == "B")
        self.assertAlmostEqual(point_b.coordinate[0], 10.04, places=10)
        self.assertAlmostEqual(point_b.coordinate[1], 2.0, places=10)
        self.assertEqual(result.degrees_of_freedom, 3)

    def test_component_without_fixed_point_is_rejected(self) -> None:
        network = Network.from_items(
            [
                Point("A", (0, 0, 0), fixed=True),
                Point("B", (1, 0, 0)),
                Point("C", (10, 0, 0)),
                Point("D", (11, 0, 0)),
            ],
            [
                Baseline("A", "B", (1, 0, 0), standard_deviation=(1, 1, 1)),
                Baseline("C", "D", (1, 0, 0), standard_deviation=(1, 1, 1)),
            ],
        )
        with self.assertRaisesRegex(NetworkError, "no fixed point"):
            adjust_network(network)

    def test_invalid_covariance_is_rejected(self) -> None:
        with self.assertRaisesRegex(NetworkError, "positive definite"):
            Baseline(
                "A",
                "B",
                (1, 2, 3),
                covariance=((1, 0, 0), (0, -1, 0), (0, 0, 1)),
            )

    def test_statistical_test_options_are_validated(self) -> None:
        network = Network.from_items(
            [Point("A", (0, 0, 0), fixed=True), Point("B", (1, 0, 0))],
            [Baseline("A", "B", (1, 0, 0), standard_deviation=(1, 1, 1))],
        )
        with self.assertRaisesRegex(NetworkError, "global_significance"):
            adjust_network(network, global_significance=1.0)


class JsonInputTests(unittest.TestCase):
    def test_json_input(self) -> None:
        payload = {
            "points": [
                {"name": "A", "coordinate": [0, 0, 0], "fixed": True},
                {"name": "B", "coordinate": [1, 1, 1]},
            ],
            "baselines": [
                {"from": "A", "to": "B", "delta": [2, 3, 4], "std": [0.01, 0.01, 0.01]}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            network = read_network(path)
        self.assertEqual(len(network.points), 2)
        self.assertEqual(network.baselines[0].delta, (2.0, 3.0, 4.0))


if __name__ == "__main__":
    unittest.main()
