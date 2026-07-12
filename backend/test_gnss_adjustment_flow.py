import unittest

try:
    from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
    from backend.processors.gnss_adjustment_runtime import _llh_to_ecef, parse_agrica
except ModuleNotFoundError:
    from processors.round_robin_manager import RoundRobinAdjustmentManager
    from processors.gnss_adjustment_runtime import _llh_to_ecef, parse_agrica


def _agrica_sentence(
    *,
    baseline_neu,
    rover_llh,
    base_llh=(21.0, 105.0, 10.0),
    baseline_std_neu=(0.01, 0.01, 0.01),
    rover_ecef=(-1560000.0, 5000000.0, 2200000.0),
    rover_position_std_ecef=(0.02, 0.03, 0.04),
):
    """Create the subset of a valid UM980 AGRICA sentence needed by the parser."""

    parts = ["0"] * 57
    parts[0] = "GNSS"
    parts[1] = "232"
    parts[2:8] = ["24", "1", "1", "0", "0", "0"]
    parts[8] = "4"
    parts[10:13] = ["8", "16", "8"]
    parts[13:16] = [str(value) for value in baseline_neu]
    parts[16:19] = [str(value) for value in baseline_std_neu]
    parts[28] = "0.0107"
    parts[29:32] = [str(value) for value in rover_llh]
    parts[32:35] = [str(value) for value in rover_ecef]
    parts[38:41] = [str(value) for value in rover_position_std_ecef]
    parts[41:44] = [str(value) for value in base_llh]
    parts[48] = "0.999"
    parts[53] = "11"
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

    def _add(
        self,
        station_id,
        station_code,
        baseline_neu,
        rover_llh,
        base_llh=(21.0, 105.0, 10.0),
        **sentence_options,
    ):
        return self.manager.add_agrica_payload(
            _agrica_sentence(
                baseline_neu=baseline_neu,
                rover_llh=rover_llh,
                base_llh=base_llh,
                **sentence_options,
            ),
            {
                "project_id": 17,
                "station_id": station_id,
                "station_code": station_code,
            },
        )

    def test_connected_network_includes_cross_baseline_and_has_redundancy(self):
        # Fixed CORS base -> S1 and fixed CORS base -> S2.
        self._add(101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0))
        self._add(102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0))
        self.assertTrue(self.manager.has_complete_seed_observations(17))

        # During the S1 rotation, S2 observes S1 -> S2 = (3, 3, 0) in N/E/U.
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        self._add(
            102,
            "S2",
            (3.0, 3.0, 0.0),
            (21.0002, 105.0, 10.0),
            base_llh=(21.0001, 105.0, 10.0),
        )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        self.assertEqual(result["rover_count"], 2)
        self.assertEqual(len(result["baselines"]), 3)
        self.assertGreater(result["quality"]["degrees_of_freedom"], 0)
        self.assertEqual(result["source"], "AGRICA_ROUND_ROBIN")

    def test_transition_observation_from_fixed_base_is_not_mislabeled_as_cross_baseline(self):
        self._add(101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0))
        self._add(102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0))
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"

        rejected = self._add(
            102,
            "S2",
            (4.0, 5.0, 0.0),
            (21.0002, 105.0, 10.0),
            base_llh=(21.0, 105.0, 10.0),
        )

        self.assertEqual(rejected, [])
        self.assertEqual(len(session["clusters"][0]["observations"]), 2)
        self.assertIn("correction source has not switched", self.manager.get_last_ingest_diagnostic(17)["message"])

    def test_unfinished_fragment_is_discarded_when_base_window_changes(self):
        sentence = _agrica_sentence(
            baseline_neu=(1.0, 2.0, 0.0),
            rover_llh=(21.0001, 105.0, 10.0),
        )
        self.manager.add_agrica_payload(sentence[:200], {
            "project_id": 17, "station_id": 101, "station_code": "S1",
        })
        self.assertTrue(self.manager.has_pending_agrica_fragment(17, 101))

        self.manager._clear_cluster_fragment_buffers(17, self.manager._sessions[17]["clusters"][0])

        self.assertFalse(self.manager.has_pending_agrica_fragment(17, 101))

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

    def test_seed_step_display_is_capped_at_configured_maximum(self):
        self.manager._sessions[17]["seed_collection_steps"] = set(range(127))

        status = self.manager.get_seed_collection_status(17)

        self.assertEqual(status["step_count"], self.manager.SEED_COLLECTION_MAX_STEPS)

    def test_seed_baseline_accepts_missing_reported_base_when_cluster_base_is_configured(self):
        accepted = self._add(
            101,
            "S1",
            (1.0, 2.0, 0.0),
            (21.0001, 105.0, 10.0),
            base_llh=(0.0, 0.0, 0.0),
        )

        self.assertEqual(len(accepted), 1)
        self.assertIn(
            "using configured fixed BASE",
            self.manager.get_last_ingest_diagnostic(17)["message"],
        )

    def test_parser_keeps_baseline_and_rover_position_uncertainty_separate(self):
        observation = parse_agrica(
            _agrica_sentence(
                baseline_neu=(1.0, 2.0, 3.0),
                baseline_std_neu=(0.004, 0.005, 0.011),
                rover_llh=(21.0, 105.0, 10.0),
                rover_position_std_ecef=(0.1, 0.2, 0.3),
            ),
            project_id=17,
            station_id=101,
            rover_name="S1",
        )[0]

        self.assertEqual(observation.std_neu, (0.004, 0.005, 0.011))
        self.assertEqual(observation.rover_position_std_ecef, (0.1, 0.2, 0.3))
        self.assertEqual(observation.full_data["gps_satellites"], 8)
        self.assertEqual(observation.full_data["bds_satellites"], 16)
        self.assertEqual(observation.full_data["glonass_satellites"], 8)
        self.assertEqual(observation.full_data["galileo_satellites"], 11)
        self.assertAlmostEqual(observation.full_data["diff_age"], 0.999)
        self.assertAlmostEqual(observation.full_data["velocity_up_std"], 0.0107)

    def test_inconsistent_rover_ecef_is_excluded_from_raw_mean_but_baseline_is_kept(self):
        base_llh = (21.0, 105.0, 10.0)
        base_ecef = _llh_to_ecef(*base_llh)

        def expected_rover(baseline):
            delta = self.manager._baseline_ecef(
                type("Observation", (), {"baseline_neu": baseline})(),
                base_llh,
            )
            return tuple(base_ecef[index] + delta[index] for index in range(3))

        self._add(
            101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0),
            rover_ecef=expected_rover((1.0, 2.0, 0.0)),
        )
        self._add(
            102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
            baseline_std_neu=(0.2, 0.01, 0.01),
            rover_ecef=expected_rover((4.0, 5.0, 0.0)),
        )
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        inconsistent = tuple(value + 272.0 for value in expected_rover((4.0, 5.0, 0.0)))
        self._add(
            102, "S2", (3.0, 3.0, 0.0), (21.0002, 105.0, 10.0),
            base_llh=(21.0001, 105.0, 10.0),
            rover_ecef=inconsistent,
        )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        self.assertEqual(result["quality"]["observation_baseline_count"], 3)
        self.assertEqual(result["quality"]["baseline_std_warning_count"], 1)
        self.assertEqual(result["quality"]["raw_ecef_inconsistent_count"], 1)
        self.assertEqual(
            result["quality"]["trusted_subset"]["observation_baseline_count"],
            2,
        )
        self.assertEqual(result["points"]["S2"]["raw_rover_ecef_observation_count"], 1)
        self.assertEqual(result["points"]["S2"]["raw_rover_ecef_rejected_count"], 1)
        flagged = [
            item for item in result["baseline_observations"]
            if "BASELINE_POSITION_INCONSISTENT" in item["quality_flags"]
        ]
        self.assertEqual(len(flagged), 1)


if __name__ == "__main__":
    unittest.main()
