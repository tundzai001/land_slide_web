import io
import math
import os
import re
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
        grid_nan_str = self.valid_grid.replace(b"100.0 101.5", b"not-a-number 101.5")
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(grid_nan_str)
        self.assertEqual(ctx.exception.detail, INVALID_ELEVATION_DETAIL)

        # Trigger NaN non-finite elevation
        grid_nan_float = self.valid_grid.replace(b"100.0 101.5", b"nan 101.5")
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(grid_nan_float)
        self.assertEqual(ctx.exception.detail, INVALID_ELEVATION_DETAIL)

        # Trigger extra values (size mismatch)
        grid_extra = self.valid_grid.replace(b"98 99", b"98 99 100")
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(grid_extra)
        self.assertEqual(ctx.exception.detail, GRID_SIZE_MISMATCH_DETAIL)

        # Trigger missing values
        grid_missing = self.valid_grid.replace(b"98 99", b"98")
        with self.assertRaises(HTTPException) as ctx:
            inspect_ascii_grid(grid_missing)
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

    def test_other_sensors_and_gnss_audit_coverage(self):
        import asyncio
        from app.mqtt.bridge.sensor_pipeline.other_sensors import OtherSensorPayloadMixin
        from app.mqtt.persistence.gnss_audit import GnssAuditPersistenceMixin

        # 1. other sensors (rain / water)
        handler = OtherSensorPayloadMixin()
        proc = MagicMock()
        proc.process.return_value = {"rain": 5.0}

        async def run_sensors():
            res = await handler._process_other_sensor_payload(
                {"type": "rain"}, '{"value": 5.0}', 1, 10, "ST10", proc, {}, 1, False, 1000
            )
            self.assertEqual(res, {"rain": 5.0})

        asyncio.run(run_sensors())

        # 2. gnss audit anomaly with buffer lock
        class MockAudit(GnssAuditPersistenceMixin):
            def __init__(self):
                self._buffer_lock = asyncio.Lock()
                self._active_gnss_anomalies = set()

        audit = MockAudit()

        async def run_audit():
            # non anomaly status
            self.assertFalse(await audit._should_record_gnss_anomaly(1, {"status": "FIXED"}))
            # anomaly status UNSTABLE_FIX
            self.assertTrue(await audit._should_record_gnss_anomaly(1, {"status": "UNSTABLE_FIX"}))
            # duplicate anomaly status
            self.assertFalse(await audit._should_record_gnss_anomaly(1, {"status": "UNSTABLE_FIX"}))
            # clear anomaly
            await audit._clear_gnss_anomaly(1)
            # anomaly can be recorded again
            self.assertTrue(await audit._should_record_gnss_anomaly(1, {"status": "UNSTABLE_FIX"}))

        asyncio.run(run_audit())

    def test_refactored_helpers_coverage(self):
        import asyncio
        from processors.gnss_adjustment.observation import RoundRobinObservationMixin
        self.assertTrue(RoundRobinObservationMixin._detect_rtcm_preamble(b"\xd3\x00\x05data"))
        self.assertFalse(RoundRobinObservationMixin._detect_rtcm_preamble(b"normal text"))

        from app.mqtt.transport import MQTTTransportMixin
        self.assertEqual(MQTTTransportMixin._decode_incoming_payload("gnss", b"$GPGGA,123456*00\n"), "$GPGGA,123456*00")
        self.assertEqual(MQTTTransportMixin._decode_incoming_payload("rain", b'{"rain": 1.2}'), '{"rain": 1.2}')
        self.assertIsNone(MQTTTransportMixin._decode_incoming_payload("rain", b'\xff\xfe\xfa'))

        from app.mqtt.persistence.alerts import AlertPersistenceMixin
        self.assertEqual(AlertPersistenceMixin._highest_alert_priority(["LOW", "CRITICAL", "MEDIUM"]), "CRITICAL")
        self.assertEqual(AlertPersistenceMixin._highest_alert_priority([]), "LOW")

        class MockAlerts(AlertPersistenceMixin):
            def _get_sensor_offline_threshold(self, cfg, sensor_type):
                return 60

        alerts = MockAlerts()
        ttl_map = alerts._build_alert_ttl_map({})
        self.assertEqual(ttl_map['gnss_velocity'], 120)

        from app.shared.project_location import _dem_center_point
        async def run_dem():
            res = await _dem_center_point(None, 999999)
            self.assertIsNone(res)
        asyncio.run(run_dem())

    def test_refactored_nested_ternaries_helpers(self):
        from app.features.stations.query_router import _compute_station_status
        self.assertEqual(_compute_station_status(True, False), "online")
        self.assertEqual(_compute_station_status(False, True), "stale")
        self.assertEqual(_compute_station_status(False, False), "offline")

        from app.mqtt.bridge.sensor_pipeline.persistence import _extract_metric_values
        self.assertEqual(_extract_metric_values("gnss", {"speed_2d_mm_s": 1.5, "total_displacement_mm": 2.5}), (1.5, 2.5))
        self.assertEqual(_extract_metric_values("rain", {"intensity_mm_h": 10.0, "accumulated_mm": 25.0}), (10.0, 25.0))
        self.assertEqual(_extract_metric_values("water", {"water_level": 3.0, "intensity_mm_h": 4.0}), (3.0, 4.0))
        self.assertEqual(_extract_metric_values("imu", {"roll": 5.0, "pitch": 6.0}), (5.0, 6.0))

        from app.shared.project_dem import _resolve_project_dem_dir
        self.assertIsNotNone(_resolve_project_dem_dir())

        from app.shared.project_location import map_mode
        self.assertEqual(map_mode({"map_mode": "auto"}), "auto")
        self.assertEqual(map_mode({"map_mode": "manual"}), "manual")
        self.assertEqual(map_mode({"lat": 10.0, "lon": 106.0}), "manual")
        self.assertEqual(map_mode({}), "auto")

    def test_adjustment_phase_computation(self):
        from app.mqtt.bridge.adjustment import MQTTAdjustmentMixin
        from app.features.users.router import USER_NOT_FOUND

        self.assertEqual(USER_NOT_FOUND, "User not found")

        # Active states
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "PAUSED"}]),
            "PAUSED"
        )
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "FREE_NETWORK"}]),
            "FREE_NETWORK"
        )
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "STARTING"}]),
            "COLLECTING_BASELINE"
        )

        # Terminal states
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "COMPLETED"}, {"status": "ERROR"}]),
            "PARTIAL_FAILED"
        )
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "FAILED_QUALITY_GATE"}]),
            "FAILED_QUALITY_GATE"
        )
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "ERROR"}]),
            "ERROR"
        )
        self.assertEqual(
            MQTTAdjustmentMixin._compute_adjustment_phase([{"status": "COMPLETED"}]),
            "COMPLETED"
        )

    def test_user_router_endpoints(self):
        import asyncio
        from unittest.mock import AsyncMock
        from sqlalchemy.exc import IntegrityError
        from app.features.users.router import (
            toggle_user_status,
            update_user,
            delete_user,
            update_user_projects,
            create_user,
            USER_NOT_FOUND,
        )
        from app import schemas
        from app.models import auth as model_auth

        async def run_tests():
            db = AsyncMock()
            current_user = model_auth.User(id=1, username="admin_operator", role="admin")

            # 1. toggle_user_status: not found
            res_mock = MagicMock()
            res_mock.scalar_one_or_none.return_value = None
            db.execute.return_value = res_mock
            with self.assertRaises(HTTPException) as ctx:
                await toggle_user_status(999, schemas.UserStatusUpdate(is_active=False), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, USER_NOT_FOUND)

            # toggle_user_status: admin user
            admin_target = model_auth.User(id=2, username="admin", role="admin", is_active=True)
            res_mock.scalar_one_or_none.return_value = admin_target
            with self.assertRaises(HTTPException) as ctx:
                await toggle_user_status(2, schemas.UserStatusUpdate(is_active=False), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot change status of the admin user")

            # toggle_user_status: cannot deactivate yourself
            self_user = model_auth.User(id=1, username="admin_operator", role="admin", is_active=True)
            res_mock.scalar_one_or_none.return_value = self_user
            with self.assertRaises(HTTPException) as ctx:
                await toggle_user_status(1, schemas.UserStatusUpdate(is_active=False), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot deactivate yourself")

            # toggle_user_status: success
            target_user = model_auth.User(id=3, username="op1", role="operator", is_active=True)
            res_mock.scalar_one_or_none.return_value = target_user
            res = await toggle_user_status(3, schemas.UserStatusUpdate(is_active=False), db=db, current_user=current_user)
            self.assertEqual(res, {"status": "success", "is_active": False})

            # 2. update_user: not found
            res_mock.scalar_one_or_none.return_value = None
            with self.assertRaises(HTTPException) as ctx:
                await update_user(999, schemas.UserUpdate(), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, USER_NOT_FOUND)

            # update_user: invalid role
            res_mock.scalar_one_or_none.return_value = target_user
            target_user.role = "invalid_role"
            with self.assertRaises(HTTPException) as ctx:
                await update_user(3, schemas.UserUpdate(), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Invalid role")
            target_user.role = "operator"

            # update_user: cannot change primary admin role
            res_mock.scalar_one_or_none.return_value = admin_target
            with self.assertRaises(HTTPException) as ctx:
                await update_user(2, schemas.UserUpdate(role="operator"), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot change the primary admin role")

            # update_user: cannot change own role
            res_mock.scalar_one_or_none.return_value = self_user
            with self.assertRaises(HTTPException) as ctx:
                await update_user(1, schemas.UserUpdate(role="viewer"), db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot change your own role")

            # update_user: success (full_name, password, assigned_projects)
            res_mock.scalar_one_or_none.return_value = target_user
            with patch("app.auth.get_password_hash", return_value="hashed_pw"):
                updated = await update_user(
                    3,
                    schemas.UserUpdate(full_name="New Name", password="ValidPassword123#", role="operator", assigned_projects=[10]),
                    db=db,
                    current_user=current_user
                )
                self.assertEqual(updated.full_name, "New Name")
                self.assertEqual(updated.assigned_projects, [10])

            # 3. delete_user: cannot delete yourself
            with self.assertRaises(HTTPException) as ctx:
                await delete_user(1, db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot delete yourself")

            # delete_user: not found
            res_mock.scalar_one_or_none.return_value = None
            with self.assertRaises(HTTPException) as ctx:
                await delete_user(999, db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, USER_NOT_FOUND)

            # delete_user: admin user
            res_mock.scalar_one_or_none.return_value = admin_target
            with self.assertRaises(HTTPException) as ctx:
                await delete_user(2, db=db, current_user=current_user)
            self.assertEqual(ctx.exception.detail, "Cannot delete the admin user")

            # delete_user: success
            res_mock.scalar_one_or_none.return_value = target_user
            res_del = await delete_user(3, db=db, current_user=current_user)
            self.assertEqual(res_del, {"status": "success"})

            # 4. update_user_projects: not found
            res_mock.scalar_one_or_none.return_value = None
            with self.assertRaises(HTTPException) as ctx:
                await update_user_projects(999, schemas.UserProjectsUpdate(assigned_projects=[1]), db=db, _user=current_user)
            self.assertEqual(ctx.exception.detail, USER_NOT_FOUND)

            # update_user_projects: success operator
            res_mock.scalar_one_or_none.return_value = target_user
            res_proj = await update_user_projects(3, schemas.UserProjectsUpdate(assigned_projects=[5, 6]), db=db, _user=current_user)
            self.assertEqual(res_proj, {"status": "success", "assigned_projects": [5, 6]})

            # 5. create_user: username exists
            res_mock.scalar_one_or_none.return_value = target_user
            with self.assertRaises(HTTPException) as ctx:
                await create_user(schemas.UserCreate(username="op1", password="ValidPassword123#", role="operator"), db=db, _user=current_user)
            self.assertEqual(ctx.exception.detail, "Username already exists")

            # create_user: IntegrityError
            res_mock.scalar_one_or_none.return_value = None
            db.commit.side_effect = IntegrityError("dup", "params", "orig")
            with patch("app.auth.get_password_hash", return_value="hpw"):
                with self.assertRaises(HTTPException) as ctx:
                    await create_user(schemas.UserCreate(username="op2", password="ValidPassword123#", role="operator"), db=db, _user=current_user)
                self.assertEqual(ctx.exception.detail, "Username already exists")
            db.commit.side_effect = None

            # create_user: success
            with patch("app.auth.get_password_hash", return_value="hpw"):
                created = await create_user(schemas.UserCreate(username="op2", password="ValidPassword123#", role="operator", assigned_projects=[1]), db=db, _user=current_user)
                self.assertEqual(created.username, "op2")

        asyncio.run(run_tests())

    def test_simulation_engine_extended_coverage(self):
        from app.features.simulation.engine import (
            normalize_parameters,
            run_simulation,
            _terrain_profile,
            STATE_SLIDING,
            STATE_DEPOSITED,
        )

        # Invalid param type
        with self.assertRaises(ValueError):
            normalize_parameters({"cohesion": "not_a_number"})

        # Invalid param range
        with self.assertRaises(ValueError):
            normalize_parameters({"cohesion": -5.0})

        # Invalid duration
        with self.assertRaises(ValueError):
            run_simulation({}, 500, 1)
        with self.assertRaises(ValueError):
            run_simulation({}, 700000, 1)

        # Terrain profile
        params = normalize_parameters({})
        profile = _terrain_profile(params)
        self.assertGreater(len(profile), 0)

        # Trigger sliding scenario: steep slope, excessive rain, pore pressure
        sliding_sim = run_simulation(
            {
                "slope_angle": 55.0,
                "rainfall": 350.0,
                "pore_pressure_ratio": 0.5,
                "friction_angle": 15.0,
                "cohesion": 1.0,
                "fos_warning": 1.5,
                "fos_critical": 1.2,
            },
            duration_seconds=7200,
            seed=42,
        )
        self.assertIn("time_series", sliding_sim)
        self.assertIn("summary", sliding_sim)
        self.assertEqual(sliding_sim["summary"]["classification"], "Đã xảy ra trượt mô phỏng")
        self.assertTrue(any(e["state"] == STATE_SLIDING for e in sliding_sim["events"]))

    def test_websocket_connection_manager_coverage(self):
        import asyncio
        from app.websocket import (
            ConnectionManager,
            WS_OPERATIONS_PATH,
            TYPE_SENSOR_DATA,
            TYPE_STATION_STATUS,
            TYPE_ALERT,
        )

        mgr = ConnectionManager()
        self.assertEqual(mgr._normalize_ids([1, 2]), {1, 2})
        self.assertEqual(mgr._normalize_ids(None), set())
        with self.assertRaises(ValueError):
            mgr._normalize_ids("not_a_list")
        with self.assertRaises(ValueError):
            mgr._normalize_ids([1, "2"])
        with self.assertRaises(ValueError):
            mgr._normalize_ids([-1])

        # Test _should_send
        from unittest.mock import AsyncMock
        mock_ws = MagicMock()
        mock_ws.url.path = "/ws/updates"
        mock_ws.accept = AsyncMock()
        mock_ws.send_text = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mock_ws.close = AsyncMock()
        mock_ws.state.ensure_authorized = None
        mock_ws.state.authorization_failed = False
        mock_ws.state.user_role = "admin"
        mock_ws.state.user_project_ids = [10]

        async def run_ws_tests():
            # Connect
            await mgr.connect(mock_ws)
            self.assertIn(mock_ws, mgr.active_connections)

            # Update subscriptions
            import json
            ok_invalid = await mgr.handle_client_message(mock_ws, "not-json")
            self.assertFalse(ok_invalid)

            ok_err = await mgr.handle_client_message(mock_ws, json.dumps({
                "type": "subscribe",
                "station_ids": ["invalid"],
            }))
            self.assertTrue(ok_err)

            ok = await mgr.handle_client_message(mock_ws, json.dumps({
                "type": "subscribe",
                "station_ids": [1, 2],
                "project_ids": [10],
                "channels": ["sensor", "status"],
            }))
            self.assertTrue(ok)

            # Check _should_send matching
            msg_matching = {"station_id": 1, "project_id": 10, "type": TYPE_SENSOR_DATA}
            self.assertTrue(mgr._should_send(mock_ws, msg_matching))

            # Channel not subscribed
            msg_other_channel = {"station_id": 1, "project_id": 10, "type": "alert"}
            self.assertFalse(mgr._should_send(mock_ws, msg_other_channel))

            # Station not subscribed
            msg_other_station = {"station_id": 999, "project_id": 10, "type": TYPE_SENSOR_DATA}
            self.assertFalse(mgr._should_send(mock_ws, msg_other_station))

            # Operations socket check
            ops_ws = MagicMock()
            ops_ws.url.path = WS_OPERATIONS_PATH
            ops_ws.state.authorization_failed = False
            ops_ws.state.user_role = "admin"
            ops_ws.state.user_project_ids = [10]
            self.assertTrue(mgr._should_send(ops_ws, {"type": "incident_changed", "project_id": 10}))
            self.assertFalse(mgr._should_send(ops_ws, {"type": TYPE_SENSOR_DATA, "station_id": 1}))

            # Broadcast helpers
            await mgr.broadcast({"station_id": 1, "sensor_type": "gnss", "type": TYPE_SENSOR_DATA})
            await mgr.broadcast({"station_id": 1, "risk_level": "CRITICAL", "type": TYPE_STATION_STATUS})
            await mgr.broadcast({"id": 1, "severity": "HIGH", "type": TYPE_ALERT})
            await mgr.broadcast_admins({"type": "admin_event"})
            await mgr.broadcast_operations({"type": "incident_changed", "project_id": 10})

            # Disconnect
            mgr.disconnect(mock_ws)
            self.assertNotIn(mock_ws, mgr.active_connections)

        asyncio.run(run_ws_tests())

    def test_station_common_coordinate_helpers(self):
        from app.features.stations.common import (
            _extract_sensor_coordinates,
            _format_computed_location,
            calculate_station_location,
        )
        self.assertEqual(_extract_sensor_coordinates({}), [])
        coords = _extract_sensor_coordinates({
            "gnss": {"lat": 10.5, "lon": 106.5, "h": 15.0},
            "invalid": {"lat": "bad", "lon": None},
        })
        self.assertEqual(len(coords), 1)
        self.assertEqual(coords[0]["lat"], 10.5)

        single_loc = _format_computed_location([{"lat": 10.5, "lon": 106.5, "h": 15.0}])
        self.assertEqual(single_loc["source"], "Single Sensor (Auto)")

        multi_loc = _format_computed_location([
            {"lat": 10.0, "lon": 106.0, "h": 10.0},
            {"lat": 12.0, "lon": 108.0, "h": 20.0},
        ])
        self.assertEqual(multi_loc["lat"], 11.0)
        self.assertEqual(multi_loc["source"], "Average of 2 sensors")

        dem_loc = {"source": "project-dem-grid", "lat": 15.0, "lon": 108.0}
        self.assertEqual(calculate_station_location({}, dem_loc), dem_loc)
        self.assertIsNone(calculate_station_location({}, None))

    def test_origin_fetcher_parse_coordinates(self):
        from app.features.stations.origin_fetcher import GNSSLiveFetcher
        fetcher = GNSSLiveFetcher("127.0.0.1", 2101, "MP1", "user", "pass")
        # Valid coordinates
        res = fetcher._parse_coordinates("1030.0000", "N", "10630.0000", "E")
        self.assertIsNotNone(res)
        lat, lon = res
        self.assertAlmostEqual(lat, 10.5)
        self.assertAlmostEqual(lon, 106.5)

        # Invalid cases
        self.assertIsNone(fetcher._parse_coordinates("", "N", "10630.0000", "E"))
        self.assertIsNone(fetcher._parse_coordinates("1030.0000", "X", "10630.0000", "E"))
        self.assertIsNone(fetcher._parse_coordinates("1070.0000", "N", "10630.0000", "E"))

        # GNGGA parser
        nmea = "$GNGGA,000000.00,1030.0000,N,10630.0000,E,1,08,1.0,15.0,M,5.0,M,,*47"
        parsed = fetcher._parse_gngga(nmea)
        if parsed:
            self.assertIn("lat", parsed)
            self.assertIn("h", parsed)

    def test_browser_session_token_helpers(self):
        from app.browser_session import (
            _extract_and_validate_claims,
            _verify_csrf_if_cookie_mutation,
            csrf_token,
        )
        from app.auth import JWTError

        # Valid Bearer header
        mock_decoder = lambda tok: {"transport": "bearer", "jti": "jti123"}
        token, claims = _extract_and_validate_claims("Bearer mytoken", None, mock_decoder, JWTError)
        self.assertEqual(token, "mytoken")

        # Invalid Bearer format
        with self.assertRaises(JWTError):
            _extract_and_validate_claims("Basic auth", None, mock_decoder, JWTError)

        # Bearer using cookie transport
        cookie_decoder = lambda tok: {"transport": "cookie", "jti": "jti123"}
        with self.assertRaises(JWTError):
            _extract_and_validate_claims("Bearer mytoken", None, cookie_decoder, JWTError)

        # Valid Cookie transport
        token_c, claims_c = _extract_and_validate_claims(None, "cookietok", cookie_decoder, JWTError)
        self.assertEqual(token_c, "cookietok")

        # CSRF verify GET method does not raise
        req_get = Request({"type": "http", "method": "GET", "headers": []})
        _verify_csrf_if_cookie_mutation(req_get, True, "jti123")

        # CSRF verify POST method with valid token
        valid_csrf = csrf_token("jti123")
        req_post = Request({
            "type": "http",
            "method": "POST",
            "headers": [
                (b"origin", b"https://site.example"),
                (b"x-csrf-token", valid_csrf.encode()),
            ],
        })
        with patch.object(settings, "CORS_ORIGINS", "https://site.example"):
            _verify_csrf_if_cookie_mutation(req_post, True, "jti123")

    def test_formats_excel_helpers(self):
        import io
        from app.features.data_export.database.formats import (
            _format_cell_values,
            _convert_csv_to_workbook,
        )
        from openpyxl import Workbook
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("test")
        cells = _format_cell_values(["normal", "x" * 35000], ws)
        self.assertEqual(len(cells), 2)
        self.assertTrue(cells[1].value.endswith("... [TRUNCATED - xem file CSV để có đầy đủ]"))
        ws.append(cells)
        wb.save(io.BytesIO())

        csv_content = io.StringIO("col1,col2\nval1,val2\nval3,val4\n")
        wb_res = _convert_csv_to_workbook(csv_content)
        self.assertIsNotNone(wb_res)
        wb_res.save(io.BytesIO())

    def test_operations_backups_helpers(self):
        import asyncio
        from app.features.operations.backups import (
            _run_scheduled_backup_step,
            _run_daily_log_cleanup_step,
            _handle_scheduler_error,
        )
        from app.features.operations import store

        async def run_backup_helpers():
            with patch.object(store, "claim_backup_schedule", return_value=False):
                await _run_scheduled_backup_step(1000)

            with patch.object(store, "claim_daily_log_cleanup", return_value=False):
                await _run_daily_log_cleanup_step(1000)

            with patch.object(store, "append", return_value=None):
                await _handle_scheduler_error(ValueError("test error"))

        asyncio.run(run_backup_helpers())

    def test_mqtt_transport_gnss_message_handler(self):
        from app.mqtt.transport import MQTTTransportMixin

        transport = MQTTTransportMixin()
        transport.round_robin_manager = MagicMock()
        mock_msg = MagicMock()
        mock_msg.payload = b"$GNGGA,000000.00,10.0,N,106.0,E,1,08,1.0,15.0,M,5.0,M,,*47"
        info = {"station_code": "TEST01", "device_id": 1, "station_id": 2, "type": "gnss"}

        # Handle with decrypted_payload
        transport._handle_gnss_message(info, mock_msg, "$GNGGA...", "topic/gnss")
        transport.round_robin_manager.add_receiver_command_payload.assert_called_once()

    def test_rescue_router_helpers(self):
        from app.features.rescue.router import (
            _parse_rescue_request_payload,
            _broadcast_rescue_request_events,
        )
        import asyncio
        async def run_rescue():
            req_json = MagicMock()
            req_json.json = AsyncMock(return_value={
                "requester_name": "Test",
                "phone": "0987654321",
                "message": "Can cuu ho",
                "latitude": 10.5,
                "longitude": 106.5,
                "rescue_type": "landslide",
            })
            payload, img = await _parse_rescue_request_payload(req_json, "application/json")
            self.assertEqual(payload.requester_name, "Test")

            row = MagicMock(id=1, created_at=1000, requester_name="Test", phone="09", latitude=10.5, longitude=106.5, accuracy_m=1.0, status="pending")
            incident_case = MagicMock(id=1, revision=1, version=1, project_id=1, station_id=1)
            incident_event = MagicMock(id=1, sequence=1)
            parsed = {"text": "msg", "rescue_type": "landslide", "province_city": "HN", "source_link": "", "image_url": ""}
            await _broadcast_rescue_request_events(row, incident_case, incident_event, True, parsed)

        asyncio.run(run_rescue())

    def test_auth_validate_user_credentials(self):
        from app.features.authentication.router import _validate_user_credentials
        from fastapi import HTTPException
        import asyncio

        async def run_auth():
            form = MagicMock(username="x" * 255, password="secret")
            with self.assertRaises(HTTPException):
                await _validate_user_credentials(form, MagicMock())

            form2 = MagicMock(username="user", password="x" * 75)
            with self.assertRaises(HTTPException):
                await _validate_user_credentials(form2, MagicMock())

        asyncio.run(run_auth())

    def test_websocket_validation_helpers(self):
        from app.features.frontend.websocket import (
            _validate_ws_preconditions,
            _validate_ws_payload,
        )
        import asyncio

        async def run_ws():
            ws = MagicMock()
            ws.headers = {"origin": "http://disallowed.example"}
            ws.close = AsyncMock()
            with patch.object(settings, "CORS_ORIGINS", "http://allowed.example"):
                self.assertIsNone(await _validate_ws_preconditions(ws))

            ws2 = MagicMock()
            ws2.headers = {}
            ws2.url.path = "/invalid/ws"
            ws2.close = AsyncMock()
            self.assertIsNone(await _validate_ws_preconditions(ws2))

            payload = {"sub": "user1", "channel": "operations", "purpose": "websocket", "jti": "jti123", "session_id": "s1"}
            u, c, j, p = _validate_ws_payload(payload, "/ws/operations")
            self.assertEqual(u, "user1")
            self.assertEqual(c, "operations")

        asyncio.run(run_ws())

    def test_cors_stations_helpers(self):
        from app.features.projects.cors_stations import (
            _should_return_cached_cors,
            _check_cors_retry_cooldown,
            _handle_cors_fetch_exception,
        )
        import requests

        self.assertFalse(_should_return_cached_cors(True, 10.0))
        self.assertFalse(_check_cors_retry_cooldown(True, 5.0, 10.0))

        # Check HTTPError 401 raises
        mock_resp = MagicMock(status_code=401)
        http_err = requests.HTTPError(response=mock_resp)
        with self.assertRaises(requests.HTTPError):
            _handle_cors_fetch_exception(http_err, False, 10.0)

    def test_station_create_devices_helper(self):
        from app.features.stations.query_router import _create_station_devices

        db_mock = MagicMock()
        st_mock = MagicMock(station_code="ST01", name="Station 01", id=10)
        sensors = {
            "gnss": {"topic": "station/ST01/gnss", "mqtt": {"qos": 1}},
            "rain": {"topic": ""},  # Empty topic skipped
        }
        _create_station_devices(db_mock, st_mock, sensors)
        self.assertEqual(db_mock.add.call_count, 1)

    def test_processors_cors_helpers(self):
        from processors.gnss_adjustment.cors import RoundRobinCorsMixin, PUBLIC_MAP_STATIONS_ENDPOINT

        mixin = RoundRobinCorsMixin()
        mixin._cors_token_sync = MagicMock(return_value="cors_token123")

        path, tok = mixin._resolve_cors_path_and_token(PUBLIC_MAP_STATIONS_ENDPOINT, None)
        self.assertEqual(path, "/api/integrations/stations")
        self.assertEqual(tok, "cors_token123")

        path2, tok2 = mixin._resolve_cors_path_and_token(PUBLIC_MAP_STATIONS_ENDPOINT, "bearer_normal")
        self.assertEqual(path2, "/api/map/stations")

        dev_path = "/api/devices/DEV1/configure-service"
        res_dev, _ = mixin._resolve_cors_path_and_token(dev_path, "cors_token")
        self.assertEqual(res_dev, "/api/integrations/stations/DEV1/configure-service")

    def test_sensor_catalog_helpers(self):
        from app.shared.sensor_catalog import (
            _process_extensometer_payload,
            _validate_fields,
            _validate_optional_metrics,
            _validate_metadata,
            _validate_waveform,
            process_monitoring_payload,
        )

        # _process_extensometer_payload invalid points
        self.assertIsNone(_process_extensometer_payload({}, "mm"))
        self.assertIsNone(_process_extensometer_payload({"points": "bad"}, "mm"))
        self.assertIsNone(_process_extensometer_payload({"points": {"": 1.0}}, "mm"))
        self.assertIsNone(_process_extensometer_payload({"points": {"k" * 81: 1.0}}, "mm"))
        self.assertIsNone(_process_extensometer_payload({"points": {"p1": True}}, "mm"))
        self.assertEqual(_process_extensometer_payload({"points": {"p1": 12.5}}, "mm"), {"points": {"p1": 12.5}, "unit": "mm"})

        # _validate_fields invalid
        res = {}
        self.assertFalse(_validate_fields({"f1": "string"}, ["f1"], res))
        self.assertTrue(_validate_fields({"f1": 10.0}, ["f1"], res))
        self.assertEqual(res["f1"], 10.0)

        # _validate_optional_metrics
        res_opt = {}
        self.assertFalse(_validate_optional_metrics({"opt": "bad"}, [{"field": "opt"}], res_opt))
        self.assertTrue(_validate_optional_metrics({"opt": 5.5}, [{"field": "opt"}], res_opt))

        # _validate_metadata
        res_meta = {}
        self.assertFalse(_validate_metadata({"measured_at": -1}, res_meta))
        self.assertFalse(_validate_metadata({"sequence": -1}, res_meta))
        self.assertFalse(_validate_metadata({"sequence": True}, res_meta))
        self.assertFalse(_validate_metadata({"quality": "invalid_val"}, res_meta))
        self.assertFalse(_validate_metadata({"model": ""}, res_meta))
        self.assertTrue(_validate_metadata({"measured_at": 1700000000, "quality": "valid"}, res_meta))

        # _validate_waveform
        res_wave = {}
        self.assertTrue(_validate_waveform({}, "accelerometer", res_wave))
        self.assertFalse(_validate_waveform({"waveform": {}}, "rain", res_wave))
        self.assertFalse(_validate_waveform({"waveform": "bad"}, "accelerometer", res_wave))
        self.assertFalse(_validate_waveform({"waveform": {"sample_rate_hz": 0}}, "accelerometer", res_wave))
        self.assertFalse(_validate_waveform({"waveform": {"sample_rate_hz": 50, "start_at": -1}}, "accelerometer", res_wave))
        self.assertFalse(_validate_waveform({"waveform": {"sample_rate_hz": 50, "start_at": 1700000000, "x": [1], "y": [1, 2], "z": [1]}}, "accelerometer", res_wave))

    def test_station_configuration_helpers(self):
        from app.features.stations.configuration import (
            _merge_station_config,
            _auto_compute_station_location,
        )

        st = MagicMock()
        st.id = 5
        st.config = {
            "gnss_origin": {"lat": 21.0, "lon": 105.0},
            "offline_thresholds": 100,
        }
        user = MagicMock()
        cfg_data = {
            "config": {
                "gnss_origin": {"lat": 0.0, "lon": 0.0},
                "vn2000_params": {"zone": 48},
                "nested": {"key": 1},
            }
        }
        with patch("app.features.stations.configuration.flag_modified"):
            _merge_station_config(st, cfg_data, user)
        # GNSS origin locked preserved
        self.assertEqual(st.config["gnss_origin"]["lat"], 21.0)
        self.assertEqual(st.config["vn2000"], {"zone": 48})

        # _auto_compute_station_location
        st.location = None
        st.config = {
            "rain_origin": {"lat": 21.0, "lon": 105.0},
            "piezometer_origin": {"lat": 21.2, "lon": 105.2},
        }
        _auto_compute_station_location(st)
        self.assertEqual(st.location["lat"], 21.1)
        self.assertEqual(st.location["lon"], 105.1)

    def test_topics_bridge_helpers(self):
        from app.mqtt.bridge.topics import MQTTTopicMixin

        mixin = MQTTTopicMixin()
        mixin.runtime_mqtt = {
            "broker": "default.broker",
            "port": 1883,
            "user": "defuser",
            "password": "defpassword",
        }
        mixin.processors_cache = {}

        # 1. _resolve_device_broker_config
        dev = MagicMock(config={"mqtt": {"host": "custom.broker", "port": 8883, "username": "u", "password": "p", "use_tls": True}})
        st = MagicMock(config={})
        key = mixin._resolve_device_broker_config(dev, st)
        self.assertEqual(key, ("custom.broker", 8883, "u", "p", True))

        # Fallback to runtime_mqtt
        dev_empty = MagicMock(config={})
        key_def = mixin._resolve_device_broker_config(dev_empty, st)
        self.assertEqual(key_def, ("default.broker", 1883, "defuser", "defpassword", False))

        # 2. _resolve_device_processor
        dev_rain = MagicMock(id=1, device_type="rain")
        self.assertTrue(mixin._resolve_device_processor(dev_rain, st, "device_1", "context"))
        self.assertIn("device_1", mixin.processors_cache)

        dev_unsupported = MagicMock(id=2, device_type="nonexistent_type")
        self.assertFalse(mixin._resolve_device_processor(dev_unsupported, st, "device_2", "context"))

        # 3. _stop_unused_mqtt_clients
        mock_client = MagicMock()
        b_key = ("broker1", 1883, None, None, False)
        mixin._sub_clients = {b_key: mock_client}
        mixin._client_topics = {b_key: {"topic1"}}
        mixin._stop_unused_mqtt_clients({})
        mock_client.disconnect.assert_called_once()
        self.assertNotIn(b_key, mixin._sub_clients)

    def test_query_router_advanced_payload(self):
        from app.features.stations.query_router import _format_gnss_advanced_payload

        self.assertIsNone(_format_gnss_advanced_payload(None))
        raw = {"pos_e": 10.0, "pos_n": 20.0, "pos_u": 30.0}
        formatted = _format_gnss_advanced_payload(raw)
        self.assertEqual(formatted["adv_x"], 10.0)
        self.assertEqual(formatted["adv_y"], 20.0)
        self.assertEqual(formatted["adv_h"], 30.0)
        self.assertEqual(formatted["adv_dx"], 0.0)

    def test_cors_base_stations_helpers(self):
        from app.features.projects.cors_stations import (
            _resolve_cors_online_status,
            _extract_cors_streams,
            _parse_cors_station_item,
        )

        # _resolve_cors_online_status
        self.assertTrue(_resolve_cors_online_status({"is_online": True}, ""))
        self.assertTrue(_resolve_cors_online_status({}, "active"))
        self.assertTrue(_resolve_cors_online_status({"ntrip_connected": True}, ""))
        self.assertFalse(_resolve_cors_online_status({}, "offline"))

        # _extract_cors_streams fallback
        svc_cfg = {
            "serverhost1": "cors1.vn",
            "mountpoint1": "BASE01",
            "serverport1": 2101,
            "server1_enabled": True,
        }
        streams = _extract_cors_streams({}, svc_cfg)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["server_id"], 1)

        # _parse_cors_station_item invalid
        self.assertIsNone(_parse_cors_station_item(None))
        self.assertIsNone(_parse_cors_station_item({"lat": "bad", "lon": 105.0}))
        self.assertIsNone(_parse_cors_station_item({"lat": 95.0, "lon": 105.0}))

        # _parse_cors_station_item valid
        item = {
            "name": "HN01",
            "lat": 21.0,
            "lon": 105.0,
            "alt": 20.0,
            "status": "online",
            "service_config": svc_cfg,
        }
        parsed = _parse_cors_station_item(item)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["name"], "HN01")
        self.assertTrue(parsed["is_online"])

    def test_query_router_stations_helpers(self):
        import time
        from unittest.mock import MagicMock
        from app.features.stations.query_router import (
            _build_stations_query,
            _compute_station_online,
            _serialize_station_row,
        )
        from fastapi import HTTPException

        # _build_stations_query
        q1 = _build_stations_query(1, "test", "name")
        self.assertIsNotNone(q1)
        q2 = _build_stations_query(1, None, "-created_at")
        self.assertIsNotNone(q2)
        with self.assertRaises(HTTPException):
            _build_stations_query(1, None, "unsupported_field")

        # _compute_station_online
        station = MagicMock()
        station.id = 10
        station.config = {}
        d1 = MagicMock(device_type="gnss")
        self.assertFalse(_compute_station_online(station, [d1], {}, int(time.time())))
        self.assertTrue(_compute_station_online(station, [d1], {(10, "gnss"): int(time.time())}, int(time.time())))

        # _serialize_station_row
        d1.id = 101
        d1.device_code = "DEV01"
        d1.name = "GNSS Dev"
        d1.mqtt_topic = "topic/gnss"
        station.station_code = "ST01"
        station.name = "Station 1"
        station.location = {}
        station.status = "online"
        serialized = _serialize_station_row(station, [d1], True, include_runtime=True)
        self.assertEqual(serialized["id"], 10)
        self.assertEqual(serialized["status"], "online")
        self.assertEqual(len(serialized["devices"]), 1)

    def test_gnss_runtime_validation_helpers(self):
        import numpy as np
        from processors.gnss.runtime import GNSSRuntimeMixin

        class MockRuntime(GNSSRuntimeMixin):
            def __init__(self):
                self.origin = {"lat": 10.0, "lon": 105.0, "h": 50.0}
                self._origin_locked_at = 1000
                self._origin_record_id = 1
                self.tracking_offset_enu = np.array([0.0, 0.0, 0.0])
                self.min_fix_quality = 4
                self.reacquire_candidates = [{"pos_enu": [1.0, 2.0, 3.0], "fix_quality": 4, "ts": 1005}]

        runtime = MockRuntime()
        # _snapshot_reacquire_candidates
        candidates, quarantine = runtime._snapshot_reacquire_candidates()
        self.assertEqual(len(candidates), 1)

        # _validate_stored_origin_and_offset
        val_bad_origin = {"origin": None}
        self.assertFalse(runtime._validate_stored_origin_and_offset(val_bad_origin))
        val_good = {
            "origin": {"id": 1, "lat": 10.0, "lon": 105.0, "h": 50.0, "locked_at": 1000},
            "tracking_offset_enu": [0.0, 0.0, 0.0],
        }
        self.assertTrue(runtime._validate_stored_origin_and_offset(val_good))

        # _validate_stored_quarantine
        self.assertEqual(runtime._validate_stored_quarantine(None, 1000.0), ([], None))
        self.assertIsNone(runtime._validate_stored_quarantine({"started_at": 999}, 1000.0))
        valid_q = {
            "started_at": 1001,
            "candidates": [{"pos_enu": [1.0, 2.0, 3.0], "fix_quality": 4, "ts": 1002}],
        }
        res = runtime._validate_stored_quarantine(valid_q, 1000.0)
        self.assertIsNotNone(res)
        restored, started = res
        self.assertEqual(started, 1001.0)
        self.assertEqual(len(restored), 1)

    def test_ingest_spool_envelope(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from app.mqtt.persistence.ingest import SensorIngestPersistenceMixin

        mixin = SensorIngestPersistenceMixin()
        mock_spool = MagicMock()
        mock_spool.acknowledge = AsyncMock()
        mixin._get_ingest_spool = MagicMock(return_value=mock_spool)
        mixin._ensure_ingest_metrics()

        # Non-dict envelope
        self.assertFalse(asyncio.run(mixin._process_spool_envelope("not a dict")))

        # Empty records envelope acknowledges and returns True
        self.assertTrue(asyncio.run(mixin._process_spool_envelope({"batch_id": "b1", "records": []})))
        mock_spool.acknowledge.assert_called_with("b1")

        # Valid envelope
        mixin._persist_sensor_batch = AsyncMock(return_value={"inserted": 5, "deduped": 1})
        valid_env = {"batch_id": "b2", "records": [{"val": 123}]}
        self.assertTrue(asyncio.run(mixin._process_spool_envelope(valid_env)))
        self.assertEqual(mixin._ingest_metrics["inserted"], 5)
        self.assertEqual(mixin._ingest_metrics["deduped"], 1)

        # Failure during persistence returns False
        mixin._persist_sensor_batch = AsyncMock(side_effect=RuntimeError("db err"))
        self.assertFalse(asyncio.run(mixin._process_spool_envelope(valid_env)))
        self.assertEqual(mixin._ingest_metrics["spool_retries"], 1)

    def test_landslide_alerts_helpers(self):
        import time
        from processors.landslide.alerts import (
            _init_alert_counter,
            _step_alert_counter,
            _handle_safe_deassertion,
        )

        counter = {}
        _init_alert_counter(counter)
        self.assertIsNone(counter["latched_level"])
        self.assertEqual(counter["safe_count"], 0)

        # Step counter with new level
        counter["last_level"] = None
        self.assertFalse(_step_alert_counter(counter, "WARNING", required_steps=2))
        self.assertEqual(counter["count"], 1)
        self.assertEqual(counter["last_level"], "WARNING")

        # Step counter again to latch
        self.assertTrue(_step_alert_counter(counter, "WARNING", required_steps=2))
        self.assertEqual(counter["latched_level"], "WARNING")

        # Already latched level returns False
        self.assertFalse(_step_alert_counter(counter, "WARNING", required_steps=2))

        # Level change resets count
        self.assertFalse(_step_alert_counter(counter, "CRITICAL", required_steps=2))
        self.assertEqual(counter["count"], 1)
        self.assertEqual(counter["last_level"], "CRITICAL")

        # Deassertion with pending safe count
        pending = _handle_safe_deassertion(counter, safe_confirm_steps=3, station_id=1, label="TILT")
        self.assertEqual(pending, {"level": "PENDING"})
        self.assertEqual(counter["safe_count"], 1)

        # Reach safe confirm steps resets counter
        _handle_safe_deassertion(counter, safe_confirm_steps=2, station_id=1, label="TILT")
        self.assertIsNone(counter["latched_level"])
        self.assertEqual(counter["count"], 0)

        # Deassertion with timeout > 900s
        counter["latched_level"] = "WARNING"
        counter["latched_time"] = time.time() - 1000
        res = _handle_safe_deassertion(counter, safe_confirm_steps=3, station_id=1, label="TILT")
        self.assertIsNone(res)
        self.assertIsNone(counter["latched_level"])

        # Deassertion without latched level decrements count
        counter["count"] = 2
        _handle_safe_deassertion(counter, safe_confirm_steps=3, station_id=1, label="TILT")
        self.assertEqual(counter["count"], 1)
        _handle_safe_deassertion(counter, safe_confirm_steps=3, station_id=1, label="TILT")
        self.assertEqual(counter["count"], 0)
        self.assertIsNone(counter["last_level"])

    def test_gnss_velocity_helpers(self):
        import numpy as np
        from processors.gnss.velocity import GNSSVelocityMixin

        # Config parsing with defaults
        cfg = GNSSVelocityMixin._parse_velocity_confirmation_config({})
        self.assertEqual(cfg, (3, 30.0, 0.70, 15.0, 30.0))

        # Config parsing with invalid types
        cfg2 = GNSSVelocityMixin._parse_velocity_confirmation_config({
            "velocity_confirmation_samples": "invalid",
            "velocity_confirmation_duration_s": None,
            "velocity_confirmation_direction_cosine": "abc",
            "velocity_confirmation_min_gap_s": {},
            "velocity_confirmation_max_gap_s": [],
        })
        self.assertEqual(cfg2, (3, 30.0, 0.70, 15.0, 30.0))

        # Valid motion checks
        vec = np.array([1.0, 0.0, 0.0])
        self.assertTrue(GNSSVelocityMixin._is_valid_motion(100.0, vec, True, True))
        self.assertFalse(GNSSVelocityMixin._is_valid_motion(float("nan"), vec, True, True))
        self.assertFalse(GNSSVelocityMixin._is_valid_motion(100.0, np.array([0.0, 0.0, 0.0]), True, True))
        self.assertFalse(GNSSVelocityMixin._is_valid_motion(100.0, vec, False, True))
        self.assertFalse(GNSSVelocityMixin._is_valid_motion(100.0, vec, True, False))

    def test_cors_refactored_helpers(self):
        # _apply_stream_to_cors_cfg
        cfg = {}
        stream = {
            "server_id": 1,
            "mountpoint": "TEST1",
            "host": "cors.example.com",
            "port": 2101,
            "format": "RTCM3",
            "carrier": "2",
            "lat": 21.0,
            "lon": 105.0,
            "alt": 10.0,
        }
        RoundRobinCorsMixin._apply_stream_to_cors_cfg(cfg, stream, 1)
        self.assertEqual(cfg["mountpoint1"], "TEST1")
        self.assertEqual(cfg["serverhost1"], "cors.example.com")
        self.assertEqual(cfg["serverport1"], 2101)

        # _match_cors_station_servers
        mixin = RoundRobinCorsMixin()
        station_entry = {
            "serial": "SN123",
            "service_config": {
                "mountpoint1": "ALPHA",
                "serverhost1": "cors.example.com",
            },
        }
        res_matches = mixin._match_cors_station_servers(
            station_entry, "alpha", "cors.example.com", "sn123", 1
        )
        self.assertEqual(len(res_matches), 1)
        self.assertEqual(res_matches[0][0], "SN123")
        self.assertEqual(res_matches[0][1], 1)

        # _match_station_candidate_servers
        station_cand = {
            "service_config": {
                "mountpoint1": "HANOI",
                "serverhost1": "cors.example.com",
            }
        }
        cand_matches = mixin._match_station_candidate_servers(
            station_cand, 1, "cors.example.com", "hanoi"
        )
        self.assertEqual(len(cand_matches), 1)
        self.assertEqual(cand_matches[0][1], 1)

    def test_observation_refactored_helpers(self):
        import asyncio
        from processors.gnss_adjustment.observation import (
            RoundRobinObservationMixin,
            _CommandAckWaiter,
        )

        # _collect_diagnostics_raw_gnss
        fake_rec = MagicMock()
        fake_rec.base_name = "BASE"
        fake_rec.observation = MagicMock(epoch_ts=100.0, station_id=1, raw="$RAW")
        fake_session = {
            "clusters": [
                {"observations": [fake_rec]}
            ]
        }
        res = RoundRobinObservationMixin._collect_diagnostics_raw_gnss(fake_session)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["station_id"], 1)

        # _extract_agrica_complete_and_tail
        records, tail = RoundRobinObservationMixin._extract_agrica_complete_and_tail(
            "#AGRICA,1,2*45\r\n#AGRICA,3,4*56\r\npartial_tail"
        )
        self.assertEqual(records, ["#AGRICA,1,2*45", "#AGRICA,3,4*56"])
        self.assertEqual(tail, "")

        # _resolve_observation_best_llh
        self.assertEqual(
            RoundRobinObservationMixin._resolve_observation_best_llh(
                (21.0, 105.0, 50.0), None
            ),
            (21.0, 105.0, 50.0),
        )

        # _populate_rover_llh_cache_metadata
        mock_obs = MagicMock()
        mock_obs.rover_llh = (21.0, 105.0, 50.0)
        mock_obs.rover_ecef = None
        mock_obs.rover_name = "ROV1"
        mock_obs.full_data = {"undulation": 2.5}
        cache_entry = {}
        RoundRobinObservationMixin._populate_rover_llh_cache_metadata(
            cache_entry, mock_obs, (21.0, 105.0, 50.0), (21.0, 105.0, 50.0)
        )
        self.assertEqual(cache_entry["undulation"], 2.5)

        # _process_framed_command_line
        waiter = _CommandAckWaiter("STA1", "MODE ROVER", MagicMock())
        res = RoundRobinObservationMixin._process_framed_command_line(
            waiter, "$COMMAND,MODE ROVER,RESPONSE:OK*12", "topic/cmd"
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["accepted"])

        # Unframed line
        waiter2 = _CommandAckWaiter("STA1", "UNLOGALL", MagicMock())
        res_echo = RoundRobinObservationMixin._process_unframed_command_line(
            waiter2, "UNLOGALL", "topic/cmd"
        )
        self.assertIsNone(res_echo)
        self.assertTrue(waiter2.echo_seen)
        res_ok = RoundRobinObservationMixin._process_unframed_command_line(
            waiter2, "OK", "topic/cmd"
        )
        self.assertIsNotNone(res_ok)
        self.assertTrue(res_ok["accepted"])

    def test_results_and_receiver_refactored_helpers(self):
        import asyncio
        from processors.gnss_adjustment.results import RoundRobinResultsMixin
        from processors.gnss_adjustment.receiver import RoundRobinReceiverMixin

        # 1. _filter_vector_outliers - insufficient samples
        samples = [
            {"from": "A", "to": "B", "delta": [1.0, 2.0, 3.0], "raw_index": 0},
            {"from": "A", "to": "B", "delta": [1.0, 2.0, 3.0], "raw_index": 1},
        ]
        filtered, diags = RoundRobinResultsMixin._filter_vector_outliers(samples, min_samples=5)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(diags[0]["vector_filter_status"], "NOT_EVALUATED_INSUFFICIENT_GROUP")

        # 2. _filter_vector_outliers - with outlier
        samples_norm = [
            {"from": "A", "to": "B", "delta": [10.0, 20.0, 30.0], "raw_index": i}
            for i in range(6)
        ]
        samples_norm.append({"from": "A", "to": "B", "delta": [100.0, 200.0, 300.0], "raw_index": 6})
        filtered, diags = RoundRobinResultsMixin._filter_vector_outliers(
            samples_norm, min_samples=5, absolute_floor_m=1.0, sigma_multiplier=3.0
        )
        self.assertEqual(len(filtered), 6)
        self.assertEqual(diags[-1]["vector_filter_status"], "EVALUATED_OUTLIER")

        # 3. _filter_position_type_mixes
        mix_samples = [
            {"from": "A", "to": "B", "delta": [1.0, 2.0, 3.0], "position_type": 4, "raw_index": 0},
            {"from": "A", "to": "B", "delta": [1.0, 2.0, 3.0], "position_type": 7, "raw_index": 1},
        ]
        filtered_mix, diags_mix = RoundRobinResultsMixin._filter_position_type_mixes(mix_samples)
        self.assertEqual(len(filtered_mix), 1)
        self.assertEqual(filtered_mix[0]["position_type"], 4)
        self.assertEqual(len(diags_mix), 1)

        # 4. _weighted_edges
        import numpy as np
        results_inst = RoundRobinResultsMixin()
        results_inst.STABILITY_EWMA_FAST_TAU_SECONDS = 3.0
        results_inst.STABILITY_EWMA_SLOW_TAU_SECONDS = 30.0
        edge_samples = [
            {"from": "A", "to": "B", "delta": [1.0, 2.0, 3.0], "std": [0.01, 0.01, 0.01], "covariance": np.eye(3) * 0.0001, "observation_epoch": 100, "raw_index": 0, "ratio": 2.5, "velocity_up_std": 0.01},
            {"from": "A", "to": "B", "delta": [1.01, 1.99, 3.02], "std": [0.01, 0.01, 0.01], "covariance": np.eye(3) * 0.0001, "observation_epoch": 101, "raw_index": 1, "ratio": 2.5, "velocity_up_std": 0.01},
        ]
        weighted = results_inst._weighted_edges(edge_samples)
        self.assertEqual(len(weighted), 1)
        self.assertEqual(weighted[0]["from"], "A")
        self.assertEqual(weighted[0]["to"], "B")

        # 5. _handle_rover_restore_failure in receiver
        receiver_inst = RoundRobinReceiverMixin()
        receiver_inst._emit_progress = AsyncMock()
        receiver_inst._last_set_error = "test error"

        res_undul = asyncio.run(receiver_inst._handle_rover_restore_failure(
            rover_code="ROV1",
            command_text="config undulation test",
            command_index=2,
            total_commands=5,
            project_id=1,
            attempt=1,
            set_transport_failure=False,
        ))
        self.assertTrue(res_undul)

        res_save = asyncio.run(receiver_inst._handle_rover_restore_failure(
            rover_code="ROV1",
            command_text="saveconfig",
            command_index=5,
            total_commands=5,
            project_id=1,
            attempt=1,
            set_transport_failure=False,
        ))
        self.assertFalse(res_save)

        with self.assertRaises(RuntimeError):
            asyncio.run(receiver_inst._handle_rover_restore_failure(
                rover_code="ROV1",
                command_text="mode rover",
                command_index=1,
                total_commands=5,
                project_id=1,
                attempt=1,
                set_transport_failure=False,
            ))

        with self.assertRaises(RuntimeError):
            asyncio.run(receiver_inst._handle_rover_restore_failure(
                rover_code="ROV1",
                command_text="mode rover",
                command_index=1,
                total_commands=5,
                project_id=1,
                attempt=1,
                set_transport_failure=True,
            ))








