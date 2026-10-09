"""CORS integration response keeps map fields without exposing service credentials."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.features.projects.cors_stations import _normalize_cors_base_stations, get_cors_base_stations


class CorsIntegrationTests(unittest.TestCase):
    def test_offline_base_is_kept_and_credentials_are_not_returned(self):
        stations = _normalize_cors_base_stations([
            {
                "serial": "BASE-1", "name": "SinQuyen1", "lat": 22.6,
                "lon": 103.8, "alt": 165.2, "status": "awaiting_license",
                "ntrip_connected": False,
                "service_config": {
                    "server1_enabled": True, "mountpoint1": "SinQuyen1",
                    "password1": "SECRET", "username1": "PRIVATE",
                },
                "streams": [{
                    "stream_id": "s1", "host": "caster.example", "port": 2101,
                    "mountpoint": "SinQuyen1", "enabled": True,
                    "password": "SECRET",
                }],
            },
            {"name": "invalid", "lat": float("nan"), "lon": 103.8},
        ])
        self.assertEqual(len(stations), 1)
        station = stations[0]
        self.assertFalse(station["is_online"])
        self.assertEqual(station["service_config"], {
            "server1_enabled": True, "mountpoint1": "SinQuyen1",
        })
        self.assertEqual(station["streams"][0]["server_id"], 1)
        self.assertNotIn("SECRET", str(station))
        self.assertNotIn("PRIVATE", str(station))


class CorsPublicRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_and_offline_backup_are_visible_without_service_config(self):
        stations = _normalize_cors_base_stations([
            {"serial": "1", "name": "Primary", "lat": 22, "lon": 103,
             "status": "online", "service_config": {"password1": "SECRET"}},
            {"serial": "2", "name": "Backup", "lat": 22.1, "lon": 103.1,
             "status": "offline", "service_config": {"password1": "SECRET"}},
            {"serial": "3", "name": "Unrelated", "lat": 21, "lon": 105},
        ])
        project = SimpleNamespace(gnss_clusters=[{
            "base_station": "Primary", "backup_base_station": "Backup",
        }])
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [project]))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        request = Request({"type": "http", "headers": []})
        with patch("app.features.projects.cors_stations._fetch_cors_base_stations_sync", return_value=stations), \
             patch("app.features.projects.cors_stations.get_optional_current_user_from_request", new_callable=AsyncMock, return_value=None), \
             patch("app.features.projects.cors_stations.user_project_filter_ids", return_value=None):
            visible = await get_cors_base_stations(request, db, object())
        self.assertEqual({station["name"] for station in visible}, {"Primary", "Backup"})
        self.assertFalse(next(station for station in visible if station["name"] == "Backup")["station_online"])
        self.assertNotIn("SECRET", str(visible))
        self.assertTrue(all("service_config" not in station for station in visible))


if __name__ == "__main__":
    unittest.main()
