import unittest

try:
    from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
except ModuleNotFoundError:
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
    return "#AGRICA,0;" + ",".join(parts) + "*00000000"


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

    def test_agrica_fragment_is_buffered_until_crc_arrives(self):
        sentence = _agrica_sentence(
            baseline_neu=(1.0, 2.0, 0.0),
            rover_llh=(21.0, 105.0, 10.0),
        )
        split_at = sentence.index("81.3350") if "81.3350" in sentence else len(sentence) // 2
        first_fragment, second_fragment = sentence[:split_at], sentence[split_at:]

        first_result = self.manager.add_agrica_payload(first_fragment, {
            "project_id": 17, "station_id": 101, "station_code": "S1",
        })
        self.assertEqual(first_result, [])
        self.assertTrue(self.manager.has_pending_agrica_fragment(17, 101))
        self.assertIn(
            "Buffered AGRICA fragment",
            self.manager.get_last_ingest_diagnostic(17)["message"],
        )

        second_result = self.manager.add_agrica_payload(second_fragment, {
            "project_id": 17, "station_id": 101, "station_code": "S1",
        })
        self.assertEqual(len(second_result), 1)
        self.assertFalse(self.manager.has_pending_agrica_fragment(17, 101))

    def test_missing_rover_is_excluded_after_ten_seed_steps(self):
        self.manager.configure_project(18, [{
            "name": "cluster-with-offline-rover",
            "stations": [201, 202, 203],
            "rovers": ["A", "B", "C"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])
        for station_id, station_code, baseline in ((201, "A", (1.0, 0.0, 0.0)), (202, "B", (2.0, 0.0, 0.0))):
            self.manager.add_agrica_payload(
                _agrica_sentence(baseline_neu=baseline, rover_llh=(21.0, 105.0, 10.0)),
                {"project_id": 18, "station_id": station_id, "station_code": station_code},
            )

        self.manager._sessions[18]["seed_collection_steps"] = set(range(10))
        before_skip = self.manager.get_seed_collection_status(18)
        self.assertTrue(before_skip["fallback_ready"])
        self.assertEqual(before_skip["missing_station_ids"], [203])

        after_skip = self.manager.skip_missing_seed_stations(18)
        self.assertTrue(after_skip["complete"])
        self.assertEqual(after_skip["skipped_station_ids"], [203])
        self.assertEqual(self.manager._sessions[18]["clusters"][0]["stations"], [201, 202])


if __name__ == "__main__":
    unittest.main()
