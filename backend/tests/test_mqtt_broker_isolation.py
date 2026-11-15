import asyncio
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.mqtt.bridge.topics import MQTTTopicMixin


class BrokerIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_brokers_start_independently_and_failed_setup_is_retried(self):
        await self.check_broker_retry()

    async def test_tls_setup_failure_never_connects_without_tls(self):
        await self.check_broker_retry(tls_failure=True)

    async def check_broker_retry(self, tls_failure=False):
        bridge = MQTTTopicMixin()
        bridge.runtime_mqtt = dict(broker="default.example", port=1883, user="", password="")
        bridge.processors_cache = {"device_1": None, "device_2": None}
        bridge._sub_clients = {}
        bridge._client_topics = defaultdict(set)
        bridge.topic_reload_interval = 60
        bridge.on_connect = Mock()
        bridge.on_message = Mock()
        bridge.on_disconnect = Mock()
        bridge.on_connect_fail = Mock()
        bridge._apply_runtime_defaults_to_station_config = lambda config: config
        rows = []
        for index, host in enumerate(("aitogy.asia", "aitogy.click"), 1):
            device = SimpleNamespace(
                id=index, name=host, device_code=str(index), device_type="rain",
                mqtt_topic=f"gnss/{index}", config={"mqtt": {"host": host, "use_tls": tls_failure}},
            )
            station = SimpleNamespace(
                id=index, name=host, station_code=str(index), config={},
            )
            project = SimpleNamespace(id=1, name="test", project_code="test", gnss_clusters=[])
            rows.append((device, station, project))
        session = AsyncMock()
        session.execute.return_value = Mock(all=Mock(return_value=rows))
        context = AsyncMock()
        context.__aenter__.return_value = session
        failed_client, healthy_client, retried_client = Mock(), Mock(), Mock()
        if tls_failure:
            failed_client.tls_set_context.side_effect = ValueError("invalid TLS setup")
        else:
            failed_client.connect_async.side_effect = ValueError("invalid setup")

        with (
            patch("app.mqtt.bridge.topics.ConfigSessionLocal", return_value=context),
            patch("app.mqtt.bridge.topics.mqtt.Client", side_effect=[failed_client, healthy_client, retried_client]),
            patch("app.mqtt.bridge.topics.asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            for _ in range(2):
                with self.assertRaises(asyncio.CancelledError):
                    await bridge.reload_topics_from_db()

        if tls_failure:
            failed_client.connect_async.assert_not_called()

        healthy_client.connect_async.assert_called_once_with("aitogy.click", 1883, 60)
        healthy_client.loop_start.assert_called_once()
        healthy_client.subscribe.assert_called_once_with("gnss/2")
        retried_client.connect_async.assert_called_once_with("aitogy.asia", 1883, 60)
        retried_client.loop_start.assert_called_once()
        retried_client.subscribe.assert_called_once_with("gnss/1")
        for client in (failed_client, healthy_client, retried_client):
            client.connect.assert_not_called()
        self.assertEqual(len(bridge._sub_clients), 2)
