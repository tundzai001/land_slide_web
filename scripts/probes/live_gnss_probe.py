"""Read-only live MQTT probe for the configured Sin Quyen GNSS receivers."""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import paho.mqtt.client as mqtt

from app.config import settings
from app.mqtt.ntrip_pusher import Rtcm3FrameFilter


TOPICS = {
    "device/860549070374009/upload": "Dap2_1",
    "device/860549070365916/upload": "Dap2_2",
    "device/DEMO_DEVICE_1/upload": "Dap1_1",
    "device/DEMO_DEVICE_2/upload": "Dap1_2",
    "device/DEMO_DEVICE_3/upload": "Dap1_3",
    "device/DEMO_DEVICE_4/upload": "Dap1_4",
}

GGA_RE = re.compile(
    rb"\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?"
)
AGRICA_RE = re.compile(rb"#AGRICA[^*\r\n]*\*[0-9A-Fa-f]{8}")
COMMAND_RE = re.compile(rb"\$command,[^\r\n]+", re.IGNORECASE)


@dataclass
class TopicStats:
    messages: int = 0
    payload_bytes: int = 0
    payload_lengths: list[int] = field(default_factory=list)
    d3_bytes: int = 0
    valid_rtcm_bytes: int = 0
    valid_rtcm_frames: int = 0
    gga_sentences: int = 0
    agrica_sentences: int = 0
    command_responses: int = 0
    last_gga_quality: int | None = None
    last_gga_satellites: int | None = None
    first_hex: str = ""
    last_hex: str = ""
    text_buffer: bytearray = field(default_factory=bytearray)
    rtcm_filter: Rtcm3FrameFilter = field(default_factory=Rtcm3FrameFilter)

    def feed(self, payload: bytes) -> None:
        self.messages += 1
        self.payload_bytes += len(payload)
        self.payload_lengths.append(len(payload))
        self.d3_bytes += payload.count(b"\xd3")
        preview = payload[:48].hex()
        if not self.first_hex:
            self.first_hex = preview
        self.last_hex = preview

        frames = self.rtcm_filter.feed(payload)
        self.valid_rtcm_bytes += len(frames)
        cursor = 0
        while cursor + 6 <= len(frames):
            frame_length = ((frames[cursor + 1] & 0x03) << 8) | frames[cursor + 2]
            cursor += frame_length + 6
            self.valid_rtcm_frames += 1

        self.command_responses += len(COMMAND_RE.findall(payload))
        self.text_buffer.extend(payload)
        if len(self.text_buffer) > 256_000:
            del self.text_buffer[:-128_000]

        text = bytes(self.text_buffer)
        agrica_matches = list(AGRICA_RE.finditer(text))
        gga_matches = list(GGA_RE.finditer(text))
        if agrica_matches:
            self.agrica_sentences += len(agrica_matches)
        if gga_matches:
            self.gga_sentences += len(gga_matches)
            last = gga_matches[-1].group(0).decode("ascii", errors="ignore")
            fields = last.split(",")
            try:
                self.last_gga_quality = int(fields[6])
                self.last_gga_satellites = int(fields[7])
            except (IndexError, TypeError, ValueError):
                pass

        consumed = max(
            [match.end() for match in (*agrica_matches, *gga_matches)] or [0]
        )
        if consumed:
            del self.text_buffer[:consumed]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args()

    stats = {topic: TopicStats() for topic in TOPICS}
    connected = threading.Event()
    connect_error: list[str] = []

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        reason_value = getattr(reason_code, "value", reason_code)
        if reason_value != 0:
            connect_error.append(str(reason_code))
            connected.set()
            return
        for topic in TOPICS:
            client.subscribe(topic, qos=0)
        connected.set()

    def on_message(_client, _userdata, message):
        topic_stats = stats.get(message.topic)
        if topic_stats is not None:
            topic_stats.feed(bytes(message.payload))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"landslide-live-probe-{int(time.time())}",
    )
    client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 30)
    client.loop_start()
    try:
        if not connected.wait(timeout=10):
            print("ERROR: MQTT connection timed out")
            return 2
        if connect_error:
            print(f"ERROR: MQTT connection rejected: {connect_error[-1]}")
            return 2
        print(
            f"Capturing {len(TOPICS)} raw GNSS topics for {args.duration:.1f}s "
            f"from {settings.MQTT_BROKER}:{settings.MQTT_PORT} ...",
            flush=True,
        )
        deadline = time.monotonic() + max(0.1, args.duration)
        while time.monotonic() < deadline:
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    finally:
        client.disconnect()
        client.loop_stop()

    print("\nRAW MQTT SUMMARY")
    for topic, station in TOPICS.items():
        item = stats[topic]
        lengths = item.payload_lengths
        length_text = (
            f"{min(lengths)}/{sum(lengths) / len(lengths):.1f}/{max(lengths)}"
            if lengths
            else "-/-/-"
        )
        diagnostics = item.rtcm_filter.diagnostics()
        print(
            f"{station} {topic}: messages={item.messages}, bytes={item.payload_bytes}, "
            f"payload_len[min/avg/max]={length_text}, AGRICA={item.agrica_sentences}, "
            f"GGA={item.gga_sentences}, last_gga_quality={item.last_gga_quality}, "
            f"satellites={item.last_gga_satellites}, command_responses={item.command_responses}, "
            f"D3_bytes={item.d3_bytes}, valid_RTCM_frames={item.valid_rtcm_frames}, "
            f"valid_RTCM_bytes={item.valid_rtcm_bytes}, crc_failures={diagnostics['crc_failures']}"
        )
        print(f"  first48={item.first_hex or '-'}")
        print(f"  last48 ={item.last_hex or '-'}")

    return 0 if all(item.messages for item in stats.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
