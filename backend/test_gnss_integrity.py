import asyncio
import unittest
from collections import deque

import numpy as np

from processors.gnss_processor import GNSSVelocityProcessor
from mqtt_bridge import MQTTBridge


class GnssFixedOnlyTests(unittest.TestCase):
    def _processor_without_db(self):
        processor = GNSSVelocityProcessor.__new__(GNSSVelocityProcessor)
        processor.device_id = 99
        processor.context_label = "test"
        processor.state = "ORIGIN_LOCKED"
        processor.origin = {
            "lat": 21.0,
            "lon": 107.0,
            "h": 10.0,
            "R": np.eye(3),
            "ecef": np.zeros(3),
        }
        processor.stats = {
            "total_processed": 0,
            "low_quality_rejected": 0,
            "origin_resets": 0,
            "spike_rejected": 0,
        }
        processor.history = deque([{"sentinel": True}], maxlen=31)
        processor.velocity_history = deque(["sentinel"], maxlen=5)
        processor.reacquire_candidates = deque(["sentinel"], maxlen=10)
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
        for _ in range(6):
            candidate = processor._handle_processing("$GNGGA,TEST", 4, config)
            if candidate and candidate.get("type") == "gnss_processed":
                result = candidate

        self.assertIsNotNone(result)
        forward_data = result["data"]["forwarding_data"]["data"]
        self.assertGreater(forward_data["total_displacement_mm"], 1.0)
        self.assertEqual(set(forward_data), {
            "lat", "lon", "h", "pos_e", "pos_n", "pos_u",
            "total_displacement_mm", "speed_2d_mm_s", "fix_quality", "fix_mode",
            "num_sats", "hdop", "origin_lat", "origin_lon", "origin_h",
            "adv_x", "adv_y", "adv_h", "adv_dx", "adv_dy", "adv_dh",
            "adv_vdx", "adv_vdy", "adv_vdh",
        })

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
        self.assertIn("PERSISTENT_OFFSET_QUARANTINED", {result.get("status") for result in shifted_results})
        self.assertLess(float(processor.history[-1]["pos_enu"][0]), 0.01)
        self.assertLess(float(processor.disp_enu_state[0]), 0.01)

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
