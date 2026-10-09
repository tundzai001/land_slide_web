"""Monitoring channels shared with the frontend build.

New channels accept calibrated engineering values, never raw vibrating-wire counts.
"""
import json
import math
import re
from pathlib import Path

SENSOR_CATALOG = {row['key']: row for row in json.loads(
    Path(__file__).with_suffix('.json').read_text(encoding='utf-8')
)}
MONITORING_TYPES = {key for key, row in SENSOR_CATALOG.items() if not row['legacy']}
METADATA_FIELDS = ('measured_at', 'quality', 'serial_number', 'model', 'calibration_id',
                   'reference_id', 'location_label', 'axis_convention', 'event_id', 'sequence')
CUSTOM_KEY = re.compile(r'^custom_[0-9a-f]{12}$')


def is_custom_sensor(sensor_type):
    return isinstance(sensor_type, str) and CUSTOM_KEY.fullmatch(sensor_type) is not None


def is_monitoring_type(sensor_type):
    return sensor_type in MONITORING_TYPES or is_custom_sensor(sensor_type)


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def process_monitoring_payload(sensor_type, payload, custom_unit=None):
    """Reject missing/non-finite channels and mismatched engineering units."""
    spec = SENSOR_CATALOG.get(sensor_type) if not is_custom_sensor(sensor_type) else {'unit': custom_unit, 'fields': ['value']}
    if spec is None or spec['unit'] is None:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get('unit', spec['unit']) != spec['unit']:
        return None
    if sensor_type == 'extensometer':
        points = payload.get('points')
        if not isinstance(points, dict) or not 1 <= len(points) <= 64:
            return None
        if any(not isinstance(key, str) or not key.strip() or len(key) > 80
               or isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for key, value in points.items()):
            return None
        result = {'points': points, 'unit': spec['unit']}
    else:
        result = {'unit': spec['unit']}
    for field in ([] if sensor_type == 'extensometer' else spec['fields']):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        result[field] = value
    for metric in spec.get('optional_metrics', []):
        field = metric['field']
        if field in payload:
            if not _number(payload[field]):
                return None
            result[field] = payload[field]
    for field in METADATA_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field == 'measured_at':
            if not _number(value) or not 0 < value < 253402300800:
                return None
        elif field == 'sequence':
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
        elif field == 'quality':
            if value not in ('valid', 'suspect', 'invalid', 'unknown'):
                return None
        elif not isinstance(value, str) or not value.strip() or len(value) > 160:
            return None
        result[field] = value
    if 'waveform' in payload:
        if sensor_type != 'accelerometer':
            return None
        wave = payload['waveform']
        if not isinstance(wave, dict) or not _number(wave.get('sample_rate_hz')) or not 0 < wave['sample_rate_hz'] <= 10000:
            return None
        if not _number(wave.get('start_at')) or not 0 < wave['start_at'] < 253402300800:
            return None
        axes = [wave.get(axis) for axis in ('x', 'y', 'z')]
        if any(not isinstance(axis, list) or not 1 <= len(axis) <= 1024 or any(not _number(v) for v in axis) for axis in axes):
            return None
        if len({len(axis) for axis in axes}) != 1:
            return None
        result['waveform'] = {field: wave[field] for field in ('start_at', 'sample_rate_hz', 'x', 'y', 'z')}
    return result
