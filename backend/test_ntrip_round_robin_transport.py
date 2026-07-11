import asyncio
import base64
import unittest
from unittest.mock import AsyncMock, patch

try:
    from backend.app.modules.ntrip_pusher import NtripPusher, Rtcm3FrameFilter, _crc24q
    from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
    ROUND_ROBIN_MODULE = "backend.processors.round_robin_manager"
except ModuleNotFoundError:
    from app.modules.ntrip_pusher import NtripPusher, Rtcm3FrameFilter, _crc24q
    from processors.round_robin_manager import RoundRobinAdjustmentManager
    ROUND_ROBIN_MODULE = "processors.round_robin_manager"


class _FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def _rtcm_frame(payload: bytes) -> bytes:
    header = bytes((0xD3, (len(payload) >> 8) & 0x03, len(payload) & 0xFF))
    body = header + payload
    return body + _crc24q(body).to_bytes(3, "big")


class RtcmFilterTests(unittest.TestCase):
    def test_mixed_text_and_fragmented_rtcm_yields_only_valid_frames(self):
        frame_a = _rtcm_frame(b"\x3e\xd0\x01\x02")
        frame_b = _rtcm_frame(b"\x43\x20\x03")
        invalid = frame_a[:-1] + bytes((frame_a[-1] ^ 0xFF,))
        stream_filter = Rtcm3FrameFilter()

        self.assertEqual(stream_filter.feed(b"$GNGGA,text\r\n" + frame_a[:4]), b"")
        self.assertEqual(
            stream_filter.feed(frame_a[4:] + b"#AGRICA,text" + invalid + frame_b),
            frame_a + frame_b,
        )


class NtripHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_waits_for_caster_acceptance(self):
        request_received = asyncio.Event()
        rtcm_received = asyncio.Event()
        received_data = bytearray()

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            request_received.set()
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            received_data.extend(await reader.read(10))
            rtcm_received.set()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        pusher = NtripPusher("S1", "127.0.0.1", port, "S1_BASE", "secret")
        try:
            await pusher.start(timeout=1.0)
            self.assertTrue(request_received.is_set())
            self.assertTrue(pusher.is_running)
            frame = _rtcm_frame(b"\x3e\xd0\x01\x02")
            pusher.queue.put_nowait(frame)
            await pusher.wait_for_rtcm(timeout=1.0)
            await asyncio.wait_for(rtcm_received.wait(), timeout=1.0)
            self.assertEqual(bytes(received_data), frame)
        finally:
            await pusher.stop()
            server.close()
            await server.wait_closed()

    async def test_start_surfaces_caster_rejection(self):
        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ERROR - Bad password\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        pusher = NtripPusher("S1", "127.0.0.1", port, "S1_BASE", "wrong")
        try:
            with self.assertRaisesRegex(ConnectionError, "Bad password"):
                await pusher.start(timeout=1.0)
            self.assertFalse(pusher.is_running)
        finally:
            await pusher.stop()
            server.close()
            await server.wait_closed()


class RoundRobinCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_rejection_preserves_caster_response_detail(self):
        received_request = bytearray()

        async def handle(reader, writer):
            received_request.extend(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.0 401 Unauthorized\r\n\r\nBad SET credentials")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            accepted = await manager._send_set_command(
                "CORS_A", "Dap1_2", "receiver-2", [b"mode rover survey\r\n"]
            )
        finally:
            server.close()
            await server.wait_closed()

        self.assertFalse(accepted)
        expected_auth = base64.b64encode(b"Dap1_2:12345")
        self.assertIn(b"SET /CORS_A HTTP/1.1\r\n", received_request)
        self.assertIn(b"Authorization: Basic " + expected_auth, received_request)
        self.assertIn(b"User-Agent: NTRIP Client/1.0/receiver-2", received_request)
        self.assertIn(b"Host: 127.0.0.1:", received_request)
        self.assertIn("401 Unauthorized", manager._last_set_error)
        self.assertIn("mountpoint=CORS_A", manager._last_set_error)

    def test_client_table_prefers_exact_station_over_prefix_collision(self):
        client_table = (
            "STR;Dap1_10;110;Dap1_10;0;\r\n"
            "STR;Dap1_1;101;Dap1_1;0;\r\n"
        )
        selected = RoundRobinAdjustmentManager._select_client_info(client_table, "Dap1_1")

        self.assertEqual(selected["receiverID"], "101")
        self.assertEqual(selected["Mountpoint"], "Dap1_1")

    def test_client_table_can_match_station_by_receiver_id(self):
        client_table = "STR;generic-user;Dap1_2;CORS_A;0;\r\n"
        selected = RoundRobinAdjustmentManager._select_client_info(client_table, "Dap1_2")

        self.assertEqual(selected["Username"], "generic-user")
        self.assertEqual(selected["receiverID"], "Dap1_2")

    async def test_client_lookup_searches_all_configured_aicasters(self):
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            caster_host="aitogy.com.vn",
            caster_hosts=["aitogy.com.vn", "aitogy.click"],
        )

        async def query(host):
            if host == "aitogy.com.vn":
                return "STR;other;other;CORS_A;0;\r\n"
            return "STR;generic;Dap1_2;CORS_B;0;\r\n"

        manager._query_client_table = query
        selected = await manager._find_client_info("Dap1_2")

        self.assertEqual(selected["CasterHost"], "aitogy.click")
        self.assertEqual(selected["Mountpoint"], "CORS_B")

    def test_temporary_base_commands_do_not_reset_or_persist_base_mode(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands = manager._build_geotek_lte_unicore_config(
            "FIXED", lat=21.0, lon=105.0, alt=10.0
        )
        command_text = b"".join(commands).lower()

        self.assertNotIn(b"freset", command_text)
        self.assertNotIn(b"saveconfig", command_text)
        self.assertIn(b"mode base 21.0 105.0 10.0", command_text)
        self.assertIn(b"rtcm1074 com2 1", command_text)

        rover_text = b"".join(manager._build_geotek_lte_unicore_rover_config()).lower()
        self.assertIn(b"mode rover survey", rover_text)
        self.assertIn(b"agrica com2 1", rover_text)

    async def test_collection_starts_only_after_route_handshake_and_restores_rover(self):
        events = []

        async def route_start(station_code, host, port, mountpoint, password):
            events.append(("route_started", station_code, host, port, mountpoint, password))
            return True

        async def route_stop(station_code):
            events.append(("route_stopped", station_code))

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            source_host="caster.example",
            source_port=2101,
            source_password="source-secret",
            route_start_callback=route_start,
            route_stop_callback=route_stop,
        )
        manager.rover_llh_cache["S1"] = {"lat": 21.0, "lon": 105.0, "alt": 10.0}
        manager._find_client_info = AsyncMock(return_value={
            "Username": "S1",
            "receiverID": "101",
            "Mountpoint": "CORS_A",
        })

        async def send_set(
            _mountpoint, _username, _receiver_id, commands, password="123", **_kwargs
        ):
            mode = "rover" if any(b"mode rover" in command.lower() for command in commands) else "base"
            events.append((f"set_{mode}", password))
            return True

        manager._send_set_command = send_set

        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._set_rover_as_temporary_base(
                "S1",
                route_host="aitogy.click",
                route_port=2101,
                route_mountpoint="QN.CP",
                route_password="12345",
                on_collection_started=lambda: events.append(("collection_started",)),
                on_collection_stopped=lambda: events.append(("collection_stopped",)),
            )

        event_names = [event[0] for event in events]
        self.assertEqual(
            event_names,
            [
                "set_base",
                "route_started",
                "collection_started",
                "collection_stopped",
                "route_stopped",
                "set_rover",
            ],
        )
        self.assertEqual(
            events[1],
            ("route_started", "S1", "aitogy.click", 2101, "QN.CP", "12345"),
        )

    async def test_route_rejection_still_restores_rover_without_collecting(self):
        events = []

        async def route_start(*_args):
            events.append("route_rejected")
            raise ConnectionError("caster rejected route")

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
        )
        manager.rover_llh_cache["S1"] = {"lat": 21.0, "lon": 105.0, "alt": 10.0}
        manager._find_client_info = AsyncMock(return_value={
            "Username": "S1",
            "receiverID": "101",
            "Mountpoint": "CORS_A",
        })

        async def send_set(
            _mountpoint, _username, _receiver_id, commands, password="123", **_kwargs
        ):
            events.append("set_rover" if any(b"mode rover" in c.lower() for c in commands) else "set_base")
            return True

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(ConnectionError, "caster rejected route"):
                await manager._set_rover_as_temporary_base(
                    "S1",
                    on_collection_started=lambda: events.append("collection_started"),
                )

        self.assertEqual(events, ["set_base", "route_rejected", "set_rover"])


if __name__ == "__main__":
    unittest.main()
