"""Idle recovery never fights manual or scheduled adjustment ownership."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from app.mqtt.bridge import MQTTBridge
from app.mqtt.ntrip_pusher import _crc24q
from processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager


def rtcm_frame():
    body = b"\xd3\x00\x03\x43\x20\x03"
    return body + _crc24q(body).to_bytes(3, "big")


class IdleRoverGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = MQTTBridge.__new__(MQTTBridge)
        self.manager = RoundRobinAdjustmentManager(Mock())
        self.bridge.round_robin_manager = self.manager
        self.bridge._idle_rover_rtcm_seen = {}
        self.bridge._idle_rover_retry_at = {}
        self.bridge.adjustment_phase = {}
        self.bridge.adjustment_run_contexts = {}
        self.cluster = {"stations": [13, 10], "rovers": ["CP06", "CP03"]}
        self.info = {
            "type": "gnss", "station_id": 13, "station_code": "CP06",
            "project_id": 4, "project_gnss_clusters": [self.cluster],
        }
        self.bridge.topic_map = {"topic": self.info, "duplicate": self.info}
        self.manager._find_client_info = AsyncMock(return_value={"Mountpoint": "QN.CP"})
        self.manager.restore_rover_stream = AsyncMock()

    async def emit_and_check(self, payload=None):
        self.manager.observe_gnss_payload(self.info, payload if payload is not None else rtcm_frame())
        await self.bridge._check_idle_rover_streams()

    async def test_persistent_valid_rtcm_recovers_only_once_per_station(self):
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_not_awaited()
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_awaited_once_with(
            "CP06", client_info={"Mountpoint": "QN.CP"},
        )
        await self.emit_and_check()
        await self.emit_and_check()
        self.assertEqual(self.manager.restore_rover_stream.await_count, 1)

    async def test_noise_bad_crc_and_partial_frames_do_not_send_commands(self):
        frame = rtcm_frame()
        await self.emit_and_check(b"$GNGGA,text\r\n#AGRICA,text\r\n\xd3")
        await self.emit_and_check(frame[:-1] + bytes([frame[-1] ^ 1]))
        self.assertFalse(self.manager.get_gnss_stream_health("CP06")["valid_rtcm_recent"])
        await self.emit_and_check(frame[:4])
        self.manager.restore_rover_stream.assert_not_awaited()
        await self.emit_and_check(frame[4:])
        self.assertTrue(self.manager.get_gnss_stream_health("CP06")["valid_rtcm_recent"])
        self.manager.restore_rover_stream.assert_not_awaited()
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_awaited_once()

    async def test_old_single_rtcm_frame_does_not_trigger_recovery(self):
        await self.emit_and_check()
        await self.emit_and_check(b"$GNGGA,text\r\n#AGRICA,text\r\n")
        self.manager.restore_rover_stream.assert_not_awaited()

    async def test_manual_scheduled_starting_seed_running_and_paused_are_protected(self):
        for run_id, source in ((4, "manual"), (-4001, "scheduled")):
            for phase in (None, "STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"):
                with self.subTest(run_id=run_id, source=source, phase=phase):
                    self.manager.configure_project(run_id, [self.cluster])
                    self.bridge.adjustment_phase[run_id] = phase
                    self.bridge.adjustment_run_contexts[run_id] = {"source": source}
                    await self.emit_and_check()
                    await self.emit_and_check()
                    self.manager._find_client_info.assert_not_awaited()
                    self.manager.clear_project(run_id)

    async def test_cleanup_task_and_unrestored_topology_remain_protected(self):
        self.manager.configure_project(4, [self.cluster])
        self.bridge.adjustment_phase[4] = "ERROR"
        self.manager.running_tasks[4] = Mock(done=Mock(return_value=False))
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager.running_tasks.clear()
        self.manager._sessions[4]["seed_topology_snapshots"] = {"BASE": {}}
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_not_awaited()

    async def test_retry_startup_reservation_overrides_previous_error_phase(self):
        self.manager.configure_project(4, [self.cluster])
        self.bridge.adjustment_phase[4] = "ERROR"
        self.manager._sessions[4]["idle_recovery_reserved"] = True
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager._find_client_info.assert_not_awaited()

    async def test_completed_and_unrelated_sessions_do_not_block_idle_rover(self):
        self.manager.configure_project(4, [self.cluster])
        self.bridge.adjustment_phase[4] = "COMPLETED"
        self.manager.configure_project(5, [{"stations": [20, 21], "rovers": ["OTHER1", "OTHER2"]}])
        self.bridge.adjustment_phase[5] = "FREE_NETWORK"
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_awaited_once()

    async def test_non_rover_mqtt_source_is_never_changed(self):
        self.info["project_gnss_clusters"] = [{"stations": [10, 12], "rovers": ["CP03", "CP08"]}]
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager._find_client_info.assert_not_awaited()

    async def test_failure_is_logged_and_rate_limited_then_retried(self):
        self.manager.restore_rover_stream.side_effect = RuntimeError("receiver ACK missing")
        await self.emit_and_check()
        with self.assertLogs("app.mqtt.bridge.rover_guard", level="ERROR") as captured:
            await self.emit_and_check()
        self.assertIn("recovery not verified", captured.output[0])
        await self.emit_and_check()
        self.assertEqual(self.manager.restore_rover_stream.await_count, 1)
        self.bridge._idle_rover_retry_at["cp06"] = 0
        await self.emit_and_check()
        self.assertEqual(self.manager.restore_rover_stream.await_count, 2)

    async def test_no_control_session_sends_no_receiver_commands(self):
        self.manager._find_client_info.return_value = None
        await self.emit_and_check()
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager._find_client_info.assert_awaited_once()
        self.manager.restore_rover_stream.assert_not_awaited()

    async def test_startup_waits_for_idle_repair_and_then_reserves_station(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def restore(*_args, **_kwargs):
            entered.set()
            await release.wait()

        self.manager.restore_rover_stream.side_effect = restore
        await self.emit_and_check()
        repairing = asyncio.create_task(self.emit_and_check())
        await entered.wait()

        async def start_adjustment():
            async with self.manager._idle_rover_recovery_lock:
                self.manager.configure_project(4, [self.cluster])

        starting = asyncio.create_task(start_adjustment())
        await asyncio.sleep(0)
        self.assertFalse(starting.done())
        release.set()
        await asyncio.gather(repairing, starting)
        self.bridge._idle_rover_retry_at.clear()
        await self.emit_and_check()
        await self.emit_and_check()
        self.manager.restore_rover_stream.assert_awaited_once()

    async def test_restore_requires_live_output_after_receiver_ack(self):
        self.manager._restore_rover_output_sequence = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "did not prove fresh GGA"):
            await RoundRobinAdjustmentManager.restore_rover_stream(
                self.manager, "CP06", client_info={"Mountpoint": "QN.CP"}, verify_seconds=0,
            )
