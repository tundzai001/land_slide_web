import unittest
import time
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import BaseData
from app.features.operations import store

from app import auth
from app.features.authentication.router import create_websocket_ticket
from app.features.frontend.router import _consume_ws_ticket


class JwtCompatibilityTests(unittest.TestCase):
    def test_access_token_round_trip_uses_configured_algorithm(self):
        token = auth.create_access_token({"sub": "security-smoke-test"})

        payload = auth.jwt.decode(
            token,
            auth.settings.SECRET_KEY,
            algorithms=[auth.settings.ALGORITHM],
        )

        self.assertEqual(payload["sub"], "security-smoke-test")

    def test_tampered_access_token_raises_shared_jwt_error(self):
        token = auth.create_access_token({"sub": "security-smoke-test"})

        with self.assertRaises(auth.JWTError):
            auth.jwt.decode(
                f"{token}tampered",
                auth.settings.SECRET_KEY,
                algorithms=[auth.settings.ALGORITHM],
            )


class WebSocketTicketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseData.metadata.create_all(self.engine)
        self.previous_engine = store.configure_engine(self.engine)

    def tearDown(self):
        store.configure_engine(self.previous_engine)
        self.engine.dispose()

    async def test_ticket_is_short_lived_and_websocket_scoped(self):
        response = await create_websocket_ticket(
            SimpleNamespace(username="admin", role="admin", id=1, is_active=True, assigned_projects=[]),
            body={"channel": "admin"},
            token=auth.create_access_token({"sub": "admin"}),
        )
        payload = auth.jwt.decode(
            response["ticket"],
            auth.settings.SECRET_KEY,
            algorithms=[auth.settings.ALGORITHM],
        )

        self.assertEqual(payload["sub"], "admin")
        self.assertEqual(payload["purpose"], "websocket")
        self.assertLessEqual(payload["exp"] - int(auth.datetime.now(auth.timezone.utc).timestamp()), 30)

    async def test_ticket_jti_is_one_time(self):
        from app.features.authentication import sessions
        sessions.create_ws_ticket("security-test-jti", int(time.time()) + 30)
        self.assertTrue(await _consume_ws_ticket("security-test-jti"))
        self.assertFalse(await _consume_ws_ticket("security-test-jti"))


if __name__ == "__main__":
    unittest.main()
