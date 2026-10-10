import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import BaseData
from app.features.authentication import sessions
from app.features.operations import store
from app.websocket import ConnectionManager


class SessionSecurityTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseData.metadata.create_all(engine)
        self.previous_engine = store.configure_engine(engine)
        self.engine = engine
        self.user = SimpleNamespace(id=7, username="reviewer", hashed_password="hash-v1", is_active=True)

    def tearDown(self):
        store.configure_engine(self.previous_engine)
        self.engine.dispose()

    def test_logout_and_password_change_invalidate_session(self):
        sessions.create("session-review", self.user, 4_000_000_000)
        self.assertTrue(sessions.valid("session-review", self.user))
        self.user.hashed_password = "hash-v2"
        self.assertFalse(sessions.valid("session-review", self.user))
        sessions.revoke("session-review")
        self.assertFalse(sessions.valid("session-review", self.user))

    def test_rate_limit_applies_to_loopback_and_account(self):
        for _ in range(10):
            sessions.check_login("127.0.0.1", "guess-target")
        with self.assertRaises(HTTPException) as raised:
            sessions.check_login("127.0.0.1", "guess-target")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("Retry-After", raised.exception.headers)

    def test_client_cannot_expand_project_subscription(self):
        manager = ConnectionManager()
        socket = SimpleNamespace(state=SimpleNamespace(user_role="operator", user_project_ids=[4]))
        manager._subscriptions[id(socket)] = {"legacy": True}
        self.assertTrue(manager._should_send(socket, {"type": "sensor_data", "project_id": 4}))
        self.assertFalse(manager._should_send(socket, {"type": "sensor_data", "project_id": 9}))
        self.assertFalse(manager._should_send(socket, {"type": "sensor_data"}))


if __name__ == "__main__":
    unittest.main()
