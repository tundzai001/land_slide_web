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

    def test_auth_and_incident_coverage(self):
        import asyncio
        from app.auth import oauth2_scheme, require_permission, Permission
        from app.features.incidents.cases import append_event
        from app.features.incidents.write_router import _mutate_case

        # 1. oauth2_scheme
        from app.auth import create_access_token, Role
        valid_tok = create_access_token({"sub": "admin", "role": "admin"})
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {valid_tok}".encode())],
        }
        req = Request(scope)
        self.assertEqual(oauth2_scheme(req), valid_tok)

        # 2. require_permission
        checker = require_permission(Permission.MANAGE_INCIDENTS)
        admin_user = MagicMock()
        admin_user.is_superuser = False
        admin_user.role = Role.ADMIN
        self.assertEqual(checker(admin_user), admin_user)

        normal_user = MagicMock()
        normal_user.is_superuser = False
        normal_user.role = Role.VIEWER
        with self.assertRaises(HTTPException) as ctx:
            checker(normal_user)
        self.assertEqual(ctx.exception.status_code, 403)

        # 3. append_event with async flush
        async def run_append():
            mock_db = MagicMock()
            mock_db.flush = unittest.mock.AsyncMock()
            case = MagicMock()
            case.id = 42
            case.last_event_sequence = 2
            ev = await append_event(
                mock_db, case, "status_changed", actor_kind="user", note="test note"
            )
            mock_db.flush.assert_awaited_once()
            self.assertEqual(ev.sequence, 3)
            return ev

        asyncio.run(run_append())

        # 4. _mutate_case with sync and async mutate
        async def run_mutate_case():
            mock_db = MagicMock()
            def mock_add(obj):
                if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                    obj.id = 99
            mock_db.add.side_effect = mock_add
            mock_db.execute = unittest.mock.AsyncMock()
            mock_db.flush = unittest.mock.AsyncMock()
            mock_db.commit = unittest.mock.AsyncMock()
            mock_db.refresh = unittest.mock.AsyncMock()

            mock_case = MagicMock()
            mock_case.id = 10
            mock_case.version = 1
            mock_case.last_event_sequence = 0
            mock_case.status = "new"
            mock_case.project_id = 1
            mock_case.station_id = 1

            result_case = MagicMock()
            result_case.scalar_one_or_none.return_value = mock_case
            result_none = MagicMock()
            result_none.scalar_one_or_none.return_value = None

            # 1st: load_case -> mock_case, 2nd: existing_mutation -> None
            # 3rd: load_case -> mock_case, 4th: existing_mutation -> None
            mock_db.execute.side_effect = [result_case, result_none, result_case, result_none]

            # sync mutate without changes
            def sync_mutate_fn(c):
                return False, "noop", None, {}

            res = await _mutate_case(
                mock_db, admin_user, 10, "test", {}, "idemp-key-1", sync_mutate_fn
            )
            self.assertEqual(res["case"]["status"], "new")

            # async mutate with changes
            async def async_mutate_fn(c):
                c.status = "acknowledged"
                return True, "status_changed", "acknowledged", {}

            res2 = await _mutate_case(
                mock_db, admin_user, 10, "test", {}, "idemp-key-2", async_mutate_fn
            )
            self.assertEqual(res2["case"]["status"], "acknowledged")

        asyncio.run(run_mutate_case())

    def test_sensor_forwarding_gnss_sync(self):
        from app.mqtt.bridge.sensor_pipeline.forwarding import SensorForwardingMixin
        mixin = SensorForwardingMixin()
        mixin._forward_gnss({}, 1, "water", {})
        mixin._forward_gnss({"forwarding": {}}, 1, "gnss", {"forwarding_data": {}})

    def test_simulation_runs_dict_fromkeys(self):
        import asyncio
        from app.features.simulation.schemas import SimulationCreate
        from app.features.simulation.runs import create_run
        payload = SimulationCreate(
            parameters={"c": 10.0, "phi": 25.0, "gamma": 18.0},
            station_id=1,
            mode="station_snapshot",
        )
        mock_data_db = MagicMock()
        mock_data_db.commit = unittest.mock.AsyncMock()
        mock_data_db.refresh = unittest.mock.AsyncMock()
        mock_config_db = MagicMock()
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_user.is_superuser = True

        async def run_test():
            with patch("app.features.simulation.runs._station_inputs") as mock_inputs:
                mock_inputs.return_value = {
                    "station": MagicMock(name="st1"),
                    "project": MagicMock(name="p1"),
                    "parameters": {"c": 10.0, "phi": 25.0, "gamma": 18.0},
                    "parameter_sources": {},
                    "sensor_snapshot": {},
                    "warnings": [],
                }
                with patch("app.features.simulation.runs._start_worker"):
                    run_obj = await create_run(payload, mock_data_db, mock_config_db, mock_user)
                    self.assertIsNotNone(run_obj)

        asyncio.run(run_test())
