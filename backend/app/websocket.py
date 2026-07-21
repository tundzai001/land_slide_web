# backend/app/websocket.py - FIXED VERSION
from fastapi import WebSocket
from typing import List, Dict
import json
import logging
import asyncio
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

class ConnectionManager:
    SEND_TIMEOUT_SECONDS = 2.0

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # MQTT pipelines broadcast concurrently. Serialize writes per browser;
        # Starlette rejects overlapping sends on the same WebSocket.
        self._send_locks: Dict[int, asyncio.Lock] = {}
        
        # GIẢM THROTTLE - Cho phép cập nhật nhanh hơn
        self.last_broadcast_time = defaultdict(float)
        self.last_station_risk_level = {}
        self.throttle_intervals = {
            'sensor_data': 0.1,      # 10 lần/giây (tăng từ 2 lần/giây)
            'station_status': 0.5,   # 2 lần/giây (tăng từ 1 lần/2s)
            'alert': 0.0             # Không throttle
        }
        
        #  GIẢM BUFFER TIME - Flush nhanh hơn
        self.message_buffer = defaultdict(dict)
        self.buffer_task = None

    def _risk_severity(self, raw_level: str) -> int:
        level = str(raw_level or '').upper()
        severity_map = {
            'LOW': 0,
            'INFO': 0,
            'MEDIUM': 1,
            'WARNING': 1,
            'HIGH': 2,
            'CRITICAL': 3,
            'EXTREME': 3,
            'OFFLINE': -1,
        }
        return severity_map.get(level, 0)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)
        self._send_locks.setdefault(id(websocket), asyncio.Lock())
        logger.info(f"✅ WebSocket connected. Total: {len(self.active_connections)}")
        
        if self.buffer_task is None or self.buffer_task.done():
            self.buffer_task = asyncio.create_task(self._flush_buffer_periodically())

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            self._send_locks.pop(id(websocket), None)
            logger.info(f"❌ WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        FIXED: Gửi realtime ngay lập tức cho sensor_data
        """
        msg_type = message.get('type')
        
        # ALERT → Gửi ngay
        if msg_type == 'alert' or message.get('level') in ['WARNING', 'CRITICAL']:
            await self._send_to_all(message)
            return
        
        if msg_type == 'station_status':
            station_id = message.get('station_id')
            key = f"status_{station_id}"
            current_level = str(message.get('risk_level') or message.get('level') or '').upper()
            prev_level = self.last_station_risk_level.get(station_id, '')
            is_escalation = self._risk_severity(current_level) > self._risk_severity(prev_level)
            
            current_time = time.time()
            if (
                not is_escalation
                and current_time - self.last_broadcast_time[key] < self.throttle_intervals['station_status']
            ):
                return
            
            self.last_broadcast_time[key] = current_time
            self.last_station_risk_level[station_id] = current_level
            await self._send_to_all(message)
            return

        if msg_type == 'sensor_data':
            station_id = message.get('station_id')
            sensor_type = message.get('sensor_type')
            key = f"{station_id}_{sensor_type}"
            
            current_time = time.time()
            
            # Chỉ throttle 0.1s (10 lần/giây)
            if current_time - self.last_broadcast_time[key] < self.throttle_intervals['sensor_data']:
                return
            
            self.last_broadcast_time[key] = current_time
            await self._send_to_all(message)
            return

        await self._send_to_all(message)
    
    async def _flush_buffer_periodically(self):
        while True:
            try:
                await asyncio.sleep(0.2) 
                
                if not self.message_buffer:
                    continue
                
                messages_to_send = list(self.message_buffer.values())
                self.message_buffer.clear()
                
                if messages_to_send:
                    await self._send_batch(messages_to_send)
                    
            except Exception as e:
                logger.error(f"❌ Error in buffer flush: {e}")

    async def _send_batch(self, messages: List[dict]):
        """Gửi nhiều message cùng lúc"""
        batch_payload = {
            'type': 'batch_update',
            'data': messages
        }
        await self._send_to_all(batch_payload)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send through the same per-client lock used by broadcasts."""
        await self._send_one(websocket, message)

    async def _send_one(self, connection: WebSocket, message: dict):
        if connection not in self.active_connections:
            return
        send_lock = self._send_locks.setdefault(
            id(connection), asyncio.Lock()
        )
        async with send_lock:
            # Another broadcast may have removed the client while this
            # coroutine waited. Never send again after close.
            if connection not in self.active_connections:
                return
            try:
                await asyncio.wait_for(
                    connection.send_json(message),
                    timeout=self.SEND_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                # Membership makes removal/logging idempotent across all
                # concurrent broadcast snapshots.
                if connection in self.active_connections:
                    detail = str(exc).strip() or exc.__class__.__name__
                    logger.warning(
                        "WebSocket client removed after send failure: %s",
                        detail,
                    )
                    self.disconnect(connection)

    async def _send_to_all(self, message: dict):
        """Fan out concurrently; one dead browser must never block server work."""
        connections = tuple(self.active_connections)
        if not connections:
            return

        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections),
            return_exceptions=True,
        )

# Khởi tạo instance global
manager = ConnectionManager()
