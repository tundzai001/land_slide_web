"""MQTT GNSS origin fetcher."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class GNSSLiveFetcher:
    def __init__(self, broker: str, port: int, username: str = "", password: str = "", use_tls: bool = False):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.received_data = None
        self.is_connected = False

    def _parse_gngga(self, gngga_string: str) -> Optional[dict]:
        try:
            parts = gngga_string.strip().split(',')
            if len(parts) < 12:
                return None

            lat_str, lon_str = parts[2], parts[4]
            lat_dir = parts[3].upper() if parts[3] else ''
            lon_dir = parts[5].upper() if parts[5] else ''
            if not lat_str or not lon_str:
                return None
            if lat_dir not in ('N', 'S') or lon_dir not in ('E', 'W'):
                return None

            # Persisted origins use ellipsoidal height. Missing geoid would
            # silently store MSL and shift the origin by tens of metres.
            if not parts[9] or not parts[11]:
                return None
            altitude_msl = float(parts[9])
            geoid_sep = float(parts[11])
            h = altitude_msl + geoid_sep

            lat_deg = int(lat_str[:2])
            lat_min = float(lat_str[2:])
            lon_deg = int(lon_str[:3])
            lon_min = float(lon_str[3:])
            if not (0.0 <= lat_min < 60.0 and 0.0 <= lon_min < 60.0):
                return None

            lat = float(lat_deg) + lat_min / 60.0
            if lat_dir == 'S':
                lat = -lat
            lon = float(lon_deg) + lon_min / 60.0
            if lon_dir == 'W':
                lon = -lon
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                return None

            fix_quality = int(parts[6]) if parts[6] else 0
            num_sats = int(parts[7]) if parts[7] else 0
            return {'lat': lat, 'lon': lon, 'h': h, 'fix_quality': fix_quality, 'num_sats': num_sats}
        except (ValueError, IndexError, TypeError):
            return None

    def _extract_gngga(self, payload_bytes: bytes) -> Optional[str]:
        if not payload_bytes:
            return None

        import re
        gga_regex = re.compile(rb'\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?')

        match = gga_regex.search(payload_bytes)
        if not match and b'\x00' in payload_bytes:
            # Some encoders interleave NULL bytes; remove them and retry.
            compact_bytes = payload_bytes.replace(b'\x00', b'')
            match = gga_regex.search(compact_bytes)

        if not match:
            return None

        return match.group(0).decode('ascii', errors='ignore').strip()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_connected = True
            logger.info(f"[GNSSLiveFetcher] Connected to broker, subscribing to {userdata['topic']}")
            client.subscribe(userdata['topic'])
        else:
            logger.error(f"[GNSSLiveFetcher] Connect failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = self._extract_gngga(msg.payload)
            if not payload:
                # Log full payload representation if it's binary or invalid
                raw_repr = msg.payload[:100].hex() if b'\x00' in msg.payload else msg.payload[:100].decode('utf-8', errors='ignore')
                logger.info(f"[GNSSLiveFetcher] No GGA found in payload on {msg.topic}. Raw start: {raw_repr}")
                return

            logger.info(f"[GNSSLiveFetcher] Received GNSS message on {msg.topic}: {payload}")
            parsed = self._parse_gngga(payload)
            if parsed and parsed['fix_quality'] >= 1:
                logger.info(f"[GNSSLiveFetcher] Valid GNSS parsed: {parsed}")
                self.received_data = parsed
                client.disconnect()
            else:
                logger.warning(f"[GNSSLiveFetcher] Parse failed or invalid fix_quality: {parsed}")
        except Exception as e:
            logger.error(f"[GNSSLiveFetcher] Exception processing message: {e}")

    async def fetch_origin(self, topic: str, timeout: int = 30) -> Optional[dict]:
        try:
            import paho.mqtt.client as mqtt

            self.received_data = None
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata={'topic': topic})
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            if self.username: client.username_pw_set(self.username, self.password)

            if self.use_tls:
                import ssl
                client.tls_set_context(ssl.create_default_context())

            client.connect(self.broker, self.port, 60)
            client.loop_start()

            start_time = asyncio.get_event_loop().time()
            while self.received_data is None:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    logger.warning("[GNSSLiveFetcher] Timeout reached waiting for GNSS data.")
                    client.loop_stop()
                    client.disconnect()
                    return None
                await asyncio.sleep(0.5)

            client.loop_stop()
            return self.received_data
        except Exception as e:
            logger.error(f"Error in fetch_origin: {e}")
            return None
