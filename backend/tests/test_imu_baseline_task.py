import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import unittest

from app.mqtt.bridge.sensor_pipeline.other_sensors import OtherSensorPayloadMixin


class ImuBaselineTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_save_task_is_retained_until_finished(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def save(*args):
            started.set()
            await release.wait()

        handler = OtherSensorPayloadMixin()
        handler._save_imu_baseline = AsyncMock(side_effect=save)
        processor = SimpleNamespace(origin_locked=True, baseline={'roll': 1, 'pitch': 2, 'yaw': 3}, process=lambda *_: {'roll': 1})
        result = await handler._process_other_sensor_payload(
            {'type': 'imu'}, '{}', 1, 2, 'station', processor, {}, 3, False, 4
        )
        await started.wait()
        assert result == {'roll': 1}
        task, = handler._baseline_save_tasks
        assert not task.done()
        release.set()
        await task
        await asyncio.sleep(0)
        assert not handler._baseline_save_tasks
        handler._save_imu_baseline.assert_awaited_once_with(2, {'baseline_roll': 1, 'baseline_pitch': 2, 'baseline_yaw': 3})
