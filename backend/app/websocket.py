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
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        
        # GIẢM THROTTLE - Cho phép cập nhật nhanh hơn
        self.last_broadcast_time = defaultdict(float)
        self.throttle_intervals = {
            'sensor_data': 0.1,      # 10 lần/giây (tăng từ 2 lần/giây)
            'station_status': 0.5,   # 2 lần/giây (tăng từ 1 lần/2s)
            'alert': 0.0             # Không throttle
        }
        
        #  GIẢM BUFFER TIME - Flush nhanh hơn
        self.message_buffer = defaultdict(dict)
        self.buffer_task = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✅ WebSocket connected. Total: {len(self.active_connections)}")
        
        if self.buffer_task is None or self.buffer_task.done():
            self.buffer_task = asyncio.create_task(self._flush_buffer_periodically())

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
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
            
            current_time = time.time()
            if current_time - self.last_broadcast_time[key] < self.throttle_intervals['station_status']:
                return
            
            self.last_broadcast_time[key] = current_time
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

    async def _send_to_all(self, message: dict):
        """Gửi message tới tất cả client"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"❌ WS send error: {e}")
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

# Khởi tạo instance global
manager = ConnectionManager()