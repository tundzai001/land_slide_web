import asyncio
import unittest

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
