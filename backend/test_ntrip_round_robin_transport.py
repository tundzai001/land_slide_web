import asyncio
import base64
import json
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
        diagnostics = stream_filter.diagnostics()
        self.assertEqual(diagnostics["valid_frames"], 2)
        self.assertGreaterEqual(diagnostics["crc_failures"], 1)

    def test_text_only_payload_has_actionable_diagnostics(self):
        pusher = NtripPusher("S1", "caster", 2101, "S1_BASE", "secret")
        pusher._last_chunk_at = 1.0
        pusher._first_chunk_hex = b"#AGRICA".hex()
        pusher._last_chunk_hex = b"#AGRICA".hex()
        pusher._rtcm_filter.feed(b"#AGRICA,text-only")

        diagnostics = pusher.diagnostics()

        self.assertEqual(diagnostics["mqtt_chunks"], 1)
        self.assertEqual(diagnostics["d3_preambles"], 0)
        self.assertIn("no RTCM3 0xD3", diagnostics["likely_cause"])

    def test_no_fix_gga_diagnostics_identify_station_health(self):
        pusher = NtripPusher("Dap1_4", "caster", 2101, "SinQuyen1", "secret")
        payload = b"$GNGGA,091637.00,,,,,0,1,99.99,,,,,,*00\r\n"
        pusher.observe_gnss_chunk(payload)
        pusher._rtcm_filter.feed(payload)

        diagnostics = pusher.diagnostics()

        self.assertEqual(diagnostics["last_gga_fix_quality"], 0)
        self.assertEqual(diagnostics["last_gga_satellites"], 1)
        self.assertIn("no GNSS fix", diagnostics["likely_cause"])
        self.assertIn("COM2-to-MQTT", diagnostics["likely_cause"])


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
    async def test_fixed_base_configures_host_selected_server_not_always_s1(self):
        class FakeResponse:
            status = 200

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body.encode()

        original_config = {
            "stream_on_demand": False,
            "stream_active": True,
            "server1_enabled": True,
            "serverhost1": "caster-one.example",
            "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False,
            "server1_stream_active": True,
            "server2_enabled": True,
            "serverhost2": "caster-two.example",
            "mountpoint2": "SinQuyen1",
            "server2_stream_on_demand": False,
            "server2_stream_active": True,
        }
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            web_cors_api_token="cors-admin-token",
        )
        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            if request.full_url.endswith("/api/public/map-stations"):
                return FakeResponse(json.dumps([{
                    "serial": "S1-SERIAL",
                    "name": "SinQuyen1",
                    "service_config": original_config,
                }]))
            return FakeResponse(json.dumps({
                "status": "service_config_sent_and_saved",
                "channel": "mqtt",
            }))

        with patch("urllib.request.urlopen", side_effect=urlopen):
            await manager._toggle_cors_fixed_base(
                "SinQuyen1",
                sleep=True,
                selected_host="https://caster-two.example:2101",
            )
            await manager._toggle_cors_fixed_base(
                "SinQuyen1",
                sleep=False,
                selected_host="caster-two.example",
            )

        self.assertTrue(requests[0][0].full_url.endswith("/api/public/map-stations"))
        self.assertTrue(
            requests[1][0].full_url.endswith(
                "/api/devices/S1-SERIAL/configure-service"
            )
        )
        self.assertEqual(requests[1][0].headers["Authorization"], "Bearer cors-admin-token")
        sleep_payload = json.loads(requests[1][0].data.decode())
        self.assertFalse(sleep_payload["server1_stream_on_demand"])
        self.assertTrue(sleep_payload["server1_stream_active"])
        self.assertTrue(sleep_payload["server2_stream_on_demand"])
        self.assertFalse(sleep_payload["server2_stream_active"])
        self.assertTrue(sleep_payload["stream_on_demand"])
        self.assertTrue(sleep_payload["stream_active"])
        restored_payload = json.loads(requests[2][0].data.decode())
        self.assertEqual(restored_payload, original_config)

    async def test_fixed_base_requires_configure_service_confirmation(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"status": "command_sent_only"}).encode()

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            web_cors_api_token="cors-admin-token",
        )
        map_response = type("MapResponse", (), {
            "status": 200,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
            "read": lambda self: json.dumps([{
                "serial": "S1-SERIAL",
                "service_config": {
                    "server1_enabled": True,
                    "serverhost1": "caster-one.example",
                    "mountpoint1": "SinQuyen1",
                    "server1_stream_on_demand": False,
                    "server1_stream_active": True,
                },
            }]).encode(),
        })()
        with patch(
            "urllib.request.urlopen",
            side_effect=[map_response, FakeResponse()],
        ):
            with self.assertRaisesRegex(RuntimeError, "did not confirm device"):
                await manager._toggle_cors_fixed_base(
                    "SinQuyen1",
                    sleep=True,
                    selected_host="caster-one.example",
                )

    async def test_mqtt_ack_requires_exact_echo_then_response_on_same_topic(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        waiter = manager._register_command_ack_waiter(
            "Dap1_2",
            "mode base 22.6 103.8 174.2",
        )
        info = {"station_code": "Dap1_2"}

        self.assertFalse(manager.add_receiver_command_payload("OK", info, "gnss/dap1_2"))
        self.assertFalse(
            manager.add_receiver_command_payload(
                "mode base 22.6 103.8 174.2\r\nOK",
                {"station_code": "Dap1_4"},
                "gnss/dap1_2",
            )
        )
        self.assertFalse(
            manager.add_receiver_command_payload(
                "mode base 22.6 103.8 174.3\r\nOK",
                info,
                "gnss/dap1_2",
            )
        )
        self.assertTrue(
            manager.add_receiver_command_payload(
                "mode base 22.6 103.8 174.2",
                info,
                "gnss/dap1_2",
            )
        )
        self.assertFalse(
            manager.add_receiver_command_payload("OK", info, "gnss/other-topic")
        )
        self.assertTrue(manager.add_receiver_command_payload("OK", info, "gnss/dap1_2"))

        result = await asyncio.wait_for(waiter.future, timeout=0.5)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["topic"], "gnss/dap1_2")

    async def test_mqtt_command_frame_accepts_full_command_and_reports_no_function(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        info = {"station_code": "Dap1_1"}
        topic = "device/DEMO_DEVICE_1/upload"

        ok_waiter = manager._register_command_ack_waiter(
            "Dap1_1",
            "mode rover survey",
        )
        self.assertTrue(
            manager.add_receiver_command_payload(
                "$COMMAND,mode rover survey,Response:OK*00",
                info,
                topic,
            )
        )
        ok_result = await asyncio.wait_for(ok_waiter.future, timeout=0.5)
        self.assertTrue(ok_result["accepted"])
        self.assertEqual(ok_result["response"], "OK")
        self.assertEqual(
            ok_result["raw_response"],
            "$COMMAND,mode rover survey,Response:OK*00",
        )

        rejected_waiter = manager._register_command_ack_waiter(
            "Dap1_1",
            "rtcm1045 com2 1",
        )
        self.assertTrue(
            manager.add_receiver_command_payload(
                "$COMMAND,rtcm1045 com2 1,Response:NO FUNCTION*00",
                info,
                topic,
            )
        )
        rejected_result = await asyncio.wait_for(rejected_waiter.future, timeout=0.5)
        self.assertFalse(rejected_result["accepted"])
        self.assertEqual(rejected_result["response"], "NO FUNCTION")

    async def test_key_only_command_frame_requires_exact_echo_first(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        info = {"station_code": "Dap1_1"}
        topic = "device/DEMO_DEVICE_1/upload"
        waiter = manager._register_command_ack_waiter(
            "Dap1_1",
            "mode base 22.6 103.8 174.2",
        )

        self.assertFalse(
            manager.add_receiver_command_payload(
                "$COMMAND,MODE,Response:OK*00",
                info,
                topic,
            )
        )
        self.assertTrue(
            manager.add_receiver_command_payload(
                "MODE   BASE 22.6 103.8 174.2",
                info,
                topic,
            )
        )
        self.assertTrue(
            manager.add_receiver_command_payload(
                "$COMMAND,MODE,Response:OK*00",
                info,
                topic,
            )
        )
        result = await asyncio.wait_for(waiter.future, timeout=0.5)
        self.assertTrue(result["accepted"])

    async def test_rover_recovery_preflight_blocks_base_without_mqtt_ack(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.rover_llh_cache["Dap1_1"] = {
            "lat": 22.6267,
            "lon": 103.8094,
            "alt": 174.7,
        }
        manager._find_client_info = AsyncMock(return_value={
            "Username": "Dap1_1",
            "receiverID": "1.4.10",
            "Mountpoint": "SinQuyen1",
            "CasterHost": "aitogy.com.vn",
            "CasterPort": 2101,
        })
        sent_commands = []

        async def send_set(_mountpoint, _username, _receiver_id, commands, **_kwargs):
            sent_commands.extend(commands)
            manager._last_set_error = "no verified MQTT ACK"
            return False

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "Refusing to set Dap1_1 as BASE"):
                await manager._set_rover_as_temporary_base("Dap1_1")

        self.assertEqual(
            sent_commands,
            [b"mode rover survey\r\n", b"mode rover survey\r\n"],
        )

    def test_rover_recovery_sequence_restores_mode_outputs_and_saves_config(self):
        commands = RoundRobinAdjustmentManager._build_unicore_rover_config()
        self.assertEqual(commands, [
            b"mode rover survey\r\n",
            b"unlogall\r\n",
            b"gpgga com2 1\r\n",
            b"AGRICA COM2 1\r\n",
            b"saveconfig\r\n",
        ])
        self.assertEqual(commands[-1], b"saveconfig\r\n")

    async def test_set_uses_mqtt_ack_instead_of_socket_echo(self):
        command = b"mode base 22.6 103.8 174.2\r\n"
        command_received = asyncio.Event()

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
            await writer.drain()
            received = await reader.readline()
            self.assertEqual(received, command)
            writer.write(received)  # Socket echo is deliberately not an ACK.
            await writer.drain()
            command_received.set()
            await asyncio.sleep(0.2)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            send_task = asyncio.create_task(
                manager._send_set_command(
                    "CORS_A",
                    "Dap1_2",
                    "receiver-2",
                    [command],
                    ack_station_code="Dap1_2",
                    command_response_timeout=1.0,
                )
            )
            await asyncio.wait_for(command_received.wait(), timeout=2.0)
            await asyncio.sleep(0)
            self.assertFalse(send_task.done())
            manager.add_receiver_command_payload(
                command.decode().strip(),
                {"station_code": "Dap1_2"},
                "devices/dap1_2/gnss",
            )
            manager.add_receiver_command_payload(
                "OK",
                {"station_code": "Dap1_2"},
                "devices/dap1_2/gnss",
            )
            accepted = await asyncio.wait_for(send_task, timeout=2.0)
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertIn("MQTT topic=devices/dap1_2/gnss", manager._last_set_response)

    async def test_mode_command_uses_short_burst_until_mqtt_ack_arrives(self):
        command = b"mode rover survey\r\n"
        three_commands_received = asyncio.Event()
        received_commands = []

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            while len(received_commands) < 3:
                received_commands.append(await reader.readline())
            three_commands_received.set()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            send_task = asyncio.create_task(
                manager._send_set_command(
                    "CORS_A",
                    "Dap1_2",
                    "receiver-2",
                    [command],
                    ack_station_code="Dap1_2",
                    command_response_timeout=2.0,
                )
            )
            await asyncio.wait_for(three_commands_received.wait(), timeout=1.5)
            manager.add_receiver_command_payload(
                "$command,mode rover survey,response: OK*3F",
                {"station_code": "Dap1_2"},
                "devices/dap1_2/gnss",
            )
            accepted = await asyncio.wait_for(send_task, timeout=1.0)
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_commands, [command, command, command])

    async def test_agrica_command_uses_short_burst_until_mqtt_ack_arrives(self):
        command = b"AGRICA COM2 1\r\n"
        five_commands_received = asyncio.Event()
        received_commands = []

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            while len(received_commands) < 5:
                received_commands.append(await reader.readline())
            five_commands_received.set()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            send_task = asyncio.create_task(
                manager._send_set_command(
                    "CORS_A",
                    "Dap1_3",
                    "receiver-3",
                    [command],
                    ack_station_code="Dap1_3",
                    command_response_timeout=2.0,
                )
            )
            await asyncio.wait_for(five_commands_received.wait(), timeout=2.0)
            manager.add_receiver_command_payload(
                "$command,AGRICA COM2 1,response: OK*03",
                {"station_code": "Dap1_3"},
                "devices/dap1_3/gnss",
            )
            accepted = await asyncio.wait_for(send_task, timeout=1.0)
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_commands, [command] * 5)

    async def test_gpgga_command_uses_short_burst_until_mqtt_ack_arrives(self):
        command = b"gpgga com2 1\r\n"
        four_commands_received = asyncio.Event()
        received_commands = []

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            while len(received_commands) < 4:
                received_commands.append(await reader.readline())
            four_commands_received.set()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            send_task = asyncio.create_task(
                manager._send_set_command(
                    "CORS_A",
                    "Dap1_1",
                    "receiver-1",
                    [command],
                    ack_station_code="Dap1_1",
                    command_response_timeout=2.0,
                )
            )
            await asyncio.wait_for(four_commands_received.wait(), timeout=1.5)
            manager.add_receiver_command_payload(
                "$command,gpgga com2 1,response: OK*20",
                {"station_code": "Dap1_1"},
                "devices/dap1_1/gnss",
            )
            accepted = await asyncio.wait_for(send_task, timeout=1.0)
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_commands, [command] * 4)

    async def test_unlogall_uses_bounded_burst_until_mqtt_ack_arrives(self):
        command = b"unlogall\r\n"
        two_commands_received = asyncio.Event()
        received_commands = []

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            while len(received_commands) < 2:
                received_commands.append(await reader.readline())
            two_commands_received.set()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            send_task = asyncio.create_task(
                manager._send_set_command(
                    "CORS_A",
                    "Dap1_1",
                    "receiver-1",
                    [command],
                    ack_station_code="Dap1_1",
                    command_response_timeout=2.0,
                )
            )
            await asyncio.wait_for(two_commands_received.wait(), timeout=1.0)
            manager.add_receiver_command_payload(
                "$command,unlogall,response: OK*40",
                {"station_code": "Dap1_1"},
                "devices/dap1_1/gnss",
            )
            accepted = await asyncio.wait_for(send_task, timeout=1.0)
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_commands, [command] * 2)

    async def test_single_restore_command_waits_for_receiver_response(self):
        received_command = bytearray()

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
            await writer.drain()
            received_command.extend(await reader.readline())
            writer.write(b"OK\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        try:
            accepted = await manager._send_set_command(
                "CORS_A",
                "Dap1_2",
                "receiver-2",
                [b"unlogall\r\n"],
                wait_for_command_response=True,
            )
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_command, b"unlogall\r\n")
        self.assertEqual(manager._last_set_response, "OK")

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
                "CORS_A", "Dap1_2", "receiver-2", [b"unlogall\r\n"]
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

    def test_temporary_base_and_rover_recovery_both_end_with_saveconfig(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands = manager._build_unicore_base_config(
            "FIXED", lat=21.0, lon=105.0, alt=10.0
        )
        command_text = b"".join(commands).lower()

        self.assertEqual(commands, [
            b"unlogall\r\n",
            b"mode base 21.0 105.0 10.0\r\n",
            b"rtcm1006 com2 10\r\n",
            b"rtcm1033 com2 10\r\n",
            b"rtcm1074 com2 1\r\n",
            b"rtcm1124 com2 1\r\n",
            b"rtcm1084 com2 1\r\n",
            b"rtcm1094 com2 1\r\n",
            b"saveconfig\r\n",
        ])

        rover_text = b"".join(manager._build_unicore_rover_config()).lower()
        self.assertEqual(
            rover_text,
            b"mode rover survey\r\nunlogall\r\ngpgga com2 1\r\n"
            b"agrica com2 1\r\nsaveconfig\r\n",
        )

    def test_survey_base_profile_clears_logs_before_entering_base_mode(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())

        commands = manager._build_unicore_base_config("SURVEY_IN", duration=75)

        self.assertEqual(commands[:2], [
            b"unlogall\r\n",
            b"mode base time 75\r\n",
        ])
        self.assertEqual(commands[-1], b"saveconfig\r\n")

    async def test_optional_msm7_timeout_keeps_msm4_fallback_and_reaches_saveconfig(self):
        received_commands = []
        manager = None

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            while True:
                command = await reader.readline()
                if not command:
                    break
                received_commands.append(command)
                if command == b"saveconfig\r\n":
                    manager.add_receiver_command_payload(
                        "$command,saveconfig,response: OK*55",
                        {"station_code": "Dap1_3"},
                        "device/dap1_3/upload",
                    )
                    await asyncio.sleep(0.05)
                    break
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), caster_host="127.0.0.1", caster_port=port
        )
        manager.RTCM_COMMAND_BURST_COUNT = 1
        try:
            accepted = await manager._send_set_command(
                "SinQuyen1",
                "Dap1_3",
                "1.4.10",
                [b"rtcm1087 com2 1\r\n", b"saveconfig\r\n"],
                ack_station_code="Dap1_3",
                command_response_timeout=0.5,
                optional_unacknowledged_commands=["rtcm1087 com2 1"],
            )
        finally:
            server.close()
            await server.wait_closed()

        self.assertTrue(accepted)
        self.assertEqual(received_commands[-1], b"saveconfig\r\n")
        self.assertEqual(received_commands.count(b"rtcm1087 com2 1\r\n"), 3)
        self.assertIn("rtcm1087 com2 1", manager._last_set_warnings[0])

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
            command_text = commands[0].decode("ascii").strip().lower()
            command_name = command_text.split()[0]
            is_base_profile = any(
                command.decode("ascii").strip().lower().startswith("mode base")
                for command in commands
            )
            if is_base_profile:
                event_name = "set_base"
            elif command_text.startswith("mode rover"):
                event_name = "set_rover"
            else:
                event_name = f"restore_{command_name}"
            events.append((event_name, password))
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
                "set_rover",
                "set_base",
                "route_started",
                "collection_started",
                "collection_stopped",
                "route_stopped",
                "set_rover",
                "restore_unlogall",
                "restore_gpgga",
                "restore_agrica",
                "restore_saveconfig",
            ],
        )
        self.assertEqual(
            events[2],
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
            command_text = commands[0].decode("ascii").strip().lower()
            command_name = command_text.split()[0]
            is_base_profile = any(
                command.decode("ascii").strip().lower().startswith("mode base")
                for command in commands
            )
            if is_base_profile:
                event_name = "set_base"
            elif command_text.startswith("mode rover"):
                event_name = "set_rover"
            else:
                event_name = f"restore_{command_name}"
            events.append(event_name)
            return True

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "caster rejected route"):
                await manager._set_rover_as_temporary_base(
                    "S1",
                    on_collection_started=lambda: events.append("collection_started"),
                )

        self.assertEqual(events, [
            "set_rover",
            "set_base",
            "route_rejected",
            "set_rover",
            "restore_unlogall",
            "restore_gpgga",
            "restore_agrica",
            "restore_saveconfig",
        ])

    async def test_missing_rtcm_reapplies_clean_base_profile_and_retries_route(self):
        route_calls = 0
        route_stops = []
        command_groups = []
        collection_events = []

        async def route_start(*_args):
            nonlocal route_calls
            route_calls += 1
            if route_calls == 1:
                raise RuntimeError(
                    "No valid RTCM3 frame was forwarded within 25s; d3_preambles=0"
                )
            return True

        async def route_stop(station_code):
            route_stops.append(station_code)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_stop_callback=route_stop,
        )
        manager.rover_llh_cache["S1"] = {"lat": 21.0, "lon": 105.0, "alt": 10.0}
        manager._find_client_info = AsyncMock(return_value={
            "Username": "S1",
            "receiverID": "101",
            "Mountpoint": "CORS_A",
        })

        async def send_set(_mountpoint, _username, _receiver_id, commands, **_kwargs):
            command_groups.append(list(commands))
            return True

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._set_rover_as_temporary_base(
                "S1",
                on_collection_started=lambda: collection_events.append("started"),
                on_collection_stopped=lambda: collection_events.append("stopped"),
            )

        expected_base_profile = manager._build_unicore_base_config(
            "FIXED", lat=21.0, lon=105.0, alt=10.0
        )
        self.assertEqual(route_calls, 2)
        self.assertEqual(collection_events, ["started", "stopped"])
        self.assertEqual(command_groups[1], expected_base_profile)
        self.assertEqual(command_groups[2], expected_base_profile)
        # One stop cleans the failed attempt and one stops the successful route.
        self.assertEqual(route_stops, ["S1", "S1"])

    async def test_collection_waits_for_verified_cross_rovers_before_stable_window(self):
        status_calls = 0

        async def route_start(*_args):
            return True

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_stop_callback=AsyncMock(),
        )
        manager.rover_llh_cache["S1"] = {"lat": 21.0, "lon": 105.0, "alt": 10.0}
        manager._find_client_info = AsyncMock(return_value={
            "Username": "S1",
            "receiverID": "101",
            "Mountpoint": "CORS_A",
        })
        manager._send_set_command = AsyncMock(return_value=True)

        def collection_status():
            nonlocal status_calls
            status_calls += 1
            if status_calls < 3:
                return {"sample_count": 0, "rover_names": set()}
            if status_calls == 3:
                return {"sample_count": 1, "rover_names": {"S2"}}
            return {"sample_count": 2, "rover_names": {"S2", "S3"}}

        sleep_mock = AsyncMock()
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=sleep_mock):
            await manager._set_rover_as_temporary_base(
                "S1",
                collection_status_callback=collection_status,
                expected_cross_rovers={"S2", "S3"},
            )

        self.assertEqual(status_calls, 4)
        delays = [call.args[0] for call in sleep_mock.await_args_list]
        self.assertEqual(
            delays.count(manager.CROSS_BASE_STATUS_POLL_SECONDS),
            3,
        )
        self.assertIn(manager.CROSS_BASE_STABLE_COLLECTION_SECONDS, delays)

    async def test_rover_restore_retries_each_command_until_ack_before_advancing(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands_seen = []
        responses = iter([False, True, True, True, True, True])

        async def send_set(_mountpoint, _username, _receiver_id, commands, **kwargs):
            commands_seen.append((commands[0], kwargs.get("wait_for_command_response")))
            return next(responses)

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._restore_rover_output_sequence(
                rover_code="S1",
                mountpoint="CORS_A",
                client_info={"Username": "S1", "receiverID": "101"},
                commands=manager._build_unicore_rover_config(),
                project_id=17,
            )

        self.assertEqual(
            [command for command, _ in commands_seen],
            [
                b"mode rover survey\r\n",
                b"mode rover survey\r\n",
                b"unlogall\r\n",
                b"gpgga com2 1\r\n",
                b"AGRICA COM2 1\r\n",
                b"saveconfig\r\n",
            ],
        )
        self.assertTrue(all(wait_for_response for _, wait_for_response in commands_seen))

    async def test_rover_restore_does_not_fail_when_only_saveconfig_ack_is_missing(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands_seen = []
        responses = iter([True, True, True, True, False, False, False])

        async def send_set(_mountpoint, _username, _receiver_id, commands, **_kwargs):
            commands_seen.append(commands[0])
            manager._last_set_error = "no verified MQTT ACK"
            return next(responses)

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._restore_rover_output_sequence(
                rover_code="Dap1_2",
                mountpoint="SinQuyen1",
                client_info={"Username": "Dap1_2", "receiverID": "1.4.10"},
                commands=manager._build_unicore_rover_config(),
                project_id=3,
            )

        self.assertEqual(commands_seen[-3:], [b"saveconfig\r\n"] * 3)
        self.assertEqual(commands_seen.count(b"mode rover survey\r\n"), 1)


if __name__ == "__main__":
    unittest.main()
