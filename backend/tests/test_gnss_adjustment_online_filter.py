import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.features.gnss_adjustment.clusters import (
    restrict_clusters_to_online_stations,
    streaming_gnss_station_ids,
)


class GnssAdjustmentOnlineFilterTests(unittest.TestCase):
    def test_recent_mqtt_payload_recovers_stations_while_db_is_stale(self):
        clusters = [{
            "name": "Dam 4",
            "stations": [4, 5],
            "rovers": ["Dap4_1", "Dap4_2"],
        }]
        stations = {
            4: SimpleNamespace(config={"offline_thresholds": {"gnss": 90}}),
            5: SimpleNamespace(config={"offline_thresholds": {"gnss": 90}}),
        }

        def stream_health(rover_code, *, freshness_seconds):
            self.assertIn(rover_code, {"Dap4_1", "Dap4_2"})
            self.assertEqual(freshness_seconds, 90.0)
            return {"payload_recent": True}

        with patch(
            "app.features.gnss_adjustment.clusters.mqtt_service.round_robin_manager.get_gnss_stream_health",
            side_effect=stream_health,
        ):
            online = streaming_gnss_station_ids(clusters, stations)

        active, excluded = restrict_clusters_to_online_stations(
            clusters,
            online,
        )
        self.assertEqual(active[0]["stations"], [4, 5])
        self.assertEqual(excluded, [])

    def test_failure_identifies_online_and_offline_rovers(self):
        clusters = [{
            "name": "Dam 4",
            "stations": [4, 5, 6],
            "rovers": ["Dap4_1", "Dap4_2", "Dap4_3"],
        }]

        with self.assertRaisesRegex(
            ValueError,
            r"Dam 4: online=\['Dap4_1'\], offline=\['Dap4_2', 'Dap4_3'\]",
        ):
            restrict_clusters_to_online_stations(clusters, {4})


if __name__ == "__main__":
    unittest.main()
