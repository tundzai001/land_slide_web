import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.mqtt.persistence.alerts import AlertPersistenceMixin


class DummyAlertManager(AlertPersistenceMixin):
    def __init__(self):
        self._alert_suppression_last_attempt = {}
        self._alert_suppression_interval_seconds = 5.0
        self._diag_last_log_ts = {}

    def _is_station_alerting_enabled(self, config):
        return True

    def _get_sensor_offline_threshold(self, config, sensor_type):
        return 60


class TestAlertPoolSafety(unittest.IsolatedAsyncioTestCase):
    async def test_get_station_active_alert_summary_reuses_passed_db_session(self):
        manager = DummyAlertManager()
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.all.return_value = []
        mock_db.execute.return_value = mock_res

        with patch("app.mqtt.persistence.alerts.DataSessionLocal") as mock_session_local:
            result = await manager._get_station_active_alert_summary(
                station_id=1,
                station_config={"alerting": {"enabled": True}},
                db=mock_db,
            )
            mock_session_local.assert_not_called()
            mock_db.execute.assert_awaited_once()
            self.assertEqual(result["risk_level"], "LOW")
            self.assertEqual(result["unresolved_count"], 0)

    async def test_suppress_station_alerts_skips_update_when_no_active_alerts(self):
        manager = DummyAlertManager()
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_res

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_db
        mock_context.__aexit__.return_value = None

        with patch("app.mqtt.persistence.alerts.DataSessionLocal", return_value=mock_context), \
             patch("app.websocket.manager.broadcast") as mock_broadcast:
            await manager._suppress_station_alerts(station_id=10)
            # Only SELECT was called, no UPDATE executed, no broadcast
            self.assertEqual(mock_db.execute.await_count, 1)
            mock_broadcast.assert_not_called()
