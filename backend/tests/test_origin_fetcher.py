"""Live origin fetch must use the same GGA height rules as monitoring."""
import unittest

from app.features.stations.origin_fetcher import GNSSLiveFetcher


class OriginFetcherParseTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = GNSSLiveFetcher("127.0.0.1", 1883)

    def test_ellipsoidal_height_adds_geoid_separation(self):
        sentence = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,145.277,M,37.485,M,1.0,0"
        point = self.fetcher._parse_gngga(sentence)
        self.assertAlmostEqual(point["lat"], 21.05)
        self.assertAlmostEqual(point["lon"], 107.3166667, places=6)
        self.assertAlmostEqual(point["h"], 182.762)
        self.assertEqual(point["fix_quality"], 4)
        self.assertEqual(point["num_sats"], 20)

    def test_missing_geoid_is_rejected_instead_of_storing_msl_height(self):
        sentence = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,10.0,M,,M,1.0,0"
        self.assertIsNone(self.fetcher._parse_gngga(sentence))

    def test_invalid_nmea_minutes_are_rejected(self):
        sentence = "$GNGGA,010203.00,2165.000000,N,10719.000000,E,4,20,0.8,10.0,M,0.0,M,1.0,0"
        self.assertIsNone(self.fetcher._parse_gngga(sentence))


if __name__ == "__main__":
    unittest.main()
