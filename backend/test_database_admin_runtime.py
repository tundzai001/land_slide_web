import unittest
from types import SimpleNamespace

from app.routers.database_admin import _device_runtime_state


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


if __name__ == "__main__":
    unittest.main()
