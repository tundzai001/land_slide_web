import time
import unittest
from types import SimpleNamespace

from app.features.stations.router import _summarize_station_alerts


class AlertPersistenceContractTests(unittest.TestCase):
    def test_unresolved_alert_survives_ttl_as_explicit_stale_state(self):
        alert = SimpleNamespace(
            level="CRITICAL",
            category="gnss_velocity",
            message="GNSS reference change was rejected",
            timestamp=int(time.time()) - 3600,
        )

        result = _summarize_station_alerts(
            [alert],
            {
                "alert_ttl_seconds": {"gnss_velocity": 60},
                "alerting": {"enabled": True},
            },
        )

        self.assertEqual(result["overall_risk"], "CRITICAL")
        self.assertEqual(len(result["active_alerts"]), 1)
        self.assertEqual(len(result["stale_alerts"]), 1)
        self.assertEqual(result["active_alerts"][0]["stale"], True)
        self.assertEqual(result["active_alerts"][0]["message"], alert.message)
        self.assertEqual(result["fresh_alerts"], [])

    def test_resolved_alerts_are_not_reintroduced(self):
        result = _summarize_station_alerts([], {"alerting": {"enabled": True}})
        self.assertEqual(result["overall_risk"], "LOW")
        self.assertEqual(result["active_alerts"], [])
        self.assertEqual(result["stale_alerts"], [])


if __name__ == "__main__":
    unittest.main()
