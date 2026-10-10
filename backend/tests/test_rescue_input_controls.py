"""Reject malformed public intake before touching storage or the database."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import BigInteger, Integer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import BaseData, get_data_db
from app.features.rescue import storage
from app.features.rescue.router import router
from app.models.data import RescueRequest


class RescueInputControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        self.app = app
        app.include_router(router)

        async def unused_database():
            yield None

        app.dependency_overrides[get_data_db] = unused_database
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.flag = patch.object(settings, "RESCUE_REQUEST_ENABLED", True)
        self.flag.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.flag.stop()

    async def test_invalid_json_coordinates_and_fields_return_422_without_persisting_images(self):
        invalid = [[], {}, {"latitude": 91, "longitude": 105},
                   {"latitude": "NaN", "longitude": 105},
                   {"latitude": 21, "longitude": 105, "accuracy_m": -1},
                   {"latitude": 21, "longitude": 105, "message": "x" * 5001},
                   {"latitude": 21, "longitude": 105, "source_link": "javascript:alert(1)"}]
        with patch.object(storage, "persist_data_url") as persist:
            for payload in invalid:
                response = await self.client.post("/api/public/rescue-requests", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
            response = await self.client.post("/api/public/rescue-requests", content=b"{", headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            persist.assert_not_called()

    async def test_multipart_validates_coordinates_before_storing_file(self):
        with patch.object(storage, "persist_upload", AsyncMock()) as persist:
            response = await self.client.post("/api/public/rescue-requests", data={"latitude": "bad", "longitude": "105"},
                files={"image_file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")})
            self.assertEqual(response.status_code, 422)
            persist.assert_not_called()

    async def test_valid_multipart_keeps_intake_workflow_and_persists_image(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        # PostgreSQL BigInteger primary keys are identity columns; SQLite needs
        # INTEGER to exercise the same auto-generated ID behavior in this test.
        integer_ids = [column for table in BaseData.metadata.tables.values()
                       for column in table.columns
                       if column.primary_key and isinstance(column.type, BigInteger)]
        original_types = [column.type for column in integer_ids]
        try:
            for column in integer_ids:
                column.type = Integer()
            async with engine.begin() as connection:
                await connection.run_sync(BaseData.metadata.create_all)
        finally:
            for column, column_type in zip(integer_ids, original_types):
                column.type = column_type

        async def database():
            async with sessions() as db:
                yield db

        self.app.dependency_overrides[get_data_db] = database
        try:
            with tempfile.TemporaryDirectory(prefix="rescue-image-") as directory, patch.object(storage, "RESCUE_IMAGE_DIR", Path(directory)):
                response = await self.client.post("/api/public/rescue-requests", data={
                    "latitude": "21", "longitude": "105", "accuracy_m": "", "message": "Cần hỗ trợ",
                    "source_link": "https://example.test/rescue",
                }, files={"image_file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")})
                self.assertEqual(response.status_code, 200, response.text)
                async with sessions() as db:
                    row = await db.get(RescueRequest, response.json()["id"])
                    self.assertEqual((row.latitude, row.longitude), (21, 105))
                    self.assertIsNone(row.accuracy_m)
                    self.assertEqual(storage.unpack_message(row.message)["text"], "Cần hỗ trợ")
                self.assertEqual(len(list(Path(directory).iterdir())), 1)
        finally:
            await engine.dispose()

    async def test_upload_reads_only_limit_plus_one_byte(self):
        upload = AsyncMock()
        upload.content_type = "image/png"
        upload.read.return_value = b"\x89PNG\r\n\x1a\n" + b"x" * storage.MAX_RESCUE_IMAGE_BYTES
        with self.assertRaises(HTTPException) as error:
            await storage.persist_upload(upload)
        self.assertEqual(error.exception.status_code, 413)
        upload.read.assert_awaited_once_with(storage.MAX_RESCUE_IMAGE_BYTES + 1)

    async def test_oversized_base64_is_rejected_before_decoding(self):
        with patch.object(base64, "b64decode") as decode:
            with self.assertRaises(HTTPException) as error:
                storage.persist_data_url("data:image/png;base64," + "A" * (storage.MAX_RESCUE_IMAGE_BYTES * 2))
            self.assertEqual(error.exception.status_code, 413)
            decode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
