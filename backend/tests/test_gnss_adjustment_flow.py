import unittest
import time
import numpy as np
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

try:
    from backend.processors.gnss_adjustment.round_robin import (
        RoundRobinAdjustmentManager,
        _SafeRoverRotationSkip,
        _InformationAccumulator,
        _graph_components,
        _initial_positive_sequence_ess,
        _rolling_mean_stability,
    )
    from backend.processors.gnss_adjustment.runtime import _llh_to_ecef, parse_agrica
except ModuleNotFoundError:
    from processors.gnss_adjustment.round_robin import (
        RoundRobinAdjustmentManager,
        _SafeRoverRotationSkip,
        _InformationAccumulator,
        _graph_components,
        _initial_positive_sequence_ess,
        _rolling_mean_stability,
    )
    from processors.gnss_adjustment.runtime import _llh_to_ecef, parse_agrica


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
    minute=0,
    undulation=0.0,
):
    """Create the subset of a valid UM980 AGRICA sentence needed by the parser."""

    parts = ["0"] * 57
    parts[0] = "GNSS"
    parts[1] = "232"
    parts[2:8] = ["24", "1", "1", "0", str(minute), str(second)]
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
    parts[50] = str(undulation)
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
        self.assertFalse(self.manager.has_complete_seed_observations(17))
        self.assertEqual(
            self.manager.get_seed_collection_status(17)["warming_station_ids"],
            [101, 102],
        )
        seed_stationary_epochs = (
            2 * self.manager.STABILITY_WINDOW_SECONDS
            + self.manager.STABILITY_HOLD_SECONDS
        )
        for second in range(1, seed_stationary_epochs):
            self._add(
                101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0),
                second=second,
            )
            self._add(
                102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
                second=second,
            )
        self.assertFalse(self.manager.has_complete_seed_observations(17))
        # The verified warm-up is part of the same seed session. One more
        # epoch reaches both 30 seconds and 30 distinct epochs; collection must
        # not restart from zero here.
        for second in (self.manager.SEED_SOLVER_MIN_DURATION_SECONDS,):
            self._add(
                101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0),
                second=second,
            )
            self._add(
                102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0),
                second=second,
            )
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
        m0 = result["quality"]["reference_standard_deviation"]
        self.assertGreater(m0, 0.0)
        for point in result["points"].values():
            prior = np.asarray([
                point["std_x_a_priori"],
                point["std_y_a_priori"],
                point["std_z_a_priori"],
            ])
            posterior = np.asarray([
                point["std_x_a_posteriori"],
                point["std_y_a_posteriori"],
                point["std_z_a_posteriori"],
            ])
            np.testing.assert_allclose(posterior, m0 * prior, rtol=1e-12, atol=1e-15)
        self.assertEqual(
            result["quality"]["pre_stable_window_excluded_count"],
            0,
        )
        fixed_edges = [
            edge for edge in result["baselines"] if edge["from"] == "BASE"
        ]
        self.assertTrue(all(
            edge["observation_count"]
            == seed_stationary_epochs + 1
            for edge in fixed_edges
        ))
        self.assertTrue(all(
            edge["effective_sample_size"] == 1.0
            for edge in result["quality"]["effective_sample_size_edges"]
        ))
        self.assertTrue(all(
            edge["acf_estimated_effective_sample_size"] >= 1.0
            for edge in result["quality"]["effective_sample_size_edges"]
        ))
        for edge in result["baselines"]:
            formal = np.asarray(edge["formal_covariance_xyz"], dtype=float)
            used = np.asarray(edge["session_covariance_used_xyz"], dtype=float)
            self.assertTrue(np.all(np.linalg.eigvalsh(formal) > 0.0))
            self.assertTrue(np.all(np.linalg.eigvalsh(used) > 0.0))
            self.assertTrue(np.all(np.diag(used) >= np.diag(formal)))
            self.assertGreaterEqual(edge["session_count"], 1)
            self.assertAlmostEqual(
                edge["total_covariance_inflation_factor"],
                edge["temporal_inflation_factor"]
                * edge["scatter_scale_factor"],
            )
            self.assertGreaterEqual(edge["max_session_mean_separation_m"], 0.0)

    def test_final_solver_uses_immutable_fixed_base_seed_snapshot(self):
        self._add(101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0))
        self._add(102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0))

        session = self.manager._sessions[17]
        cluster = session["clusters"][0]
        cluster["fixed_base_seed_cutoff_index"] = len(cluster["observations"])
        self.manager._freeze_temporary_base_coordinates(cluster)

        # Reproduce the field failure: later handover bookkeeping mutates the
        # live BASE records after their seed has already been accepted/frozen.
        for record in cluster["observations"]:
            record.solver_eligible = False
            record.quality_flags = ("EXCLUDE_POST_SEED_TRANSITION",)

        session["active_bases"][0] = "S1"
        self._add(
            102,
            "S2",
            (3.0, 3.0, 0.0),
            (21.0002, 105.0, 10.0),
            base_llh=(21.0001, 105.0, 10.0),
        )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, cluster)

        fixed_edges = {
            edge["to"]
            for edge in result["baselines"]
            if edge["from"] == "BASE"
        }
        self.assertEqual(fixed_edges, {"S1", "S2"})
        self.assertEqual(len(result["baselines"]), 3)

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

    def test_rolling_mean_stability_is_componentwise_and_detects_returning_drift(self):
        stable_samples = [
            (epoch, (1.0 + epoch * 0.00001, 2.0, 3.0))
            for epoch in range(0, 41, 2)
        ]
        stable = _rolling_mean_stability(stable_samples)
        self.assertTrue(stable["stable"])
        self.assertEqual(stable["window_seconds"], 10)
        self.assertGreaterEqual(stable["stable_run_seconds"], 10)
        self.assertLess(abs(stable["delta_neu_m"][0]), 0.003)

        drifting_samples = [
            (epoch, (1.0, 2.0, 3.0 + max(0, epoch - 20) * 0.001))
            for epoch in range(0, 41, 2)
        ]
        drifting = _rolling_mean_stability(drifting_samples)
        self.assertFalse(drifting["stable"])
        self.assertGreater(abs(drifting["delta_neu_m"][2]), 0.005)

    def test_rolling_stability_rejects_scatter_and_slope_even_when_means_match(self):
        oscillating = [
            (epoch, (1.0 + (0.02 if epoch % 2 else -0.02), 2.0, 3.0))
            for epoch in range(40)
        ]
        scatter = _rolling_mean_stability(
            oscillating,
            ewma_horizontal_limit_m=1.0,
            ewma_up_limit_m=1.0,
        )
        self.assertTrue(scatter["mean_stable"])
        self.assertFalse(scatter["scatter_stable"])
        self.assertFalse(scatter["stable"])

        repeating_ramp = [
            (epoch, (1.0 + (epoch % 10) * 0.002, 2.0, 3.0))
            for epoch in range(40)
        ]
        slope = _rolling_mean_stability(
            repeating_ramp,
            horizontal_std_limit_m=1.0,
            ewma_horizontal_limit_m=1.0,
            ewma_up_limit_m=1.0,
        )
        self.assertTrue(slope["mean_stable"])
        self.assertFalse(slope["slope_stable"])
        self.assertFalse(slope["stable"])

    def test_information_accumulator_matches_batch_weighted_mean(self):
        accumulator = _InformationAccumulator()
        vectors = [
            np.asarray((1.0, 2.0, 3.0)),
            np.asarray((1.2, 1.9, 3.1)),
        ]
        covariances = [
            np.diag((0.04, 0.09, 0.16)),
            np.diag((0.01, 0.04, 0.09)),
        ]
        for epoch, (vector, covariance) in enumerate(
            zip(vectors, covariances, strict=True), start=1
        ):
            accumulator.add(
                epoch,
                vector,
                covariance,
                fast_tau_seconds=3.0,
                slow_tau_seconds=30.0,
                retention_seconds=30,
            )
        precision = sum(np.linalg.solve(item, np.eye(3)) for item in covariances)
        information = sum(
            np.linalg.solve(covariance, vector)
            for covariance, vector in zip(covariances, vectors, strict=True)
        )
        expected_mean = np.linalg.solve(precision, information)
        expected_covariance = np.linalg.solve(precision, np.eye(3))
        np.testing.assert_allclose(accumulator.mean, expected_mean, atol=1e-12)
        np.testing.assert_allclose(
            accumulator.formal_covariance,
            expected_covariance,
            atol=1e-12,
        )

    def test_seed_solver_reuses_warmup_at_half_hz(self):
        stations = (
            (101, "S1", (1.0, 2.0, 0.0), (21.0001, 105.0, 10.0)),
            (102, "S2", (4.0, 5.0, 0.0), (21.0002, 105.0, 10.0)),
        )
        for epoch in range(0, 41, 2):
            minute, second = divmod(epoch, 60)
            for station_id, station_code, baseline, rover_llh in stations:
                self._add(
                    station_id,
                    station_code,
                    baseline,
                    rover_llh,
                    minute=minute,
                    second=second,
                )

        opened = self.manager.get_seed_collection_status(17)
        self.assertFalse(opened["complete"])
        self.assertTrue(all(
            opened["clusters"][0]["solver_window_open_by_station"].values()
        ))
        self.assertTrue(all(
            count == 21
            for count in opened["clusters"][0]["solver_sample_counts_by_station"].values()
        ))

        # Continue the same session to 30 distinct epochs. At 0.5 Hz this has
        # broad temporal coverage without collecting a second seed window.
        for epoch in range(42, 59, 2):
            minute, second = divmod(epoch, 60)
            for station_id, station_code, baseline, rover_llh in stations:
                self._add(
                    station_id,
                    station_code,
                    baseline,
                    rover_llh,
                    minute=minute,
                    second=second,
                )

        completed = self.manager.get_seed_collection_status(17)
        self.assertTrue(completed["complete"])
        self.assertEqual(
            completed["solver_min_distinct_epochs"],
            self.manager.SEED_SOLVER_MIN_DISTINCT_EPOCHS,
        )
        self.assertTrue(all(
            count == self.manager.SEED_SOLVER_MIN_DISTINCT_EPOCHS
            for count in completed["clusters"][0]["solver_sample_counts_by_station"].values()
        ))

    def test_fixed_base_warmup_opens_even_when_rolling_three_mm_is_not_met(self):
        stations = (
            (101, "S1", (21.0001, 105.0, 10.0)),
            (102, "S2", (21.0002, 105.0, 10.0)),
        )
        for epoch in range(20):
            for station_id, station_code, rover_llh in stations:
                self._add(
                    station_id,
                    station_code,
                    (1.0 + epoch * 0.0007, 2.0, 0.0),
                    rover_llh,
                    second=epoch,
                )

        opened = self.manager.get_seed_collection_status(17)
        rolling = opened["clusters"][0]["rolling_stability_by_station"]
        self.assertTrue(any(not item["stable"] for item in rolling.values()))
        self.assertTrue(all(
            opened["clusters"][0]["solver_window_open_by_station"].values()
        ))
        self.assertTrue(all(
            opened["clusters"][0]["warmup_ready_by_station"].values()
        ))

    def test_seed_status_distinguishes_float_from_silent_station(self):
        self._add(
            101,
            "S1",
            (1.0, 2.0, 0.0),
            (21.0001, 105.0, 10.0),
            position_type=5,
        )

        status = self.manager.get_seed_collection_status(17)

        self.assertEqual(status["invalid_fix_station_ids"], [101])
        self.assertEqual(status["silent_station_ids"], [102])
        self.assertEqual(
            status["clusters"][0]["latest_position_type_by_station"][101],
            5,
        )

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
        self.assertEqual(len(session["clusters"][0]["observations"]), 3)
        audit_record = session["clusters"][0]["observations"][-1]
        self.assertFalse(audit_record.solver_eligible)
        self.assertIn("EXCLUDE_UNCONFIRMED_SOURCE", audit_record.quality_flags)
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

    def test_missing_rover_is_excluded_after_complete_seed_window(self):
        self.manager.configure_project(18, [{
            "name": "cluster-with-offline-rover",
            "stations": [201, 202, 203],
            "rovers": ["A", "B", "C"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])
        stationary_epochs = (
            2 * self.manager.STABILITY_WINDOW_SECONDS
            + self.manager.STABILITY_HOLD_SECONDS
        )
        for second in range(stationary_epochs):
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
        self.assertFalse(after_skip["complete"])
        self.assertEqual(after_skip["skipped_station_ids"], [203])
        self.assertEqual(self.manager._sessions[18]["clusters"][0]["stations"], [201, 202])
        for sample_index in range(self.manager.SEED_SOLVER_MIN_DURATION_SECONDS + 1):
            minute, second = divmod(sample_index, 60)
            for station_id, station_code, baseline in (
                (201, "A", (1.0, 0.0, 0.0)),
                (202, "B", (2.0, 0.0, 0.0)),
            ):
                self.manager.add_agrica_payload(
                    _agrica_sentence(
                        baseline_neu=baseline,
                        rover_llh=(21.0, 105.0, 10.0),
                        minute=minute + 1,
                        second=second,
                    ),
                    {"project_id": 18, "station_id": station_id, "station_code": station_code},
                )
        self.assertTrue(self.manager.get_seed_collection_status(18)["complete"])

    def test_seed_step_display_is_capped_at_configured_maximum(self):
        self.manager._sessions[17]["seed_collection_steps"] = set(range(127))

        status = self.manager.get_seed_collection_status(17)

        self.assertEqual(status["step_count"], self.manager.SEED_COLLECTION_MAX_STEPS)

    def test_four_selected_rovers_continue_with_three_after_seed_window(self):
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
        stationary_epochs = (
            2 * self.manager.STABILITY_WINDOW_SECONDS
            + self.manager.STABILITY_HOLD_SECONDS
        )
        for second in range(stationary_epochs):
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
        self.assertEqual(status["step_count"], self.manager.SEED_COLLECTION_MAX_STEPS)
        self.assertEqual(status["missing_station_ids"], [6])

        skipped = self.manager.skip_missing_seed_stations(19)
        self.assertFalse(skipped["complete"])
        self.assertEqual(skipped["skipped_station_ids"], [6])
        self.assertEqual(self.manager._sessions[19]["clusters"][0]["stations"], [4, 5, 7])
        for sample_index in range(self.manager.SEED_SOLVER_MIN_DURATION_SECONDS + 1):
            minute, second = divmod(sample_index, 60)
            for station_id, station_code, baseline in live:
                self.manager.add_agrica_payload(
                    _agrica_sentence(
                        baseline_neu=baseline,
                        rover_llh=(21.0, 105.0, 10.0),
                        minute=minute + 1,
                        second=second,
                    ),
                    {"project_id": 19, "station_id": station_id, "station_code": station_code},
                )
        self.assertTrue(self.manager.get_seed_collection_status(19)["complete"])

    def test_sparse_seed_rover_is_skipped_after_stability_timeout(self):
        self.manager.configure_project(20, [{
            "name": "three-rover-cluster",
            "stations": [201, 202, 203],
            "rovers": ["ReadyA", "ReadyB", "Sparse"],
            "base_station": "CORS-A",
            "base_lat": 21.0,
            "base_lon": 105.0,
            "base_alt": 10.0,
        }])
        ready_epochs = self.manager.SEED_SOLVER_MIN_DURATION_SECONDS + 1
        for second in range(ready_epochs):
            for station_id, station_code, baseline in (
                (201, "ReadyA", (1.0, 0.0, 0.0)),
                (202, "ReadyB", (2.0, 0.0, 0.0)),
            ):
                self.manager.add_agrica_payload(
                    _agrica_sentence(
                        baseline_neu=baseline,
                        rover_llh=(21.0, 105.0, 10.0),
                        second=second,
                    ),
                    {
                        "project_id": 20,
                        "station_id": station_id,
                        "station_code": station_code,
                    },
                )
        for second in range(2):
            self.manager.add_agrica_payload(
                _agrica_sentence(
                    baseline_neu=(3.0, 0.0, 0.0),
                    rover_llh=(21.0, 105.0, 10.0),
                    second=second,
                ),
                {
                    "project_id": 20,
                    "station_id": 203,
                    "station_code": "Sparse",
                },
            )
        self.manager._sessions[20]["seed_started_monotonic"] = (
            time.monotonic() - self.manager.SEED_STABILITY_TIMEOUT_SECONDS - 1.0
        )

        status = self.manager.get_seed_collection_status(20)

        self.assertTrue(status["stability_timeout"])
        self.assertTrue(status["fallback_ready"])
        self.assertEqual(status["warming_station_ids"], [203])
        self.assertEqual(status["timeout_skippable_station_ids"], [203])

        skipped = self.manager.skip_missing_seed_stations(20)

        self.assertTrue(skipped["complete"])
        self.assertEqual(skipped["skipped_station_ids"], [203])
        self.assertEqual(
            self.manager._sessions[20]["clusters"][0]["stations"],
            [201, 202],
        )

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
            "matches configured fixed BASE",
            self.manager.get_last_ingest_diagnostic(17)["message"],
        )

    def test_backup_fixed_base_is_locked_from_reported_agrica_coordinate(self):
        cluster = self.manager._sessions[17]["clusters"][0]
        cluster["fixed_base_candidates"] = [
            {
                "role": "primary",
                "base_station": "SinQuyen1",
                "base_lat": 21.0,
                "base_lon": 105.0,
                "base_alt": 10.0,
                "base_stream_host": "primary.example",
                "base_stream_port": 2101,
                "base_stream_mp": "SinQuyen1",
            },
            {
                "role": "backup",
                "base_station": "SinQuyen2",
                "base_lat": 21.01,
                "base_lon": 105.01,
                "base_alt": 12.0,
                "base_stream_host": "backup.example",
                "base_stream_port": 2101,
                "base_stream_mp": "SinQuyen1",
            },
        ]
        cluster["selected_fixed_base_candidate"] = None

        accepted = self._add(
            101,
            "S1",
            (1.0, 2.0, 0.0),
            (21.0101, 105.01, 12.0),
            base_llh=(21.01, 105.01, 12.0),
        )

        self.assertEqual(len(accepted), 1)
        selected = cluster["selected_fixed_base_candidate"]
        self.assertEqual(selected["role"], "backup")
        self.assertEqual(cluster["base_station"], "SinQuyen2")
        self.assertEqual(cluster["base_stream_host"], "backup.example")
        self.assertEqual(cluster["base_stream_mp"], "SinQuyen1")
        self.assertIn("selected backup fixed base", cluster["fixed_base_selection_diagnostic"])
        conflicting = self._add(
            102,
            "S2",
            (1.0, 2.0, 0.0),
            (21.0001, 105.0, 10.0),
            base_llh=(21.0, 105.0, 10.0),
        )
        self.assertEqual(conflicting, [])
        self.assertEqual(
            cluster["selected_fixed_base_candidate"]["base_station"],
            "SinQuyen2",
        )

    def test_stale_temporary_base_fixed_solution_is_not_mislabeled_as_fixed_base(self):
        rejected = self._add(
            101,
            "S1",
            (2.0, 1.0, 0.0),
            (21.0015, 105.0, 10.0),
            base_llh=(0.0, 0.0, 0.0),
        )

        self.assertEqual(rejected, [])
        diagnostic = self.manager.get_last_ingest_diagnostic(17)["message"]
        self.assertIn("does not match distance to configured fixed BASE", diagnostic)
        self.assertIn("previous temporary-base Fixed solution", diagnostic)
        audit_record = self.manager._sessions[17]["clusters"][0]["observations"][-1]
        self.assertFalse(audit_record.solver_eligible)
        self.assertEqual(audit_record.base_name, "BASE")
        self.assertIn("EXCLUDE_UNCONFIRMED_SOURCE", audit_record.quality_flags)

    def test_matching_base_coordinate_still_requires_plausible_baseline_length(self):
        self.manager._sessions[17]["clusters"][0][
            "require_fixed_base_length_check"
        ] = True
        rejected = self._add(
            101,
            "S1",
            (5.0, 0.0, 0.0),
            (21.01, 105.0, 10.0),
            # Metadata already names the selected base, but this short vector
            # is still from another correction source roughly 1.1 km away.
            base_llh=(21.0, 105.0, 10.0),
        )

        self.assertEqual(rejected, [])
        diagnostic = self.manager.get_last_ingest_diagnostic(17)["message"]
        self.assertIn("baseline horizontal length", diagnostic)
        self.assertIn("previous RTCM source", diagnostic)
        audit_record = self.manager._sessions[17]["clusters"][0]["observations"][-1]
        self.assertFalse(audit_record.solver_eligible)
        self.assertIn("EXCLUDE_UNCONFIRMED_SOURCE", audit_record.quality_flags)

        accepted = self._add(
            101,
            "S1",
            (1113.2, 0.0, 0.0),
            (21.01, 105.0, 10.0),
            base_llh=(21.0, 105.0, 10.0),
            second=1,
        )
        self.assertEqual(len(accepted), 1)
        self.assertIn(
            "baseline length",
            self.manager.get_last_ingest_diagnostic(17)["message"],
        )

    def test_gross_loop_misclosure_keeps_audit_but_blocks_official_publish(self):
        # Two correct fixed-base edges plus a cross edge that duplicates one
        # fixed-base vector emulate a stale temporary-base Fixed solution being
        # mislabeled after the route changes.
        self._add(101, "S1", (100.0, 0.0, 0.0), (21.0009, 105.0, 10.0))
        self._add(102, "S2", (200.0, 0.0, 0.0), (21.0018, 105.0, 10.0))
        session = self.manager._sessions[17]
        session["active_bases"][0] = "S1"
        self._add(
            102,
            "S2",
            (200.0, 0.0, 0.0),
            (21.0018, 105.0, 10.0),
            base_llh=(21.0009, 105.0, 10.0),
        )
        session["active_bases"].clear()

        result = self.manager._build_cluster_result(17, 0, session["clusters"][0])

        self.assertFalse(result["official_publish_allowed"])
        self.assertEqual(result["quality_gate"]["status"], "FAILED_QUALITY_GATE")
        self.assertGreater(result["quality_gate"]["max_pre_adjustment_loop_closure_m"], 0.003)
        self.assertIsNone(result["quality_gate"]["pre_adjustment_loop_closure_limit_m"])
        self.assertTrue(result["quality_gate"]["loop_closure_diagnostic_only"])
        self.assertEqual(result["quality_gate"]["closure_failures"], [])
        self.assertNotIn("0.003", " ".join(result["quality_gate"]["reasons"]))
        self.assertTrue(result["quality_gate"]["audit_report_allowed"])

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

    def test_temporary_base_cache_uses_ecef_ellipsoidal_height_not_agrica_msl_height(self):
        ellipsoidal_llh = (21.0, 105.0, -7.2)
        self._add(
            101,
            "S1",
            (1.0, 2.0, 0.0),
            (21.0, 105.0, 16.8),
            rover_ecef=_llh_to_ecef(*ellipsoidal_llh),
            undulation=-24.0,
        )

        cached = self.manager.rover_llh_cache["S1"]
        self.assertAlmostEqual(cached["lat"], ellipsoidal_llh[0], places=7)
        self.assertAlmostEqual(cached["lon"], ellipsoidal_llh[1], places=7)
        self.assertAlmostEqual(cached["alt"], ellipsoidal_llh[2], places=3)
        self.assertAlmostEqual(cached["orthometric_alt"], 16.8, places=3)
        self.assertAlmostEqual(cached["ellipsoid_alt"], -7.2, places=3)
        self.assertAlmostEqual(cached["undulation"], -24.0, places=3)

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
    async def test_failed_rotation_can_proceed_when_other_base_connects_graph(self):
        attempted_rovers = []
        progress_messages = []
        published_results = []
        errors = []

        async def progress_callback(_project_id, message):
            progress_messages.append(message)

        async def result_callback(_project_id, result):
            published_results.append(result)

        async def error_callback(_project_id, message):
            errors.append(message)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            error_callback=error_callback,
        )
        manager.configure_project(70, [{
            "name": "skip-cluster",
            "stations": [701, 702],
            "rovers": ["R1", "R2"],
        }])
        manager._freeze_temporary_base_coordinates = Mock(
            return_value={"R1": {}, "R2": {}}
        )

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
        self.assertEqual(errors, [])
        self.assertTrue(any(
            "Proceeding with connected partial rotation coverage" in message
            for message in progress_messages
        ))

    async def test_partial_rotation_uses_targeted_recovery_to_connect_graph(self):
        attempted_rovers = []
        expected_targets = []
        published_results = []
        errors = []

        async def result_callback(_project_id, result):
            published_results.append(result)

        async def error_callback(_project_id, message):
            errors.append(message)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            result_callback=result_callback,
            error_callback=error_callback,
        )
        manager.configure_project(71, [{
            "name": "targeted-recovery-cluster",
            "stations": [701, 702, 703],
            "rovers": ["R1", "R2", "R3"],
        }])
        manager._freeze_temporary_base_coordinates = Mock(
            return_value={"R1": {}, "R2": {}, "R3": {}}
        )

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

        self.assertEqual(attempted_rovers, ["R1", "R2", "R2", "R3", "R3", "R1"])
        self.assertEqual(expected_targets[0], {"R2", "R3"})
        self.assertEqual(expected_targets[-1], {"R3"})
        self.assertEqual(len(published_results), 1)
        self.assertEqual(errors, [])

    async def test_disconnected_cross_graph_still_aborts_adjustment(self):
        published_results = []
        errors = []
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            result_callback=lambda _project_id, result: published_results.append(result),
            error_callback=lambda _project_id, message: errors.append(message),
        )
        manager.configure_project(74, [{
            "name": "disconnected-cluster",
            "stations": [701, 702],
            "rovers": ["R1", "R2"],
        }])
        manager._freeze_temporary_base_coordinates = Mock(
            return_value={"R1": {}, "R2": {}}
        )
        manager._set_rover_as_temporary_base = AsyncMock()
        manager._build_cluster_result = Mock(return_value={"rover_count": 2})

        await manager._run_cycle(74)

        self.assertEqual(published_results, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("cross-baseline graph remains disconnected", errors[0])
        manager._build_cluster_result.assert_not_called()

    async def test_high_std_cross_samples_do_not_stop_rotation_retry(self):
        attempted_rovers = []
        attempts_by_rover = {"R1": 0, "R2": 0}

        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(72, [{
            "name": "quality-retry-cluster",
            "stations": [701, 702],
            "rovers": ["R1", "R2"],
        }])
        manager._freeze_temporary_base_coordinates = Mock(
            return_value={"R1": {}, "R2": {}}
        )

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

        self.assertEqual(attempted_rovers, ["R1", "R1", "R2", "R2"])

    async def test_complete_cross_graph_still_rotates_every_configured_base(self):
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
        manager._freeze_temporary_base_coordinates = Mock(
            return_value={"R1": {}, "R2": {}, "R3": {}}
        )

        async def rotate(rover_code, **_kwargs):
            attempted_rovers.append(rover_code)
            for target in {"R1", "R2", "R3"} - {rover_code}:
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

        self.assertEqual(attempted_rovers, ["R1", "R2", "R3"])
        self.assertTrue(any(
            "3/3 temporary-BASE rotations completed" in message
            for message in progress_messages
        ))

    async def test_inter_rotation_reacquires_fixed_base_before_next_sleep(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        cluster = {
            "rovers": ["R1", "R2", "R3"],
            "observations": [],
        }
        toggle_calls = []

        async def toggle(mountpoint, enabled, selected_host="", **_kwargs):
            toggle_calls.append((mountpoint, enabled, selected_host))

        async def add_fixed_epochs(_delay):
            if cluster["observations"]:
                return
            for rover_name in ("R2",):
                for epoch in range(3):
                    cluster["observations"].append(
                        SimpleNamespace(
                            base_name="BASE",
                            solver_eligible=True,
                            observation=SimpleNamespace(
                                rover_name=rover_name,
                                epoch_ts=epoch,
                                std_neu=(0.01, 0.01, 0.01),
                                baseline_neu=(10.0, 0.0, 0.0),
                            ),
                        )
                    )

        manager._set_cors_fixed_base_enabled = AsyncMock(side_effect=toggle)
        manager._find_client_info = AsyncMock(return_value={"Username": "R2"})
        module_name = RoundRobinAdjustmentManager.__module__
        with patch(f"{module_name}.asyncio.sleep", new=add_fixed_epochs):
            await manager._reacquire_fixed_base_between_rotations(
                71,
                cluster,
                next_rover="R2",
                mountpoint="FIXED",
                selected_host="caster.example",
            )

        self.assertEqual(
            toggle_calls,
            [
                ("FIXED", True, "caster.example"),
            ],
        )
        self.assertGreaterEqual(manager._find_client_info.await_count, 2)
        manager._find_client_info.assert_any_await(
            "R2",
            project_id=71,
            log_missing=False,
        )
        self.assertTrue(cluster["observations"])
        self.assertTrue(all(
            not record.solver_eligible
            and "EXCLUDE_INTER_ROTATION_REACQUISITION" in record.quality_flags
            for record in cluster["observations"]
        ))

    async def test_inter_rotation_reacquisition_extends_for_live_transition_data(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
        manager.INTER_ROTATION_CLIENT_POLL_SECONDS = 5
        cluster = {
            "rovers": ["R1", "R2"],
            "observations": [],
        }
        progress_messages = []
        manager.progress_callback = AsyncMock(
            side_effect=lambda _project_id, message: progress_messages.append(message)
        )
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(return_value={"Username": "R2"})

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        valid_epochs_added = False

        async def advance_clock(_delay):
            nonlocal valid_epochs_added
            fake_loop.now += 30.0
            if fake_loop.now <= 90.0:
                cluster["observations"].append(SimpleNamespace(
                    base_name="BASE",
                    solver_eligible=False,
                    observation=SimpleNamespace(
                        rover_name="R2",
                        epoch_ts=int(fake_loop.now),
                        std_neu=(0.01, 0.01, 0.01),
                        baseline_neu=(10.0, 0.0, 0.0),
                    ),
                ))
            elif fake_loop.now >= 150.0 and not valid_epochs_added:
                valid_epochs_added = True
                for epoch in (150, 151, 152):
                    cluster["observations"].append(SimpleNamespace(
                        base_name="BASE",
                        solver_eligible=True,
                        observation=SimpleNamespace(
                            rover_name="R2",
                            epoch_ts=epoch,
                            std_neu=(0.01, 0.01, 0.01),
                            baseline_neu=(10.0, 0.0, 0.0),
                        ),
                    ))

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            completed = await manager._reacquire_fixed_base_between_rotations(
                71,
                cluster,
                next_rover="R2",
                mountpoint="FIXED",
                selected_host="caster.example",
            )

        self.assertTrue(completed)
        self.assertTrue(valid_epochs_added)
        self.assertGreaterEqual(fake_loop.now, 150.0)
        self.assertTrue(any(
            "extending adaptively" in message for message in progress_messages
        ))
        self.assertEqual(manager._set_cors_fixed_base_enabled.await_count, 1)

    async def test_inter_rotation_missing_aicaster_session_skips_offline_rover(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
        manager.INTER_ROTATION_CLIENT_POLL_SECONDS = 5
        cluster = {
            "rovers": ["R1", "R2"],
            "observations": [],
        }
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(return_value=None)
        progress_messages = []
        manager.progress_callback = AsyncMock(
            side_effect=lambda _project_id, message: progress_messages.append(message)
        )

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()

        async def advance_clock(_delay):
            fake_loop.now += 30.0

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            reacquired = await manager._reacquire_fixed_base_between_rotations(
                71,
                cluster,
                next_rover="R2",
                mountpoint="FIXED",
                selected_host="caster.example",
            )

        self.assertFalse(reacquired)
        self.assertGreaterEqual(manager._find_client_info.await_count, 2)
        self.assertTrue(any(
            "AICaster session disappeared" in message
            and "skipping its temporary-BASE rotation" in message
            and "session=checked-missing" in message
            for message in progress_messages
        ))

    async def test_inter_rotation_aicaster_query_failure_is_not_treated_as_offline(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
        manager.INTER_ROTATION_CLIENT_POLL_SECONDS = 5
        cluster = {
            "rovers": ["R1", "R2"],
            "observations": [],
        }
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(
            side_effect=RuntimeError("client table unavailable")
        )

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()

        async def advance_clock(_delay):
            fake_loop.now += 30.0

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            with self.assertRaisesRegex(RuntimeError, "session=check-failed"):
                await manager._reacquire_fixed_base_between_rotations(
                    71,
                    cluster,
                    next_rover="R2",
                    mountpoint="FIXED",
                    selected_host="caster.example",
                )

    async def test_inter_rotation_live_control_without_fixed_epochs_skips_stale_rover(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
        manager.INTER_ROTATION_CLIENT_POLL_SECONDS = 5
        cluster = {
            "rovers": ["R1", "R2"],
            "observations": [],
        }
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(return_value={"Username": "R2"})
        progress_messages = []
        manager.progress_callback = AsyncMock(
            side_effect=lambda _project_id, message: progress_messages.append(message)
        )

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()

        async def advance_clock(_delay):
            fake_loop.now += 30.0
            if fake_loop.now == 30.0:
                for epoch in (30, 31, 32):
                    cluster["observations"].append(SimpleNamespace(
                        base_name="BASE",
                        solver_eligible=True,
                        observation=SimpleNamespace(
                            rover_name="R1",
                            epoch_ts=epoch,
                            std_neu=(0.01, 0.01, 0.01),
                            baseline_neu=(10.0, 0.0, 0.0),
                        ),
                    ))

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            reacquired = await manager._reacquire_fixed_base_between_rotations(
                71,
                cluster,
                next_rover="R2",
                mountpoint="FIXED",
                selected_host="caster.example",
            )

        self.assertFalse(reacquired)
        self.assertLessEqual(fake_loop.now, 60.0)
        self.assertEqual(cluster["_last_reacquire_skip_mode"], "offline")
        self.assertTrue(any(
            "session is active" in message
            and "no fresh, solver-eligible fixed-BASE epochs" in message
            and "data-plane-stale rover" in message
            for message in progress_messages
        ))

    async def test_inter_rotation_all_rovers_silent_remains_fixed_base_failure(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 120
        cluster = {"rovers": ["R1", "R2"], "observations": []}
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(return_value={"Username": "R2"})

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()

        async def advance_clock(_delay):
            fake_loop.now += 30.0

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            with self.assertRaisesRegex(RuntimeError, "Fixed BASE reacquisition"):
                await manager._reacquire_fixed_base_between_rotations(
                    71,
                    cluster,
                    next_rover="R2",
                    mountpoint="FIXED",
                    selected_host="caster.example",
                )

    async def test_live_agrica_without_control_session_waives_only_base_rotation(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.INTER_ROTATION_REACQUIRE_TIMEOUT_SECONDS = 120
        manager.INTER_ROTATION_REACQUIRE_ACTIVITY_GRACE_SECONDS = 60
        manager.INTER_ROTATION_REACQUIRE_MAX_SECONDS = 300
        manager.INTER_ROTATION_CLIENT_POLL_SECONDS = 5
        cluster = {
            "rovers": ["R1", "R2"],
            "observations": [],
        }
        manager._set_cors_fixed_base_enabled = AsyncMock()
        manager._find_client_info = AsyncMock(return_value=None)
        progress_messages = []
        manager.progress_callback = AsyncMock(
            side_effect=lambda _project_id, message: progress_messages.append(message)
        )

        class FakeLoop:
            now = 0.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        added = False

        async def advance_clock(_delay):
            nonlocal added
            fake_loop.now += 30.0
            if not added:
                added = True
                for epoch in (30, 31, 32):
                    cluster["observations"].append(SimpleNamespace(
                        base_name="BASE",
                        # Transition AGRICA proves data-plane liveness even
                        # when source validation correctly quarantines it.
                        solver_eligible=False,
                        observation=SimpleNamespace(
                            rover_name="R2",
                            epoch_ts=epoch,
                            std_neu=(0.01, 0.01, 0.01),
                            baseline_neu=(10.0, 0.0, 0.0),
                        ),
                    ))

        module_name = RoundRobinAdjustmentManager.__module__
        with (
            patch(f"{module_name}.asyncio.get_running_loop", return_value=fake_loop),
            patch(f"{module_name}.asyncio.sleep", new=advance_clock),
        ):
            reacquired = await manager._reacquire_fixed_base_between_rotations(
                71,
                cluster,
                next_rover="R2",
                mountpoint="FIXED",
                selected_host="caster.example",
            )

        self.assertFalse(reacquired)
        self.assertEqual(cluster["_last_reacquire_skip_mode"], "uncontrolled")
        self.assertTrue(any(
            "AGRICA is live" in message
            and "skipping only its temporary-BASE rotation" in message
            and "remains eligible as a rover" in message
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
        manager._freeze_temporary_base_coordinates = Mock(
            side_effect=lambda cluster: {
                rover: {} for rover in cluster["rovers"]
            }
        )
        async def rotate(rover_code, **_kwargs):
            for cluster in manager._sessions[71]["clusters"]:
                if rover_code not in cluster["rovers"]:
                    continue
                target = next(
                    candidate
                    for candidate in cluster["rovers"]
                    if candidate != rover_code
                )
                cluster["observations"].append(
                    SimpleNamespace(
                        base_name=rover_code,
                        observation=SimpleNamespace(
                            rover_name=target,
                            std_neu=(0.01, 0.01, 0.01),
                            baseline_neu=(10.0, 0.0, 0.0),
                        ),
                    )
                )
                return

        manager._set_rover_as_temporary_base = rotate

        async def toggle_fixed_base(_mountpoint, enabled, selected_host="", **_kwargs):
            events.append(("base-server", "enabled" if enabled else "disabled"))

        manager._set_cors_fixed_base_enabled = AsyncMock(side_effect=toggle_fixed_base)
        manager._reacquire_fixed_base_between_rotations = AsyncMock()
        manager._build_cluster_result = Mock(return_value={"rover_count": 2})

        module_name = RoundRobinAdjustmentManager.__module__
        with patch(f"{module_name}.asyncio.sleep", new=AsyncMock()):
            await manager._run_cycle(71)

        restore_index = events.index(("base-server", "enabled"))
        result_index = events.index(("result", "published"))
        self.assertLess(restore_index, result_index)
        self.assertEqual(
            manager._reacquire_fixed_base_between_rotations.await_count,
            2,
        )
        self.assertTrue(any(
            kind == "progress" and "aggregating repeated baselines" in message
            for kind, message in events[restore_index:result_index]
        ))
        self.assertFalse(any(kind == "progress" for kind, _message in events[result_index + 1:]))


if __name__ == "__main__":
    unittest.main()
