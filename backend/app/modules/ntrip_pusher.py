import asyncio
import logging
from typing import Dict
import base64

logger = logging.getLogger(__name__)

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
            auth_str = f"{self.password}"
            auth_b64 = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
            
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
            
            if "OK" not in resp_text and "ICY 200" not in resp_text:
                logger.error(f"[NTRIP Pusher] {self.station_code}: Caster rejected connection. Response: {resp_text}")
                return
            
            logger.info(f"[NTRIP Pusher] {self.station_code}: Successfully connected to caster. Starting push...")

            # Forward data from queue
            while self.is_running:
                data = await self.queue.get()
                writer.write(data)
                await writer.drain()

        except asyncio.CancelledError:
            logger.info(f"[NTRIP Pusher] {self.station_code}: Task cancelled.")
        except Exception as e:
            logger.error(f"[NTRIP Pusher] {self.station_code}: Error in push loop: {e}")
        finally:
            self.is_running = False
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except:
                    pass
            logger.info(f"[NTRIP Pusher] {self.station_code}: Connection closed.")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.task = asyncio.create_task(self._push_loop())

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
        pusher.start()
        logger.info(f"[NTRIP Pusher] Started for station {station_code}")

    @classmethod
    async def stop_pusher(cls, station_code: str):
        if station_code in cls._instances:
            await cls._instances[station_code].stop()
            del cls._instances[station_code]
            logger.info(f"[NTRIP Pusher] Stopped for station {station_code}")

    @classmethod
    def feed_data(cls, station_code: str, data: bytes):
        if station_code in cls._instances:
            pusher = cls._instances[station_code]
            if pusher.is_running:
                try:
                    pusher.queue.put_nowait(data)
                except asyncio.QueueFull:
                    logger.warning(f"[NTRIP Pusher] {station_code}: Queue full, dropping data.")

ntrip_manager = NtripPusherManager()
