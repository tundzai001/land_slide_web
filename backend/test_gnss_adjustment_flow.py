import unittest

from processors.round_robin_manager import RoundRobinAdjustmentManager


def _agrica_sentence(*, baseline_neu, rover_llh):
    """Create the subset of a valid UM980 AGRICA sentence needed by the parser."""

    parts = ["0"] * 57
    parts[0] = "GNSS"
    parts[1] = "232"
    parts[2:8] = ["24", "1", "1", "0", "0", "0"]
    parts[8] = "4"
    parts[13:16] = [str(value) for value in baseline_neu]
    parts[16:19] = ["0.01", "0.01", "0.01"]
    parts[29:32] = [str(value) for value in rover_llh]
    parts[32:35] = ["-1560000", "5000000", "2200000"]
    parts[38:41] = ["0.01", "0.01", "0.01"]
    # Deliberately use the receiver's zero base fields. The collector must use
    # the configured fixed base / point approximation instead.
    parts[41:44] = ["0", "0", "0"]
    return "#AGRICA,0;" + ",".join(parts) + "*00"


class _FakeMqttClient:
    def publish(self, *_args, **_kwargs):
        return None


class RoundRobinAdjustmentFlowTests(unittest.TestCase):
    def setUp(self):
        self.manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        self.manager.configure_project(17, [{
            "name": "cluster-a",
            "stations": [101, 102],
            "rovers": ["S1", "S2"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])

    def _add(self, station_id, station_code, baseline_neu, rover_llh):
        return self.manager.add_agrica_payload(
            _agrica_sentence(baseline_neu=baseline_neu, rover_llh=rover_llh),
            {
                "project_id": 17,
                "station_id": station_id,
                "station_code": station_code,
            },
        )

    def test_connected_network_includes_cross_baseline_and_has_redundancy(self):
        # Fixed CORS base -> S1 and fixed CORS base -> S2.
        self._add(101, "S1", (1.0, 2.0, 0.0), (21.0, 105.0, 10.0))
        self._add(102, "S2", (4.0, 5.0, 0.0), (21.0, 105.0, 10.0))
        self.assertTrue(self.manager.has_complete_seed_observations(17))

        # During the S1 rotation, S2 observes S1 -> S2 = (3, 3, 0) in N/E/U.
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        self._add(102, "S2", (3.0, 3.0, 0.0), (21.0, 105.0, 10.0))
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        self.assertEqual(result["rover_count"], 2)
        self.assertEqual(len(result["baselines"]), 3)
        self.assertGreater(result["quality"]["degrees_of_freedom"], 0)
        self.assertEqual(result["source"], "AGRICA_ROUND_ROBIN")


if __name__ == "__main__":
    unittest.main()
