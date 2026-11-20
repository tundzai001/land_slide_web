import asyncio
import unittest
from pathlib import Path

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse

from app.models import config as model_config
from app.models.pi_device import PiDevice
from app.features.frontend.router import read_login, read_map
from app.features.stations.router import get_public_dashboard_summary
from app.shared.pagination import normalize_page, set_pagination_headers, slice_rows


class ResponsiveUiContractTests(unittest.TestCase):
    def test_pagination_keeps_legacy_full_array_and_sets_headers(self):
        rows = list(range(7))
        offset, limit = normalize_page(None, None)
        response = Response()
        set_pagination_headers(response, total=len(rows), offset=offset, limit=limit)
        self.assertEqual(slice_rows(rows, offset, limit), rows)
        self.assertEqual(response.headers["X-Total-Count"], "7")
        self.assertEqual(response.headers["X-Offset"], "0")
        self.assertEqual(response.headers["X-Limit"], "7")


    def test_pagination_slice_and_validation(self):
        self.assertEqual(slice_rows(list(range(10)), *normalize_page(3, 2)), [3, 4])
        with self.assertRaises(HTTPException) as invalid_offset:
            normalize_page(-1, 10)
        self.assertEqual(invalid_offset.exception.status_code, 422)
        with self.assertRaises(HTTPException) as invalid_limit:
            normalize_page(0, 501)
        self.assertEqual(invalid_limit.exception.status_code, 422)


    def test_map_and_login_deep_links_serve_the_application_shell(self):
        map_response = asyncio.run(read_map())
        login_response = asyncio.run(read_login())
        self.assertIsInstance(map_response, FileResponse)
        self.assertEqual(Path(map_response.path).name, "map.html")
        self.assertIsInstance(login_response, FileResponse)
        self.assertEqual(Path(login_response.path).name, "app.html")
        self.assertEqual(login_response.headers["x-robots-tag"], "noindex, noarchive")


    def test_additive_runtime_indexes_are_registered(self):
        station_indexes = {index.name for index in model_config.Station.__table__.indexes}
        device_indexes = {index.name for index in model_config.Device.__table__.indexes}
        pi_indexes = {index.name for index in PiDevice.__table__.indexes}
        self.assertIn("ix_stations_project_status", station_indexes)
        self.assertIn("ix_devices_station_active", device_indexes)
        self.assertIn("ix_pi_devices_status_station_seen", pi_indexes)


    def test_empty_dashboard_summary_contract(self):
        class EmptyResult:
            def scalars(self):
                return self

            def all(self):
                return []

        class EmptySession:
            async def execute(self, _statement):
                return EmptyResult()

        payload = asyncio.run(get_public_dashboard_summary(EmptySession(), EmptySession()))
        self.assertEqual(payload["stations"], {"total": 0, "online": 0, "offline": 0, "stale": 0})
        self.assertTrue(payload["updated_at"].endswith("Z"))


    def test_landing_uses_summary_endpoint_without_runtime_jsx_compiler(self):
        frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
        landing = (frontend_dir / "index.html").read_text(encoding="utf-8")
        script = (frontend_dir / "js" / "landing-common.js").read_text(encoding="utf-8")
        app_shell = (frontend_dir / "app.html").read_text(encoding="utf-8")
        self.assertIn("/api/public/dashboard-summary", script)
        self.assertNotIn("tailwindcss", landing)
        self.assertNotIn("babel", landing.lower())
        self.assertNotIn("babel", app_shell.lower())
        self.assertFalse((frontend_dir / "js" / "babel-runtime-loader.js").exists())
        self.assertFalse((frontend_dir / "js" / "babel-worker.js").exists())


    def test_dist_contains_only_compiled_browser_entrypoints(self):
        frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
        dist_dir = frontend_dir / "dist"
        expected = {
            "admin-app.min.js", "admin.min.css", "app-base.min.css", "app-runtime.min.js",
            "aitogy.png", "app.html", "build-manifest.json", "digital-twin.min.js", "index.html",
            "about.html", "about.min.css", "about.min.js", "landing.min.css", "landing.min.js", "login.min.css", "map-app.min.js",
            "map.html", "map.min.css", "mapbox-gl-sdk.min.css", "mapbox-gl-sdk.min.js", "shared.min.js", "social-card.png",
        }
        self.assertEqual({item.name for item in dist_dir.iterdir()}, expected)
        for name in ("index.html", "about.html", "map.html", "app.html"):
            document = (dist_dir / name).read_text(encoding="utf-8")
            self.assertNotIn("__BUILD_VERSION__", document)
            self.assertNotIn('src="/js/', document)
            self.assertNotIn('href="/css/', document)
        for bundle in dist_dir.glob("*.js"):
            source = bundle.read_text(encoding="utf-8")
            self.assertNotIn("sourceMappingURL", source)
            self.assertNotIn("text/babel", source.lower())


if __name__ == "__main__":
    unittest.main()
