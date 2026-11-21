"""Controlled live BASE-output probe with guaranteed ROVER restoration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import paho.mqtt.client as mqtt

from app.config import settings
from processors.gnss_adjustment.runtime import parse_agrica
from processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
from live_gnss_probe import AGRICA_RE, TOPICS, TopicStats


STATION_TOPIC = {station: topic for topic, station in TOPICS.items()}


class _UnusedPublisher:
    def publish(self, *_args, **_kwargs):
        return None


class LiveFeed:
    def __init__(
        self,
        manager: RoundRobinAdjustmentManager,
        payload_callback=None,
        *,
        topics=None,
        mqtt_broker: str | None = None,
        mqtt_port: int | None = None,
        mqtt_user: str | None = None,
        mqtt_password: str | None = None,
    ):
        self.manager = manager
        self.payload_callback = payload_callback
        self.topics = dict(topics or TOPICS)
        self.station_topic = {
            station: topic for topic, station in self.topics.items()
        }
        self.mqtt_broker = str(mqtt_broker or settings.MQTT_BROKER)
        self.mqtt_port = int(mqtt_port or settings.MQTT_PORT)
        self.connected = threading.Event()
        self.connect_error = ""
        self.lock = threading.Lock()
        self.stats = {station: TopicStats() for station in self.station_topic}
        self.buffers = {station: bytearray() for station in self.station_topic}
        self.latest_agrica: dict[str, tuple[float, str]] = {}

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"landslide-base-probe-{int(time.time())}",
        )
        self.client.username_pw_set(
            mqtt_user or settings.MQTT_USER,
            mqtt_password or settings.MQTT_PASSWORD,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        reason_value = getattr(reason_code, "value", reason_code)
        if reason_value != 0:
            self.connect_error = str(reason_code)
            self.connected.set()
            return
        for topic in self.topics:
            client.subscribe(topic, qos=0)
        self.connected.set()

    def _on_message(self, _client, _userdata, message):
        station = self.topics.get(message.topic)
        if station is None:
            return
        payload = bytes(message.payload)
        self.manager.add_receiver_command_payload(
            payload.decode("utf-8", errors="ignore"),
            {"station_code": station},
            message.topic,
        )
        with self.lock:
            self.stats[station].feed(payload)
            buffer = self.buffers[station]
            buffer.extend(payload)
            if len(buffer) > 256_000:
                del buffer[:-128_000]
            matches = list(AGRICA_RE.finditer(bytes(buffer)))
            if matches:
                latest = matches[-1]
                self.latest_agrica[station] = (
                    time.monotonic(),
                    latest.group(0).decode("ascii", errors="ignore"),
                )
                del buffer[: latest.end()]
        if self.payload_callback is not None:
            self.payload_callback(station, message.topic, payload)

    def start(self) -> None:
        self.client.connect(self.mqtt_broker, self.mqtt_port, 30)
        self.client.loop_start()
        if not self.connected.wait(timeout=10):
            raise RuntimeError("MQTT connection timed out")
        if self.connect_error:
            raise RuntimeError(f"MQTT connection rejected: {self.connect_error}")

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def reset_stats(self, station: str) -> None:
        with self.lock:
            self.stats[station] = TopicStats()

    def snapshot(self, station: str) -> TopicStats:
        with self.lock:
            return self.stats[station]

    def latest_llh(self, station: str) -> tuple[float, float, float] | None:
        with self.lock:
            item = self.latest_agrica.get(station)
        if not item:
            return None
        observations = parse_agrica(
            item[1],
            project_id=0,
            station_id=0,
            rover_name=station,
        )
        if not observations:
            return None
        return observations[-1].rover_llh

    def latest_agrica_time(self, station: str) -> float:
        with self.lock:
            item = self.latest_agrica.get(station)
        return item[0] if item else 0.0


def print_stats(station: str, stats: TopicStats) -> None:
    diagnostic = stats.rtcm_filter.diagnostics()
    lengths = stats.payload_lengths
    length_text = (
        f"{min(lengths)}/{sum(lengths) / len(lengths):.1f}/{max(lengths)}"
        if lengths
        else "-/-/-"
    )
    print(
        f"BASE_CAPTURE {station}: messages={stats.messages}, bytes={stats.payload_bytes}, "
        f"payload_len[min/avg/max]={length_text}, GGA={stats.gga_sentences}, "
        f"AGRICA={stats.agrica_sentences}, D3_bytes={stats.d3_bytes}, "
        f"valid_RTCM_frames={stats.valid_rtcm_frames}, "
        f"valid_RTCM_bytes={stats.valid_rtcm_bytes}, "
        f"crc_failures={diagnostic['crc_failures']}, "
        f"last_gga_quality={stats.last_gga_quality}, "
        f"satellites={stats.last_gga_satellites}"
    )
    print(f"  first48={stats.first_hex or '-'}")
    print(f"  last48 ={stats.last_hex or '-'}")


async def wait_for_llh(feed: LiveFeed, station: str, max_wait_seconds: float = 15.0):
    deadline = time.monotonic() + max_wait_seconds
    while time.monotonic() < deadline:
        llh = feed.latest_llh(station)
        if llh and all(value is not None for value in llh):
            return tuple(float(value) for value in llh)
        await asyncio.sleep(0.25)
    raise RuntimeError(f"No complete AGRICA LLH received for {station}")


async def _wait_for_rover_restored(feed: LiveFeed, station: str, restore_started: float, max_wait_seconds: float = 15.0) -> None:
    deadline = restore_started + max_wait_seconds
    while time.monotonic() < deadline:
        if feed.latest_agrica_time(station) >= restore_started:
            print(f"{station}: ROVER restore verified by fresh AGRICA output.")
            return
        await asyncio.sleep(0.25)
    print(f"WARNING {station}: restore commands completed but fresh AGRICA was not seen.")


async def probe_station(
    manager: RoundRobinAdjustmentManager,
    feed: LiveFeed,
    station: str,
    capture_seconds: float,
) -> bool:
    print(f"\n=== {station}: controlled BASE output test ===", flush=True)
    llh = await wait_for_llh(feed, station)
    print(f"{station}: live rover LLH={llh}")
    client_info = await manager._find_client_info(station)
    if not client_info:
        raise RuntimeError(f"No active AICaster SET session found for {station}")
    mountpoint = str(client_info.get("Mountpoint") or "")
    print(
        f"{station}: SET target={client_info.get('CasterHost')}:"
        f"{client_info.get('CasterPort')}/{mountpoint}"
    )

    def send(commands):
        return manager._send_set_command(
            mountpoint,
            client_info.get("Username", station),
            client_info.get("receiverID", ""),
            commands,
            password=manager.control_password,
            caster_host=client_info.get("CasterHost"),
            caster_port=client_info.get("CasterPort"),
            wait_for_command_response=True,
            ack_station_code=station,
        )

    rover_commands = manager._build_unicore_rover_config()
    base_commands = manager._build_unicore_base_config(
        "FIXED",
        lat=llh[0],
        lon=llh[1],
        alt=llh[2],
    )
    base_applied = False
    try:
        if not await send([rover_commands[0]]):
            raise RuntimeError(f"{station}: ROVER preflight ACK failed: {manager._last_set_error}")
        if not await send(base_commands):
            raise RuntimeError(f"{station}: BASE profile ACK failed: {manager._last_set_error}")
        base_applied = True
        print(f"{station}: BASE profile ACKed; settling 10s ...", flush=True)
        await asyncio.sleep(10)
        feed.reset_stats(station)
        print(f"{station}: capturing raw BASE output for {capture_seconds:.1f}s ...", flush=True)
        await asyncio.sleep(capture_seconds)
        stats = feed.snapshot(station)
        print_stats(station, stats)
        return stats.valid_rtcm_frames > 0
    finally:
        print(f"{station}: restoring ROVER + GPGGA + AGRICA ...", flush=True)
        try:
            await manager._restore_rover_output_sequence(
                rover_code=station,
                mountpoint=mountpoint,
                client_info=client_info,
                commands=rover_commands,
                project_id=None,
            )
            restore_started = time.monotonic()
            await _wait_for_rover_restored(feed, station, restore_started, max_wait_seconds=15.0)
        except Exception:
            logging.exception("CRITICAL: ROVER restoration failed for %s", station)
            if base_applied:
                raise


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stations", nargs="+", choices=sorted(STATION_TOPIC))
    parser.add_argument("--capture", type=float, default=20.0)
    args = parser.parse_args()

    hosts = [host.strip() for host in settings.NTRIP_HOSTS.split(",") if host.strip()]
    if not hosts:
        raise RuntimeError("NTRIP_HOSTS must contain at least one caster host")
    manager = RoundRobinAdjustmentManager(
        _UnusedPublisher(),
        caster_host=hosts[0],
        caster_hosts=hosts,
        caster_port=settings.NTRIP_PORT,
        control_password=settings.NTRIP_PASSWORD,
    )
    feed = LiveFeed(manager)
    feed.start()
    try:
        await asyncio.sleep(3)
        results = {}
        for station in args.stations:
            results[station] = await probe_station(manager, feed, station, args.capture)
        print("\nCONTROLLED BASE TEST RESULT")
        for station, passed in results.items():
            print(f"{station}: {'RTCM OK' if passed else 'NO RTCM'}")
        return 0 if all(results.values()) else 1
    finally:
        feed.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(async_main()))
