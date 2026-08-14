import unittest

from backend.app.services.gnss_risk import map_gnss_daily_risk


class GnssDailyRiskTests(unittest.TestCase):
    def test_maps_all_velocity_classification_families(self):
        cases = {
            "Extremely rapid": "CRITICAL",
            "Very rapid": "CRITICAL",
            "Rapid": "CRITICAL",
            "Moderate": "HIGH",
            "Slow": "MEDIUM",
            "Very slow": "MEDIUM",
            "Stable": "LOW",
            "": "LOW",
        }

        for classification, expected in cases.items():
            with self.subTest(classification=classification):
                self.assertEqual(map_gnss_daily_risk(classification), expected)


if __name__ == "__main__":
    unittest.main()
