import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import paho.mqtt.client as mqtt

from backend.app.mqtt.transport import MQTTTransportMixin


class _Client:
    def __init__(self):
        self.stopped = False
        self.disconnected = False

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True


class _Bridge(MQTTTransportMixin):
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.client = _Client()
        self._stopping = False
        self._background_tasks = set()
        self._threadsafe_futures = set()


class MQTTTransportLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_robin_source_failure_does_not_switch_caster(self):
        bridge = _Bridge()
        bridge.topic_map = {}
        bridge.round_robin_manager = SimpleNamespace(
            caster_hosts=["backup.example", "selected.example"]
        )
        for error in (
            "Caster rejected SOURCE: ERROR - Mountpoint already in using",
            "Connection refused",
        ):
            with self.subTest(error=error), patch("app.mqtt.ntrip_pusher.ntrip_manager") as pushers:
                # The other caster accepts SOURCE, but has no rover clients.
                pushers.start_pusher = AsyncMock(side_effect=[RuntimeError(error), True])
                pushers.stop_pusher = AsyncMock()
                pushers.get_diagnostics.return_value = {}
                with self.assertRaisesRegex(RuntimeError, error):
                    await bridge._start_round_robin_ntrip_route(
                        "CP08", "selected.example", 2101, "QN.CP", "secret"
                    )
                pushers.start_pusher.assert_awaited_once_with(
                    "CP08", "selected.example", 2101, "QN.CP", "secret"
                )
                pushers.stop_pusher.assert_awaited_once_with("CP08")

    async def test_round_robin_source_opens_selected_caster_and_all_mountpoints(self):
        bridge = _Bridge()
        bridge.topic_map = {}
        bridge.round_robin_manager = SimpleNamespace(caster_hosts=["backup.example"])
        with patch("app.mqtt.ntrip_pusher.ntrip_manager") as pushers:
            pushers.start_pusher = AsyncMock()
            self.assertTrue(await bridge._start_round_robin_ntrip_route(
                "CP08", "selected.example", 2101, "QN.CP,OTHER", "secret"
            ))
            pushers.start_pusher.assert_awaited_once_with(
                "CP08", "selected.example", 2101, "QN.CP,OTHER", "secret"
            )

    async def test_invalid_default_broker_does_not_block_device_workers(self):
        bridge = _Bridge()
        bridge.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        bridge.runtime_mqtt = {"broker": "", "port": 1883}
        bridge.reload_topics_from_db = AsyncMock()
        bridge._flush_loop = AsyncMock()
        bridge._drain_ingest_spool_loop = AsyncMock()

        bridge.start()
        await asyncio.sleep(0)

        bridge.reload_topics_from_db.assert_awaited_once()
        bridge._flush_loop.assert_awaited_once()
        bridge._drain_ingest_spool_loop.assert_awaited_once()
        await asyncio.gather(*bridge._background_tasks)

    async def test_refused_default_connection_retries_while_workers_run(self):
        bridge = _Bridge()
        bridge.runtime_mqtt = {"broker": "offline.example", "port": 1883}
        bridge.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        bridge.client.reconnect_delay_set(0.01, 0.01)
        bridge.client.reconnect = Mock(side_effect=ConnectionRefusedError(10061, "refused"))
        bridge.client.on_connect_fail = bridge.on_connect_fail
        bridge.reload_topics_from_db = AsyncMock()
        bridge._flush_loop = AsyncMock()
        bridge._drain_ingest_spool_loop = AsyncMock()

        try:
            bridge.start()
            async with asyncio.timeout(2):
                while bridge.client.reconnect.call_count < 2:
                    await asyncio.sleep(0.01)
            bridge.reload_topics_from_db.assert_awaited_once()
            bridge._flush_loop.assert_awaited_once()
            bridge._drain_ingest_spool_loop.assert_awaited_once()
        finally:
            bridge.client.disconnect()
            bridge.client.loop_stop()
            await asyncio.gather(*bridge._background_tasks)

    async def test_disconnect_leaves_retry_to_network_loop(self):
        bridge = _Bridge()
        bridge.runtime_mqtt = {"broker": "offline.example", "port": 1883}
        client = Mock()
        bridge.on_disconnect(client, None, None, 1, None)
        bridge.on_disconnect(client, ("other.example", 1883, None, None, False), None, 1, None)
        client.reconnect.assert_not_called()

    async def test_stop_cancels_and_awaits_all_tracked_work(self):
        bridge = _Bridge()
        bridge._track_background_task(asyncio.sleep(60))
        bridge._submit_threadsafe(asyncio.sleep(60), "test-pipeline")
        await asyncio.sleep(0)

        await bridge.stop()

        self.assertTrue(bridge.client.stopped)
        self.assertTrue(bridge.client.disconnected)
        self.assertTrue(bridge._stopping)
        self.assertEqual(bridge._background_tasks, set())
        self.assertEqual(bridge._threadsafe_futures, set())


if __name__ == "__main__":
    unittest.main()
