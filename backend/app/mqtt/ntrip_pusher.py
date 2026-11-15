import asyncio
import logging
import re
import time
from typing import Dict

logger = logging.getLogger(__name__)


def _crc24q(data: bytes) -> int:
    """Return the RTCM3 CRC-24Q for *data*."""

    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


class Rtcm3FrameFilter:
    """Extract complete, CRC-valid RTCM3 frames from mixed MQTT chunks."""

    def __init__(self):
        self._buffer = bytearray()
        self.chunk_count = 0
        self.byte_count = 0
        self.preamble_count = 0
        self.invalid_header_count = 0
        self.crc_failure_count = 0
        self.valid_frame_count = 0
        self.valid_frame_bytes = 0

    def feed(self, data: bytes) -> bytes:
        if data:
            self.chunk_count += 1
            self.byte_count += len(data)
            self.preamble_count += data.count(b"\xd3")
            self._buffer.extend(data)

        frames = bytearray()
        while True:
            preamble_index = self._buffer.find(b"\xd3")
            if preamble_index < 0:
                self._buffer.clear()
                break
            if preamble_index:
                del self._buffer[:preamble_index]
            if len(self._buffer) < 3:
                break

            # RTCM3 reserves the upper six bits of the second header byte.
            if self._buffer[1] & 0xFC:
                self.invalid_header_count += 1
                del self._buffer[0]
                continue
            payload_length = ((self._buffer[1] & 0x03) << 8) | self._buffer[2]
            frame_length = 3 + payload_length + 3
            if len(self._buffer) < frame_length:
                break

            frame = bytes(self._buffer[:frame_length])
            expected_crc = int.from_bytes(frame[-3:], "big")
            if _crc24q(frame[:-3]) != expected_crc:
                self.crc_failure_count += 1
                del self._buffer[0]
                continue
            self.valid_frame_count += 1
            self.valid_frame_bytes += len(frame)
            frames.extend(frame)
            del self._buffer[:frame_length]

        return bytes(frames)

    def diagnostics(self) -> dict:
        return {
            "mqtt_chunks": self.chunk_count,
            "mqtt_bytes": self.byte_count,
            "d3_preambles": self.preamble_count,
            "invalid_headers": self.invalid_header_count,
            "crc_failures": self.crc_failure_count,
            "valid_frames": self.valid_frame_count,
            "valid_frame_bytes": self.valid_frame_bytes,
            "partial_buffer_bytes": len(self._buffer),
        }

class NtripPusher:
    def __init__(self, station_code: str, host: str, port: int, mountpoint: str, password: str):
        self.station_code = station_code
        self.host = host
        self.port = port
        self.mountpoint = mountpoint
        self.password = password
        
        self.queue = asyncio.Queue(maxsize=100)
        self.task: asyncio.Task | None = None
        self.is_running = False
        self._ready = asyncio.Event()
        self._startup_error: Exception | None = None
        self._rtcm_filter = Rtcm3FrameFilter()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._first_rtcm_sent = asyncio.Event()
        self._created_at = time.monotonic()
        self._last_chunk_at: float | None = None
        self._first_chunk_hex: str | None = None
        self._last_chunk_hex: str | None = None
        self._queued_frame_batches = 0
        self._sent_frame_batches = 0
        self._sent_bytes = 0
        self._caster_response = None
        self._last_gga_fix_quality: int | None = None
        self._last_gga_satellites: int | None = None
        self._last_gga_preview: str | None = None

    def observe_gnss_chunk(self, data: bytes) -> None:
        """Capture actionable receiver health from mixed GNSS MQTT payloads."""

        text = bytes(data).decode("ascii", errors="ignore")
        matches = re.findall(r"\$(?:GN|GP|GA|GB)GGA,[^\r\n*]*", text, flags=re.IGNORECASE)
        if not matches:
            return
        sentence = matches[-1]
        fields = sentence.split(",")
        if len(fields) < 8:
            return
        try:
            self._last_gga_fix_quality = int(fields[6]) if fields[6] else None
        except ValueError:
            self._last_gga_fix_quality = None
        try:
            self._last_gga_satellites = int(fields[7]) if fields[7] else None
        except ValueError:
            self._last_gga_satellites = None
        self._last_gga_preview = sentence[:160]

    async def _push_loop(self):
        reader = None
        writer = None
        try:
            logger.info(f"[NTRIP Pusher] {self.station_code}: Connecting to {self.host}:{self.port} for mountpoint {self.mountpoint}")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10.0
            )

            # Send NTRIP SOURCE request
            # NTRIP version 1 or 2 server/source connection
            request = (
                f"SOURCE {self.password} /{self.mountpoint}\r\n"
                f"Source-Agent: NTRIP NtripServerCMD/1.0\r\n"
                f"\r\n"
            )
            
            writer.write(request.encode('ascii'))
            await writer.drain()
            
            # Read response
            response = await asyncio.wait_for(reader.read(1024), timeout=10.0)
            resp_text = response.decode('utf-8', errors='ignore').strip()
            
            first_line = resp_text.splitlines()[0] if resp_text else ""
            self._caster_response = first_line or "<empty response>"
            accepted = (
                "ICY 200" in first_line
                or first_line.startswith("HTTP/1.0 200")
                or first_line.startswith("HTTP/1.1 200")
                or first_line == "OK"
            )
            if not accepted:
                if first_line.startswith("SOURCETABLE 200"):
                    raise ConnectionError(
                        "Caster returned SOURCETABLE instead of accepting SOURCE "
                        f"/{self.mountpoint}; verify the configured mountpoint, source password, and upload protocol"
                    )
                response_preview = " ".join(resp_text.split())[:500] or "<empty response>"
                raise ConnectionError(
                    f"Caster rejected SOURCE /{self.mountpoint}: {response_preview}"
                )
            
            logger.info(f"[NTRIP Pusher] {self.station_code}: Successfully connected to caster. Starting push...")
            self._ready.set()

            # Forward data from queue
            while self.is_running:
                data = await self.queue.get()
                writer.write(data)
                await writer.drain()
                self._sent_frame_batches += 1
                self._sent_bytes += len(data)
                self._first_rtcm_sent.set()

        except asyncio.CancelledError:
            logger.info(f"[NTRIP Pusher] {self.station_code}: Task cancelled.")
            raise
        except Exception as e:
            self._startup_error = e
            self._ready.set()
            logger.error(f"[NTRIP Pusher] {self.station_code}: Error in push loop: {e}")
        finally:
            self.is_running = False
            self._ready.set()
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
            logger.info(f"[NTRIP Pusher] {self.station_code}: Connection closed.")

    async def start(self, timeout: float = 12.0):
        if self.is_running:
            return
        self._loop = asyncio.get_running_loop()
        self.is_running = True
        self.task = asyncio.create_task(self._push_loop())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self.stop()
            raise TimeoutError(
                f"NTRIP SOURCE handshake timed out for {self.host}:{self.port}/{self.mountpoint}"
            ) from exc
        if self._startup_error is not None:
            error = self._startup_error
            await self.stop()
            raise error
        if not self.is_running:
            await self.stop()
            raise ConnectionError("NTRIP SOURCE connection closed during startup")

    async def wait_for_rtcm(self, timeout: float = 10.0) -> None:
        try:
            await asyncio.wait_for(self._first_rtcm_sent.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            diagnostics = self.diagnostics()
            raise TimeoutError(
                f"No valid RTCM3 frame was forwarded for station {self.station_code} "
                f"within {timeout:g}s; diagnostics={diagnostics}"
            ) from exc

    def diagnostics(self) -> dict:
        result = self._rtcm_filter.diagnostics()
        result.update({
            "station": self.station_code,
            "source_target": f"{self.host}:{self.port}/{self.mountpoint}",
            "caster_response": self._caster_response,
            "pusher_running": self.is_running,
            "queue_size": self.queue.qsize(),
            "queued_frame_batches": self._queued_frame_batches,
            "sent_frame_batches": self._sent_frame_batches,
            "sent_bytes": self._sent_bytes,
            "last_gga_fix_quality": self._last_gga_fix_quality,
            "last_gga_satellites": self._last_gga_satellites,
            "last_gga_preview": self._last_gga_preview,
            "first_chunk_hex": self._first_chunk_hex,
            "last_chunk_hex": self._last_chunk_hex,
            "last_chunk_age_s": (
                round(time.monotonic() - self._last_chunk_at, 3)
                if self._last_chunk_at is not None
                else None
            ),
            "elapsed_s": round(time.monotonic() - self._created_at, 3),
        })
        if result["sent_bytes"] > 0:
            result["likely_cause"] = "RTCM fanout was written to the caster"
        elif result["mqtt_chunks"] == 0:
            result["likely_cause"] = "no MQTT payload reached the pusher for this station"
        elif result["d3_preambles"] == 0 and result["last_gga_fix_quality"] == 0:
            satellite_detail = (
                f", satellites={result['last_gga_satellites']}"
                if result["last_gga_satellites"] is not None
                else ""
            )
            result["likely_cause"] = (
                "receiver emitted GGA with no GNSS fix (quality=0"
                f"{satellite_detail}) and no RTCM3; verify antenna/satellite "
                "visibility plus the station COM2-to-MQTT binary mapping"
            )
        elif result["d3_preambles"] == 0:
            result["likely_cause"] = "MQTT payloads arrived but contained no RTCM3 0xD3 preamble"
        elif result["valid_frames"] == 0 and result["crc_failures"]:
            result["likely_cause"] = "RTCM-like data arrived but failed CRC-24Q validation"
        elif result["valid_frames"] == 0 and result["partial_buffer_bytes"]:
            result["likely_cause"] = "only an incomplete RTCM3 frame arrived before timeout"
        else:
            result["likely_cause"] = "valid RTCM was queued but not confirmed written to the caster"
        return result

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            self.task = None


class NtripPusherManager:
    _instances: Dict[str, list[NtripPusher]] = {}

    @classmethod
    async def start_pusher(cls, station_code: str, host: str, port: int, mountpoint: str, password: str):
        # Stop existing if any
        if station_code in cls._instances:
            await cls.stop_pusher(station_code)
        
        pushers = []
        for mp in [m.strip() for m in str(mountpoint).split(",") if m.strip()]:
            pushers.append(NtripPusher(station_code, host, port, mp, password))
        
        cls._instances[station_code] = pushers
        try:
            await asyncio.gather(*(pusher.start() for pusher in pushers))
        except Exception:
            await asyncio.gather(
                *(pusher.stop() for pusher in pushers),
                return_exceptions=True,
            )
            cls._instances.pop(station_code, None)
            raise
        logger.info(f"[NTRIP Pusher] Started for station {station_code} to mountpoints: {[p.mountpoint for p in pushers]}")

    @classmethod
    async def stop_pusher(cls, station_code: str):
        if station_code in cls._instances:
            pushers = cls._instances[station_code]
            await asyncio.gather(*(pusher.stop() for pusher in pushers), return_exceptions=True)
            del cls._instances[station_code]
            logger.info(f"[NTRIP Pusher] Stopped for station {station_code}")

    @classmethod
    async def wait_for_rtcm(cls, station_code: str, timeout: float = 10.0) -> None:
        pushers = cls._instances.get(station_code)
        if not pushers:
            raise RuntimeError(f"NTRIP pusher is not running for station {station_code}")
        await asyncio.gather(*(pusher.wait_for_rtcm(timeout=timeout) for pusher in pushers))

    @classmethod
    def feed_data(cls, station_code: str, data: bytes):
        if station_code in cls._instances:
            pushers = cls._instances[station_code]
            # Since all pushers for a station process the exact same RTCM, we only need to filter once.
            if pushers and pushers[0].is_running:
                try:
                    sample_hex = bytes(data[:24]).hex()
                    rtcm_data = None
                    for pusher in pushers:
                        if pusher.is_running:
                            pusher._last_chunk_at = time.monotonic()
                            if pusher._first_chunk_hex is None:
                                pusher._first_chunk_hex = sample_hex
                            pusher._last_chunk_hex = sample_hex
                            pusher.observe_gnss_chunk(data)
                            if rtcm_data is None:
                                rtcm_data = pusher._rtcm_filter.feed(data)
                            
                            if rtcm_data and pusher._loop and pusher._loop.is_running():
                                def enqueue(p=pusher, rd=rtcm_data) -> None:
                                    try:
                                        p.queue.put_nowait(rd)
                                        p._queued_frame_batches += 1
                                    except asyncio.QueueFull:
                                        logger.warning(
                                            f"[NTRIP Pusher] {station_code}: Queue full for {p.mountpoint}, dropping data."
                                        )
                                pusher._loop.call_soon_threadsafe(enqueue)
                except Exception as exc:
                    logger.error(f"[NTRIP Pusher] {station_code}: Could not queue RTCM data: {exc}")

    @classmethod
    def get_diagnostics(cls, station_code: str) -> dict:
        pushers = cls._instances.get(station_code)
        if not pushers:
            return {"station": station_code, "likely_cause": "pusher instance is not running"}
        return {p.mountpoint: p.diagnostics() for p in pushers}

ntrip_manager = NtripPusherManager()
