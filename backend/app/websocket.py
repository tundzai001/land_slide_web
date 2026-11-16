"""Realtime fan-out with legacy compatibility and protocol-v2 subscriptions."""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

WS_OPERATIONS_PATH = "/ws/operations"

ADJUSTMENT_CHANNEL = "adjustment"
RESCUE_CHANNEL = "rescue"
SENSOR_CHANNEL = "sensor"
ALERT_CHANNEL = "alerts"
STATUS_CHANNEL = "status"
INCIDENT_CHANNEL = "incident"

TYPE_SENSOR_DATA = "sensor_data"
TYPE_STATION_STATUS = "station_status"
TYPE_ALERT = "alert"
TYPE_INCIDENT_CHANGED = "incident_changed"
TYPE_RESCUE_REQUEST = "rescue_request"

KEY_PROJECT_IDS = "project_ids"
KEY_STATION_IDS = "station_ids"
KEY_CHANNELS = "channels"
KEY_USER_ROLE = "user_role"
KEY_USER_PROJECT_IDS = "user_project_ids"
KEY_LEGACY = "legacy"
KEY_STATION_ID = "station_id"
KEY_PROJECT_ID = "project_id"
KEY_SENSOR_TYPE = "sensor_type"
KEY_DETAIL = "detail"
KEY_STATE = "state"
ROLE_ADMIN = "admin"
ERR_SUBSCRIPTION = "subscription_error"


class ConnectionManager:
    SEND_TIMEOUT_SECONDS = 2.0
    PROTOCOL_VERSION = 2
    MAX_SUBSCRIPTION_IDS = 1000
    CHANNEL_BY_MESSAGE_TYPE = {
        TYPE_SENSOR_DATA: SENSOR_CHANNEL,
        "sensor_status": SENSOR_CHANNEL,
        TYPE_STATION_STATUS: STATUS_CHANNEL,
        TYPE_ALERT: ALERT_CHANNEL,
        TYPE_RESCUE_REQUEST: RESCUE_CHANNEL,
        "rescue_request_updated": RESCUE_CHANNEL,
        "rescue_request_deleted": RESCUE_CHANNEL,
        "gnss_adjustment_progress": ADJUSTMENT_CHANNEL,
        "gnss_adjustment_step": ADJUSTMENT_CHANNEL,
        "origin_locked_event": ADJUSTMENT_CHANNEL,
        "gnss_offset_calibration_progress": ADJUSTMENT_CHANNEL,
        "gnss_origin_relock_progress": ADJUSTMENT_CHANNEL,
        TYPE_INCIDENT_CHANGED: INCIDENT_CHANNEL,
    }
    RELIABLE_MESSAGE_TYPES = {
        TYPE_ALERT,
        TYPE_INCIDENT_CHANGED,
        TYPE_RESCUE_REQUEST,
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
            TYPE_SENSOR_DATA: 0.1,
            TYPE_STATION_STATUS: 0.5,
            TYPE_ALERT: 0.0,
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
        operations_socket = websocket.url.path == WS_OPERATIONS_PATH
        self._subscriptions[id(websocket)] = {
            KEY_LEGACY: not operations_socket,
            KEY_STATION_IDS: set(),
            KEY_PROJECT_IDS: set(getattr(websocket.state, KEY_USER_PROJECT_IDS, []) or []),
            KEY_CHANNELS: {"incident"} if operations_socket else set(),
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
                "channel": getattr(websocket.state, "ws_channel", KEY_LEGACY),
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
        if raw_ids is None:
            return set()
        if not isinstance(raw_ids, list) or len(raw_ids) > ConnectionManager.MAX_SUBSCRIPTION_IDS:
            raise ValueError("Station and project IDs must be bounded lists")
        normalized = set()
        for raw_id in raw_ids:
            if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 1:
                raise ValueError("Station and project IDs must be positive integers")
            normalized.add(raw_id)
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

        try:
            station_ids = self._normalize_ids(payload.get(KEY_STATION_IDS))
            project_ids = self._normalize_ids(payload.get(KEY_PROJECT_IDS))
            raw_channels = payload.get(KEY_CHANNELS) or []
            if not isinstance(raw_channels, list) or len(raw_channels) > 32:
                raise ValueError("Channels must be a bounded list")
        except ValueError as exc:
            await self.send_personal(websocket, {"type": ERR_SUBSCRIPTION, KEY_DETAIL: str(exc)})
            return True
        state = getattr(websocket, KEY_STATE, None)
        if getattr(state, KEY_USER_ROLE, None) not in {None, ROLE_ADMIN} and not project_ids.issubset(
            set(getattr(state, KEY_USER_PROJECT_IDS, []) or [])
        ):
            await self.send_personal(websocket, {"type": ERR_SUBSCRIPTION, KEY_DETAIL: "Project access denied"})
            return True
        if len(station_ids) + len(project_ids) > self.MAX_SUBSCRIPTION_IDS:
            await self.send_personal(
                websocket,
                {
                    "type": ERR_SUBSCRIPTION,
                    KEY_DETAIL: (
                        f"At most {self.MAX_SUBSCRIPTION_IDS} station/project IDs "
                        "are allowed"
                    ),
                },
            )
            return True

        allowed_channels = set(self.CHANNEL_BY_MESSAGE_TYPE.values())
        channels = {
            str(channel).strip().lower()
            for channel in raw_channels
            if str(channel).strip().lower() in allowed_channels
        }
        subscription = self._subscriptions.setdefault(
            id(websocket),
            {
                KEY_LEGACY: True,
                KEY_STATION_IDS: set(),
                KEY_PROJECT_IDS: set(),
                KEY_CHANNELS: set(),
            },
        )
        subscription[KEY_LEGACY] = False
        if action == "subscribe":
            subscription[KEY_STATION_IDS] = station_ids
            subscription[KEY_PROJECT_IDS] = project_ids
            subscription[KEY_CHANNELS] = channels
        else:
            subscription[KEY_STATION_IDS].difference_update(station_ids)
            subscription[KEY_PROJECT_IDS].difference_update(project_ids)
            subscription[KEY_CHANNELS].difference_update(channels)

        await self.send_personal(
            websocket,
            {
                "type": "subscription_ack",
                KEY_STATION_IDS: sorted(subscription[KEY_STATION_IDS]),
                KEY_PROJECT_IDS: sorted(subscription[KEY_PROJECT_IDS]),
                KEY_CHANNELS: sorted(subscription[KEY_CHANNELS]),
            },
        )
        return True

    def _should_send(self, connection: WebSocket, message: dict) -> bool:
        state = getattr(connection, KEY_STATE, None)
        if getattr(state, "authorization_failed", False):
            return False
        path = getattr(getattr(connection, "url", None), "path", None)
        message_type = str(message.get("type") or "")
        if path == WS_OPERATIONS_PATH and message_type != TYPE_INCIDENT_CHANGED:
            return False
        if path == "/ws/updates" and (
            message_type == TYPE_INCIDENT_CHANGED or message_type.startswith("rescue_request")
        ):
            return False
        role = getattr(state, KEY_USER_ROLE, None)
        if role is not None and role != ROLE_ADMIN:
            allowed = set(getattr(state, KEY_USER_PROJECT_IDS, []) or [])
            try:
                if int(message.get(KEY_PROJECT_ID)) not in allowed:
                    return False
            except (TypeError, ValueError):
                return False
        subscription: Optional[dict] = self._subscriptions.get(id(connection))
        if not subscription or subscription.get(KEY_LEGACY, True):
            return True

        channel = self.CHANNEL_BY_MESSAGE_TYPE.get(message_type, message_type)
        channels = subscription.get(KEY_CHANNELS) or set()
        if channels and channel not in channels:
            return False

        # Sensor data is the highest-volume stream and is station-scoped.
        if channel == "sensor":
            station_ids = subscription.get(KEY_STATION_IDS) or set()
            project_ids = subscription.get(KEY_PROJECT_IDS) or set()
            message_station_id = message.get(KEY_STATION_ID)
            if not station_ids and not project_ids:
                return False
            if station_ids:
                try:
                    if int(message_station_id) not in station_ids:
                        return False
                except (TypeError, ValueError):
                    return False

        project_ids = subscription.get(KEY_PROJECT_IDS) or set()
        message_project_id = message.get(KEY_PROJECT_ID)
        if project_ids:
            try:
                if int(message_project_id) not in project_ids:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    async def broadcast(self, message: dict):
        message_type = message.get("type")
        if message_type == TYPE_ALERT or message.get("level") in {"WARNING", "CRITICAL"}:
            await self._send_to_all(message)
            return

        if message_type == TYPE_STATION_STATUS:
            station_id = message.get(KEY_STATION_ID)
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
                < self.throttle_intervals[TYPE_STATION_STATUS]
            ):
                return
            self.last_broadcast_time[key] = current_time
            self.last_station_risk_level[station_id] = current_level
            await self._send_to_all(message)
            return

        if message_type == TYPE_SENSOR_DATA:
            key = f"{message.get('station_id')}_{message.get('sensor_type')}"
            current_time = time.time()
            if (
                current_time - self.last_broadcast_time[key]
                < self.throttle_intervals[TYPE_SENSOR_DATA]
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
            and getattr(connection.state, KEY_USER_ROLE, None) == ROLE_ADMIN
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

        The telemetry ``/ws/updates`` stream deliberately never receives Incident
        cases or Rescue metadata.  Project filtering is delegated to the same
        subscription gate used by sensor streams.
        """
        def in_operations_scope(connection: WebSocket) -> bool:
            state = getattr(connection, KEY_STATE, None)
            role = getattr(state, KEY_USER_ROLE, None)
            if role == ROLE_ADMIN:
                return True
            project_id = message.get(KEY_PROJECT_ID)
            if project_id is None:
                return False
            project_ids = set(getattr(state, KEY_USER_PROJECT_IDS, []) or [])
            try:
                return int(project_id) in {int(value) for value in project_ids}
            except (TypeError, ValueError):
                return False

        connections = tuple(
            connection
            for connection in self.active_connections
            if connection.url.path == WS_OPERATIONS_PATH
            and getattr(connection.state, KEY_USER_ROLE, None) in {ROLE_ADMIN, "operator", "viewer"}
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

    async def close_session(self, session_id: str):
        """Immediately close a revoked session on this worker; other workers revalidate."""
        for connection in tuple(self.active_connections):
            if getattr(connection.state, "session_id", None) == session_id:
                connection.state.authorization_failed = True
                self.disconnect(connection)
                try:
                    await connection.close(code=1008, reason="Session revoked")
                except Exception:
                    pass

    async def _delivery_authorized(self, connection: WebSocket, message: dict) -> bool:
        validator = getattr(getattr(connection, KEY_STATE, None), "ensure_authorized", None)
        if validator and not await validator():
            return False
        # Recheck queued envelopes after authorization and subscription changes.
        return message.get("type") in {"hello", "pong", "subscription_ack", ERR_SUBSCRIPTION} or self._should_send(connection, message)

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
                    str(message.get(KEY_STATION_ID) or ""),
                    str(message.get(KEY_SENSOR_TYPE) or ""),
                )
                queue_items = list(outbox._queue)  # bounded internal deque
                for index, queued in enumerate(queue_items):
                    queued_key = (
                        str(queued.get("type") or ""),
                        str(queued.get(KEY_STATION_ID) or ""),
                        str(queued.get(KEY_SENSOR_TYPE) or ""),
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
                if not await self._delivery_authorized(connection, message):
                    return
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
                    if not await self._delivery_authorized(connection, message):
                        continue
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
