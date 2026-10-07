"""Exercise the real persistence decision without database dependencies."""
import importlib.util
from pathlib import Path
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class MonitoringPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_waveform_chunk_is_saved_despite_throttle(self):
        config = SimpleNamespace(settings=SimpleNamespace(SAVE_INTERVAL_DEFAULT=60))
        path = Path(__file__).parents[1] / 'app/mqtt/bridge/sensor_pipeline/persistence.py'
        spec = importlib.util.spec_from_file_location('monitoring_persistence_test_target', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'app.config':config}):
            spec.loader.exec_module(module)
        target = module.SensorPersistenceMixin()
        target.last_save_time = defaultdict(dict, {1:{'accelerometer':100}})
        target.runtime_save_intervals = {'default':60}
        target._buffer_sensor_record = AsyncMock()
        target._flush_write_buffer = AsyncMock()
        args = dict(info={},raw_payload='{}',alert=None,is_dangerous=False,is_just_resolved=False,
                    station_id=1,station_name='ST01',sensor_type='accelerometer',device_id=2,
                    station_config={},current_timestamp=101)
        await target._save_processed_data(processed_data={'x':0,'y':0,'z':0}, **args)
        target._buffer_sensor_record.assert_not_awaited()
        for timestamp in [101,102]:
            args['current_timestamp'] = timestamp
            await target._save_processed_data(processed_data={'x':0,'y':0,'z':0,'waveform':{'x':[0]}}, **args)
        self.assertEqual(target._buffer_sensor_record.await_count, 2)
        target._flush_write_buffer.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
