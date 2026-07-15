import asyncio
import unittest

try:
    from backend.app.websocket import ConnectionManager
except ModuleNotFoundError:
    from app.websocket import ConnectionManager


class _RecordingSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class _HangingSocket:
    async def send_json(self, _message):
        await asyncio.Event().wait()


class _BrokenSocket:
    async def send_json(self, _message):
        raise ConnectionError("browser closed")


class WebSocketIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_or_hanging_browser_does_not_block_other_clients(self):
        manager = ConnectionManager()
        manager.SEND_TIMEOUT_SECONDS = 0.02
        healthy = _RecordingSocket()
        hanging = _HangingSocket()
        broken = _BrokenSocket()
        manager.active_connections = [hanging, healthy, broken]
        message = {"type": "gnss_adjustment_progress", "phase": "FREE_NETWORK"}

        await asyncio.wait_for(manager.broadcast(message), timeout=0.2)

        self.assertEqual(healthy.messages, [message])
        self.assertEqual(manager.active_connections, [healthy])

    async def test_broadcast_without_web_clients_is_a_noop(self):
        manager = ConnectionManager()

        await asyncio.wait_for(
            manager.broadcast({"type": "gnss_adjustment_progress"}),
            timeout=0.1,
        )

        self.assertEqual(manager.active_connections, [])


if __name__ == "__main__":
    unittest.main()
