import unittest

import numpy as np

from backend.processors.gnss_adjustment.models import Baseline, Network, Point
from backend.processors.gnss_adjustment.solver import adjust_network
from backend.processors.gnss_adjustment.transforms import (
    ecef_point_covariance_to_enu,
    neu_standard_deviation_to_ecef_covariance,
)


class StandardDeviationTransformationTests(unittest.TestCase):
    def test_point_covariance_is_preserved_in_adjustment_result(self):
        network = Network.from_items(
            [
                Point("BASE", (0.0, 0.0, 0.0), fixed=True),
                Point("A", (1.0, 2.0, 3.0), fixed=False),
            ],
            [
                Baseline(
                    "BASE",
                    "A",
                    (1.0, 2.0, 3.0),
                    standard_deviation=(0.1, 0.2, 0.3),
                )
            ],
        )

        result = adjust_network(network)
        point = next(item for item in result.points if item.name == "A")

        self.assertEqual(len(point.covariance), 3)
        self.assertEqual(len(point.covariance[0]), 3)
        self.assertGreater(point.standard_deviation[0], 0.0)
        self.assertGreater(point.standard_deviation[1], 0.0)
        self.assertGreater(point.standard_deviation[2], 0.0)

    def test_ecef_covariance_rotates_to_expected_enu_axes(self):
        covariance_ecef = np.diag([1.0, 4.0, 9.0])
        covariance_enu = ecef_point_covariance_to_enu(
            covariance_ecef,
            (6378137.0, 0.0, 0.0),
        )

        self.assertAlmostEqual(covariance_enu[0, 0], 4.0, places=12)
        self.assertAlmostEqual(covariance_enu[1, 1], 9.0, places=12)
        self.assertAlmostEqual(covariance_enu[2, 2], 1.0, places=12)

    def test_neu_standard_deviation_rotates_to_ecef_covariance(self):
        covariance_ecef = neu_standard_deviation_to_ecef_covariance(
            (2.0, 3.0, 4.0),
            latitude_deg=0.0,
            longitude_deg=0.0,
        )

        np.testing.assert_allclose(covariance_ecef, np.diag([16.0, 9.0, 4.0]))

    def test_published_std_is_apriori_when_posterior_scale_is_too_small(self):
        network = Network.from_items(
            [
                Point("BASE", (0.0, 0.0, 0.0), fixed=True),
                Point("A", (1.0, 2.0, 3.0), fixed=False),
            ],
            [
                Baseline("BASE", "A", (1.0, 2.0, 3.0), standard_deviation=(0.1, 0.1, 0.1)),
                Baseline("BASE", "A", (1.001, 2.0, 3.0), standard_deviation=(0.1, 0.1, 0.1)),
            ],
        )

        result = adjust_network(network)
        point = next(item for item in result.points if item.name == "A")

        self.assertFalse(result.global_test.passed)
        self.assertAlmostEqual(point.standard_deviation[0], 0.1 / np.sqrt(2.0), places=12)
        self.assertGreater(point.standard_deviation[0], point.posterior_standard_deviation[0])


if __name__ == "__main__":
    unittest.main()
