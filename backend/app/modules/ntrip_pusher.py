import asyncio
import logging
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

    def feed(self, data: bytes) -> bytes:
        if data:
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
                del self._buffer[0]
                continue
            payload_length = ((self._buffer[1] & 0x03) << 8) | self._buffer[2]
            frame_length = 3 + payload_length + 3
            if len(self._buffer) < frame_length:
                break

            frame = bytes(self._buffer[:frame_length])
            expected_crc = int.from_bytes(frame[-3:], "big")
            if _crc24q(frame[:-3]) != expected_crc:
                del self._buffer[0]
                continue
            frames.extend(frame)
            del self._buffer[:frame_length]

        return bytes(frames)

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
                f"Source-Agent: NTRIP landslide_backend/1.0\r\n"
                f"\r\n"
            )
            
            writer.write(request.encode('ascii'))
            await writer.drain()
            
            # Read response
            response = await asyncio.wait_for(reader.read(1024), timeout=10.0)
            resp_text = response.decode('utf-8', errors='ignore').strip()
            
            first_line = resp_text.splitlines()[0] if resp_text else ""
            accepted = (
                "ICY 200" in first_line
                or first_line.startswith("HTTP/1.0 200")
                or first_line.startswith("HTTP/1.1 200")
                or first_line == "OK"
            )
            if not accepted:
                raise ConnectionError(f"Caster rejected SOURCE connection: {resp_text or '<empty response>'}")
            
            logger.info(f"[NTRIP Pusher] {self.station_code}: Successfully connected to caster. Starting push...")
            self._ready.set()

            # Forward data from queue
            while self.is_running:
                data = await self.queue.get()
                writer.write(data)
                await writer.drain()
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
                except:
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
            raise TimeoutError(
                f"No valid RTCM3 frame was forwarded for station {self.station_code} within {timeout:g}s"
            ) from exc

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None


class NtripPusherManager:
    _instances: Dict[str, NtripPusher] = {}

    @classmethod
    async def start_pusher(cls, station_code: str, host: str, port: int, mountpoint: str, password: str):
        # Stop existing if any
        if station_code in cls._instances:
            await cls._instances[station_code].stop()
        
        pusher = NtripPusher(station_code, host, port, mountpoint, password)
        cls._instances[station_code] = pusher
        try:
            await pusher.start()
        except Exception:
            cls._instances.pop(station_code, None)
            raise
        logger.info(f"[NTRIP Pusher] Started for station {station_code}")

    @classmethod
    async def stop_pusher(cls, station_code: str):
        if station_code in cls._instances:
            await cls._instances[station_code].stop()
            del cls._instances[station_code]
            logger.info(f"[NTRIP Pusher] Stopped for station {station_code}")

    @classmethod
    async def wait_for_rtcm(cls, station_code: str, timeout: float = 10.0) -> None:
        pusher = cls._instances.get(station_code)
        if not pusher:
            raise RuntimeError(f"NTRIP pusher is not running for station {station_code}")
        await pusher.wait_for_rtcm(timeout=timeout)

    @classmethod
    def feed_data(cls, station_code: str, data: bytes):
        if station_code in cls._instances:
            pusher = cls._instances[station_code]
            if pusher.is_running:
                try:
                    # GNSS MQTT payloads also contain GGA/AGRICA text.  An
                    # NTRIP source must forward only complete RTCM3 frames.
                    rtcm_data = pusher._rtcm_filter.feed(data)
                    if rtcm_data and pusher._loop and pusher._loop.is_running():
                        def enqueue() -> None:
                            try:
                                pusher.queue.put_nowait(rtcm_data)
                            except asyncio.QueueFull:
                                logger.warning(
                                    f"[NTRIP Pusher] {station_code}: Queue full, dropping data."
                                )

                        # Paho invokes feed_data from its network thread; an
                        # asyncio.Queue must only be touched by its event loop.
                        pusher._loop.call_soon_threadsafe(enqueue)
                except Exception as exc:
                    logger.error(f"[NTRIP Pusher] {station_code}: Could not queue RTCM data: {exc}")

ntrip_manager = NtripPusherManager()
