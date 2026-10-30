"""MQTT reception keeps stations online without refreshing old measurements."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response

from app.features.stations import query_router
from app.runtime import mqtt_service


def result(items):
    return SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: items), all=lambda: items,
        scalar_one_or_none=lambda: items[0] if items else None,
    )


class StationActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_station_list_uses_mqtt_heartbeat_when_processed_cache_is_old(self):
        now = 1_800_000_000
        stations = [SimpleNamespace(
            id=index, station_code=code, name=code, config={}, location=None,
        ) for index, code in enumerate(("CP03", "CP05", "CP06", "CP08", "CP01"), 1)]
        devices = [SimpleNamespace(
            id=index, station_id=index, device_type="gnss", mqtt_topic=f"device/{index}/upload",
            device_code=station.station_code, name=station.name,
            last_data_time=now - 1 if station.station_code == "CP05" else now - 100,
        ) for index, station in enumerate(stations, 1)]
        cache = [SimpleNamespace(
            station_id=station.id, sensor_type="gnss",
            timestamp=now - 1 if station.station_code in {"CP03", "CP08"} else now - 100,
        ) for station in stations]
        for elapsed in (0, 31):
            config_db = SimpleNamespace(execute=AsyncMock(side_effect=[result(stations), result(devices)]))
            data_db = SimpleNamespace(execute=AsyncMock(side_effect=[result(cache), result([])]))
            with (
                self.subTest(elapsed=elapsed),
                patch.object(mqtt_service, "_device_update_buffer", {3: now - 1}),
                patch.object(query_router.time, "time", return_value=now + elapsed),
            ):
                rows = await query_router.get_stations_by_project(
                    project_id=4, response=Response(), q=None, status=None, offset=None,
                    limit=None, sort=None, include_runtime=True, db_config=config_db,
                    db_data=data_db, current_user=SimpleNamespace(role="admin"),
                )
                expected = {station.station_code: "offline" for station in stations}
                if not elapsed:
                    expected.update({code: "online" for code in ("CP03", "CP05", "CP06", "CP08")})
                self.assertEqual({row["station_code"]: row["status"] for row in rows}, expected)
        self.assertEqual(cache[1].timestamp, now - 100)

    async def test_detail_keeps_old_measurement_timestamp_while_device_is_online(self):
        now = 1_800_000_000
        station = SimpleNamespace(
            id=13, project_id=4, name="CP06", station_code="CP06", config={},
            location=None, last_update=now - 100,
        )
        device = SimpleNamespace(id=16, station_id=13, device_type="gnss", last_data_time=now - 100)
        cache = SimpleNamespace(sensor_type="gnss", timestamp=now - 100, data={"status": "NO_DATA"})
        config_db = SimpleNamespace(execute=AsyncMock(side_effect=[result([station]), result([device]), result([])]))
        data_db = SimpleNamespace(execute=AsyncMock(side_effect=[result([cache]), result([])]))
        with (
            patch.object(mqtt_service, "_device_update_buffer", {16: now - 1}),
            patch.object(query_router.time, "time", return_value=now),
            patch.object(query_router, "get_optional_current_user_from_request", AsyncMock(return_value=None)),
            patch.object(query_router, "_calculate_station_risk_assessment", AsyncMock(return_value={})),
        ):
            row = await query_router.get_station_detail(
                station_id=13, request=None, include_history=False,
                db_config=config_db, db_data=data_db, db_auth=None,
            )
        self.assertEqual(row["status"], "online")
        self.assertTrue(row["sensors"]["gnss"]["is_online"])
        self.assertEqual(row["sensors"]["gnss"]["latest_timestamp"], now - 100)
        self.assertEqual(row["sensors"]["gnss"]["last_received_timestamp"], now - 1)
        self.assertEqual(row["sensors"]["gnss"]["latest"]["status"], "NO_DATA")
