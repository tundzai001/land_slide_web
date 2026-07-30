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
    def __init__(self):
        self.send_calls = 0

    async def send_json(self, _message):
        self.send_calls += 1
        await asyncio.Event().wait()


class _BrokenSocket:
    async def send_json(self, _message):
        raise ConnectionError("browser closed")


class _OverlapDetectingSocket:
    def __init__(self):
        self.messages = []
        self.sending = False

    async def send_json(self, message):
        if self.sending:
            raise RuntimeError("overlapping websocket send")
        self.sending = True
        try:
            await asyncio.sleep(0.002)
            self.messages.append(message)
        finally:
            self.sending = False


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

    async def test_concurrent_broadcasts_are_serialized_per_client(self):
        manager = ConnectionManager()
        socket = _OverlapDetectingSocket()
        manager.active_connections = [socket]
        messages = [
            {"type": "gnss_adjustment_progress", "sequence": sequence}
            for sequence in range(20)
        ]

        await asyncio.gather(*(manager.broadcast(item) for item in messages))

        self.assertEqual(len(socket.messages), len(messages))
        self.assertEqual(manager.active_connections, [socket])

    async def test_concurrent_timeouts_remove_and_attempt_dead_client_once(self):
        manager = ConnectionManager()
        manager.SEND_TIMEOUT_SECONDS = 0.02
        hanging = _HangingSocket()
        manager.active_connections = [hanging]

        await asyncio.gather(*(
            manager.broadcast({"type": "gnss_adjustment_progress", "n": n})
            for n in range(25)
        ))

        self.assertEqual(hanging.send_calls, 1)
        self.assertEqual(manager.active_connections, [])

    async def test_protocol_v2_scopes_sensor_stream_to_selected_station(self):
        manager = ConnectionManager()
        socket = _RecordingSocket()
        manager.active_connections = [socket]

        handled = await manager.handle_client_message(
            socket,
            '{"type":"subscribe","station_ids":[101],"channels":["sensor","alerts"]}',
        )
        self.assertTrue(handled)
        self.assertEqual(socket.messages[-1]["type"], "subscription_ack")
        socket.messages.clear()

        await manager.broadcast(
            {"type": "sensor_data", "station_id": 101, "sensor_type": "gnss"}
        )
        await manager.broadcast(
            {"type": "sensor_data", "station_id": 102, "sensor_type": "gnss"}
        )

        self.assertEqual(len(socket.messages), 1)
        self.assertEqual(socket.messages[0]["station_id"], 101)

    async def test_legacy_connection_keeps_broadcast_contract(self):
        manager = ConnectionManager()
        socket = _RecordingSocket()
        manager.active_connections = [socket]

        await manager.broadcast(
            {"type": "sensor_data", "station_id": 101, "sensor_type": "gnss"}
        )

        self.assertEqual(len(socket.messages), 1)

    async def test_protocol_v2_without_station_suppresses_sensor_stream(self):
        manager = ConnectionManager()
        socket = _RecordingSocket()
        manager.active_connections = [socket]

        await manager.handle_client_message(
            socket,
            '{"type":"subscribe","station_ids":[],"channels":["sensor","status"]}',
        )
        socket.messages.clear()
        await manager.broadcast(
            {"type": "sensor_data", "station_id": 101, "sensor_type": "gnss"}
        )

        self.assertEqual(socket.messages, [])


if __name__ == "__main__":
    unittest.main()
