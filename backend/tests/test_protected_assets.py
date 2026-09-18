import asyncio
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.responses import Response
from unittest.mock import patch

from app.features.data_export.reports.adjustment import router as gnss_adjustment_reports
from app.features.rescue import router as rescue
from app.features.rescue import storage as rescue_storage


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


class _DataResult:
    def __init__(self, records):
        self.records = records

    def scalars(self):
        return self

    def all(self):
        return self.records


class _DataSession:
    def __init__(self, records):
        self.records = records

    async def execute(self, _statement):
        return _DataResult(self.records)


class ProtectedAssetTests(unittest.TestCase):
    def test_report_download_is_project_scoped_and_rejects_unsafe_names(self):
        user = SimpleNamespace(role="admin")
        db = _ProjectSession(SimpleNamespace(id=17))
        report_name = "gnss_adjustment_17_1700000000.json"
        payload = {
            "project_id": 17,
            "timestamp": 1700000000,
            "adjustment_key": "run:17:0:1",
            "audit_json_url": f"/api/admin/gnss/adjustment/reports/17/{report_name}",
            "excel_report_url": "/api/admin/gnss/adjustment/reports/17/gnss_adjustment_17_1700000000.xlsx",
        }
        response = asyncio.run(
            gnss_adjustment_reports.download_gnss_adjustment_report(
                17, report_name, db, user, _DataSession([SimpleNamespace(
                    data=payload,
                    adjustment_project_id=17,
                    adjustment_key="run:17:0:1",
                    timestamp=1700000000,
                )]),
            )
        )
        with self.subTest("response type"):
            self.assertIsInstance(response, Response)
            self.assertEqual(response.media_type, "application/json")
        with self.subTest("headers"):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertIn("no-store", response.headers["cache-control"])

        for invalid_name in (
            "../gnss_adjustment_17_1700000000.json",
            "gnss_adjustment_18_1700000000.json",
            "gnss_adjustment_17_1700000000.html",
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    gnss_adjustment_reports.download_gnss_adjustment_report(
                        17, invalid_name, db, user
                    )
                )
            self.assertEqual(raised.exception.status_code, 404)

    def test_operator_cannot_download_another_projects_report(self):
        user = SimpleNamespace(role="operator", assigned_projects=[99])
        db = _ProjectSession(SimpleNamespace(id=17))
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                gnss_adjustment_reports.download_gnss_adjustment_report(
                    17, "gnss_adjustment_17_1700000000.json", db, user
                )
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_missing_xlsx_is_rebuilt_from_persisted_json_payload(self):
        report_name = "gnss_adjustment_17_1700000000.xlsx"
        payload = {
            "project_id": 17,
            "timestamp": 1700000000,
            "computed_at": 1700000000,
            "audit_json_url": f"/api/admin/gnss/adjustment/reports/17/{report_name[:-5]}.json",
            "excel_report_url": f"/api/admin/gnss/adjustment/reports/17/{report_name}",
            "points": {},
            "baselines": [],
            "loops": [],
            "base": {},
            "quality": {},
        }
        record = SimpleNamespace(
            data=payload,
            adjustment_project_id=17,
            timestamp=1700000000,
        )
        response = asyncio.run(
            gnss_adjustment_reports.download_gnss_adjustment_report(
                17,
                report_name,
                _ProjectSession(SimpleNamespace(id=17)),
                SimpleNamespace(role="admin"),
                _DataSession([record]),
            )
        )
        self.assertIsInstance(response, Response)
        self.assertTrue(response.body)

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
