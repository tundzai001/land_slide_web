import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

try:
    from backend.processors.round_robin_manager import (
        RoundRobinAdjustmentManager,
        _SafeRoverRotationSkip,
        _graph_components,
        _initial_positive_sequence_ess,
    )
    from backend.processors.gnss_adjustment_runtime import _llh_to_ecef, parse_agrica
except ModuleNotFoundError:
    from processors.round_robin_manager import (
        RoundRobinAdjustmentManager,
        _SafeRoverRotationSkip,
        _graph_components,
        _initial_positive_sequence_ess,
    )
    from processors.gnss_adjustment_runtime import _llh_to_ecef, parse_agrica


def _agrica_sentence(
    *,
    baseline_neu,
    rover_llh,
    base_llh=(21.0, 105.0, 10.0),
    baseline_std_neu=(0.01, 0.01, 0.01),
    rover_ecef=(-1560000.0, 5000000.0, 2200000.0),
    rover_position_std_ecef=(0.02, 0.03, 0.04),
    position_type=4,
    second=0,
):
    """Create the subset of a valid UM980 AGRICA sentence needed by the parser."""

    parts = ["0"] * 57
    parts[0] = "GNSS"
    parts[1] = "232"
    parts[2:8] = ["24", "1", "1", "0", "0", str(second)]
    parts[8] = str(position_type)
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
        self.assertEqual(len(result["loops"]), 1)
        self.assertEqual(
            set(result["loops"][0]["points"]),
            {"BASE", "S1", "S2"},
        )
        self.assertGreater(result["quality"]["degrees_of_freedom"], 0)
        self.assertEqual(result["source"], "AGRICA_ROUND_ROBIN")

    def test_position_type_4_is_preferred_and_type_7_is_rejected_per_edge(self):
        self._add(
            101,
            "S1",
            (1.0, 2.0, 0.0),
            (21.0001, 105.0, 10.0),
            position_type=4,
        )
        self._add(
            102,
            "S2",
            (4.0, 5.0, 0.0),
            (21.0002, 105.0, 10.0),
            position_type=4,
        )
        self._add(
            102,
            "S2",
            (4.02, 5.03, 0.01),
            (21.0002, 105.0, 10.0),
            position_type=7,
        )
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        self._add(
            102,
            "S2",
            (3.0, 3.0, 0.0),
            (21.0002, 105.0, 10.0),
            base_llh=(21.0001, 105.0, 10.0),
            position_type=4,
        )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        self.assertEqual(result["quality"]["position_type_rejected_count"], 1)
        self.assertEqual(result["quality"]["raw_rejected_count"], 1)
        self.assertEqual(len(result["quality"]["position_type_filter_edges"]), 1)
        rejected = [
            row for row in result["baseline_observations"]
            if "REJECTED_POSITION_TYPE_7" in row["quality_flags"]
        ]
        self.assertEqual(len(rejected), 1)
        fixed_to_s2 = next(
            baseline for baseline in result["baselines"]
            if baseline["from"] == "BASE" and baseline["to"] == "S2"
        )
        self.assertEqual(fixed_to_s2["position_types"], [4])
        self.assertEqual(fixed_to_s2["observation_count"], 1)

    def test_effective_sample_size_is_conservative_for_short_or_correlated_series(self):
        self.assertEqual(_initial_positive_sequence_ess([1, 2, 3, 4, 5, 6, 7]), 1.0)
        pooled_short = _initial_positive_sequence_ess(
            [1, 2, 3, 4, 5, 6, 7],
            fallback_lag_one_correlation=0.9,
        )
        self.assertGreater(pooled_short, 1.0)
        self.assertLess(pooled_short, 2.0)
        correlated = [float(index) for index in range(40)]
        effective = _initial_positive_sequence_ess(correlated)
        self.assertGreaterEqual(effective, 1.0)
        self.assertLess(effective, 10.0)

    def test_four_rovers_require_three_cross_edges_and_three_independent_loops(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(19, [{
            "name": "four-rover-cluster",
            "stations": [191, 192, 193, 194],
            "rovers": ["R1", "R2", "R3", "R4"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])

        rover_llh = {
            "R1": (21.0001, 105.0, 10.0),
            "R2": (21.0002, 105.0, 10.0),
            "R3": (21.0003, 105.0, 10.0),
            "R4": (21.0004, 105.0, 10.0),
        }

        def add(station_id, station_code, baseline_neu, base_llh=(21.0, 105.0, 10.0)):
            return manager.add_agrica_payload(
                _agrica_sentence(
                    baseline_neu=baseline_neu,
                    rover_llh=rover_llh[station_code],
                    base_llh=base_llh,
                ),
                {
                    "project_id": 19,
                    "station_id": station_id,
                    "station_code": station_code,
                },
            )

        for station_id, station_code, north in (
            (191, "R1", 10.0),
            (192, "R2", 20.0),
            (193, "R3", 30.0),
            (194, "R4", 40.0),
        ):
            add(station_id, station_code, (north, 0.0, 0.0))

        session = manager._sessions[19]
        cluster = session["clusters"][0]
        session["active_bases"][0] = "R1"
        add(192, "R2", (10.0, 0.0, 0.0), base_llh=rover_llh["R1"])
        session["active_bases"].clear()

        with self.assertRaisesRegex(
            ValueError,
            r"need at least 3 distinct cross-edge\(s\).*collected 1.*R3, R4",
        ):
            manager._build_cluster_result(19, 0, cluster)

        session["active_bases"][0] = "R2"
        add(193, "R3", (10.0, 0.0, 0.0), base_llh=rover_llh["R2"])
        session["active_bases"][0] = "R3"
        add(194, "R4", (10.0, 0.0, 0.0), base_llh=rover_llh["R3"])
        session["active_bases"].clear()

        result = manager._build_cluster_result(19, 0, cluster)
        self.assertEqual(len(result["baselines"]), 7)
        self.assertEqual(len(result["loops"]), 3)
        self.assertTrue(all(len(set(loop["points"])) >= 3 for loop in result["loops"]))

    def test_edge_count_and_participation_do_not_hide_disconnected_graph(self):
        components = _graph_components(
            ["R1", "R2", "R3", "R4", "R5"],
            [
                ("R1", "R2"),
                ("R2", "R3"),
                ("R1", "R3"),
                ("R4", "R5"),
            ],
        )

        self.assertEqual(
            {frozenset(component) for component in components},
            {frozenset({"R1", "R2", "R3"}), frozenset({"R4", "R5"})},
        )

    def test_vector_jump_is_rejected_even_when_receiver_reports_small_std(self):
        # Eight stable epochs define each fixed-base edge. Two S2 epochs then
        # jump hundreds of metres while claiming millimetre-level STD.
        for second in range(8):
            self._add(
                101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0),
                second=second,
            )
            self._add(
                102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
                second=second,
            )
        for second, bad_vector in (
            (8, (236.9876, 171.4235, -0.4259)),
            (9, (236.9912, 171.3986, -0.4032)),
        ):
            self._add(
                102,
                "S2",
                bad_vector,
                (21.0002, 105.0, 10.0),
                baseline_std_neu=(0.0071, 0.0080, 0.0206),
                second=second,
            )

        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        for second in range(10, 18):
            self._add(
                102,
                "S2",
                (3.0, 3.0, 0.0),
                (21.0002, 105.0, 10.0),
                base_llh=(21.0001, 105.0, 10.0),
                second=second,
            )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        rejected = [
            row for row in result["baseline_observations"]
            if "REJECTED_VECTOR_OUTLIER" in row["quality_flags"]
        ]
        self.assertEqual(len(rejected), 2)
        self.assertEqual(result["quality"]["vector_outlier_count"], 2)
        self.assertEqual(result["quality"]["raw_rejected_count"], 2)
        self.assertTrue(result["quality"]["global_test"]["applicable"])
        self.assertIsInstance(result["quality"]["global_test"]["passed"], bool)
        self.assertEqual(
            result["quality"]["global_test"]["method"],
            "UPPER_TAIL_NETWORK_QUALITY",
        )
        self.assertEqual(
            result["quality"]["stochastic_model_test"]["method"],
            "TWO_SIDED_MODEL_CALIBRATION",
        )
        self.assertIn(
            result["quality"]["stochastic_model_test"]["status"],
            {
                "CONSERVATIVE_WEIGHTS",
                "CONSISTENT",
                "OPTIMISTIC_WEIGHTS_OR_MODEL_ERROR",
            },
        )
        self.assertTrue(result["quality"]["effective_sample_size_edges"])
        self.assertIn("passed", result["quality"]["independent_epoch_sensitivity"])
        self.assertFalse(
            result["quality"]["independent_epoch_sensitivity"]["used_for_published_solution"]
        )
        self.assertTrue(all(row["vector_deviation_from_edge_m"] > 250 for row in rejected))
        fixed_to_s2 = next(
            baseline for baseline in result["baselines"]
            if baseline["from"] == "BASE" and baseline["to"] == "S2"
        )
        self.assertEqual(fixed_to_s2["observation_count"], 8)

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
        for second in range(10):
            for station_id, station_code, baseline in (
                (201, "A", (1.0, 0.0, 0.0)),
                (202, "B", (2.0, 0.0, 0.0)),
            ):
                self.manager.add_agrica_payload(
                    _agrica_sentence(
                        baseline_neu=baseline,
                        rover_llh=(21.0, 105.0, 10.0),
                        second=second,
                    ),
                    {"project_id": 18, "station_id": station_id, "station_code": station_code},
                )

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

    def test_four_selected_rovers_continue_with_three_after_ten_gnss_epochs(self):
        self.manager.configure_project(19, [{
            "name": "four-rover-cluster",
            "stations": [4, 5, 6, 7],
            "rovers": ["Dap1_4", "Dap1_1", "Silent", "Dap1_2"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])
        live = (
            (4, "Dap1_4", (595.0, -342.0, -22.0)),
            (5, "Dap1_1", (81.0, -354.0, -22.0)),
            (7, "Dap1_2", (318.0, -182.0, -22.0)),
        )
        for second in range(10):
            for station_id, station_code, baseline in live:
                self.manager.add_agrica_payload(
                    _agrica_sentence(
                        baseline_neu=baseline,
                        rover_llh=(21.0, 105.0, 10.0),
                        second=second,
                    ),
                    {"project_id": 19, "station_id": station_id, "station_code": station_code},
                )

        status = self.manager.get_seed_collection_status(19)
        self.assertTrue(status["fallback_ready"])
        self.assertEqual(status["step_count"], 10)
        self.assertEqual(status["missing_station_ids"], [6])

        skipped = self.manager.skip_missing_seed_stations(19)
        self.assertTrue(skipped["complete"])
        self.assertEqual(skipped["skipped_station_ids"], [6])
        self.assertEqual(self.manager._sessions[19]["clusters"][0]["stations"], [4, 5, 7])

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
        self.assertEqual(observation.std_neu_raw, (0.004, 0.005, 0.011))
        self.assertEqual(observation.rover_position_std_ecef, (0.1, 0.2, 0.3))
        self.assertEqual(observation.rover_position_std_ecef_raw, (0.1, 0.2, 0.3))
        self.assertEqual(observation.full_data["gps_satellites"], 8)
        self.assertEqual(observation.full_data["bds_satellites"], 16)
        self.assertEqual(observation.full_data["glonass_satellites"], 8)
        self.assertEqual(observation.full_data["galileo_satellites"], 11)
        self.assertAlmostEqual(observation.full_data["diff_age"], 0.999)
        self.assertAlmostEqual(observation.full_data["velocity_up_std"], 0.0107)

    def test_parser_preserves_zero_raw_std_and_exposes_used_fallback_separately(self):
        observation = parse_agrica(
            _agrica_sentence(
                baseline_neu=(1.0, 2.0, 3.0),
                baseline_std_neu=(0.0, 0.0, 0.0),
                rover_llh=(21.0, 105.0, 10.0),
                rover_position_std_ecef=(0.0, 0.0, 0.0),
            ),
            project_id=17,
            station_id=101,
            rover_name="S1",
        )[0]

        self.assertEqual(observation.std_neu_raw, (0.0, 0.0, 0.0))
        self.assertEqual(observation.std_neu, (0.02, 0.02, 0.02))
        self.assertEqual(observation.rover_position_std_ecef_raw, (0.0, 0.0, 0.0))
        self.assertEqual(observation.rover_position_std_ecef, (0.02, 0.02, 0.02))

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
            rover_ecef=expected_rover((4.0, 5.0, 0.0)),
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
        self.assertEqual(result["quality"]["raw_rejected_count"], 1)
        self.assertEqual(result["quality"]["baseline_std_warning_count"], 0)
        self.assertEqual(result["quality"]["baseline_std_raw_warning_count"], 1)
        self.assertEqual(result["quality"]["baseline_std_rejected_count"], 1)
        self.assertEqual(result["quality"]["raw_ecef_inconsistent_count"], 1)
        self.assertEqual(
            result["quality"]["trusted_subset"]["observation_baseline_count"],
            3,
        )
        self.assertEqual(result["points"]["S2"]["raw_rover_ecef_observation_count"], 1)
        self.assertEqual(result["points"]["S2"]["raw_rover_ecef_rejected_count"], 2)
        flagged = [
            item for item in result["baseline_observations"]
            if "BASELINE_POSITION_INCONSISTENT" in item["quality_flags"]
        ]
        self.assertEqual(len(flagged), 1)
        std_rejected = [
            item for item in result["baseline_observations"]
            if "REJECTED_BASELINE_STD" in item["quality_flags"]
        ]
        self.assertEqual(len(std_rejected), 1)

    def test_repeated_stable_high_std_cross_edge_is_kept_conservatively(self):
        fixed_base_llh = (21.0, 105.0, 10.0)
        temporary_base_llh = (21.0001, 105.0, 10.0)

        def expected_rover(base_llh, baseline):
            base_ecef = _llh_to_ecef(*base_llh)
            delta = self.manager._baseline_ecef(
                type("Observation", (), {"baseline_neu": baseline})(),
                base_llh,
            )
            return tuple(base_ecef[index] + delta[index] for index in range(3))

        self._add(
            101, "S1", (1.0, 2.0, 0.0), temporary_base_llh,
            rover_ecef=expected_rover(fixed_base_llh, (1.0, 2.0, 0.0)),
        )
        self._add(
            102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
            rover_ecef=expected_rover(fixed_base_llh, (4.0, 5.0, 0.0)),
        )
        fixed_base_ecef = _llh_to_ecef(*fixed_base_llh)
        temporary_base_seed_delta = self.manager._baseline_ecef(
            type("Observation", (), {"baseline_neu": (1.0, 2.0, 0.0)})(),
            fixed_base_llh,
        )
        temporary_base_ecef = tuple(
            fixed_base_ecef[index] + temporary_base_seed_delta[index]
            for index in range(3)
        )

        def expected_cross_rover(baseline):
            delta = self.manager._baseline_ecef(
                type("Observation", (), {"baseline_neu": baseline})(),
                temporary_base_llh,
            )
            return tuple(
                temporary_base_ecef[index] + delta[index]
                for index in range(3)
            )

        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        for second, baseline in enumerate(
            ((3.000, 3.000, 0.000), (3.006, 2.996, 0.004), (2.995, 3.004, -0.003)),
            start=1,
        ):
            self._add(
                102,
                "S2",
                baseline,
                (21.0002, 105.0, 10.0),
                base_llh=temporary_base_llh,
                baseline_std_neu=(4.0, 5.0, 8.0),
                rover_ecef=expected_cross_rover(baseline),
                second=second,
            )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        cross_edge = next(
            edge for edge in result["baselines"] if edge["from"] != "BASE"
        )
        self.assertEqual(cross_edge["observation_count"], 3)
        self.assertEqual(len(result["loops"]), 1)
        self.assertEqual(result["quality"]["cycle_space_dimension"], 1)
        self.assertEqual(result["quality"]["fundamental_loop_basis_rank"], 1)
        self.assertTrue(result["quality"]["loop_basis_independence_verified"])
        self.assertEqual(
            result["quality"]["baseline_std_repeatability_fallback_count"],
            3,
        )
        self.assertEqual(result["quality"]["baseline_std_rejected_count"], 0)
        fallback = result["quality"]["baseline_std_repeatability_fallback_edges"]
        self.assertEqual(len(fallback), 1)
        self.assertLess(fallback[0]["max_vector_deviation_m"], 0.05)

    def test_single_high_std_cross_epoch_cannot_create_fallback_edge(self):
        fixed_base_llh = (21.0, 105.0, 10.0)
        temporary_base_llh = (21.0001, 105.0, 10.0)

        def expected_rover(base_llh, baseline):
            base_ecef = _llh_to_ecef(*base_llh)
            delta = self.manager._baseline_ecef(
                type("Observation", (), {"baseline_neu": baseline})(),
                base_llh,
            )
            return tuple(base_ecef[index] + delta[index] for index in range(3))

        self._add(
            101, "S1", (1.0, 2.0, 0.0), temporary_base_llh,
            rover_ecef=expected_rover(fixed_base_llh, (1.0, 2.0, 0.0)),
        )
        self._add(
            102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
            rover_ecef=expected_rover(fixed_base_llh, (4.0, 5.0, 0.0)),
        )
        fixed_base_ecef = _llh_to_ecef(*fixed_base_llh)
        temporary_base_seed_delta = self.manager._baseline_ecef(
            type("Observation", (), {"baseline_neu": (1.0, 2.0, 0.0)})(),
            fixed_base_llh,
        )
        temporary_base_ecef = tuple(
            fixed_base_ecef[index] + temporary_base_seed_delta[index]
            for index in range(3)
        )

        def expected_cross_rover(baseline):
            delta = self.manager._baseline_ecef(
                type("Observation", (), {"baseline_neu": baseline})(),
                temporary_base_llh,
            )
            return tuple(
                temporary_base_ecef[index] + delta[index]
                for index in range(3)
            )

        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        baseline = (3.0, 3.0, 0.0)
        self._add(
            102,
            "S2",
            baseline,
            (21.0002, 105.0, 10.0),
            base_llh=temporary_base_llh,
            baseline_std_neu=(4.0, 5.0, 8.0),
            rover_ecef=expected_cross_rover(baseline),
            second=1,
        )
        session["active_bases"].clear()

        with self.assertRaisesRegex(
            ValueError,
            "no solver-eligible rover-to-rover baseline",
        ):
            self.manager._build_cluster_result(17, 0, session["clusters"][0])


class RoundRobinCompletionOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_safely_recovered_rover_is_skipped_and_next_rotation_continues(self):
        attempted_rovers = []
        progress_messages = []
        published_results = []

        async def progress_callback(_project_id, message):
            progress_messages.append(message)

        async def result_callback(_project_id, result):
            published_results.append(result)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            progress_callback=progress_callback,
            result_callback=result_callback,
        )
        manager.configure_project(70, [{
            "name": "skip-cluster",
            "stations": [701, 702],
            "rovers": ["R1", "R2"],
        }])

        async def rotate(rover_code, **_kwargs):
            attempted_rovers.append(rover_code)
            if rover_code == "R1":
                raise _SafeRoverRotationSkip("R1 restored to ROVER")
            manager._sessions[70]["clusters"][0]["observations"].append(
                SimpleNamespace(
                    base_name=rover_code,
                    observation=SimpleNamespace(
                        rover_name="R1",
                        std_neu=(0.01, 0.01, 0.01),
                        baseline_neu=(10.0, 0.0, 0.0),
                    ),
                )
            )

        manager._set_rover_as_temporary_base = rotate
        manager._build_cluster_result = Mock(return_value={"rover_count": 2, "quality": {}})

        await manager._run_cycle(70)

        self.assertEqual(attempted_rovers, ["R1", "R1", "R2"])
        self.assertEqual(len(published_results), 1)
        self.assertEqual(published_results[0]["quality"]["rotation_warning_count"], 1)
        self.assertTrue(any("continuing with the next rover" in item for item in progress_messages))

    async def test_disconnected_graph_retries_productive_base_for_missing_rover(self):
        attempted_rovers = []
        expected_targets = []
        published_results = []

        async def result_callback(_project_id, result):
            published_results.append(result)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            result_callback=result_callback,
        )
        manager.configure_project(71, [{
            "name": "targeted-recovery-cluster",
            "stations": [701, 702, 703],
            "rovers": ["R1", "R2", "R3"],
        }])

        async def rotate(rover_code, **kwargs):
            targets = set(kwargs.get("expected_cross_rovers") or ())
            attempted_rovers.append(rover_code)
            expected_targets.append(targets)
            if rover_code != "R1":
                return
            target = "R3" if targets == {"R3"} else "R2"
            manager._sessions[71]["clusters"][0]["observations"].append(
                SimpleNamespace(
                    base_name="R1",
                    observation=SimpleNamespace(
                        rover_name=target,
                        std_neu=(0.01, 0.01, 0.01),
                        baseline_neu=(10.0, 0.0, 0.0),
                    ),
                )
            )

        manager._set_rover_as_temporary_base = rotate
        manager._build_cluster_result = Mock(return_value={"rover_count": 3, "quality": {}})

        await manager._run_cycle(71)

        self.assertEqual(
            attempted_rovers,
            ["R1", "R1", "R2", "R2", "R3", "R3", "R1"],
        )
        self.assertEqual(expected_targets[-1], {"R3"})
        self.assertEqual(len(published_results), 1)

    async def test_high_std_cross_samples_do_not_stop_rotation_retry(self):
        attempted_rovers = []
        attempts_by_rover = {"R1": 0, "R2": 0}

        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(72, [{
            "name": "quality-retry-cluster",
            "stations": [701, 702],
            "rovers": ["R1", "R2"],
        }])

        async def rotate(rover_code, **_kwargs):
            attempted_rovers.append(rover_code)
            attempts_by_rover[rover_code] += 1
            target = "R2" if rover_code == "R1" else "R1"
            std = 0.2 if attempts_by_rover[rover_code] == 1 else 0.01
            manager._sessions[72]["clusters"][0]["observations"].append(
                SimpleNamespace(
                    base_name=rover_code,
                    observation=SimpleNamespace(
                        rover_name=target,
                        std_neu=(std, std, std),
                        baseline_neu=(25.0, 0.0, 0.0),
                    ),
                )
            )

        manager._set_rover_as_temporary_base = rotate
        manager._build_cluster_result = Mock(return_value={"rover_count": 2, "quality": {}})

        await manager._run_cycle(72)

        self.assertEqual(attempted_rovers, ["R1", "R1"])

    async def test_complete_cross_graph_skips_unnecessary_base_rotations(self):
        attempted_rovers = []
        progress_messages = []

        async def progress_callback(_project_id, message):
            progress_messages.append(message)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            progress_callback=progress_callback,
        )
        manager.configure_project(73, [{
            "name": "early-complete-cluster",
            "stations": [701, 702, 703],
            "rovers": ["R1", "R2", "R3"],
        }])

        async def rotate(rover_code, **_kwargs):
            attempted_rovers.append(rover_code)
            for target in ("R2", "R3"):
                manager._sessions[73]["clusters"][0]["observations"].append(
                    SimpleNamespace(
                        base_name=rover_code,
                        observation=SimpleNamespace(
                            rover_name=target,
                            std_neu=(0.01, 0.01, 0.01),
                            baseline_neu=(25.0, 0.0, 0.0),
                        ),
                    )
                )

        manager._set_rover_as_temporary_base = rotate
        manager._build_cluster_result = Mock(return_value={"rover_count": 3, "quality": {}})

        await manager._run_cycle(73)

        self.assertEqual(attempted_rovers, ["R1"])
        self.assertTrue(any(
            "remaining temporary-BASE rotations are unnecessary" in message
            for message in progress_messages
        ))

    async def test_fixed_base_is_restored_before_result_is_published(self):
        events = []

        async def progress_callback(_project_id, message):
            events.append(("progress", message))

        async def result_callback(_project_id, _result):
            events.append(("result", "published"))

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            progress_callback=progress_callback,
            result_callback=result_callback,
        )
        manager.configure_project(71, [
            {
                "name": "ordering-cluster-a",
                "stations": [701, 702],
                "rovers": ["R1", "R2"],
                "base_stream_mp": "FIXED_BASE",
                "base_stream_host": "caster.example",
            },
            {
                "name": "ordering-cluster-b",
                "stations": [703, 704],
                "rovers": ["R3", "R4"],
                "base_stream_mp": "FIXED_BASE",
                "base_stream_host": "caster.example",
            },
        ])
        manager._set_rover_as_temporary_base = AsyncMock()

        async def toggle_fixed_base(_mountpoint, sleep, selected_host=""):
            events.append(("base-mode", "sleep" if sleep else "restored"))

        manager._toggle_cors_fixed_base = AsyncMock(side_effect=toggle_fixed_base)
        manager._build_cluster_result = Mock(return_value={"rover_count": 2})

        module_name = RoundRobinAdjustmentManager.__module__
        with patch(f"{module_name}.asyncio.sleep", new=AsyncMock()):
            await manager._run_cycle(71)

        restore_index = events.index(("base-mode", "restored"))
        result_index = events.index(("result", "published"))
        self.assertLess(restore_index, result_index)
        self.assertTrue(any(
            kind == "progress" and "aggregating repeated baselines" in message
            for kind, message in events[restore_index:result_index]
        ))
        self.assertFalse(any(kind == "progress" for kind, _message in events[result_index + 1:]))


if __name__ == "__main__":
    unittest.main()
