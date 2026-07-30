import asyncio
import unittest

from app.mqtt.persistence import MQTTPersistenceMixin


class _BufferedPersistence(MQTTPersistenceMixin):
    def __init__(self):
        self._buffer_lock = asyncio.Lock()
        self._latest_cache_buffer = {}


class LatestSensorCacheBufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_coalesces_to_newest_value_per_station_and_sensor(self):
        persistence = _BufferedPersistence()

        await persistence._upsert_latest_sensor_cache(8, "gnss", 200, {"x": 2})
        await persistence._upsert_latest_sensor_cache(8, "gnss", 100, {"x": 1})
        await persistence._upsert_latest_sensor_cache(8, "rain", 150, {"mm": 3})

        self.assertEqual(len(persistence._latest_cache_buffer), 2)
        self.assertEqual(
            persistence._latest_cache_buffer[(8, "gnss")],
            {
                "station_id": 8,
                "sensor_type": "gnss",
                "timestamp": 200,
                "data": {"x": 2},
            },
        )


if __name__ == "__main__":
    unittest.main()
