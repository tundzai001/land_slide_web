"""Read-only discovery of active GNSS device topics on an MQTT broker."""

from __future__ import annotations

import argparse
from collections import defaultdict
import re
import threading
import time

import paho.mqtt.client as mqtt

from backend.app.config import settings


AGRICA_RE = re.compile(rb"#AGRICA[^*\r\n]*\*[0-9A-Fa-f]{8}")
GGA_RE = re.compile(rb"\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="aitogy.click")
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args()

    connected = threading.Event()
    connection_error = []
    lock = threading.Lock()
    messages = defaultdict(int)
    byte_counts = defaultdict(int)
    agrica_counts = defaultdict(int)
    gga_counts = defaultdict(int)
    buffers = defaultdict(bytearray)

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        value = getattr(reason_code, "value", reason_code)
        if value != 0:
            connection_error.append(str(reason_code))
        else:
            client.subscribe("device/+/upload", qos=0)
        connected.set()

    def on_message(_client, _userdata, message):
        topic = str(message.topic)
        payload = bytes(message.payload)
        with lock:
            messages[topic] += 1
            byte_counts[topic] += len(payload)
            buffer = buffers[topic]
            buffer.extend(payload)
            if len(buffer) > 256_000:
                del buffer[:-128_000]
            raw = bytes(buffer)
            agrica = list(AGRICA_RE.finditer(raw))
            gga = list(GGA_RE.finditer(raw))
            agrica_counts[topic] += len(agrica)
            gga_counts[topic] += len(gga)
            consumed = max([item.end() for item in (*agrica, *gga)] or [0])
            if consumed:
                del buffer[:consumed]

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"landslide-gnss-discovery-{int(time.time())}",
    )
    client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(str(args.broker), int(settings.MQTT_PORT), 30)
    client.loop_start()
    try:
        if not connected.wait(timeout=10):
            raise RuntimeError("MQTT connection timed out")
        if connection_error:
            raise RuntimeError(f"MQTT connection rejected: {connection_error[-1]}")
        deadline = time.monotonic() + max(5.0, float(args.duration))
        while time.monotonic() < deadline:
            time.sleep(0.2)
    finally:
        client.disconnect()
        client.loop_stop()

    gnss_topics = sorted(
        topic for topic in messages
        if agrica_counts[topic] or gga_counts[topic]
    )
    print(
        f"GNSS discovery broker={args.broker}: "
        f"active_device_topics={len(messages)}, gnss_topics={len(gnss_topics)}"
    )
    for topic in gnss_topics:
        print(
            f"  {topic}: messages={messages[topic]}, bytes={byte_counts[topic]}, "
            f"AGRICA={agrica_counts[topic]}, GGA={gga_counts[topic]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
