import asyncio
import unittest
from collections import deque
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from processors.gnss_processor import GNSSVelocityProcessor
from app.mqtt.bridge import MQTTBridge
from processors.landslide_analyzer import LandslideAnalyzer


class GnssFixedOnlyTests(unittest.TestCase):
    def test_adjustment_gga_does_not_poison_monitoring_history(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        bridge.round_robin_manager = Mock()
        bridge.round_robin_manager._sessions = {
            -3001: {"clusters": [{"stations": [5, 7]}]},
        }
        bridge.round_robin_manager.has_pending_agrica_fragment.return_value = False
        bridge.adjustment_phase = {-3001: "FREE_NETWORK"}
        bridge.adjustment_run_contexts = {-3001: {"project_id": 3}}
        bridge._touch_active_alert = AsyncMock()
        bridge._upsert_latest_sensor_cache = AsyncMock()
        bridge._is_processing_storage_enabled = Mock(return_value=True)
        bridge._buffer_lock = asyncio.Lock()
        bridge._sensor_buffer = []
        processor = Mock()
        processor.process_gngga.return_value = None
        processor._origin_relock_in_progress = False

        async def process(station_id):
            return await bridge._process_gnss_payload(
                info={"type": "gnss", "project_id": 3},
                raw_payload="$GNGGA,TEST", public_project_id=3,
                station_id=station_id, station_name="station", processor=processor,
                station_config={}, device_id=8, adjustment_only=False,
                current_timestamp=1_700_000_000,
            )

        with patch("app.mqtt.bridge.sensor_pipeline.gnss.manager.broadcast", new_callable=AsyncMock) as broadcast:
            for phase in ["STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"]:
                bridge.adjustment_phase[-3001] = phase
                asyncio.run(process(5))
                processor.process_gngga.assert_not_called()
            self.assertEqual(bridge._touch_active_alert.await_count, 4)
            self.assertEqual(broadcast.await_args.args[0]["data"]["status"], "ADJUSTMENT_IN_PROGRESS")
            self.assertFalse(bridge._sensor_buffer)
            asyncio.run(process(9))
            processor.process_gngga.assert_called_once_with("$GNGGA,TEST", {})
            bridge.adjustment_phase[-3001] = "COMPLETED"
            asyncio.run(process(5))
            self.assertEqual(processor.process_gngga.call_count, 2)

    def test_seed_handover_and_failed_restore_pause_only_affected_monitoring(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        bridge.round_robin_manager = Mock()
        bridge.round_robin_manager._sessions = {-3001: {
            "clusters": [{"stations": [5, 7]}], "monitoring_project_id": 3,
            "seed_topology_snapshots": {"base": {"service_config": {}}},
        }}
        bridge.adjustment_phase = {-3001: "ERROR"}
        bridge.adjustment_run_contexts = {}
        self.assertTrue(bridge._monitoring_paused_for_adjustment(3, 5))
        self.assertFalse(bridge._monitoring_paused_for_adjustment(4, 5))
        self.assertFalse(bridge._monitoring_paused_for_adjustment(3, 9))
        bridge.round_robin_manager._sessions[-3001]["seed_topology_snapshots"] = {}
        self.assertFalse(bridge._monitoring_paused_for_adjustment(3, 5))

    def test_cors_reference_event_reaches_only_affected_gnss_processors(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        affected, unrelated, other_project = Mock(), Mock(), Mock()
        bridge.topic_map = {
            "a": {"station_id": 7, "project_id": 1, "type": "gnss", "processor": affected},
            "duplicate": {"station_id": 7, "project_id": 1, "type": "gnss", "processor": affected},
            "b": {"station_id": 8, "project_id": 1, "type": "gnss", "processor": unrelated},
            "c": {"station_id": 9, "project_id": 2, "type": "gnss", "processor": other_project},
        }
        bridge._handle_gnss_reference_change(
            {"stations": ["7"], "project_id": 1}, 1_700_000_000.0, "cors_failover",
        )
        affected.mark_reference_changed.assert_called_once_with(
            timestamp=1_700_000_000.0, source="cors_failover",
        )
        unrelated.mark_reference_changed.assert_not_called()
        other_project.mark_reference_changed.assert_not_called()

    def test_cors_reference_event_accepts_persisted_station_codes(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        affected, unrelated = Mock(), Mock()
        bridge.topic_map = {
            "a": {"station_id": 7, "station_code": "Dap1_1", "project_id": 1,
                  "type": "gnss", "processor": affected},
            "b": {"station_id": 8, "station_code": "Dap1_2", "project_id": 1,
                  "type": "gnss", "processor": unrelated},
        }

        bridge._handle_gnss_reference_change(
            {"stations": ["Dap1_1"], "project_id": 1}, 1_700_000_000.0,
            "cors_failover",
        )

        affected.mark_reference_changed.assert_called_once_with(
            timestamp=1_700_000_000.0, source="cors_failover",
        )
        unrelated.mark_reference_changed.assert_not_called()

    def test_verified_reference_waits_for_delayed_fixed_and_stable_window(self):
        processor = self._processor_without_db()
        base_ts = 1_700_000_000.0
        processor.history = deque([{"ts": base_ts - 1, "pos_enu": np.zeros(3)}], maxlen=1200)
        processor.reacquire_candidates.clear()
        processor.mark_reference_changed(base_ts, "cors_failover")
        for index in range(6):
            result = processor._handle_reference_transition(
                base_ts + index, np.zeros(3), 4, {}, "$GNGGA,TEST",
            )
            self.assertEqual(result["status"], "REFERENCE_TRANSITION")
        # The receiver needs 90 seconds to regain FIXED, then reports a noisy
        # first window before settling at the 44 cm vertical shift from the log.
        positions = [np.array([0.12, 0.0, u]) for u in (0.3, 0.5, 0.3, 0.5, 0.3, 0.5)]
        positions += [np.array([0.12, 0.0, 0.44])] * 10
        results = []
        for index, position in enumerate(positions):
            result = processor._handle_reference_transition(
                base_ts + 90 + index, position, 4, {}, "$GNGGA,TEST",
            )
            results.append(result)
            if result and result["status"] == "TRACKING_REACQUIRED":
                break
        self.assertEqual(results[5]["status"], "REFERENCE_TRANSITION")
        self.assertEqual(results[-1]["status"], "TRACKING_REACQUIRED")
        np.testing.assert_allclose(processor.tracking_offset_enu, [0.12, 0.0, 0.44])
        np.testing.assert_allclose(processor.history[-1]["pos_enu"], np.zeros(3))
        self.assertEqual(processor._last_handled_reference_event_ts, base_ts)

    def test_runtime_reference_event_expires_without_accepting_a_late_shift(self):
        processor = self._processor_without_db()
        base_ts = 1_700_000_000.0
        processor.history = deque([{"ts": base_ts - 1, "pos_enu": np.zeros(3)}], maxlen=1200)
        processor.reacquire_candidates.clear()
        processor.mark_reference_changed(base_ts, "cors_failover")
        processor._handle_reference_transition(base_ts, np.zeros(3), 4, {}, "test")
        result = processor._handle_reference_transition(
            base_ts + 301, np.array([0.12, 0.0, 0.44]), 4, {}, "test",
        )
        self.assertEqual(result["status"], "UNVERIFIED_POSITION_SHIFT")
        self.assertIsNone(processor._reference_transition)
        self.assertEqual(processor._last_handled_reference_event_ts, base_ts)
        np.testing.assert_allclose(processor.tracking_offset_enu, np.zeros(3))

    def test_new_reference_event_cannot_erase_an_existing_quarantine(self):
        processor = self._processor_without_db()
        base_ts = 1_700_000_000.0
        processor.history = deque([{"ts": base_ts - 85000, "pos_enu": np.zeros(3)}], maxlen=1200)
        processor._shift_started_at = base_ts - 84999
        processor.reacquire_candidates = deque([
            {"ts": base_ts - 1, "pos_enu": np.array([0.12, 0.0, 0.44]), "fix_quality": 4},
        ], maxlen=10)
        processor.mark_reference_changed(base_ts, "cors_failover")
        result = processor._handle_reference_transition(
            base_ts, np.array([0.12, 0.0, 0.44]), 4, {}, "test",
        )
        self.assertIsNone(result)
        self.assertEqual(processor._last_handled_reference_event_ts, base_ts)
        np.testing.assert_allclose(processor.tracking_offset_enu, np.zeros(3))
        np.testing.assert_allclose(processor.history[-1]["pos_enu"], np.zeros(3))

    def test_reference_transition_does_not_count_replayed_epochs(self):
        processor = self._processor_without_db()
        base_ts = 1_700_000_000.0
        processor.history = deque([{"ts": base_ts - 1, "pos_enu": np.zeros(3)}], maxlen=1200)
        processor.reacquire_candidates.clear()
        config = {"cors_failover_timestamp": base_ts}
        results = [processor._handle_reference_transition(
            base_ts, np.array([0.12, 0.0, 0.44]), 4, config, "$GNGGA,TEST",
        ) for _ in range(10)]
        self.assertNotIn("TRACKING_REACQUIRED", {result.get("status") for result in results if result})
        np.testing.assert_allclose(processor.tracking_offset_enu, np.zeros(3))

    def test_processor_waits_for_persisted_state_before_consuming_gga(self):
        processor = GNSSVelocityProcessor.__new__(GNSSVelocityProcessor)
        processor._initialization_complete = False
        processor.state = "ORIGIN_LOCKED"

        result = processor.process_gngga("$GNGGA,ignored", {})

        self.assertEqual(result["type"], "gnss_status")
        self.assertEqual(result["status"], "INITIALIZING")

    def test_uncertain_gnss_processor_status_never_becomes_safe(self):
        analyzer = LandslideAnalyzer()
        for status in (
            "INITIALIZING",
            "VELOCITY_WARMUP",
            "UNVERIFIED_POSITION_SHIFT",
            "PERSISTENT_OFFSET_QUARANTINED",
            "REJECTED_MEASUREMENT",
            "UNSTABLE_FIX",
            "INVALID_DATA",
        ):
            result = analyzer.analyze_gnss_displacement(
                99,
                [{"timestamp": 1_700_000_000, "data": {"status": status, "speed_2d": 0.0}}],
                {"GnssAlerting": {"enabled": True}},
            )
            self.assertEqual(result["level"], "PENDING")
            self.assertEqual(result["signal_state"], "UNKNOWN")

    def _processor_without_db(self):
        processor = GNSSVelocityProcessor.__new__(GNSSVelocityProcessor)
        processor.device_id = 99
        processor.db_session_factory = None
        processor.context_label = "test"
        processor.state = "ORIGIN_LOCKED"
        processor.origin = {
            "lat": 21.0,
            "lon": 107.0,
            "h": 10.0,
            "R": np.eye(3),
            "ecef": np.zeros(3),
        }
        processor._origin_locked_at = 1_699_999_900
        processor._origin_record_id = 7
        processor.min_fix_quality = 4
        processor.stats = {
            "total_processed": 0,
            "low_quality_rejected": 0,
            "origin_resets": 0,
            "spike_rejected": 0,
        }
        processor.history = deque([{"sentinel": True}], maxlen=31)
        processor.velocity_history = deque(["sentinel"], maxlen=5)
        processor.reacquire_candidates = deque(["sentinel"], maxlen=10)
        processor.tracking_offset_enu = np.zeros(3, dtype=float)
        processor.disp_enu_state = np.zeros(3, dtype=float)
        processor.disp_state_ready = False
        processor.peak_displacement_mm = 0.0
        processor._reference_changed_at = None
        processor._reference_change_source = None
        processor._last_handled_reference_event_ts = None
        processor._last_reacquire_ts = 0.0
        processor._needs_boot_anchor = False
        processor._quarantine_checkpointed = False
        return processor

    def test_rtk_float_is_status_only_and_does_not_mutate_measurement_state(self):
        processor = self._processor_without_db()
        history_before = list(processor.history)
        velocity_before = list(processor.velocity_history)
        reacquire_before = list(processor.reacquire_candidates)

        result = processor._handle_processing(
            "$GNGGA,010203.00,2103.000000,N,10719.000000,E,5,20,0.8,10.0,M,0.0,M,1.0,0*00",
            5,
            {},
        )

        self.assertEqual(result["type"], "gnss_status")
        self.assertEqual(result["status"], "UNTRUSTED_FIX")
        self.assertEqual(list(processor.history), history_before)
        self.assertEqual(list(processor.velocity_history), velocity_before)
        self.assertEqual(list(processor.reacquire_candidates), reacquire_before)

    def test_locked_origin_cannot_be_reset(self):
        processor = self._processor_without_db()
        origin_before = processor.origin.copy()

        self.assertFalse(processor.reset_origin())
        self.assertEqual(processor.state, "ORIGIN_LOCKED")
        self.assertEqual(processor.origin["lat"], origin_before["lat"])
        self.assertEqual(processor.origin["lon"], origin_before["lon"])

    def test_robust_velocity_preserves_values_above_old_one_mm_s_clip(self):
        samples = []
        for second in range(10):
            noise = 0.0002 if second % 2 == 0 else -0.0002
            samples.append({
                "ts": 1_700_000_000.0 + second,
                "pos_enu": np.array([
                    0.002 * second + noise,
                    -0.003 * second - noise,
                    0.0005 * second,
                ]),
            })

        estimate = GNSSVelocityProcessor._robust_velocity_estimate(samples)

        self.assertAlmostEqual(estimate["velocity"][0] * 1000.0, 2.0, delta=0.15)
        self.assertAlmostEqual(estimate["velocity"][1] * 1000.0, -3.0, delta=0.15)
        self.assertGreater(np.hypot(*estimate["velocity"][:2]) * 1000.0, 3.0)
        self.assertGreater(
            np.hypot(*estimate["velocity"][:2]) * 1000.0,
            estimate["confidence_95_mm_s"],
        )
        self.assertEqual(estimate["sample_count"], 10)
        self.assertEqual(estimate["duration_s"], 9.0)

    def test_stationary_noise_is_not_reported_as_significant_motion(self):
        samples = [
            {
                "ts": 1_700_000_000.0 + second,
                "pos_enu": np.array([
                    0.005 if second % 2 == 0 else -0.005,
                    -0.004 if second % 3 == 0 else 0.004,
                    0.0,
                ]),
            }
            for second in range(15)
        ]
        estimate = GNSSVelocityProcessor._robust_velocity_estimate(samples)
        speed_mm_s = np.hypot(*estimate["velocity"][:2]) * 1000.0

        self.assertLess(speed_mm_s, estimate["confidence_95_mm_s"])

    def test_velocity_spike_needs_persistent_same_direction_evidence(self):
        processor = self._processor_without_db()
        config = {
            "velocity_confirmation_samples": 3,
            "velocity_confirmation_duration_s": 20.0,
            "velocity_confirmation_direction_cosine": 0.70,
            "velocity_confirmation_min_gap_s": 10.0,
        }
        velocity = np.array([0.0006, 0.0002, 0.0])

        first = processor._update_velocity_confirmation(100.0, velocity, True, True, config)
        second = processor._update_velocity_confirmation(110.0, velocity, True, True, config)
        confirmed = processor._update_velocity_confirmation(120.0, velocity, True, True, config)

        self.assertFalse(first["confirmed"])
        self.assertFalse(second["confirmed"])
        self.assertTrue(confirmed["confirmed"])
        self.assertEqual(confirmed["sample_count"], 3)
        self.assertEqual(confirmed["duration_s"], 20.0)

        overlapping = processor._update_velocity_confirmation(
            125.0,
            velocity,
            True,
            True,
            config,
        )
        self.assertFalse(overlapping["accepted_sample"])
        self.assertEqual(overlapping["sample_count"], 3)

        # A later direction reversal breaks the evidence streak immediately;
        # the measured velocity itself is never changed by this gate.
        reversed_result = processor._update_velocity_confirmation(
            121.0,
            np.array([-0.0006, -0.0002, 0.0]),
            True,
            True,
            config,
        )
        self.assertFalse(reversed_result["confirmed"])
        self.assertEqual(reversed_result["sample_count"], 1)

    def test_analyzer_keeps_statistical_only_velocity_pending(self):
        analyzer = LandslideAnalyzer()
        result = analyzer.analyze_gnss_displacement(
            99,
            [{
                "timestamp": 1_700_000_000,
                "data": {
                    "status": "TRACKING_NORMAL",
                    "speed_2d": 0.0006719,
                    "velocity_reliable": True,
                    "velocity_significant": True,
                    "velocity_confirmed": False,
                },
            }],
            {"GnssAlerting": {"enabled": True}},
        )
        self.assertEqual(result["level"], "PENDING")
        self.assertEqual(result["category"], "gnss_velocity")

    def test_gga_time_resolves_across_utc_midnight(self):
        received = 1_704_153_601.0  # 2024-01-02 00:00:01 UTC
        resolved = GNSSVelocityProcessor._gga_epoch_seconds("235959.00", received)
        self.assertAlmostEqual(received - resolved, 2.0, places=3)

    def test_forward_payload_contract_is_unchanged(self):
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=31)
        processor.velocity_history = deque(maxlen=5)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = False
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_utc": f"01020{i}.00",
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + np.array([0.002 * i, 0.001 * i, 0.0])

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        result = None
        config = {
            "gnss_rtk_forwarding": {"enabled": True, "gnss_code": "gnss_processed"},
            "GnssAlerting": {
                "velocity_min_samples": 5,
                "velocity_min_duration_s": 4,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
            },
        }
        for _ in range(20):
            candidate = processor._handle_processing("$GNGGA,TEST", 4, config)
            if candidate and candidate.get("type") == "gnss_processed":
                result = candidate

        self.assertIsNotNone(result)
        forward_data = result["data"]["forwarding_data"]["data"]
        self.assertGreaterEqual(forward_data["total_displacement_mm"], 0.0)
        self.assertEqual(set(forward_data), {
            "lat", "lon", "h", "pos_e", "pos_n", "pos_u",
            "total_displacement_mm", "speed_2d_mm_s", "fix_quality", "fix_mode",
            "num_sats", "hdop", "origin_lat", "origin_lon", "origin_h",
            "adv_x", "adv_y", "adv_h", "adv_dx", "adv_dy", "adv_dh",
            "adv_vdx", "adv_vdy", "adv_vdh",
        })

    def test_stale_adjustment_reference_recovers_only_near_immutable_origin(self):
        for raw_position, should_recover in [(np.array([0.015, 0.005, 0.02]), True), (np.array([0.08, 0.0, 0.0]), False)]:
            with self.subTest(raw_position=raw_position):
                processor = self._processor_without_db()
                offset = np.array([0.005, 0.0, 0.01])
                processor.tracking_offset_enu = offset.copy()
                processor.history = deque([{'ts': 1_700_000_000.0, 'pos_enu': np.array([0.4, 0.0, 0.5])}], maxlen=1200)
                processor.reacquire_candidates = deque(maxlen=10)
                processor.max_step_distance_m, processor.max_step_vertical_m = 0.2, 0.15
                processor._gngga_to_ecef = lambda *_: raw_position.copy()
                tick = {'ts': 1_700_100_000.0}
                def parse(_):
                    tick['ts'] += 1
                    return {'wgs': {'lat': 21.0, 'lon': 107.0, 'h': 10.0},
                            'gga_timestamp': tick['ts'], 'num_sats': 20, 'hdop': 0.5}
                processor._parse_gngga = parse
                origin_before = dict(processor.origin)
                results = []
                for _ in range(66):
                    result = processor._handle_processing('$GNGGA,TEST', 4, {})
                    results.append(result['status'])
                self.assertNotIn('WARMING_UP', results[:65])
                if should_recover:
                    self.assertEqual(results[-1], 'WARMING_UP')
                    np.testing.assert_allclose(processor.history[-1]['pos_enu'], raw_position - offset)
                    self.assertFalse(processor.disp_state_ready)
                else:
                    self.assertEqual(results[-1], 'UNVERIFIED_POSITION_SHIFT')
                    self.assertEqual(processor.history[-1]['ts'], 1_700_000_000.0)
                np.testing.assert_array_equal(processor.tracking_offset_enu, offset)
                for key in ['lat', 'lon', 'h']:
                    self.assertEqual(processor.origin[key], origin_before[key])
                np.testing.assert_array_equal(processor.origin['ecef'], origin_before['ecef'])

    def test_repeated_rejects_are_summarized_without_accepting_shifted_samples(self):
        processor = self._processor_without_db()
        processor.history = deque([{"ts": 1_700_000_000.0, "pos_enu": np.zeros(3)}], maxlen=31)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor._gngga_to_ecef = lambda *_: np.array([1.0, 0.0, 0.0])
        tick = {"ts": 1_700_100_000.0}
        def parse(_):
            tick["ts"] += 1
            return {"wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                    "gga_timestamp": tick["ts"], "num_sats": 20, "hdop": 0.5}
        processor._parse_gngga = parse
        with patch('processors.gnss.processing.logger.warning') as warning, patch('processors.gnss.processing.time.monotonic', return_value=0.0) as clock:
            for _ in range(1000):
                result = processor._handle_processing('$GNGGA,TEST', 4, {})
            self.assertEqual(warning.call_count, 2)  # initial spike, then stable shifted cluster
            self.assertEqual(result['status'], 'UNVERIFIED_POSITION_SHIFT')
            clock.return_value = 299.0
            processor._handle_processing('$GNGGA,TEST', 4, {})
            self.assertEqual(warning.call_count, 2)
            clock.return_value = 300.0
            processor._handle_processing('$GNGGA,TEST', 4, {})
            self.assertEqual(warning.call_count, 3)
        self.assertEqual(processor.history[-1]['ts'], 1_700_000_000.0)
        np.testing.assert_array_equal(processor.history[-1]['pos_enu'], np.zeros(3))
        np.testing.assert_array_equal(processor.tracking_offset_enu, np.zeros(3))
        self.assertEqual(processor.stats['spike_rejected'], 1002)

    def test_persistent_shifted_cluster_is_quarantined_without_reacquire(self):
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = False
        processor.peak_displacement_mm = 0.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        positions = [np.array([0.001 * i, 0.0, 0.0]) for i in range(6)] + [
            np.array([1.0 + (0.001 if i % 2 else -0.001), 0.0, 0.0])
            for i in range(10)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_utc": f"0102{i:02d}.00",
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[i]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {
            "GnssAlerting": {
                "velocity_min_samples": 5,
                "velocity_min_duration_s": 4,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
            }
        }
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]

        shifted_results = [result for result in results[6:] if result]
        self.assertTrue(shifted_results)
        self.assertNotIn("TRACKING_REACQUIRED", {result.get("status") for result in shifted_results})
        quarantined = next(result for result in shifted_results if result.get("status") == "UNVERIFIED_POSITION_SHIFT")
        self.assertEqual(quarantined["data"]["possible_ground_movement"], True)
        self.assertIn("shift_e_m", quarantined["data"])
        self.assertLess(float(processor.history[-1]["pos_enu"][0]), 0.01)
        self.assertLess(float(processor.disp_enu_state[0]), 0.01)

    def test_unverified_shift_survives_processor_restart(self):
        base_ts = 1_700_000_000.0
        processor = self._processor_without_db()
        processor.history = deque([
            {"ts": base_ts, "pos_enu": np.zeros(3, dtype=float)}
        ], maxlen=1200)
        processor.reacquire_candidates = deque([
            {
                "ts": base_ts + 1.0 + index * 12.0,
                "pos_enu": np.array([0.04, 0.0, 0.40 + (0.001 if index % 2 else -0.001)]),
                "fix_quality": 4,
            }
            for index in range(6)
        ], maxlen=10)
        processor._shift_started_at = base_ts + 1.0
        processor.disp_enu_state = np.array([0.002, -0.001, 0.003])
        processor.disp_state_ready = True
        processor.peak_displacement_mm = 2.3
        checkpoint = processor._runtime_state_snapshot()

        restarted = self._processor_without_db()
        restarted.history = deque(maxlen=1200)
        restarted.reacquire_candidates = deque(maxlen=10)
        restarted.max_step_distance_m = 0.2
        restarted.max_step_vertical_m = 0.15
        restarted.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        restarted.origin["R"] = np.eye(3)

        self.assertTrue(restarted._restore_runtime_state(checkpoint))
        self.assertEqual(len(restarted.reacquire_candidates), 6)
        np.testing.assert_allclose(restarted.disp_enu_state, [0.002, -0.001, 0.003])

        restarted._parse_gngga = lambda _: {
            "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
            "gga_timestamp": base_ts + 62.0,
            "received_timestamp": base_ts + 62.1,
            "fix_quality": 4,
            "num_sats": 20,
            "hdop": 0.5,
        }
        restarted._gngga_to_ecef = lambda *_: (
            restarted.origin["ecef"] + np.array([0.04, 0.0, 0.40])
        )

        result = restarted._handle_processing("$GNGGA,TEST", 4, {})

        self.assertEqual(result["status"], "UNVERIFIED_POSITION_SHIFT")
        self.assertTrue(result["data"]["possible_ground_movement"])
        np.testing.assert_allclose(restarted.history[-1]["pos_enu"], np.zeros(3))

    def test_mismatched_restart_checkpoint_uses_safe_zero_enu_anchor(self):
        processor = self._processor_without_db()
        processor.history = deque([
            {"ts": 1_700_000_000.0, "pos_enu": np.zeros(3, dtype=float)}
        ], maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        checkpoint = processor._runtime_state_snapshot()

        restarted = self._processor_without_db()
        restarted._origin_record_id += 1
        restarted.history = deque(maxlen=1200)
        restarted.reacquire_candidates = deque(maxlen=10)
        restarted.max_step_distance_m = 0.2
        restarted.max_step_vertical_m = 0.15
        restarted.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        restarted.origin["R"] = np.eye(3)

        self.assertFalse(restarted._restore_runtime_state(checkpoint))
        restarted._parse_gngga = lambda _: {
            "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
            "gga_timestamp": 1_700_000_100.0,
            "received_timestamp": 1_700_000_100.1,
            "fix_quality": 4,
            "num_sats": 20,
            "hdop": 0.5,
        }
        restarted._gngga_to_ecef = lambda *_: (
            restarted.origin["ecef"] + np.array([0.0, 0.0, 0.40])
        )

        result = restarted._handle_processing("$GNGGA,TEST", 4, {})

        self.assertEqual(result["status"], "INVALID_DATA")
        np.testing.assert_allclose(restarted.history[-1]["pos_enu"], np.zeros(3))

    def test_stationary_noise_does_not_make_total_displacement_ramp(self):
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = False
        processor.peak_displacement_mm = 0.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_utc": f"0102{i:02d}.00",
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            jitter_e = 0.005 if i % 2 == 0 else -0.005
            jitter_n = -0.004 if i % 3 == 0 else 0.004
            return processor.origin["ecef"] + np.array([jitter_e, jitter_n, 0.0])

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {
            "GnssAlerting": {
                "velocity_min_samples": 5,
                "velocity_min_duration_s": 4,
                "displacement_window_seconds": 10,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
            }
        }
        totals = []
        for _ in range(40):
            result = processor._handle_processing("$GNGGA,TEST", 4, config)
            if result and result.get("type") == "gnss_processed":
                totals.append(result["data"]["total_displacement_mm"])

        self.assertGreater(len(totals), 20)
        self.assertLess(max(totals) - min(totals), 0.01)

    def test_low_speed_stationary_drift_does_not_ramp_displacement(self):
        processor = self._processor_without_db()
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = False
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 43,
                "hdop": 0.4,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + np.array([0.0002 * i, 0.0, 0.0])

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {
            "GnssAlerting": {
                "displacement_window_seconds": 15,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
            }
        }
        totals = []
        for _ in range(80):
            result = processor._handle_processing("$GNGGA,TEST", 4, config)
            if result and result.get("type") == "gnss_processed":
                totals.append(result["data"]["total_displacement_mm"])

        self.assertGreater(len(totals), 20)
        self.assertLess(max(totals) - min(totals), 0.01)

    def test_startup_offset_is_forwarded_without_stationary_ramp(self):
        processor = self._processor_without_db()
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 43,
                "hdop": 0.4,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            startup_offset = np.array([4.2, -2.3, 0.0])
            slow_drift = np.array([0.0002 * i, 0.0, 0.0])
            return processor.origin["ecef"] + startup_offset + slow_drift

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {
            "GnssAlerting": {
                "velocity_min_samples": 5,
                "velocity_min_duration_s": 4,
                "displacement_window_seconds": 15,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
                "displacement_stationary_speed_mm_s": 0.3,
            }
        }
        totals = []
        for _ in range(80):
            result = processor._handle_processing("$GNGGA,TEST", 4, config)
            if result and result.get("type") == "gnss_processed":
                totals.append(result["data"]["total_displacement_mm"])

        self.assertGreater(len(totals), 20)
        self.assertGreater(min(totals), 4700.0)
        self.assertLess(max(totals) - min(totals), 0.01)

    def test_gga_height_matches_persisted_ellipsoidal_origin(self):
        processor = self._processor_without_db()
        sentence = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,145.277,M,37.485,M,1.0,0"

        point = processor._parse_gngga(sentence)

        self.assertAlmostEqual(point["wgs"]["h"], 182.762)

    def test_unsafe_persisted_tracking_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            GNSSVelocityProcessor._validated_tracking_offset([-11.5059, -5.9191, 1259.4351])
        with self.assertRaises(ValueError):
            GNSSVelocityProcessor._validated_tracking_offset([2.01, 0.0, 0.0])
        with self.assertRaises(ValueError):
            GNSSVelocityProcessor._validated_tracking_offset([0.0, 0.0, 10.01])

        np.testing.assert_allclose(
            GNSSVelocityProcessor._validated_tracking_offset([0.01, -0.01, 3.5]),
            [0.01, -0.01, 3.5],
        )

    def test_manual_offset_calibration_preserves_origin_and_persists(self):
        processor = self._processor_without_db()
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor._reference_transition = None
        processor._consecutive_rejects = 0
        center = np.array([0.012, -0.007, 3.5], dtype=float)
        for second in range(60):
            processor.history.append({
                "ts": 1_700_000_000.0 + second,
                "pos_enu": np.array([9.0, 9.0, 9.0]),
            })

        saved = []

        async def save_offset(offset=None):
            saved.append(np.asarray(offset, dtype=float).copy())
            return True

        processor._async_save_tracking_offset = save_offset
        origin_before = processor.origin.copy()

        async def calibrate_with_fresh_samples():
            task = asyncio.create_task(processor.recalibrate_tracking_offset(
                minimum_samples=3,
                minimum_duration_s=2.0,
                timeout_s=1.0,
                poll_interval_s=0.001,
            ))
            await asyncio.sleep(0)
            for second in range(3):
                jitter = (second - 1) * 0.001
                processor.history.append({
                    "ts": 1_700_000_060.0 + second,
                    "pos_enu": center + np.array([jitter, -jitter, jitter]),
                })
            return await task

        result = asyncio.run(calibrate_with_fresh_samples())

        self.assertEqual(processor.origin["lat"], origin_before["lat"])
        self.assertEqual(processor.origin["lon"], origin_before["lon"])
        self.assertEqual(processor.origin["h"], origin_before["h"])
        self.assertTrue(result["origin_unchanged"])
        self.assertEqual(result["sample_count"], 3)
        np.testing.assert_allclose(processor.tracking_offset_enu, center, atol=1e-12)
        np.testing.assert_allclose(saved[0], center, atol=1e-12)
        np.testing.assert_allclose(
            processor.disp_enu_state,
            [0.001, -0.001, 0.001],
            atol=1e-12,
        )
        self.assertGreater(processor.peak_displacement_mm, 0.0)

    def test_manual_offset_calibration_captures_quarantined_fixed_samples(self):
        processor = self._processor_without_db()
        processor.history = deque([
            {"ts": 1_699_999_999.0, "pos_enu": np.zeros(3, dtype=float)},
        ], maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        center = np.array([0.04, 0.0, 0.40], dtype=float)
        sample_index = {"value": 0}

        def fake_parse(_):
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + sample_index["value"],
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            sample_index["value"] += 1
            return processor.origin["ecef"] + center

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef

        saved = []

        async def save_offset(offset=None):
            saved.append(np.asarray(offset, dtype=float).copy())
            return True

        processor._async_save_tracking_offset = save_offset

        async def calibrate_while_quarantined():
            task = asyncio.create_task(processor.recalibrate_tracking_offset(
                minimum_samples=3,
                minimum_duration_s=2.0,
                timeout_s=1.0,
                poll_interval_s=0.001,
            ))
            await asyncio.sleep(0)
            for _ in range(3):
                result = processor._handle_processing("$GNGGA,TEST", 4, {})
                self.assertIn(result["status"], {"INVALID_DATA", "UNVERIFIED_POSITION_SHIFT"})
                await asyncio.sleep(0)
            return await task

        result = asyncio.run(calibrate_while_quarantined())

        self.assertEqual(result["sample_count"], 3)
        np.testing.assert_allclose(processor.tracking_offset_enu, center, atol=1e-12)
        np.testing.assert_allclose(saved[0], center, atol=1e-12)
        self.assertFalse(processor.reacquire_candidates)
        np.testing.assert_allclose(processor.history[-1]["pos_enu"], np.zeros(3), atol=1e-12)
        post_calibration = processor._handle_processing("$GNGGA,TEST", 4, {})
        self.assertNotIn(
            post_calibration.get("status"),
            {"INVALID_DATA", "UNVERIFIED_POSITION_SHIFT"},
        )

    def test_horizontal_stale_cluster_reacquires_tracking(self):
        """Verify trạm lệch ngang (offset2D > max_step) sau khi mất fix lâu (dt > 60s) vẫn reacquire thành công."""
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.array([0.005, 0.0, 0.0])
        processor.disp_state_ready = True
        processor.peak_displacement_mm = 5.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        timestamps = list(range(6)) + list(range(120, 127))
        # Cụm điểm mới sau 120s lệch 24cm ngang (E) và 6cm đứng (U) giống trạm Sin Quyền trong log thực tế
        positions = [np.array([0.001 * i, 0.0, 0.0]) for i in range(6)] + [
            np.array([0.24 + (0.001 if i % 2 else -0.001), 0.0, 0.06])
            for i in range(7)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + timestamps[i],
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[i]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        # Verified reference change event with valid timestamp allows reacquisition
        config = {"cors_failover_timestamp": 1_700_000_000.0 + 120}
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]

        self.assertIn("TRACKING_REACQUIRED", {result.get("status") for result in results if result})
        self.assertAlmostEqual(float(processor.tracking_offset_enu[0]), 0.24, places=2)
        self.assertLess(abs(float(processor.history[-1]["pos_enu"][0])), 0.01)
        np.testing.assert_allclose(processor.disp_enu_state, [0.005, 0.0, 0.0])

        # Verify subsequent samples at the new position continue smoothly WITHOUT rejecting or looping
        subsequent_results = []
        for extra in range(5):
            pos_extra = np.array([0.24 + 0.001 * extra, 0.0, 0.06])
            timestamps.append(127 + extra)
            positions.append(pos_extra)
            res = processor._handle_processing("$GNGGA,TEST", 4, config)
            if res:
                subsequent_results.append(res)

        # Ensure NO subsequent bad fix or reacquire rejects occurred
        statuses = [r.get("status") for r in subsequent_results if r]
        self.assertNotIn("INVALID_DATA", statuses)
        self.assertNotIn("UNSTABLE_FIX", statuses)
        self.assertNotIn("PERSISTENT_OFFSET_QUARANTINED", statuses)

    def test_landslide_without_reference_change_is_not_absorbed_into_offset(self):
        """Verify real ground displacement (e.g. 30cm) is NOT absorbed into tracking offset when CORS has not changed."""
        processor = self._processor_without_db()
        processor.allow_auto_reacquire = False
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = True
        processor.peak_displacement_mm = 0.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)

        timestamps = list(range(6)) + list(range(120, 127))
        # 30cm ground displacement
        positions = [np.array([0.001 * i, 0.0, 0.0]) for i in range(6)] + [
            np.array([0.30 + (0.001 if i % 2 else -0.001), 0.0, 0.0])
            for i in range(7)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + timestamps[i],
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[i]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        # No CORS change config
        results = [processor._handle_processing("$GNGGA,TEST", 4, {}) for _ in positions]

        # Reacquire MUST NOT occur; tracking_offset must stay 0 so landslide is not zeroed out!
        self.assertNotIn("TRACKING_REACQUIRED", {r.get("status") for r in results if r})
        self.assertEqual(float(processor.tracking_offset_enu[0]), 0.0)

    def test_slow_creep_displacement_updates_without_velocity_significant(self):
        """Verify slow creep displacement (> noise floor) updates even when instantaneous velocity < 0.15 mm/s."""
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = False
        processor.peak_displacement_mm = 0.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)

        # Baseline: 20 samples at origin (0, 0, 0) with 0.5mm noise
        positions = [np.array([0.0005 if i % 2 else -0.0005, 0.0, 0.0]) for i in range(20)]
        # Then slow creep to 30mm (0.030m) over 60 seconds.  The detector
        # requires independent windows, so the fixture must span more than
        # one confirmation interval.
        positions += [
            np.array([0.0005 * i + (0.0005 if i % 2 else -0.0005), 0.0, 0.0])
            for i in range(60)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + i,
                "received_timestamp": 1_700_000_100.0 + i,
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[i]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {
            "GnssAlerting": {
                "displacement_window_seconds": 15,
                "displacement_min_samples": 5,
                "displacement_min_duration_s": 4,
                "displacement_noise_floor_min_mm": 2.0,
                "displacement_stationary_speed_mm_s": 0.0,
            }
        }
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]
        last_processed = [r for r in results if r and r.get("type") == "gnss_processed"][-1]

        # The slow 10mm creep must be detected and reflected in total_displacement_mm!
        self.assertGreater(last_processed["data"]["total_displacement_mm"], 5.0)
        self.assertIn("horizontal_displacement_mm", last_processed["data"])
        self.assertIn("vertical_displacement_mm", last_processed["data"])
        self.assertIn("displacement_3d_mm", last_processed["data"])

    def test_nmea_checksum_validation(self):
        """Verify NMEA checksum calculation and rejection of corrupted sentences."""
        # Valid checksum: $GNGGA...*47
        valid_sentence = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,10.0,M,0.0,M,1.0,0*47"
        # Calculate actual checksum for valid_sentence body
        body = "GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,10.0,M,0.0,M,1.0,0"
        chk = 0
        for c in body:
            chk ^= ord(c)
        correct_sentence = f"${body}*{chk:02X}"

        self.assertTrue(GNSSVelocityProcessor._verify_nmea_checksum(correct_sentence))
        self.assertFalse(GNSSVelocityProcessor._verify_nmea_checksum(f"${body}*FF"))
        self.assertFalse(GNSSVelocityProcessor._verify_nmea_checksum(f"${body}*ZZ"))
        # No checksum field returns True
        self.assertTrue(GNSSVelocityProcessor._verify_nmea_checksum(f"${body}"))

    def test_malformed_checksum_rejected_in_process_gngga(self):
        """Verify process_gngga rejects malformed checksum like *ZZ without stripping it."""
        processor = self._processor_without_db()
        bad_payload = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,10.0,M,0.0,M,1.0,0*ZZ"
        res = processor.process_gngga(bad_payload, {})
        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "CHECKSUM_FAILED")

    def test_missing_geoid_field_rejected(self):
        """Verify GGA sentence with missing geoid separation is rejected to prevent 30m+ false jump."""
        processor = self._processor_without_db()
        # Incomplete sentence missing field 11 (geoid separation)
        sentence_no_geoid = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,0.8,10.0,M,,M,1.0,0"
        point = processor._parse_gngga(sentence_no_geoid)
        self.assertIsNone(point)

    def test_invalid_minutes_rejected_in_parse_gngga(self):
        """Verify NMEA minutes >= 60 are rejected."""
        processor = self._processor_without_db()
        # 65.0000 minutes is invalid NMEA
        sentence_bad_minutes = "$GNGGA,010203.00,2165.000000,N,10719.000000,E,4,20,0.8,10.0,M,0.0,M,1.0,0"
        point = processor._parse_gngga(sentence_bad_minutes)
        self.assertIsNone(point)

    def test_origin_candidate_hdop_and_sats_gate(self):
        """Verify points with high HDOP (>2.0) or low sats (<10) are rejected from origin candidates."""
        processor = self._processor_without_db()
        processor.state = "AWAITING_CANDIDATES"
        processor.origin_candidates = []
        processor.required_points = 60
        # Sentence with HDOP=3.5 (too high for origin)
        res_bad_hdop = processor.process_gngga("$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,20,3.5,10.0,M,0.0,M,1.0,0", {})
        self.assertEqual(res_bad_hdop.get("status"), "AWAITING_ORIGIN")
        self.assertEqual(res_bad_hdop.get("type"), "origin_status")
        self.assertEqual(len(processor.origin_candidates), 0)

        # Sentence with Sats=6 (too few for origin)
        res_few_sats = processor.process_gngga("$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,6,0.8,10.0,M,0.0,M,1.0,0", {})
        self.assertEqual(res_few_sats.get("status"), "AWAITING_ORIGIN")
        self.assertEqual(len(processor.origin_candidates), 0)

        # Sentence with good HDOP and Sats
        res_good = processor.process_gngga("$GNGGA,010203.00,2103.000000,N,10719.000000,E,4,18,0.8,10.0,M,0.0,M,1.0,0", {})
        self.assertEqual(res_good.get("type"), "origin_collecting")
        self.assertEqual(len(processor.origin_candidates), 1)

    def test_reference_shift_below_spike_gate_is_compensated_before_history_commit(self):
        processor = self._processor_without_db()
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.tracking_offset_enu = np.zeros(3)
        processor._last_reacquire_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        positions = [np.array([0.001 * index, 0.0, 0.0]) for index in range(6)] + [
            np.array([0.101 + (0.001 if index % 2 else -0.001), 0.0, 0.08])
            for index in range(6)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            index = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + index,
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            index = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[index]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {"reference_change_timestamp": 1_700_000_006_000}
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]

        self.assertIn("REFERENCE_TRANSITION", {result.get("status") for result in results if result})
        reacquired = next(result for result in results if result and result.get("status") == "TRACKING_REACQUIRED")
        self.assertGreater(reacquired["data"]["shift_2d_m"], 0.09)
        self.assertAlmostEqual(float(processor.tracking_offset_enu[0]), 0.096, delta=0.01)
        self.assertLess(float(processor.history[-1]["pos_enu"][0]), 0.01)

    def test_reference_event_must_precede_shift_onset(self):
        processor = self._processor_without_db()
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.tracking_offset_enu = np.zeros(3)
        processor._last_reacquire_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        timestamps = list(range(6)) + list(range(120, 190))
        positions = [np.array([0.001 * index, 0.0, 0.0]) for index in range(6)] + [
            np.array([0.35, 0.0, 0.0]) for _ in range(70)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            index = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + timestamps[index],
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            index = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[index]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {"reference_change_timestamp": 1_700_000_000.0}
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]

        late_results = [result for result in results[6:] if result]
        self.assertNotIn("TRACKING_REACQUIRED", {result.get("status") for result in late_results})
        self.assertIn("UNVERIFIED_POSITION_SHIFT", {result.get("status") for result in late_results})

    def test_origin_candidates_reset_after_acquisition_gap(self):
        processor = self._processor_without_db()
        processor.state = "AWAITING_CANDIDATES"
        processor.origin = None
        processor.origin_candidates = []
        processor.required_points = 60
        processor.min_fix_quality = 4
        samples = iter((100.0, 101.0, 105.0))

        def fake_parse(_):
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": next(samples),
                "received_timestamp": 0.0,
                "hdop": 0.5,
                "num_sats": 20,
            }

        processor._parse_gngga = fake_parse
        for _ in range(3):
            processor._handle_origin_collection("$GNGGA,TEST", 4)

        self.assertEqual(len(processor.origin_candidates), 1)

    def test_tracking_offset_cap_considers_proposed_offset(self):
        """Verify proposed tracking offset (e.g. 1.9m + 0.4m = 2.3m) is rejected when exceeding 2.0m cap."""
        processor = self._processor_without_db()
        processor.filter_window_size = 30
        processor.history = deque(maxlen=1200)
        processor.reacquire_candidates = deque(maxlen=10)
        processor.max_step_distance_m = 0.2
        processor.max_step_vertical_m = 0.15
        processor.v_enu_state = np.zeros(3)
        processor.v_state_ready = False
        processor.disp_enu_state = np.zeros(3)
        processor.disp_state_ready = True
        processor.peak_displacement_mm = 0.0
        processor.last_significant_motion_ts = 0.0
        processor.origin["ecef"] = np.array([1000.0, 2000.0, 3000.0])
        processor.origin["R"] = np.eye(3)
        # Existing tracking offset = 1.9m
        processor.tracking_offset_enu = np.array([1.9, 0.0, 0.0])

        timestamps = list(range(6)) + list(range(120, 127))
        # New cluster attempts a +0.4m shift (total proposed = 1.9 + 0.4 = 2.3m > 2.0m cap)
        positions = [np.array([0.001 * i, 0.0, 0.0]) for i in range(6)] + [
            np.array([0.40 + (0.001 if i % 2 else -0.001), 0.0, 0.0])
            for i in range(7)
        ]
        sample_index = {"value": 0}

        def fake_parse(_):
            i = sample_index["value"]
            return {
                "wgs": {"lat": 21.0, "lon": 107.0, "h": 10.0},
                "gga_timestamp": 1_700_000_000.0 + timestamps[i],
                "fix_quality": 4,
                "num_sats": 20,
                "hdop": 0.5,
            }

        def fake_ecef(*_):
            i = sample_index["value"]
            sample_index["value"] += 1
            return processor.origin["ecef"] + positions[i]

        processor._parse_gngga = fake_parse
        processor._gngga_to_ecef = fake_ecef
        config = {"cors_failover_timestamp": 1_700_000_000.0 + 120}
        results = [processor._handle_processing("$GNGGA,TEST", 4, config) for _ in positions]

        # Reacquire MUST NOT occur because proposed 2.3m exceeds 2.0m cap
        self.assertNotIn("TRACKING_REACQUIRED", {r.get("status") for r in results if r})
        # Offset must stay at 1.9m, NOT 2.3m
        self.assertEqual(float(processor.tracking_offset_enu[0]), 1.9)


class GnssAuditTests(unittest.IsolatedAsyncioTestCase):
    def _bridge_without_clients(self):
        bridge = MQTTBridge.__new__(MQTTBridge)
        bridge._buffer_lock = asyncio.Lock()
        bridge._sensor_buffer = []
        bridge._gnss_audit_state = {}
        bridge._gnss_forward_error_state = {}
        bridge._station_update_buffer = {}
        bridge._active_gnss_anomalies = set()
        bridge._device_update_buffer = {}
        return bridge

    def test_runtime_defaults_include_gnss_integrity(self):
        bridge = self._bridge_without_clients()
        bridge.runtime_confirmation = {"gnss": 3, "rain": 2, "water": 2, "imu": 2}

        config = bridge._apply_runtime_defaults_to_station_config({})

        self.assertEqual(config["GnssIntegrity"]["process_max_hdop"], 2.0)
        self.assertEqual(config["GnssIntegrity"]["process_min_sats"], 10)
        self.assertEqual(config["GnssIntegrity"]["reference_transition_samples"], 6)
        self.assertTrue(bridge._is_processing_storage_enabled(config))

    async def test_processing_log_storage_can_be_disabled_per_station(self):
        bridge = self._bridge_without_clients()
        disabled_config = {"data_logging": {"enabled": False}}

        self.assertFalse(bridge._is_processing_storage_enabled(disabled_config))
        self.assertFalse(await bridge._buffer_gnss_audit(
            9, 8, 123456, "$GNGGA,TEST*00", {"status": "UNSTABLE_FIX"}, disabled_config,
        ))
        self.assertFalse(await bridge._buffer_gnss_forward_audit(
            9, 8, 123456, {}, disabled_config,
            "test/gnss", "local", "{}", "publish_failed", 7,
        ))
        self.assertEqual(bridge._sensor_buffer, [])

    async def test_rejected_raw_is_saved_even_when_only_gngga_field_is_selected(self):
        bridge = self._bridge_without_clients()
        config = {
            "data_logging": {
                "gnss": {
                    "enabled_fields": ["raw_gngga"],
                    "save_rejected_raw": False,
                }
            },
            "gnss_rtk_forwarding": {"enabled": True, "rtk_topic": "test/gnss"},
            "gnss_origin": {"lat": 21.0, "lon": 107.0, "h": 10.0},
        }
        raw = "$GNGGA,010203.00,2103.000000,N,10719.000000,E,5,20,0.8,10.0,M,0.0,M,1.0,0*00"

        await bridge._buffer_gnss_audit(
            9, 8, 123456, raw,
            {
                "status": "UNSTABLE_FIX",
                "fix_quality": 4,
                "fix_mode": "RTK_FIXED",
                "message": "Suspicious position jump",
            },
            config,
        )

        self.assertEqual(len(bridge._sensor_buffer), 1)
        data = bridge._sensor_buffer[0]["data"]
        self.assertEqual(data["raw_gngga"], raw)
        self.assertEqual(data["forward_action"], "blocked_invalid_measurement")
        self.assertIsNone(data["forward_payload"])

    async def test_forward_failure_audit_keeps_exact_json(self):
        bridge = self._bridge_without_clients()
        exact_payload = '{"type":"gnss_processed","data":{"total_displacement_mm":12.5}}'

        await bridge._buffer_gnss_forward_audit(
            9, 8, 123456,
            {
                "raw_gngga": "$GNGGA,FIXED*00",
                "fix_quality": 4,
                "fix_mode": "RTK_FIXED",
                "total_displacement_mm": 12.5,
                "speed_2d_mm_s": 0.1,
            },
            {
                "data_logging": {
                    "gnss": {
                        "enabled_fields": ["raw_gngga"],
                        "save_forward_payload": False,
                    }
                }
            },
            "test/gnss", "broker:1883", exact_payload, "publish_failed", 7,
        )

        data = bridge._sensor_buffer[0]["data"]
        self.assertEqual(bridge._sensor_buffer[0]["sensor_type"], "gnss_audit")
        self.assertEqual(data["forward_payload"], exact_payload)
        self.assertEqual(data["forward_topic"], "test/gnss")
        self.assertEqual(data["forward_rc"], 7)

    async def test_successful_forward_is_not_saved_as_abnormal(self):
        bridge = self._bridge_without_clients()
        saved = await bridge._buffer_gnss_forward_audit(
            9, 8, 123456, {}, {}, "test/gnss", "local", "{}", "published", 0,
        )
        self.assertFalse(saved)
        self.assertEqual(bridge._sensor_buffer, [])

    async def test_only_suspicious_status_is_saved_once_per_episode(self):
        bridge = self._bridge_without_clients()
        self.assertFalse(await bridge._should_record_gnss_anomaly(
            8, {"status": "UNTRUSTED_FIX", "fix_quality": 5}
        ))
        suspicious = {"status": "UNSTABLE_FIX", "fix_quality": 4}
        self.assertTrue(await bridge._should_record_gnss_anomaly(8, suspicious))
        self.assertFalse(await bridge._should_record_gnss_anomaly(8, suspicious))
        await bridge._clear_gnss_anomaly(8)
        self.assertTrue(await bridge._should_record_gnss_anomaly(8, suspicious))


if __name__ == "__main__":
    unittest.main()
