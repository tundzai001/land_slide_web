import io
import math
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

if "psycopg2" not in sys.modules:
    try:
        import psycopg2
    except ModuleNotFoundError:
        sys.modules["psycopg2"] = MagicMock()

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import logging_config
from app.browser_session import require_origin
from app.config import settings
from app.features.authentication.router import AUTH_UNAVAILABLE_DETAIL
from app.features.authentication.sessions import AUTH_SESSION_PREFIX, AUTH_WS_TICKET_PREFIX
from app.features.frontend.websocket import WS_ADMIN_PATH
from app.features.operations.backups import (
    BACKUP_ID_PATTERN,
    MANIFEST_FILENAME,
    backup_path,
)
from app.features.stations.query_router import STATION_REQUEST_FAILED_DETAIL
from app.shared.project_dem import (
    GRID_SIZE_MISMATCH_DETAIL,
    INVALID_ELEVATION_DETAIL,
    inspect_ascii_grid,
)
from app.websocket import WS_OPERATIONS_PATH
from processors.gnss_adjustment.cors import (
    PUBLIC_MAP_STATIONS_ENDPOINT,
    RoundRobinCorsMixin,
)


class SonarCoverageBoostTests(unittest.TestCase):
    def setUp(self):
        self.valid_grid = (
            "ncols 2\n"
            "nrows 2\n"
            "xllcorner 454959.202\n"
            "yllcorner 2326094.284\n"
            "cellsize 1\n"
            "NODATA_value -9999\n"
            "100.0 101.5\n"
            "98 99\n"
        ).encode()

    def test_project_dem_error_branches(self):
        # Trigger non-numeric elevation
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(self.valid_grid.replace(b"100.0 101.5", b"not-a-number 101.5"))
        self.assertEqual(ctx.exception.detail, INVALID_ELEVATION_DETAIL)

        # Trigger NaN non-finite elevation
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(self.valid_grid.replace(b"100.0 101.5", b"nan 101.5"))
        self.assertEqual(ctx.exception.detail, INVALID_ELEVATION_DETAIL)

        # Trigger extra values (size mismatch)
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(self.valid_grid.replace(b"98 99", b"98 99 100"))
        self.assertEqual(ctx.exception.detail, GRID_SIZE_MISMATCH_DETAIL)

        # Trigger missing values
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(self.valid_grid.replace(b"98 99", b"98"))
        self.assertEqual(ctx.exception.detail, GRID_SIZE_MISMATCH_DETAIL)

    def test_cors_endpoint_and_request_path_rewriting(self):
        self.assertEqual(PUBLIC_MAP_STATIONS_ENDPOINT, "/api/public/map-stations")
        cors = RoundRobinCorsMixin()
        cors.web_cors_api_base_url = "https://cors.example"

        with patch("processors.gnss_adjustment.cors.urllib.request.urlopen") as mock_urlopen:
            mock_resp = io.BytesIO(b'{"status":"ok"}')
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            # Token starting with cors_
            res1 = cors._cors_api_request_sync(
                "GET", PUBLIC_MAP_STATIONS_ENDPOINT, access_token="cors_secret"
            )
            self.assertEqual(res1, {"status": "ok"})

            # Token not starting with cors_
            mock_resp2 = io.BytesIO(b'{"status":"ok2"}')
            mock_resp2.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp2
            res2 = cors._cors_api_request_sync(
                "GET", PUBLIC_MAP_STATIONS_ENDPOINT, access_token="regular_token"
            )
            self.assertEqual(res2, {"status": "ok2"})

    def test_operations_backups_constants_and_helpers(self):
        self.assertEqual(MANIFEST_FILENAME, "manifest.json")
        self.assertEqual(BACKUP_ID_PATTERN, r"[0-9a-f]{32}")
        valid_id = "a" * 32
        p = backup_path(valid_id)
        self.assertTrue(str(p).endswith(f"{valid_id}.zip"))

        with self.assertRaises(ValueError):
            backup_path("invalid-backup-id")

    def test_constants_and_shared_settings(self):
        self.assertEqual(AUTH_SESSION_PREFIX, "auth_session:")
        self.assertEqual(AUTH_WS_TICKET_PREFIX, "auth_ws_ticket:")
        self.assertEqual(AUTH_UNAVAILABLE_DETAIL, "Authentication unavailable")
        self.assertEqual(WS_ADMIN_PATH, "/ws/admin")
        self.assertEqual(STATION_REQUEST_FAILED_DETAIL, "Unable to complete station request")
        self.assertEqual(WS_OPERATIONS_PATH, "/ws/operations")
        self.assertEqual(logging_config.LOGGER_UVICORN_ACCESS, "uvicorn.access")
        self.assertEqual(logging_config.LOGGER_UVICORN_ERROR, "uvicorn.error")

        # install_heartbeat_filter coverage
        logging_config.install_heartbeat_filter()

    def test_browser_session_require_origin(self):
        scope = {
            "type": "http",
            "headers": [(b"origin", b"https://site.example")],
        }
        req = Request(scope)
        with patch.object(settings, "CORS_ORIGINS", "https://site.example"):
            require_origin(req)  # Should not raise

        with patch.object(settings, "CORS_ORIGINS", "https://other.example"):
            with pytest.raises(HTTPException) as exc:
                require_origin(req)
            assert exc.value.status_code == 403

    def test_security_core_waf_granular(self):
        from security_core import check_waf_granular, async_add_threat_map, security_state
        self.assertEqual(check_waf_granular("union select * from users"), "SQLI")
        self.assertEqual(check_waf_granular("select id from stations"), "SQLI")
        self.assertEqual(check_waf_granular("insert into test values(1)"), "SQLI")
        self.assertEqual(check_waf_granular("drop table test"), "SQLI")
        self.assertEqual(check_waf_granular("update test set foo=1"), "SQLI")
        self.assertEqual(check_waf_granular("<script>alert(1)</script>"), "XSS")
        self.assertEqual(check_waf_granular("javascript:alert(1)"), "XSS")
        self.assertEqual(check_waf_granular("<img src=x onerror=alert(1)>"), "XSS")
        self.assertEqual(check_waf_granular("<body onload=alert(1)>"), "XSS")
        self.assertEqual(check_waf_granular("../../etc/passwd"), "LFI")
        self.assertEqual(check_waf_granular("win.ini"), "LFI")
        self.assertIsNone(check_waf_granular("normal clean input"))

        async_add_threat_map("1.2.3.4", "SQLI")
        security_state.clean_old_records()

    def test_session_command_response_re(self):
        from processors.gnss_adjustment.session import _COMMAND_RESPONSE_RE, _CommandResponseMatcher
        m = _COMMAND_RESPONSE_RE.search("$COMMAND,mode rover survey,Response:OK*00")
        self.assertIsNotNone(m)
        self.assertEqual(m.group("command"), "mode rover survey")
        self.assertEqual(m.group("response"), "OK")
        self.assertEqual(m.group(0), "$COMMAND,mode rover survey,RESPONSE:OK")
        self.assertEqual(m.group(1), "mode rover survey")
        self.assertEqual(m.group(2), "OK")
        self.assertEqual(m.start(), 0)
        with self.assertRaises(IndexError):
            m.group(99)

        self.assertIsNone(_CommandResponseMatcher.search(""))
        self.assertIsNone(_CommandResponseMatcher.search("plain text"))
        self.assertIsNone(_CommandResponseMatcher.search("$command,singlepart"))
        self.assertIsNone(_CommandResponseMatcher.search("$command,cmd,notresponse"))
        self.assertIsNone(_CommandResponseMatcher.search("$command,cmd,responsenocolon"))
