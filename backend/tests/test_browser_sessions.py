"""Browser cookie and API bearer sessions across real FastAPI request boundaries."""
import unittest
from types import SimpleNamespace

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import BaseData, get_auth_db
from app.features.authentication import router as authentication
from app.features.operations import store


class BrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseData.metadata.create_all(self.engine)
        self.previous_engine = store.configure_engine(self.engine)
        self.user = SimpleNamespace(
            id=1, username="operator", full_name="Operator", role="operator",
            is_active=True, assigned_projects=[3],
            hashed_password=bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode(),
        )
        app = FastAPI()
        app.include_router(authentication.router)

        class UserDB:
            async def execute(_self, _query):
                return SimpleNamespace(scalar_one_or_none=lambda: self.user)

        async def auth_db():
            yield UserDB()

        app.dependency_overrides[get_auth_db] = auth_db
        self.client = TestClient(app, base_url="https://monitoring.aitogy.com")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        store.configure_engine(self.previous_engine)
        self.engine.dispose()

    def browser_login(self):
        return self.client.post("/api/auth/login", data={
            "username": "operator", "password": "correct-password"
        }, headers={"Origin": "https://monitoring.aitogy.com", "X-Session-Mode": "cookie"})

    def csrf_headers(self):
        return {"Origin": "https://monitoring.aitogy.com",
                "X-CSRF-Token": self.client.cookies["__Host-monitoring_csrf"]}

    def test_cookie_is_http_only_and_csrf_is_required_for_mutations(self):
        response = self.browser_login()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("access_token", response.json())
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("__Host-monitoring_session", cookie)
        self.assertIn("httponly", cookie.lower())
        self.assertIn("secure", cookie.lower())
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/ws-ticket", json={"channel": "updates"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/ws-ticket", json={"channel": "updates"},
                                          headers=self.csrf_headers()).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"X-CSRF-Token": self.csrf_headers()["X-CSRF-Token"]}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers=self.csrf_headers()).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_cookie_token_cannot_be_replayed_as_bearer(self):
        self.browser_login()
        cookie = self.client.cookies["__Host-monitoring_session"]
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {cookie}"}).status_code, 401)

    def test_old_bearer_api_flow_still_works(self):
        response = self.client.post("/api/auth/login", data={"username": "operator", "password": "correct-password"})
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_revoke_other_sessions(self):
        self.browser_login()
        self.browser_login()
        headers = self.csrf_headers()
        rows = self.client.get("/api/auth/sessions").json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["current"] for row in rows), 1)
        response = self.client.post("/api/auth/sessions/revoke-others", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revoked"], 1)
        self.assertEqual(len(self.client.get("/api/auth/sessions").json()), 1)


if __name__ == "__main__":
    unittest.main()
