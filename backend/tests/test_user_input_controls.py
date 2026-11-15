"""Account mutations and pagination use an isolated SQLite database."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import auth
from app.database import BaseAuth, get_auth_db
from app.features.users.router import router
from app.models.auth import User


class UserInputControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="account-input-")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/auth.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(BaseAuth.metadata.create_all)
        async with self.sessions() as db:
            db.add_all([
                User(id=1, username="admin", role="admin", is_active=True, hashed_password="hash"),
                User(id=2, username="reviewer", role="viewer", is_active=True, hashed_password="old-hash", assigned_projects=[7, 9]),
                User(id=3, username="other", role="viewer", is_active=False, hashed_password="hash", assigned_projects=[8]),
                User(id=4, username="literal%name", role="operator", is_active=True, hashed_password="hash"),
            ])
            await db.commit()
        app = FastAPI()
        app.include_router(router)

        async def database():
            async with self.sessions() as db:
                yield db

        self.actor = SimpleNamespace(id=1, username="admin", role="admin", is_active=True)
        app.dependency_overrides[get_auth_db] = database
        app.dependency_overrides[auth.get_current_user] = lambda: self.actor
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.directory.cleanup()

    async def test_partial_update_preserves_project_scope_and_password(self):
        response = await self.client.put("/api/admin/users/2", json={"full_name": "Reviewer"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["assigned_projects"], [7, 9])
        with patch.object(auth, "get_password_hash", AsyncMock(return_value="new-hash")):
            response = await self.client.put("/api/admin/users/2", json={"password": "a-long-new-password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["assigned_projects"], [7, 9])
        async with self.sessions() as db:
            self.assertEqual((await db.get(User, 2)).hashed_password, "new-hash")

    async def test_project_assignment_is_explicit_strict_and_deduplicated(self):
        for payload in ({}, {"assigned_projects": None}, {"assigned_projects": [True]},
                        {"assigned_projects": ["7"]}, {"assigned_projects": [-1]},
                        {"assigned_projects": list(range(1, 502))}):
            response = await self.client.put("/api/admin/users/2/projects", json=payload)
            self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.put("/api/admin/users/2/projects", json={"assigned_projects": [9, 7, 9]})
        self.assertEqual(response.json()["assigned_projects"], [9, 7])
        response = await self.client.put("/api/admin/users/2", json={"assigned_projects": []})
        self.assertEqual(response.json()["assigned_projects"], [])

    async def test_status_rejects_coercion_and_self_lockout(self):
        for payload in ({}, {"is_active": "false"}, {"is_active": 0}):
            response = await self.client.put("/api/admin/users/2/status", json=payload)
            self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.put("/api/admin/users/2/status", json={"is_active": False})
        self.assertFalse(response.json()["is_active"])
        self.actor.id = 2
        response = await self.client.put("/api/admin/users/2/status", json={"is_active": False})
        self.assertEqual(response.status_code, 400)

    async def test_create_rejects_invalid_password_role_and_identity_before_hashing(self):
        base = {"username": "new-user", "password": "a-long-test-password", "role": "viewer"}
        invalid = [{"password": "short"}, {"password": "é" * 37}, {"role": "owner"},
                   {"username": "bad user"}, {"username": "x\x00y"}, {"username": "x" * 151}]
        with patch.object(auth, "get_password_hash", AsyncMock(return_value="hashed")) as hash_password:
            for changes in invalid:
                response = await self.client.post("/api/admin/users", json={**base, **changes})
                self.assertEqual(response.status_code, 422, response.text)
            hash_password.assert_not_called()
            response = await self.client.post("/api/admin/users", json={"username": "new-user", "password": "é" * 36})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["role"], "viewer")

    async def test_filtered_pagination_counts_full_result_and_escapes_wildcards(self):
        response = await self.client.get("/api/admin/users?role=viewer&sort=-id&limit=1&offset=1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Total-Count"], "2")
        self.assertEqual([row["id"] for row in response.json()], [2])
        response = await self.client.get("/api/admin/users", params={"q": "%"})
        self.assertEqual([row["id"] for row in response.json()], [4])
        self.assertEqual((await self.client.get("/api/admin/users?limit=0")).status_code, 422)


if __name__ == "__main__":
    unittest.main()
