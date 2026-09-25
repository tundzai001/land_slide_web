"""Realtime fan-out with legacy compatibility and protocol-v2 subscriptions."""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    SEND_TIMEOUT_SECONDS = 2.0
    PROTOCOL_VERSION = 2
    MAX_SUBSCRIPTION_IDS = 1000
    CHANNEL_BY_MESSAGE_TYPE = {
        "sensor_data": "sensor",
        "sensor_status": "sensor",
        "station_status": "status",
        "alert": "alerts",
        "rescue_request": "rescue",
        "rescue_request_updated": "rescue",
        "rescue_request_deleted": "rescue",
        "gnss_adjustment_progress": "adjustment",
        "gnss_adjustment_step": "adjustment",
        "origin_locked_event": "adjustment",
        "gnss_offset_calibration_progress": "adjustment",
        "gnss_origin_relock_progress": "adjustment",
        "incident_changed": "incident",
    }
    RELIABLE_MESSAGE_TYPES = {
        "alert",
        "incident_changed",
        "rescue_request",
        "rescue_request_updated",
        "rescue_request_deleted",
        "origin_locked_event",
        "gnss_adjustment_result",
        "gnss_adjustment_failed",
    }

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._send_locks: Dict[int, asyncio.Lock] = {}
        self._outboxes: Dict[int, asyncio.Queue] = {}
        self._sender_tasks: Dict[int, asyncio.Task] = {}
        self._outbox_drops = 0
        self._slow_client_closes = 0
        # Connections stay legacy-compatible until they send a v2 subscription.
        self._subscriptions: Dict[int, dict] = {}
        self.last_broadcast_time = defaultdict(float)
        self.last_station_risk_level = {}
        self.throttle_intervals = {
            "sensor_data": 0.1,
            "station_status": 0.5,
            "alert": 0.0,
        }

    @staticmethod
    def _risk_severity(raw_level: str) -> int:
        severity_map = {
            "LOW": 0,
            "INFO": 0,
            "MEDIUM": 1,
            "WARNING": 1,
            "HIGH": 2,
            "CRITICAL": 3,
            "EXTREME": 3,
            "OFFLINE": -1,
        }
        return severity_map.get(str(raw_level or "").upper(), 0)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)
        self._send_locks.setdefault(id(websocket), asyncio.Lock())
        self._outboxes[id(websocket)] = asyncio.Queue(maxsize=64)
        self._sender_tasks[id(websocket)] = asyncio.create_task(
            self._sender_loop(websocket), name=f"ws-sender-{id(websocket)}"
        )
        operations_socket = websocket.url.path == "/ws/operations"
        self._subscriptions[id(websocket)] = {
            "legacy": not operations_socket,
            "station_ids": set(),
            "project_ids": set(getattr(websocket.state, "user_project_ids", []) or []),
            "channels": {"incident"} if operations_socket else set(),
        }
        logger.info("WebSocket connected. Total: %s", len(self.active_connections))
        await self.send_personal(
            websocket,
            {
                "type": "hello",
                "protocol_version": self.PROTOCOL_VERSION,
                "heartbeat_interval_seconds": 20,
                "subscriptions_supported": True,
                "authz_scope_hash": getattr(websocket.state, "authz_scope_hash", None),
                "channel": getattr(websocket.state, "ws_channel", "legacy"),
            },
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            connection_id = id(websocket)
            self._send_locks.pop(connection_id, None)
            self._outboxes.pop(connection_id, None)
            sender = self._sender_tasks.pop(connection_id, None)
            if sender and sender is not asyncio.current_task():
                sender.cancel()
            self._subscriptions.pop(connection_id, None)
            logger.info("WebSocket disconnected. Total: %s", len(self.active_connections))

    @staticmethod
    def _normalize_ids(raw_ids) -> set[int]:
        normalized = set()
        for raw_id in raw_ids or ():
            try:
                normalized.add(int(raw_id))
            except (TypeError, ValueError):
                continue
        return normalized

    async def handle_client_message(self, websocket: WebSocket, raw_message: str) -> bool:
        """Apply a protocol-v2 subscribe/unsubscribe message."""
        try:
            payload = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False

        action = str(payload.get("type") or "").lower()
        if action not in {"subscribe", "unsubscribe"}:
            return False

        station_ids = self._normalize_ids(payload.get("station_ids"))
        project_ids = self._normalize_ids(payload.get("project_ids"))
        if len(station_ids) + len(project_ids) > self.MAX_SUBSCRIPTION_IDS:
            await self.send_personal(
                websocket,
                {
                    "type": "subscription_error",
                    "detail": (
                        f"At most {self.MAX_SUBSCRIPTION_IDS} station/project IDs "
                        "are allowed"
                    ),
                },
            )
            return True

        allowed_channels = set(self.CHANNEL_BY_MESSAGE_TYPE.values())
        channels = {
            str(channel).strip().lower()
            for channel in (payload.get("channels") or ())
            if str(channel).strip().lower() in allowed_channels
        }
        subscription = self._subscriptions.setdefault(
            id(websocket),
            {
                "legacy": True,
                "station_ids": set(),
                "project_ids": set(),
                "channels": set(),
            },
        )
        subscription["legacy"] = False
        if action == "subscribe":
            subscription["station_ids"] = station_ids
            subscription["project_ids"] = project_ids
            subscription["channels"] = channels
        else:
            subscription["station_ids"].difference_update(station_ids)
            subscription["project_ids"].difference_update(project_ids)
            subscription["channels"].difference_update(channels)

        await self.send_personal(
            websocket,
            {
                "type": "subscription_ack",
                "station_ids": sorted(subscription["station_ids"]),
                "project_ids": sorted(subscription["project_ids"]),
                "channels": sorted(subscription["channels"]),
            },
        )
        return True

    def _should_send(self, connection: WebSocket, message: dict) -> bool:
        subscription: Optional[dict] = self._subscriptions.get(id(connection))
        if not subscription or subscription.get("legacy", True):
            return True

        message_type = str(message.get("type") or "")
        channel = self.CHANNEL_BY_MESSAGE_TYPE.get(message_type, message_type)
        channels = subscription.get("channels") or set()
        if channels and channel not in channels:
            return False

        # Sensor data is the highest-volume stream and is station-scoped.
        if channel == "sensor":
            station_ids = subscription.get("station_ids") or set()
            project_ids = subscription.get("project_ids") or set()
            message_station_id = message.get("station_id")
            if not station_ids and not project_ids:
                return False
            if station_ids:
                try:
                    if int(message_station_id) not in station_ids:
                        return False
                except (TypeError, ValueError):
                    return False

        project_ids = subscription.get("project_ids") or set()
        message_project_id = message.get("project_id")
        if project_ids:
            try:
                if int(message_project_id) not in project_ids:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    async def broadcast(self, message: dict):
        message_type = message.get("type")
        if message_type == "alert" or message.get("level") in {"WARNING", "CRITICAL"}:
            await self._send_to_all(message)
            return

        if message_type == "station_status":
            station_id = message.get("station_id")
            key = f"status_{station_id}"
            current_level = str(
                message.get("risk_level") or message.get("level") or ""
            ).upper()
            previous_level = self.last_station_risk_level.get(station_id, "")
            is_escalation = self._risk_severity(current_level) > self._risk_severity(
                previous_level
            )
            current_time = time.time()
            if (
                not is_escalation
                and current_time - self.last_broadcast_time[key]
                < self.throttle_intervals["station_status"]
            ):
                return
            self.last_broadcast_time[key] = current_time
            self.last_station_risk_level[station_id] = current_level
            await self._send_to_all(message)
            return

        if message_type == "sensor_data":
            key = f"{message.get('station_id')}_{message.get('sensor_type')}"
            current_time = time.time()
            if (
                current_time - self.last_broadcast_time[key]
                < self.throttle_intervals["sensor_data"]
            ):
                return
            self.last_broadcast_time[key] = current_time

        await self._send_to_all(message)

    async def broadcast_admins(self, message: dict):
        """Send sensitive operational events only to authenticated admins."""
        connections = tuple(
            connection
            for connection in self.active_connections
            if connection.url.path == "/ws/admin"
            and getattr(connection.state, "user_role", None) == "admin"
            and self._should_send(connection, message)
        )
        if not connections:
            return
        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections),
            return_exceptions=True,
        )

    async def broadcast_operations(self, message: dict):
        """Send non-PII Incident envelopes to scoped operations sockets.

        The public ``/ws/updates`` stream deliberately never receives Incident
        cases or Rescue metadata.  Project filtering is delegated to the same
        subscription gate used by sensor streams.
        """
        def in_operations_scope(connection: WebSocket) -> bool:
            role = getattr(connection.state, "user_role", None)
            if role == "admin":
                return True
            project_id = message.get("project_id")
            if project_id is None:
                return False
            subscription = self._subscriptions.get(id(connection)) or {}
            project_ids = subscription.get("project_ids") or set(getattr(connection.state, "user_project_ids", []) or [])
            try:
                return int(project_id) in {int(value) for value in project_ids}
            except (TypeError, ValueError):
                return False

        connections = tuple(
            connection
            for connection in self.active_connections
            if connection.url.path == "/ws/operations"
            and getattr(connection.state, "user_role", None) in {"admin", "operator", "viewer"}
            and in_operations_scope(connection)
            and self._should_send(connection, message)
        )
        if not connections:
            return
        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections),
            return_exceptions=True,
        )

    async def send_personal(self, websocket: WebSocket, message: dict):
        await self._send_one(websocket, message)

    async def _send_one(self, connection: WebSocket, message: dict):
        if connection not in self.active_connections:
            return
        outbox = self._outboxes.get(id(connection))
        if outbox is not None:
            reliable = str(message.get("type") or "") in self.RELIABLE_MESSAGE_TYPES or bool(message.get("reliable"))
            if outbox.full():
                if reliable:
                    self._slow_client_closes += 1
                    try:
                        await connection.close(code=1013, reason="client too slow")
                    except Exception:
                        pass
                    self.disconnect(connection)
                    return
                # Best-effort sensor/status updates coalesce by station/type.
                key = (
                    str(message.get("type") or ""),
                    str(message.get("station_id") or ""),
                    str(message.get("sensor_type") or ""),
                )
                queue_items = list(outbox._queue)  # bounded internal deque
                for index, queued in enumerate(queue_items):
                    queued_key = (
                        str(queued.get("type") or ""),
                        str(queued.get("station_id") or ""),
                        str(queued.get("sensor_type") or ""),
                    ) if isinstance(queued, dict) else None
                    if queued_key == key:
                        outbox._queue[index] = message
                        return
                self._outbox_drops += 1
                return
            outbox.put_nowait(message)
            return
        send_lock = self._send_locks.setdefault(id(connection), asyncio.Lock())
        async with send_lock:
            if connection not in self.active_connections:
                return
            try:
                await asyncio.wait_for(
                    connection.send_json(message), timeout=self.SEND_TIMEOUT_SECONDS
                )
            except Exception as exc:
                if connection in self.active_connections:
                    detail = str(exc).strip() or exc.__class__.__name__
                    logger.warning(
                        "WebSocket client removed after send failure: %s", detail
                    )
                    self.disconnect(connection)

    async def _sender_loop(self, connection: WebSocket) -> None:
        outbox = self._outboxes.get(id(connection))
        if outbox is None:
            return
        try:
            while connection in self.active_connections:
                message = await outbox.get()
                try:
                    await asyncio.wait_for(
                        connection.send_json(message), timeout=self.SEND_TIMEOUT_SECONDS
                    )
                finally:
                    outbox.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if connection in self.active_connections:
                logger.warning("WebSocket sender removed client after send failure: %s", exc)
                self.disconnect(connection)

    async def _send_to_all(self, message: dict):
        connections = tuple(
            connection
            for connection in self.active_connections
            if self._should_send(connection, message)
        )
        if not connections:
            return
        await asyncio.gather(
            *(self._send_one(connection, message) for connection in connections),
            return_exceptions=True,
        )

    def diagnostics(self) -> dict:
        queues = list(self._outboxes.values())
        return {
            "clients": len(self.active_connections),
            "outbox_capacity": 64,
            "outbox_backlog": sum(queue.qsize() for queue in queues),
            "outbox_drops": int(self._outbox_drops),
            "slow_client_closes": int(self._slow_client_closes),
        }


manager = ConnectionManager()
