"""Run: PYTHONPATH=backend python3 -m unittest backend.tests.test_monitoring_sensors."""
import unittest
from types import SimpleNamespace
from app.shared.sensor_catalog import MONITORING_TYPES, SENSOR_CATALOG, process_monitoring_payload
from app.features.data_export.sensors import export_sensor_record


class MonitoringSensorTests(unittest.TestCase):
    def test_catalog_payload_and_export_round_trip(self):
        self.assertEqual(len(MONITORING_TYPES), 10)
        for sensor_type in MONITORING_TYPES:
            with self.subTest(sensor_type=sensor_type):
                spec = SENSOR_CATALOG[sensor_type]
                payload = {field: index - 0.5 for index, field in enumerate(spec['fields'])}
                if sensor_type == 'extensometer': payload = {'points': {'A1': 0, 'A2': -1.5}}
                result = process_monitoring_payload(sensor_type, payload)
                self.assertEqual(result, {**payload, 'unit': spec['unit']})
                row = export_sensor_record(SimpleNamespace(sensor_type=sensor_type, data=result), {})
                self.assertEqual(row['dataset'], sensor_type)
                for field, value in result.items():
                    exported = row['row'][row['headers'].index(field)]
                    if isinstance(value, dict):
                        import json
                        exported = json.loads(exported)
                    self.assertEqual(exported, value)

    def test_invalid_measurements_never_become_zero(self):
        for value in [None, '', '12', True, float('nan'), float('inf')]:
            self.assertIsNone(process_monitoring_payload('piezometer', {'pressure': value}))
        self.assertIsNone(process_monitoring_payload('piezometer', {'pressure': 12, 'unit': 'bar'}))
        self.assertIsNone(process_monitoring_payload('piezometer', []))
        for points in [{}, {'A1': None}, {'A1': True}, {'A1': float('nan')}, {'': 1}, {str(i): i for i in range(65)}]:
            self.assertIsNone(process_monitoring_payload('extensometer', {'points': points}))
        self.assertIsNone(process_monitoring_payload('accelerometer', {'x': 1, 'y': 2}))
        self.assertEqual(process_monitoring_payload('temperature', {'temperature': 0})['temperature'], 0)

    def test_engineering_metadata_survives_export(self):
        payload = {'pressure': 12.345678, 'temperature': 0, 'measured_at': 1700000000.125,
                   'quality': 'suspect', 'serial_number': 'P01', 'calibration_id': 'CAL-2',
                   'reference_id': 'ZERO-1', 'location_label': 'Nền đập', 'sequence': 0}
        result = process_monitoring_payload('piezometer', payload)
        self.assertEqual(result, {**payload, 'unit': 'kPa'})
        export = export_sensor_record(SimpleNamespace(sensor_type='piezometer', data=result), {})
        for field, value in result.items():
            self.assertEqual(export['row'][export['headers'].index(field)], value)
        for field, value in [('quality', 'safe'), ('measured_at', '2026-01-01'),
                             ('temperature', float('nan')), ('sequence', True), ('reference_id', '')]:
            self.assertIsNone(process_monitoring_payload('piezometer', {**payload, field:value}))

    def test_waveform_preserved_and_bounded(self):
        import json
        wave = {'start_at':1700000000.125, 'sample_rate_hz':250,
                'x':[0, -2, 1], 'y':[1, 0, 2], 'z':[3, 2, 1]}
        payload = {'x':1, 'y':2, 'z':1, 'waveform':wave, 'event_id':'EVENT-1'}
        result = process_monitoring_payload('accelerometer', payload)
        self.assertEqual(result['waveform'], wave)
        export = export_sensor_record(SimpleNamespace(sensor_type='accelerometer',data=result), {})
        text = ''.join(export['row'][export['headers'].index(f'data_json_{i}')] or '' for i in range(1,9))
        self.assertEqual(json.loads(text)['waveform'], wave)
        for malformed in [{**wave,'y':[1]}, {**wave,'sample_rate_hz':0}, {**wave,'x':[float('nan')]},
                          {**wave,'x':[0]*1025}, {**wave,'start_at':True}]:
            self.assertIsNone(process_monitoring_payload('accelerometer',{**payload,'waveform':malformed}))
        self.assertIsNone(process_monitoring_payload('temperature',{'temperature':10,'waveform':wave}))


if __name__ == '__main__':
    unittest.main()
