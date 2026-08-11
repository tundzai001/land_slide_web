import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.routers import gnss_adjustment, rescue
from app.services import rescue_storage


class _ProjectResult:
    def __init__(self, project):
        self.project = project

    def scalar_one_or_none(self):
        return self.project


class _ProjectSession:
    def __init__(self, project):
        self.project = project

    async def execute(self, _statement):
        return _ProjectResult(self.project)


class ProtectedAssetTests(unittest.TestCase):
    def test_report_download_is_project_scoped_and_rejects_unsafe_names(self):
        user = SimpleNamespace(role="admin")
        db = _ProjectSession(SimpleNamespace(id=17))
        report_name = "gnss_adjustment_17_1700000000.json"
        with (
            patch.object(gnss_adjustment, "ADJUSTMENT_REPORT_DIR", Path("C:/secure")),
            patch.object(Path, "is_file", return_value=True),
        ):
            response = asyncio.run(
                gnss_adjustment.download_gnss_adjustment_report(
                    17, report_name, db, user
                )
            )
            self.assertIsInstance(response, FileResponse)
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertIn("no-store", response.headers["cache-control"])

        for invalid_name in (
            "../gnss_adjustment_17_1700000000.json",
            "gnss_adjustment_18_1700000000.json",
            "gnss_adjustment_17_1700000000.html",
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    gnss_adjustment.download_gnss_adjustment_report(
                        17, invalid_name, db, user
                    )
                )
            self.assertEqual(raised.exception.status_code, 404)

    def test_operator_cannot_download_another_projects_report(self):
        user = SimpleNamespace(role="operator", assigned_projects=[99])
        db = _ProjectSession(SimpleNamespace(id=17))
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                gnss_adjustment.download_gnss_adjustment_report(
                    17, "gnss_adjustment_17_1700000000.json", db, user
                )
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_rescue_images_require_admin_and_valid_image_content(self):
        valid_name = "evidence.png"
        with patch.object(
            rescue_storage,
            "validated_image_media_type",
            side_effect=lambda path: "image/png" if path.name == valid_name else None,
        ):
            response = asyncio.run(
                rescue.get_rescue_image(valid_name, SimpleNamespace(role="admin"))
            )
            self.assertIsInstance(response, FileResponse)
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")

            with self.assertRaises(HTTPException) as viewer_error:
                asyncio.run(
                    rescue.get_rescue_image(
                        valid_name, SimpleNamespace(role="viewer")
                    )
                )
            self.assertEqual(viewer_error.exception.status_code, 403)

            with self.assertRaises(HTTPException) as fake_error:
                asyncio.run(
                    rescue.get_rescue_image(
                        "fake.png", SimpleNamespace(role="admin")
                    )
                )
            self.assertEqual(fake_error.exception.status_code, 404)

        with self.assertRaises(HTTPException):
            rescue_storage._validate_image(
                "image/png", b"<script>alert(1)</script>"
            )


if __name__ == "__main__":
    unittest.main()
