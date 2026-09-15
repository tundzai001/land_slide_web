import asyncio
import unittest
from types import SimpleNamespace

from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql

from app.routers.database_admin import (
    _device_runtime_state,
    admin_get_sensor_data,
)


class DeviceRuntimeStateTests(unittest.TestCase):
    def test_fresh_active_device_is_online(self):
        station = SimpleNamespace(config={"offline_thresholds": {"gnss": 45}})
        device = SimpleNamespace(device_type="gnss", last_data_time=980, is_active=True)

        state = _device_runtime_state(device, station, 1000)

        self.assertEqual(state["effective_status"], "online")
        self.assertEqual(state["age_seconds"], 20)
        self.assertEqual(state["offline_threshold_seconds"], 45)

    def test_stale_or_disabled_device_is_offline(self):
        station = SimpleNamespace(config={})
        stale = SimpleNamespace(device_type="gnss", last_data_time=900, is_active=True)
        disabled = SimpleNamespace(device_type="imu", last_data_time=999, is_active=False)

        self.assertEqual(_device_runtime_state(stale, station, 1000)["effective_status"], "offline")
        self.assertEqual(_device_runtime_state(disabled, station, 1000)["effective_status"], "offline")


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _SensorDb:
    def __init__(self, rows):
        self.rows = rows
        self.execute_count = 0
        self.last_query = None

    async def execute(self, query):
        self.execute_count += 1
        self.last_query = query
        return _RowsResult(self.rows)


class SensorDataFastPageTests(unittest.TestCase):
    def test_fast_page_skips_total_count_and_reports_has_more(self):
        rows = [
            SimpleNamespace(
                id=index,
                station_id=7,
                timestamp=1000 - index,
                sensor_type="gnss_adjusted",
                data_preview='{"type":"gnss_adjusted"}',
                value_1=None,
                value_2=None,
                value_3=None,
                value_4=None,
                value_5=None,
            )
            for index in range(1, 4)
        ]
        db = _SensorDb(rows)
        response = Response()

        result = asyncio.run(admin_get_sensor_data(
            response=response,
            offset=0,
            limit=2,
            sensor_type="gnss_adjusted",
            include_total=False,
            include_data=False,
            include_internal=True,
            db=db,
            current_user=None,
        ))

        self.assertEqual(db.execute_count, 1)
        self.assertEqual([row["id"] for row in result], [1, 2])
        self.assertEqual(response.headers["X-Has-More"], "true")
        self.assertNotIn("X-Total-Count", response.headers)
        sql = str(db.last_query.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("ADJUSTMENT_KEY IS NOT NULL", sql)
        self.assertNotIn("ROW_NUMBER", sql)

    def test_internal_stream_requires_explicit_opt_in(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(admin_get_sensor_data(
                response=Response(),
                sensor_type="gnss_adjusted",
                include_total=False,
                include_data=False,
                db=_SensorDb([]),
                current_user=None,
            ))

        self.assertEqual(raised.exception.status_code, 422)

if __name__ == "__main__":
    unittest.main()
