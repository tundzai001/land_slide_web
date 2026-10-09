import asyncio
import base64
import copy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

try:
    from backend.app.mqtt.ntrip_pusher import (
        NtripPusher,
        NtripPusherManager,
        Rtcm3FrameFilter,
        _crc24q,
    )
    from backend.processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
    ROUND_ROBIN_MODULE = "backend.processors.gnss_adjustment.round_robin"
except ModuleNotFoundError:
    from app.mqtt.ntrip_pusher import NtripPusher, NtripPusherManager, Rtcm3FrameFilter, _crc24q
    from processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
    ROUND_ROBIN_MODULE = "processors.gnss_adjustment.round_robin"


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


class RoverStreamHealthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = RoundRobinAdjustmentManager(_FakeMqttClient())

    def test_observer_classifies_text_rover_and_binary_base_output(self):
        info = {"station_code": "Dap1_1", "station_id": 11}
        self.manager.observe_gnss_payload(
            info,
            b"$GNGGA,010203.00,2100.0,N,10500.0,E,4,20,0.5,10,M,0,M,,*00\r\n"
            b"#AGRICA,COM2,0,0,0*12345678\r\n",
        )
        health = self.manager.get_gnss_stream_health("Dap1_1")
        self.assertTrue(health["ready_as_rover"])
        self.assertFalse(health["rtcm_recent"])

        self.manager.observe_gnss_payload(info, _rtcm_frame(b"\x43\x20\x03"))
        health = self.manager.get_gnss_stream_health("Dap1_1")
        self.assertTrue(health["rtcm_recent"])
        self.assertFalse(health["ready_as_rover"])

    async def test_preflight_repairs_only_bad_stream_and_verifies_live_output(self):
        self.manager.configure_project(7, [{
            "stations": [11, 12],
            "rovers": ["Dap1_1", "Dap1_2"],
        }])
        healthy = b"$GNGGA,1,2,3*00\r\n#AGRICA,COM2,0*12345678\r\n"
        self.manager.observe_gnss_payload(
            {"station_code": "Dap1_1", "station_id": 11}, healthy
        )
        self.manager.observe_gnss_payload(
            {"station_code": "Dap1_2", "station_id": 12}, _rtcm_frame(b"\x43\x20\x03")
        )
        self.manager._find_client_info = AsyncMock(return_value={
            "Mountpoint": "SinQuyen1",
            "Username": "Dap1_2",
            "receiverID": "1.4.10",
            "CasterHost": "caster",
            "CasterPort": 2101,
        })
        self.manager._emit_progress = AsyncMock()

        async def restore(**_kwargs):
            self.manager.observe_gnss_payload(
                {"station_code": "Dap1_2", "station_id": 12}, healthy
            )

        self.manager._restore_rover_output_sequence = AsyncMock(side_effect=restore)
        outcomes = await self.manager.ensure_rover_streams_ready(
            7, discovery_seconds=0, verify_seconds=1
        )

        self.assertEqual([item["status"] for item in outcomes], ["ready", "recovered"])
        self.manager._restore_rover_output_sequence.assert_awaited_once()

    async def test_preflight_can_exclude_uncontrollable_station_without_failing_run(self):
        self.manager.configure_project(8, [{
            "stations": [11, 12],
            "rovers": ["Dap1_1", "Dap1_3"],
        }])
        healthy = b"$GNGGA,1,2,3*00\r\n#AGRICA,COM2,0*12345678\r\n"
        self.manager.observe_gnss_payload(
            {"station_code": "Dap1_1", "station_id": 11}, healthy
        )
        self.manager._find_client_info = AsyncMock(return_value=None)
        self.manager._emit_progress = AsyncMock()

        outcomes = await self.manager.ensure_rover_streams_ready(
            8, discovery_seconds=0, verify_seconds=1, allow_unavailable=True
        )

        self.assertEqual(outcomes[0]["status"], "ready")
        self.assertEqual(outcomes[1]["status"], "excluded_no_control_session")
        self.assertEqual(outcomes[1]["station_code"], "Dap1_3")

    async def test_pause_resume_keeps_session_and_observations(self):
        self.manager.configure_project(9, [{
            "stations": [11, 12],
            "rovers": ["Dap1_1", "Dap1_2"],
        }])
        session = self.manager._sessions[9]
        session["clusters"][0]["observations"].append("kept")

        self.assertTrue(self.manager.pause_project(9))
        self.assertEqual(session["control_state"], "PAUSED")
        self.assertTrue(self.manager.resume_project(9))
        self.assertEqual(session["control_state"], "RUNNING")
        self.assertEqual(session["clusters"][0]["observations"], ["kept"])


class NtripHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await NtripPusherManager.stop_pusher("FANOUT")

    async def test_manager_fans_same_rtcm_to_every_mountpoint(self):
        requests = []
        received = {}
        both_frames = asyncio.Event()

        async def handle(reader, writer):
            request = await reader.readuntil(b"\r\n\r\n")
            first_line = request.splitlines()[0].decode("ascii")
            mountpoint = first_line.rsplit("/", 1)[-1]
            requests.append(mountpoint)
            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()
            received[mountpoint] = await reader.read(1024)
            if len(received) == 2:
                both_frames.set()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        frame = _rtcm_frame(b"\x3e\xd0\x01\x02")
        try:
            await NtripPusherManager.start_pusher(
                "FANOUT", "127.0.0.1", port, "SinQuyen2,SinQuyen1", "secret"
            )
            NtripPusherManager.feed_data("FANOUT", frame)
            await NtripPusherManager.wait_for_rtcm("FANOUT", timeout=1.0)
            await asyncio.wait_for(both_frames.wait(), timeout=1.0)
        finally:
            await NtripPusherManager.stop_pusher("FANOUT")
            server.close()
            await server.wait_closed()

        self.assertCountEqual(requests, ["SinQuyen2", "SinQuyen1"])
        self.assertEqual(received["SinQuyen2"], frame)
        self.assertEqual(received["SinQuyen1"], frame)

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
    async def test_temporary_route_waits_for_fixed_mountpoint_release(self):
        route_attempts = 0
        events = []

        async def route_start(*_args):
            nonlocal route_attempts
            route_attempts += 1
            events.append(f"route-{route_attempts}")
            if route_attempts < 3:
                raise RuntimeError("Caster rejected SOURCE: ERROR - Mountpoint already in using")
            return True

        async def route_stop(_station_code):
            events.append("route-stop")

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_stop_callback=route_stop,
        )
        manager.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS = 3
        manager.rover_llh_cache["Dap1_1"] = {"lat": 21.0, "lon": 105.0, "alt": 10.0}
        manager._find_client_info = AsyncMock(return_value={
            "Username": "Dap1_1",
            "receiverID": "1.4.10",
            "Mountpoint": "SinQuyen1",
        })
        manager._send_set_command = AsyncMock(return_value=True)

        async def sleep_fixed():
            events.append("fixed-sleep")

        async def wake_fixed():
            events.append("fixed-wake")
            return {
                "Username": "Dap1_1",
                "receiverID": "1.4.10",
                "Mountpoint": "SinQuyen1",
            }

        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._set_rover_as_temporary_base(
                "Dap1_1",
                route_mountpoint="SinQuyen2,SinQuyen1",
                before_route_start=sleep_fixed,
                before_rover_restore=wake_fixed,
            )

        self.assertEqual(route_attempts, 3)
        self.assertEqual(events.count("fixed-sleep"), 1)
        self.assertEqual(events.count("fixed-wake"), 1)
        self.assertLess(events.index("fixed-sleep"), events.index("route-1"))

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
            web_cors_api_token="cors_testtoken",
            web_cors_api_base_url="https://cors.example",
        )
        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            if request.full_url.endswith("/api/integrations/stations"):
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
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=False,
                selected_host="https://caster-two.example:2101",
            )
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=True,
                selected_host="caster-two.example",
            )

        self.assertTrue(requests[0][0].full_url.endswith("/api/integrations/stations"))
        self.assertTrue(
            requests[1][0].full_url.endswith(
                "/api/integrations/stations/S1-SERIAL/configure-service"
            )
        )
        self.assertEqual(requests[1][0].headers["Authorization"], "Bearer cors_testtoken")
        sleep_payload = json.loads(requests[1][0].data.decode())
        self.assertTrue(sleep_payload["server1_enabled"])
        self.assertFalse(sleep_payload["server2_enabled"])
        self.assertFalse(sleep_payload["server2_stream_on_demand"])
        self.assertTrue(sleep_payload["server2_stream_active"])
        self.assertFalse(sleep_payload["stream_on_demand"])
        self.assertTrue(sleep_payload["stream_active"])
        restored_payload = json.loads(requests[2][0].data.decode())
        self.assertEqual(restored_payload, original_config)

    async def test_fixed_base_uses_exact_serial_when_backup_shares_host_and_mountpoint(self):
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

        primary_config = {
            "server1_enabled": True,
            "serverhost1": "caster.example",
            "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False,
            "server1_stream_active": True,
        }
        backup_config = {
            "server2_enabled": True,
            "serverhost2": "caster.example",
            "mountpoint2": "SinQuyen1",
            "server2_stream_on_demand": False,
            "server2_stream_active": True,
        }
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            web_cors_api_token="cors_testtoken",
            web_cors_api_base_url="https://cors.example",
        )
        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            if request.full_url.endswith("/api/integrations/stations"):
                return FakeResponse(json.dumps([
                    {
                        "serial": "SINQUYEN1-SERIAL",
                        "name": "SinQuyen1",
                        "service_config": primary_config,
                    },
                    {
                        "serial": "SINQUYEN2-SERIAL",
                        "name": "SinQuyen2",
                        "service_config": backup_config,
                    },
                ]))
            return FakeResponse(json.dumps({
                "status": "service_config_sent_and_saved",
                "channel": "mqtt",
            }))

        with patch("urllib.request.urlopen", side_effect=urlopen):
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=False,
                selected_host="caster.example",
                selected_serial="SINQUYEN2-SERIAL",
                selected_server_id=2,
            )
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=True,
                selected_host="caster.example",
                selected_serial="SINQUYEN2-SERIAL",
                selected_server_id=2,
            )

        self.assertTrue(
            requests[1][0].full_url.endswith(
                "/api/integrations/stations/SINQUYEN2-SERIAL/configure-service"
            )
        )
        sleep_payload = json.loads(requests[1][0].data.decode())
        self.assertFalse(sleep_payload["server2_enabled"])
        self.assertFalse(sleep_payload["server2_stream_on_demand"])
        self.assertTrue(sleep_payload["server2_stream_active"])
        restored_payload = json.loads(requests[2][0].data.decode())
        self.assertEqual(restored_payload, backup_config)

    async def test_backup_s2_route_disables_both_outputs_on_backup_receiver(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        primary_config = {
            "server1_enabled": True,
            "mountpoint1": "SinQuyen1",
        }
        backup_config = {
            "server1_enabled": True,
            "serverhost1": "caster.example",
            "mountpoint1": "SinQuyen2",
            "server2_enabled": True,
            "serverhost2": "caster.example",
            "mountpoint2": "SinQuyen1",
        }
        configured = []

        with patch.object(
            manager,
            "_cors_api_request_sync",
            return_value=[
                {
                    "serial": "SINQUYEN1-SERIAL",
                    "service_config": primary_config,
                },
                {
                    "serial": "SINQUYEN2-SERIAL",
                    "service_config": backup_config,
                },
            ],
        ), patch.object(
            manager,
            "_cors_configure_service_sync",
            side_effect=lambda serial, cfg: configured.append((serial, cfg)),
        ):
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=False,
                selected_host="caster.example",
                selected_serial="SINQUYEN2-SERIAL",
                selected_server_id=2,
                all_streams=True,
            )
            self.assertTrue(manager._cors_stream_is_managed_by_adjustment("SINQUYEN2-SERIAL", 1))
            self.assertTrue(manager._cors_stream_is_managed_by_adjustment("SINQUYEN2-SERIAL", 2))
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1",
                enabled=True,
                selected_host="caster.example",
                selected_serial="SINQUYEN2-SERIAL",
                selected_server_id=2,
            )

        self.assertEqual([serial for serial, _ in configured], [
            "SINQUYEN2-SERIAL",
            "SINQUYEN2-SERIAL",
        ])
        self.assertFalse(configured[0][1]["server1_enabled"])
        self.assertFalse(configured[0][1]["server2_enabled"])
        self.assertEqual(configured[1][1], backup_config)

    async def test_parallel_clusters_restore_only_their_own_stream_on_shared_base(self):
        for restore_order in ((1, 2), (2, 1)):
            with self.subTest(restore_order=restore_order):
                manager = RoundRobinAdjustmentManager(_FakeMqttClient())
                original = {
                    "server1_enabled": True, "mountpoint1": "SinQuyen2",
                    "server2_enabled": True, "mountpoint2": "SinQuyen1",
                }
                live_config = copy.deepcopy(original)

                def find(_mp, _host, _serial, server_id):
                    return "SHARED-BASE", server_id, copy.deepcopy(live_config)

                def configure(_serial, config):
                    live_config.clear()
                    live_config.update(copy.deepcopy(config))

                async def toggle(server_id, enabled):
                    await manager._set_cors_fixed_base_enabled(
                        original[f"mountpoint{server_id}"], enabled,
                        selected_serial="SHARED-BASE", selected_server_id=server_id,
                    )

                with patch.object(manager, "_find_cors_station_sync", side_effect=find), patch.object(
                    manager, "_cors_configure_service_sync", side_effect=configure,
                ):
                    await asyncio.gather(toggle(1, False), toggle(2, False))
                    self.assertFalse(live_config["server1_enabled"])
                    self.assertFalse(live_config["server2_enabled"])
                    await toggle(restore_order[0], True)
                    self.assertTrue(live_config[f"server{restore_order[0]}_enabled"])
                    self.assertFalse(live_config[f"server{restore_order[1]}_enabled"])
                    # configure-service replaces the full device config, so the
                    # daemon must not touch either stream until both jobs release it.
                    self.assertTrue(manager._cors_stream_is_managed_by_adjustment("SHARED-BASE", 1))
                    self.assertTrue(manager._cors_stream_is_managed_by_adjustment("SHARED-BASE", 2))
                    await toggle(restore_order[1], True)
                    self.assertEqual(live_config, original)
                    self.assertFalse(manager._cors_fixed_base_snapshots)

    async def test_conflict_base_is_hard_disabled_and_returns_exact_restore_snapshot(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        original = {
            "server1_enabled": True,
            "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False,
            "server1_stream_active": True,
            "server2_enabled": True,
            "mountpoint2": "SinQuyen2",
            "server2_stream_on_demand": True,
            "server2_stream_active": False,
        }
        configured = []
        with patch.object(
            manager,
            "_cors_api_request_sync",
            return_value=[{"serial": "SQ1", "service_config": original}],
        ), patch.object(
            manager,
            "_cors_configure_service_sync",
            side_effect=lambda serial, cfg: configured.append((serial, cfg)),
        ):
            snapshot = manager._disable_conflict_base_sync("SQ1")

        self.assertEqual(snapshot, original)
        self.assertEqual(configured[0][0], "SQ1")
        self.assertFalse(configured[0][1]["server1_enabled"])
        self.assertFalse(configured[0][1]["server2_enabled"])
        self.assertFalse(configured[0][1]["server1_stream_on_demand"])
        self.assertTrue(configured[0][1]["server2_stream_on_demand"])

    async def test_failed_fixed_base_disable_can_be_retried(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        original = {
            "server1_enabled": True, "server2_enabled": True,
            "serverhost1": "caster.example", "mountpoint1": "SinQuyen1",
        }
        with patch.object(
            manager, "_find_cors_station_sync", return_value=("SQ1", 1, original),
        ), patch.object(
            manager, "_cors_configure_service_sync",
            side_effect=[RuntimeError("CORS API unavailable"), {"status": "service_config_sent_and_saved"}],
        ) as configure:
            with self.assertRaisesRegex(RuntimeError, "CORS API unavailable"):
                await manager._set_cors_fixed_base_enabled(
                    "SinQuyen1", False, "caster.example", "SQ1", 1,
                )
            snapshot = next(iter(manager._cors_fixed_base_snapshots.values()))
            self.assertFalse(snapshot["confirmed_disabled"])
            self.assertEqual(snapshot["service_config"], original)

            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1", False, "caster.example", "SQ1", 1,
            )
            self.assertEqual(configure.call_count, 2)
            self.assertEqual(len(manager._cors_fixed_base_snapshots), 1)
            self.assertTrue(snapshot["confirmed_disabled"])

    async def test_failed_fixed_base_disable_still_has_restore_snapshot(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        original = {"server1_enabled": True, "server2_enabled": True}
        with patch.object(
            manager, "_find_cors_station_sync", return_value=("SQ1", 1, original),
        ), patch.object(
            manager, "_cors_configure_service_sync",
            side_effect=[RuntimeError("response lost"), {"status": "service_config_sent_and_saved"}],
        ) as configure:
            with self.assertRaisesRegex(RuntimeError, "response lost"):
                await manager._set_cors_fixed_base_enabled(
                    "SinQuyen1", False, "caster.example", "SQ1", 1,
                )
            await manager._set_cors_fixed_base_enabled(
                "SinQuyen1", True, "caster.example", "SQ1", 1,
            )

        self.assertEqual(configure.call_args.args, ("SQ1", original))
        self.assertFalse(manager._cors_fixed_base_snapshots)

    async def test_cross_station_failover_switches_s2_both_directions(self):
        reference_changed = Mock()
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), reference_change_callback=reference_changed,
        )
        stations = [
            {
                "serial": "SQ1-SERIAL",
                "name": "SinQuyen1",
                "status": "offline",
                "service_config": {
                    "server1_enabled": True,
                    "serverhost1": "caster.example",
                    "mountpoint1": "SinQuyen1",
                    "server1_stream_on_demand": False,
                    "server1_stream_active": True,
                    "server2_enabled": False,
                    "serverhost2": "caster.example",
                    "mountpoint2": "SinQuyen2",
                    "server2_stream_on_demand": True,
                    "server2_stream_active": False,
                },
            },
            {
                "serial": "SQ2-SERIAL",
                "name": "SinQuyen2",
                "status": "online",
                "service_config": {
                    "server1_enabled": True,
                    "serverhost1": "caster.example",
                    "mountpoint1": "SinQuyen2",
                    "server1_stream_on_demand": False,
                    "server1_stream_active": True,
                    "server2_enabled": False,
                    "serverhost2": "caster.example",
                    "mountpoint2": "SinQuyen1",
                    "server2_stream_on_demand": True,
                    "server2_stream_active": False,
                },
            },
        ]
        clusters = [
            {
                "name": "Dam 1",
                "base_station": "SinQuyen1",
                "base_serial": "SQ1-SERIAL",
                "base_server_id": 1,
                "base_stream_host": "caster.example",
                "base_stream_mp": "SinQuyen1",
                "backup_base_station": "SinQuyen2",
                "backup_base_serial": "SQ2-SERIAL",
                "backup_base_server_id": 2,
                "backup_base_stream_host": "caster.example",
                "backup_base_stream_mp": "SinQuyen1",
            },
            {
                "name": "Dam 4",
                "base_station": "SinQuyen2",
                "base_serial": "SQ2-SERIAL",
                "base_server_id": 1,
                "base_stream_host": "caster.example",
                "base_stream_mp": "SinQuyen2",
                "backup_base_station": "SinQuyen1",
                "backup_base_serial": "SQ1-SERIAL",
                "backup_base_server_id": 2,
                "backup_base_stream_host": "caster.example",
                "backup_base_stream_mp": "SinQuyen2",
            },
        ]
        configured = []

        def configure(serial, service_config):
            configured.append((serial, service_config))
            return {"status": "service_config_sent_and_saved"}

        with patch.object(manager, "_cors_configure_service_sync", side_effect=configure):
            first = await manager.reconcile_cors_failover_pairs(
                clusters,
                stations=stations,
            )
            self.assertEqual([item["state"] for item in first], [
                "BACKUP_ACTIVE",
                "PRIMARY_ACTIVE",
            ])
            self.assertEqual(len(configured), 1)
            self.assertEqual(configured[0][0], "SQ2-SERIAL")
            self.assertTrue(configured[0][1]["server2_enabled"])
            self.assertTrue(configured[0][1]["server2_stream_on_demand"])
            self.assertFalse(configured[0][1]["server2_stream_active"])
            self.assertEqual(reference_changed.call_count, 1)
            self.assertEqual(reference_changed.call_args.args[0], clusters[0])
            reference_changed.reset_mock()
            await manager.reconcile_cors_failover_pairs(clusters, stations=stations)
            reference_changed.assert_not_called()

            stations[0]["status"] = "online"
            stations[1]["status"] = "offline"
            configured.clear()
            second = await manager.reconcile_cors_failover_pairs(
                clusters,
                stations=stations,
            )

        self.assertEqual([item["state"] for item in second], [
            "PRIMARY_ACTIVE",
            "BACKUP_ACTIVE",
        ])
        self.assertEqual([item[0] for item in configured], [
            "SQ2-SERIAL",
            "SQ1-SERIAL",
        ])
        self.assertFalse(configured[0][1]["server2_enabled"])
        self.assertTrue(configured[0][1]["server2_stream_on_demand"])
        self.assertFalse(configured[0][1]["server2_stream_active"])
        self.assertTrue(configured[1][1]["server2_enabled"])
        self.assertTrue(configured[1][1]["server2_stream_on_demand"])
        self.assertFalse(configured[1][1]["server2_stream_active"])
        self.assertEqual(reference_changed.call_count, 2)

    async def test_repeated_failback_from_stale_map_does_not_repeat_reference_event(self):
        reference_changed = Mock()
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(), reference_change_callback=reference_changed,
        )
        stations = [
            {"serial": "SQ1", "name": "SinQuyen1", "status": "online",
             "service_config": {"server1_enabled": False,
                                "serverhost1": "caster.example", "mountpoint1": "SinQuyen1"}},
            {"serial": "SQ2", "name": "SinQuyen2", "status": "online",
             "service_config": {"server2_enabled": True,
                                "serverhost2": "caster.example", "mountpoint2": "SinQuyen1"}},
        ]
        cluster = {
            "name": "Dam 1", "base_station": "SinQuyen1", "base_serial": "SQ1",
            "base_server_id": 1, "base_stream_host": "caster.example",
            "base_stream_mp": "SinQuyen1", "backup_base_station": "SinQuyen2",
            "backup_base_serial": "SQ2", "backup_base_server_id": 2,
            "backup_base_stream_host": "caster.example",
            "backup_base_stream_mp": "SinQuyen1",
        }
        with patch.object(manager, "_cors_configure_service_sync") as configure:
            for _ in range(2):
                # Simulate the API returning the old snapshot on every daemon poll.
                await manager.reconcile_cors_failover_pairs(
                    [cluster], stations=copy.deepcopy(stations),
                )

        self.assertEqual(configure.call_count, 4)
        reference_changed.assert_called_once()

    async def test_seed_forces_both_streams_to_selected_physical_base(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.FIXED_BASE_HANDOVER_SETTLE_SECONDS = 0
        manager.FIXED_BASE_HANDOVER_VERIFY_SECONDS = 0
        selected_config = {
            "server1_enabled": True,
            "mountpoint1": "SinQuyen2",
            "server1_stream_on_demand": False,
            "server1_stream_active": True,
            "server2_enabled": False,
            "mountpoint2": "SinQuyen1",
            "server2_stream_on_demand": True,
            "server2_stream_active": False,
        }
        other_config = {
            "server1_enabled": True,
            "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False,
            "server1_stream_active": True,
            "server2_enabled": True,
            "mountpoint2": "SinQuyen2",
            "server2_stream_on_demand": True,
            "server2_stream_active": False,
        }
        stations = [
            {"serial": "SQ2", "name": "SinQuyen2", "status": "online", "service_config": selected_config},
            {"serial": "SQ1", "name": "SinQuyen1", "status": "online", "service_config": other_config},
        ]
        candidates = [
            {
                "role": "primary", "base_station": "SinQuyen2", "base_serial": "SQ2",
                "base_server_id": 1, "base_stream_mp": "SinQuyen2",
                "base_lat": 21.0, "base_lon": 105.0, "base_alt": 10.0,
            },
            {
                "role": "backup", "base_station": "SinQuyen1", "base_serial": "SQ1",
                "base_server_id": 2, "base_stream_mp": "SinQuyen2",
                "base_lat": 21.1, "base_lon": 105.0, "base_alt": 10.0,
            },
        ]
        manager.configure_project(91, [{
            "name": "Cụm tổng", "cluster_type": "total",
            "stations": [1, 2], "rovers": ["R1", "R2"],
            "fixed_base_candidates": candidates,
        }])
        configured = []

        def configure(serial, service_config):
            configured.append((serial, service_config))
            return {"status": "service_config_sent_and_saved"}

        with patch.object(manager, "_cors_api_request_sync", return_value=stations), patch.object(
            manager, "_cors_configure_service_sync", side_effect=configure
        ):
            outcome = await manager.prepare_common_fixed_base_seed(91)
            self.assertEqual([item[0] for item in configured], ["SQ1", "SQ2"])
            self.assertFalse(configured[0][1]["server1_enabled"])
            self.assertFalse(configured[0][1]["server2_enabled"])
            self.assertTrue(configured[1][1]["server1_enabled"])
            self.assertTrue(configured[1][1]["server2_enabled"])
            self.assertTrue(configured[1][1]["server2_stream_on_demand"])
            self.assertFalse(configured[1][1]["server2_stream_active"])
            self.assertEqual(outcome[0]["selected_base"], "SinQuyen2")
            self.assertTrue(outcome[0]["opposite_online"])
            self.assertEqual(
                manager._sessions[91]["clusters"][0]["selected_fixed_base_candidate"]["base_station"],
                "SinQuyen2",
            )
            self.assertTrue(
                manager._sessions[91]["clusters"][0]["require_fixed_base_length_check"]
            )

            configured.clear()
            await manager.restore_common_fixed_base_topology(91)

        self.assertEqual([item[0] for item in configured], ["SQ1", "SQ2"])
        self.assertEqual(configured[0][1], other_config)
        self.assertEqual(configured[1][1], selected_config)

    async def test_seed_reconciles_failover_pair_before_preparing_topology(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        cluster = {
            "name": "Dam 1", "stations": [1, 2], "rovers": ["R1", "R2"],
            "base_station": "SinQuyen1",
            "backup_base_station": "SinQuyen2",
        }
        manager.configure_project(96, [cluster])
        calls = []

        async def reconcile(clusters, *, stations=None):
            calls.append(("reconcile", clusters[0]["name"]))
            return []

        async def prepare(project_id):
            calls.append(("prepare", project_id))
            return [{"state": "ready"}]

        with patch.object(
            manager,
            "_reconcile_cors_failover_pairs_unlocked",
            side_effect=reconcile,
        ), patch.object(
            manager,
            "_prepare_common_fixed_base_seed_unlocked",
            side_effect=prepare,
        ):
            outcome = await manager.prepare_common_fixed_base_seed(96)

        self.assertEqual(calls, [("reconcile", "Dam 1"), ("prepare", 96)])
        self.assertEqual(outcome, [{"state": "ready"}])

    async def test_seed_keeps_offline_counterpart_and_asserts_selected_s2(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.FIXED_BASE_HANDOVER_SETTLE_SECONDS = 0
        manager.FIXED_BASE_HANDOVER_VERIFY_SECONDS = 0
        selected_config = {
            "server1_enabled": True, "mountpoint1": "SinQuyen2",
            "server1_stream_on_demand": False, "server1_stream_active": True,
            "server2_enabled": False, "mountpoint2": "SinQuyen1",
            "server2_stream_on_demand": True, "server2_stream_active": False,
        }
        other_config = {
            "server1_enabled": True, "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False, "server1_stream_active": True,
            "server2_enabled": True, "mountpoint2": "SinQuyen2",
            "server2_stream_on_demand": True, "server2_stream_active": False,
        }
        stations = [
            {"serial": "SQ2", "name": "SinQuyen2", "status": "online", "service_config": selected_config},
            {"serial": "SQ1", "name": "SinQuyen1", "status": "offline", "service_config": other_config},
        ]
        manager.configure_project(92, [{
            "name": "Cụm tổng", "cluster_type": "total",
            "stations": [1, 2], "rovers": ["R1", "R2"],
            "fixed_base_candidates": [
                {"role": "primary", "base_station": "SinQuyen2", "base_serial": "SQ2", "base_server_id": 1, "base_stream_mp": "SinQuyen2", "base_lat": 21.0, "base_lon": 105.0},
                {"role": "backup", "base_station": "SinQuyen1", "base_serial": "SQ1", "base_server_id": 2, "base_stream_mp": "SinQuyen2", "base_lat": 21.1, "base_lon": 105.0},
            ],
        }])
        configured = []

        with patch.object(manager, "_cors_api_request_sync", return_value=stations), patch.object(
            manager,
            "_cors_configure_service_sync",
            side_effect=lambda serial, cfg: configured.append((serial, cfg)) or {"status": "service_config_sent_and_saved"},
        ):
            outcome = await manager.prepare_common_fixed_base_seed(92)

        self.assertEqual([item[0] for item in configured], ["SQ2"])
        self.assertTrue(configured[0][1]["server2_enabled"])
        self.assertTrue(configured[0][1]["server2_stream_on_demand"])
        self.assertFalse(configured[0][1]["server2_stream_active"])
        self.assertFalse(outcome[0]["opposite_online"])

    async def test_seed_accepts_live_stream_metadata_when_public_config_omits_s2(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.FIXED_BASE_HANDOVER_SETTLE_SECONDS = 0
        manager.FIXED_BASE_HANDOVER_VERIFY_SECONDS = 0
        stations = [
            {
                "serial": "SQ1", "name": "SinQuyen1", "status": "online",
                "service_config": {
                    "server1_enabled": True, "mountpoint1": "SinQuyen1",
                    "server1_stream_on_demand": False, "server1_stream_active": True,
                },
                "streams": [
                    {"server_id": 1, "enabled": True, "mountpoint": "SinQuyen1"},
                    {"server_id": 2, "enabled": True, "mountpoint": "SinQuyen2"},
                ],
            },
            {
                "serial": "SQ2", "name": "SinQuyen2", "status": "online",
                "service_config": {
                    "server1_enabled": True, "mountpoint1": "SinQuyen2",
                },
                "streams": [
                    {"server_id": 1, "enabled": True, "mountpoint": "SinQuyen2"},
                    {"server_id": 2, "enabled": True, "mountpoint": "SinQuyen1"},
                ],
            },
        ]
        manager.configure_project(95, [{
            "name": "Dam 1", "cluster_type": "total",
            "stations": [1, 2], "rovers": ["R1", "R2"],
            "fixed_base_candidates": [
                {"role": "primary", "base_station": "SinQuyen1", "base_serial": "SQ1", "base_server_id": 1, "base_stream_mp": "SinQuyen1", "base_lat": 21.1, "base_lon": 105.0},
                {"role": "backup", "base_station": "SinQuyen2", "base_serial": "SQ2", "base_server_id": 2, "base_stream_mp": "SinQuyen1", "base_lat": 21.0, "base_lon": 105.0},
            ],
        }])
        configured = []

        with patch.object(manager, "_cors_api_request_sync", return_value=stations), patch.object(
            manager,
            "_cors_configure_service_sync",
            side_effect=lambda serial, cfg: configured.append((serial, cfg)) or {"status": "service_config_sent_and_saved"},
        ):
            outcome = await manager.prepare_common_fixed_base_seed(95)

        self.assertEqual(outcome[0]["selected_base"], "SinQuyen1")
        self.assertEqual([item[0] for item in configured], ["SQ2"])
        self.assertFalse(configured[0][1]["server1_enabled"])
        self.assertFalse(configured[0][1]["server2_enabled"])

    async def test_seed_selects_online_backup_when_configured_primary_is_offline(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.FIXED_BASE_HANDOVER_SETTLE_SECONDS = 0
        manager.FIXED_BASE_HANDOVER_VERIFY_SECONDS = 0
        offline_primary_config = {
            "stream_on_demand": True, "stream_active": True,
            "server1_enabled": True, "mountpoint1": "SinQuyen1",
            "server1_stream_on_demand": False, "server1_stream_active": True,
            "server2_enabled": True, "mountpoint2": "SinQuyen2",
            "server2_stream_on_demand": True, "server2_stream_active": False,
        }
        online_backup_config = {
            "stream_on_demand": False, "stream_active": True,
            "server1_enabled": True, "mountpoint1": "SinQuyen2",
            "server1_stream_on_demand": False, "server1_stream_active": True,
            "server2_enabled": True, "mountpoint2": "SinQuyen1",
            "server2_stream_on_demand": False, "server2_stream_active": True,
        }
        stations = [
            {"serial": "SQ1", "name": "SinQuyen1", "status": "offline", "service_config": offline_primary_config},
            {"serial": "SQ2", "name": "SinQuyen2", "status": "online", "service_config": online_backup_config},
        ]
        manager.configure_project(94, [{
            "name": "Dam 1", "cluster_type": "total",
            "stations": [1, 2], "rovers": ["R1", "R2"],
            "fixed_base_candidates": [
                {"role": "primary", "base_station": "SinQuyen1", "base_serial": "SQ1", "base_server_id": 1, "base_stream_mp": "SinQuyen1", "base_lat": 21.1, "base_lon": 105.0},
                {"role": "backup", "base_station": "SinQuyen2", "base_serial": "SQ2", "base_server_id": 2, "base_stream_mp": "SinQuyen1", "base_lat": 21.0, "base_lon": 105.0},
            ],
        }])
        configured = []

        with patch.object(manager, "_cors_api_request_sync", return_value=stations), patch.object(
            manager,
            "_cors_configure_service_sync",
            side_effect=lambda serial, cfg: configured.append((serial, cfg)) or {"status": "service_config_sent_and_saved"},
        ):
            outcome = await manager.prepare_common_fixed_base_seed(94)

        self.assertEqual(outcome[0]["selected_base"], "SinQuyen2")
        self.assertEqual(outcome[0]["opposite_base"], "SinQuyen1")
        self.assertFalse(outcome[0]["opposite_online"])
        self.assertEqual(
            manager._sessions[94]["clusters"][0]["selected_fixed_base_candidate"]["role"],
            "backup",
        )
        self.assertEqual(configured, [])

    async def test_single_fixed_base_seed_does_not_require_cors_topology_api(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(93, [{
            "name": "Legacy", "stations": [1, 2], "rovers": ["R1", "R2"],
            "base_station": "CORS-A", "base_lat": 21.0, "base_lon": 105.0,
        }])

        with patch.object(manager, "_cors_api_request_sync") as cors_request:
            outcome = await manager.prepare_common_fixed_base_seed(93)

        self.assertEqual(outcome, [])
        cors_request.assert_not_called()
        self.assertEqual(
            manager._sessions[93]["clusters"][0]["selected_fixed_base_candidate"]["base_station"],
            "CORS-A",
        )

    async def test_ordinary_failover_cluster_waits_for_agrica_base_identity(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(97, [{
            "name": "Dam 1", "stations": [1, 2], "rovers": ["R1", "R2"],
            "fixed_base_candidates": [
                {"role": "primary", "base_station": "SinQuyen1", "base_lat": 21.1, "base_lon": 105.0},
                {"role": "backup", "base_station": "SinQuyen2", "base_lat": 21.0, "base_lon": 105.0},
            ],
        }])

        outcome = await manager.prepare_common_fixed_base_seed(97)

        cluster = manager._sessions[97]["clusters"][0]
        self.assertEqual(outcome, [])
        self.assertIsNone(cluster["selected_fixed_base_candidate"])
        self.assertIn("awaiting AGRICA", cluster["fixed_base_selection_diagnostic"])

    async def test_ordinary_cluster_locks_backup_from_cors_topology_api(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        manager.configure_project(98, [{
            "name": "Dam 1",
            "stations": [1, 2],
            "rovers": ["R1", "R2"],
            "base_station": "SinQuyen1",
            "base_serial": "SQ1",
            "base_server_id": 1,
            "base_stream_host": "caster.example",
            "base_stream_mp": "SinQuyen1",
            "backup_base_station": "SinQuyen2",
            "backup_base_serial": "SQ2",
            "backup_base_server_id": 2,
            "backup_base_stream_host": "caster.example",
            "backup_base_stream_mp": "SinQuyen1",
            "fixed_base_candidates": [
                {
                    "role": "primary",
                    "base_station": "SinQuyen1",
                    "base_serial": "SQ1",
                    "base_server_id": 1,
                    "base_stream_host": "caster.example",
                    "base_stream_mp": "SinQuyen1",
                    "base_lat": 21.1,
                    "base_lon": 105.0,
                },
                {
                    "role": "backup",
                    "base_station": "SinQuyen2",
                    "base_serial": "SQ2",
                    "base_server_id": 2,
                    "base_stream_host": "caster.example",
                    "base_stream_mp": "SinQuyen1",
                    "base_lat": 21.0,
                    "base_lon": 105.0,
                },
            ],
        }])
        stations = [
            {
                "serial": "SQ1",
                "name": "SinQuyen1",
                "status": "offline",
                "service_config": {
                    "server1_enabled": True,
                    "serverhost1": "caster.example",
                    "mountpoint1": "SinQuyen1",
                },
            },
            {
                "serial": "SQ2",
                "name": "SinQuyen2",
                "status": "online",
                "service_config": {
                    "server2_enabled": True,
                    "serverhost2": "caster.example",
                    "mountpoint2": "SinQuyen1",
                },
            },
        ]

        with patch.object(
            manager,
            "_cors_api_request_sync",
            return_value=stations,
        ):
            outcome = await manager.prepare_common_fixed_base_seed(98)

        cluster = manager._sessions[98]["clusters"][0]
        self.assertEqual(outcome, [])
        self.assertEqual(cluster["selected_fixed_base_candidate"]["role"], "backup")
        self.assertEqual(cluster["base_station"], "SinQuyen2")
        self.assertEqual(cluster["base_serial"], "SQ2")
        self.assertEqual(cluster["base_server_id"], 2)
        self.assertIn("CORS topology API confirmed backup", cluster["fixed_base_selection_diagnostic"])

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
            web_cors_api_base_url="https://cors.example",
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
                await manager._set_cors_fixed_base_enabled(
                    "SinQuyen1",
                    enabled=False,
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
        commands = RoundRobinAdjustmentManager._build_unicore_rover_config(-24.001831)
        self.assertEqual(commands, [
            b"mode rover survey\r\n",
            b"config undulation -24.0018\r\n",
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

    async def test_client_lookup_uses_station_configured_aicaster_username(self):
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            caster_host="aitogy.com.vn",
            caster_hosts=["aitogy.com.vn"],
        )
        manager.configure_project(94, [{
            "stations": [4, 2],
            "rovers": ["Dap4_1", "Dap1_2"],
            "aicaster_users": {
                "Dap4_1": {
                    "username": "Dap2_1",
                    "caster_host": "aitogy.com.vn",
                }
            },
        }])
        manager._query_client_table = AsyncMock(
            return_value="STR;Dap2_1;1.4.10;SinQuyen1;0;\r\n"
        )

        selected = await manager._find_client_info("Dap4_1", project_id=94)

        self.assertEqual(selected["Username"], "Dap2_1")
        self.assertEqual(selected["Mountpoint"], "SinQuyen1")

    async def test_aicaster_users_are_loaded_without_exposing_passwords(self):
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            caster_host="aitogy.com.vn",
            caster_hosts=["aitogy.com.vn"],
        )
        manager._query_user_table = AsyncMock(
            return_value=(
                "USERTABLE 200 OK\r\n\r\n"
                "STR;Dap2_1;secret;SinQuyen1,SinQuyen2,;0;online;dam;1;2;\r\n"
                "STR;Dap2_1;secret;SinQuyen1,SinQuyen2,;0;online;dam;1;2;\r\n"
                "ENDUSERTABLE\r\n"
            )
        )

        users = await manager.list_aicaster_users()

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["Username"], "Dap2_1")
        self.assertEqual(users[0]["Mountpoints"], ["SinQuyen1", "SinQuyen2"])
        self.assertNotIn("Password", users[0])
        self.assertNotIn("secret", str(users[0]))

    async def test_client_lookup_can_poll_missing_session_without_error_spam(self):
        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            caster_host="aitogy.com.vn",
            caster_hosts=["aitogy.com.vn"],
        )
        manager._query_client_table = AsyncMock(
            return_value="STR;other;other;CORS_A;0;\r\n"
        )
        module_name = RoundRobinAdjustmentManager.__module__

        with patch(f"{module_name}.logger.error") as error_log:
            selected = await manager._find_client_info(
                "Dap4_1",
                log_missing=False,
            )

        self.assertIsNone(selected)
        error_log.assert_not_called()

    def test_temporary_base_and_rover_recovery_both_end_with_saveconfig(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands = manager._build_unicore_base_config(
            "FIXED", lat=21.0, lon=105.0, alt=10.0
        )
        command_text = b"".join(commands).lower()

        self.assertEqual(commands, [
            b"unlogall\r\n",
            b"config undulation 0.0\r\n",
            b"mode base 21.0 105.0 10.0\r\n",
            b"rtcm1006 com2 10\r\n",
            b"rtcm1033 com2 10\r\n",
            b"rtcm1074 com2 1\r\n",
            b"rtcm1124 com2 1\r\n",
            b"rtcm1084 com2 1\r\n",
            b"rtcm1094 com2 1\r\n",
            b"saveconfig\r\n",
        ])

        ecef_commands = manager._build_unicore_base_config(
            "FIXED",
            ecef_xyz=(-1773825.0657882644, 5684333.063952032, 2277604.1899894723),
        )
        self.assertEqual(ecef_commands[:2], [
            b"unlogall\r\n",
            b"mode base -1773825.0658 5684333.0640 2277604.1900\r\n",
        ])
        self.assertNotIn(b"config undulation 0.0\r\n", ecef_commands)

        rover_text = b"".join(manager._build_unicore_rover_config()).lower()
        self.assertEqual(
            rover_text,
            b"mode rover survey\r\nconfig undulation auto\r\nunlogall\r\ngpgga com2 1\r\n"
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

        async def wake_fixed_base():
            events.append(("fixed_base_woken",))
            return {
                "Username": "S1",
                "receiverID": "101-new",
                "Mountpoint": "CORS_B",
            }

        async def sleep_fixed_base():
            events.append(("fixed_base_sleep",))

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
                before_rover_restore=wake_fixed_base,
                after_rover_restore=sleep_fixed_base,
            )

        event_names = [event[0] for event in events]
        self.assertEqual(
            event_names,
            [
                "set_rover",
                "route_started",
                "set_base",
                "collection_started",
                "collection_stopped",
                "route_stopped",
                "fixed_base_woken",
                "set_rover",
                "restore_config",
                "restore_unlogall",
                "restore_gpgga",
                "restore_agrica",
                "restore_saveconfig",
                "fixed_base_sleep",
            ],
        )
        self.assertEqual(
            events[1],
            ("route_started", "S1", "aitogy.click", 2101, "QN.CP", "12345"),
        )
        restore_calls = [
            event for event in events if event[0] in {"set_rover", "restore_config"}
        ]
        self.assertEqual(len(restore_calls), 3)

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
            "route_rejected",
        ])

    async def test_missing_rtcm_reapplies_clean_base_profile_and_retries_route(self):
        route_calls = 0
        route_stops = []
        command_groups = []
        collection_events = []
        wait_calls = 0

        async def route_start(*_args):
            nonlocal route_calls
            route_calls += 1
            return True

        async def route_wait(*_args):
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls == 1:
                raise RuntimeError(
                    "No valid RTCM3 frame was forwarded within 25s; d3_preambles=0"
                )

        async def route_stop(station_code):
            route_stops.append(station_code)

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_wait_callback=route_wait,
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
        self.assertEqual(wait_calls, 2)
        self.assertEqual(collection_events, ["started", "stopped"])
        self.assertEqual(command_groups[1], expected_base_profile)
        self.assertEqual(command_groups[2], expected_base_profile)
        # One stop cleans the failed attempt and one stops the successful route.
        self.assertEqual(route_stops, ["S1", "S1"])

    async def test_collection_waits_for_stationarity_and_resets_when_drift_returns(self):
        status_calls = 0
        stable_events = []
        invalid_events = []

        async def route_start(*_args):
            return True

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_stop_callback=AsyncMock(),
        )
        manager.STABILITY_HOLD_SECONDS = 0
        manager.CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS = 0
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
                return {
                    "sample_count": 0,
                    "rover_names": set(),
                    "sample_counts_by_rover": {},
                }
            if status_calls == 3:
                return {
                    "sample_count": 6,
                    "rover_names": {"S2", "S3"},
                    "sample_counts_by_rover": {"S2": 4, "S3": 1},
                }
            status = {
                "sample_count": 40,
                "rover_names": {"S2", "S3"},
                "sample_counts_by_rover": {"S2": 20, "S3": 20},
                "rolling_stability_by_rover": {
                    "S2": {
                        "stable": True,
                        "enough_samples": True,
                        "latest_epoch": status_calls,
                        "delta_neu_m": (0.0, 0.0, 0.0),
                    },
                    "S3": {
                        "stable": True,
                        "enough_samples": True,
                        "latest_epoch": status_calls,
                        "delta_neu_m": (0.0, 0.0, 0.0),
                    },
                },
            }
            if len(stable_events) == 1 and not invalid_events:
                status["rolling_stability_by_rover"]["S3"] = {
                    "stable": False,
                    "enough_samples": True,
                    "latest_epoch": status_calls,
                    "delta_neu_m": (0.009, 0.0, 0.0),
                }
                status["solver_sample_counts_by_rover"] = {"S2": 10, "S3": 10}
                status["solver_durations_by_rover_seconds"] = {"S2": 9, "S3": 9}
            elif len(stable_events) >= 2:
                status["solver_sample_counts_by_rover"] = {"S2": 61, "S3": 61}
                status["solver_durations_by_rover_seconds"] = {"S2": 60, "S3": 60}
            return status

        sleep_mock = AsyncMock()
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=sleep_mock):
            await manager._set_rover_as_temporary_base(
                "S1",
                on_stable_collection_started=lambda: stable_events.append("stable"),
                on_stable_collection_invalid=lambda reason: invalid_events.append(reason),
                collection_status_callback=collection_status,
                expected_cross_rovers={"S2", "S3"},
            )

        self.assertEqual(status_calls, 10)
        delays = [call.args[0] for call in sleep_mock.await_args_list]
        self.assertEqual(
            delays.count(manager.CROSS_BASE_STATUS_POLL_SECONDS),
            8,
        )
        self.assertEqual(stable_events, ["stable", "stable"])
        self.assertEqual(invalid_events, ["drift"])
        self.assertIn(manager.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS, delays)
        self.assertNotIn(manager.CROSS_BASE_STABLE_COLLECTION_SECONDS, delays)

    async def test_partial_handover_uses_live_rover_and_does_not_wait_for_silent_peer(self):
        progress_messages = []
        status_calls = 0

        async def route_start(*_args):
            return True

        manager = RoundRobinAdjustmentManager(
            _FakeMqttClient(),
            route_start_callback=route_start,
            route_stop_callback=AsyncMock(),
            progress_callback=AsyncMock(
                side_effect=lambda _project_id, message: progress_messages.append(message)
            ),
        )
        manager.STABILITY_HOLD_SECONDS = 0
        manager.CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS = 0
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
            status = {
                "sample_count": 20,
                "rover_names": {"S2"},
                "sample_counts_by_rover": {"S2": 20},
                "rolling_stability_by_rover": {
                    "S2": {
                        "stable": True,
                        "enough_samples": True,
                        "latest_epoch": status_calls,
                        "stable_run_seconds": 1,
                        "delta_neu_m": (0.0, 0.0, 0.0),
                    },
                },
            }
            if status_calls >= 3:
                status["solver_sample_counts_by_rover"] = {"S2": 61}
                status["solver_durations_by_rover_seconds"] = {"S2": 60}
            return status

        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._set_rover_as_temporary_base(
                "S1",
                project_id=17,
                on_stable_collection_started=lambda: None,
                collection_status_callback=collection_status,
                expected_cross_rovers={"S2", "S3"},
            )

        self.assertEqual(status_calls, 3)
        self.assertTrue(any(
            "continuing with partial live coverage" in message
            and "S3" in message
            for message in progress_messages
        ))

    async def test_temporary_base_resets_only_cross_rover_clients(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        clients = {
            "S2": {
                "Username": "S2",
                "receiverID": "102",
                "Mountpoint": "CORS_S2",
                "CasterHost": "caster.example",
                "CasterPort": 2101,
            },
            "S3": {
                "Username": "S3",
                "receiverID": "103",
                "Mountpoint": "CORS_S3",
                "CasterHost": "caster.example",
                "CasterPort": 2101,
            },
        }
        reset_calls = []

        async def find_client(station_code, **_kwargs):
            return clients.get(station_code)

        async def send_set(mountpoint, username, receiver_id, commands, **kwargs):
            reset_calls.append((mountpoint, username, receiver_id, commands, kwargs))
            return True

        manager._find_client_info = find_client
        manager._send_set_command = send_set

        await manager._reset_cross_rovers_for_temporary_base(
            temporary_base_code="S1",
            target_rovers={"S1", "S2", "S3"},
            project_id=17,
        )

        self.assertEqual(
            [(mountpoint, username, receiver_id, commands) for mountpoint, username, receiver_id, commands, _ in reset_calls],
            [
                ("CORS_S2", "S2", "102", [b"RESET\r\n"]),
                ("CORS_S3", "S3", "103", [b"RESET\r\n"]),
            ],
        )
        self.assertTrue(all(
            call_kwargs.get("wait_for_command_response") is False
            for *_prefix, call_kwargs in reset_calls
        ))

    async def test_rover_restore_retries_each_command_until_ack_before_advancing(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands_seen = []
        responses = iter([False, True, True, True, True, True, True])

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
                b"config undulation auto\r\n",
                b"unlogall\r\n",
                b"gpgga com2 1\r\n",
                b"AGRICA COM2 1\r\n",
                b"saveconfig\r\n",
            ],
        )
        self.assertTrue(all(wait_for_response for _, wait_for_response in commands_seen))

    async def test_rover_restore_refreshes_stale_set_session_and_extends_transport_retries(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        calls = []
        responses = iter([False, False, False, True, True, True, True, True, True])

        async def send_set(mountpoint, username, receiver_id, commands, **_kwargs):
            calls.append((mountpoint, username, receiver_id, commands[0]))
            accepted = next(responses)
            if not accepted:
                manager._last_set_error = (
                    f"caster.example:2101 mountpoint={mountpoint} "
                    f"username={username} auth=enabled response=empty response"
                )
            return accepted

        manager._send_set_command = send_set
        manager._find_client_info = AsyncMock(return_value={
            "Username": "Dap4_1-new",
            "receiverID": "4.1-new",
            "Mountpoint": "SinQuyen1",
            "CasterHost": "caster.example",
            "CasterPort": 2101,
        })
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._restore_rover_output_sequence(
                rover_code="Dap4_1",
                mountpoint="SinQuyen2",
                client_info={
                    "Username": "Dap2_1",
                    "receiverID": "stale",
                    "Mountpoint": "SinQuyen2",
                    "CasterHost": "caster.example",
                    "CasterPort": 2101,
                },
                commands=manager._build_unicore_rover_config(),
                project_id=3,
            )

        mode_calls = [call for call in calls if call[3] == b"mode rover survey\r\n"]
        self.assertEqual(len(mode_calls), 4)
        self.assertEqual(mode_calls[0][:3], ("SinQuyen2", "Dap2_1", "stale"))
        self.assertEqual(
            mode_calls[-1][:3],
            ("SinQuyen1", "Dap4_1-new", "4.1-new"),
        )
        self.assertEqual(manager._find_client_info.await_count, 3)

    async def test_rover_restore_does_not_fail_when_only_saveconfig_ack_is_missing(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands_seen = []
        responses = iter([True, True, True, True, True, False, False, False])

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

    async def test_unacknowledged_undulation_does_not_block_mandatory_rover_outputs(self):
        manager = RoundRobinAdjustmentManager(_FakeMqttClient())
        commands_seen = []

        async def send_set(_mountpoint, _username, _receiver_id, commands, **_kwargs):
            command = commands[0]
            commands_seen.append(command)
            manager._last_set_error = "no verified MQTT ACK"
            return not command.startswith(b"config undulation ")

        manager._send_set_command = send_set
        with patch(f"{ROUND_ROBIN_MODULE}.asyncio.sleep", new=AsyncMock()):
            await manager._restore_rover_output_sequence(
                rover_code="Dap1_2",
                mountpoint="SinQuyen1",
                client_info={"Username": "Dap1_2", "receiverID": "1.4.10"},
                commands=manager._build_unicore_rover_config(),
                project_id=3,
            )

        self.assertEqual(commands_seen.count(b"config undulation auto\r\n"), 3)
        self.assertIn(b"unlogall\r\n", commands_seen)
        self.assertIn(b"AGRICA COM2 1\r\n", commands_seen)
        self.assertEqual(commands_seen[-1], b"saveconfig\r\n")


if __name__ == "__main__":
    unittest.main()
