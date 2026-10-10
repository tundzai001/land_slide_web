"""WebSocket security regressions with real protocol handlers and isolated identity lookup."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import WebSocketDisconnect
from app import auth
from app.features.frontend import websocket as routes
from app.websocket import ConnectionManager


class Socket:
    def __init__(self, ticket, path="/ws/updates"):
        self.headers = {}
        self.query_params = {"ticket": ticket}
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace()
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.incoming = asyncio.Queue()
        self.messages = []
        self.close_code = None

    async def accept(self):
        self.accepted.set()

    async def send_json(self, message):
        self.messages.append(message)

    async def receive_text(self):
        message = await self.incoming.get()
        if isinstance(message, Exception):
            raise message
        return message

    async def close(self, code, reason):
        self.close_code = code
        self.closed.set()
        self.incoming.put_nowait(WebSocketDisconnect(code))


class WebSocketAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=1, username="operator", role="operator", is_active=True, assigned_projects=[7])
        self.manager = ConnectionManager()
        self.patches = [
            patch.object(routes, "ws_manager", self.manager),
            patch.object(routes, "AUTHORIZATION_REFRESH_SECONDS", 0.02),
            patch.object(routes, "_consume_ws_ticket", AsyncMock(return_value=True)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def ticket(self, **overrides):
        return auth.create_access_token({
            "sub": self.user.username, "purpose": "websocket", "channel": "updates",
            "session_id": "parent-session", "authz_scope_hash": routes._user_scope(self.user)[1],
            **overrides,
        })

    async def test_quiet_connection_is_revalidated_without_forced_disconnect(self):
        refreshed = asyncio.Event()
        calls = 0

        async def lookup(*args):
            nonlocal calls
            calls += 1
            if calls >= 2:
                refreshed.set()
            return self.user

        socket = Socket(self.ticket())
        with patch.object(routes, "_session_user", lookup):
            task = asyncio.create_task(routes.websocket_endpoint(socket))
            await asyncio.wait_for(refreshed.wait(), 1)
            self.assertFalse(socket.closed.is_set())
            socket.incoming.put_nowait(WebSocketDisconnect())
            await asyncio.wait_for(task, 1)
        self.assertEqual(self.manager.active_connections, [])
        self.assertEqual(self.manager._sender_tasks, {})

    async def test_quiet_revoked_session_closes_without_waiting_for_client_packet(self):
        socket = Socket(self.ticket())
        with patch.object(routes, "_session_user", AsyncMock(side_effect=[self.user, ValueError("Revoked")])):
            task = asyncio.create_task(routes.websocket_endpoint(socket))
            await asyncio.wait_for(socket.closed.wait(), 1)
            await asyncio.wait_for(task, 1)
        self.assertEqual(socket.close_code, 1008)
        self.assertEqual(self.manager.active_connections, [])

    async def test_busy_connection_cannot_postpone_session_revalidation(self):
        socket = Socket(self.ticket())

        async def continuous_ping():
            await asyncio.sleep(0)
            return "ping"

        socket.receive_text = continuous_ping
        with patch.object(routes, "_session_user", AsyncMock(side_effect=[self.user, ValueError("Revoked")])):
            task = asyncio.create_task(routes.websocket_endpoint(socket))
            await asyncio.wait_for(socket.closed.wait(), 1)
            await asyncio.wait_for(task, 1)
        self.assertEqual(socket.close_code, 1008)

    async def test_sender_revalidates_expired_authorization_before_queued_event(self):
        socket = Socket(self.ticket())
        with patch.object(routes, "_session_user", AsyncMock(return_value=self.user)):
            self.assertTrue(await routes._authorize_websocket(socket))
            await self.manager.connect(socket)
            await self.manager._outboxes[id(socket)].join()
        socket.messages.clear()
        socket.state.authorization_deadline = time.monotonic() - 1
        with patch.object(routes, "_session_user", AsyncMock(side_effect=ValueError("Revoked"))):
            await self.manager.broadcast({"type": "alert", "project_id": 7})
            await asyncio.wait_for(socket.closed.wait(), 1)
        self.assertEqual(socket.messages, [])
        self.assertEqual(socket.close_code, 1008)

    async def test_changed_project_assignment_invalidates_existing_socket(self):
        socket = Socket(self.ticket())
        changed_user = SimpleNamespace(**{**vars(self.user), "assigned_projects": [99]})
        with patch.object(routes, "_session_user", AsyncMock(side_effect=[self.user, changed_user])):
            self.assertTrue(await routes._authorize_websocket(socket))
            socket.state.authorization_deadline = 0
            self.assertFalse(await routes._refresh_authorization(socket))
        self.assertEqual(socket.close_code, 1008)

    async def test_legacy_admin_channel_still_requires_admin(self):
        socket = Socket(self.ticket(channel="legacy_admin"), path="/ws/admin")
        with patch.object(routes, "_session_user", AsyncMock(return_value=self.user)):
            self.assertFalse(await routes._authorize_websocket(socket))
        self.assertEqual(socket.close_code, 1008)

    async def test_ticket_without_expiry_is_rejected_before_identity_lookup(self):
        claims = auth.jwt.decode(self.ticket(), auth.settings.SECRET_KEY, algorithms=[auth.settings.ALGORITHM])
        del claims["exp"]
        socket = Socket(auth.jwt.encode(claims, auth.settings.SECRET_KEY, algorithm=auth.settings.ALGORITHM))
        with patch.object(routes, "_session_user", AsyncMock()) as lookup:
            self.assertFalse(await routes._authorize_websocket(socket))
            lookup.assert_not_awaited()
        self.assertEqual(socket.close_code, 1008)

    async def test_authorization_outage_closes_connection_fail_closed(self):
        socket = Socket(self.ticket())
        with patch.object(routes, "_session_user", AsyncMock(side_effect=[self.user, ConnectionError("database unavailable")])):
            self.assertTrue(await routes._authorize_websocket(socket))
            socket.state.authorization_deadline = 0
            self.assertFalse(await routes._refresh_authorization(socket))
        self.assertEqual(socket.close_code, 1013)


if __name__ == "__main__":
    unittest.main()
