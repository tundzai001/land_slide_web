"""Monitoring channels shared with the frontend build.

New channels accept calibrated engineering values, never raw vibrating-wire counts.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

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


def _process_extensometer_payload(payload, unit):
    points = payload.get('points')
    if not isinstance(points, dict) or not 1 <= len(points) <= 64:
        return None
    for key, value in points.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 80:
            return None
        if not _number(value):
            return None
    return {'points': points, 'unit': unit}


def _validate_fields(payload, fields, result):
    for field in fields:
        value = payload.get(field)
        if not _number(value):
            return False
        result[field] = value
    return True


def _validate_optional_metrics(payload, optional_metrics, result):
    for metric in optional_metrics:
        field = metric['field']
        if field in payload:
            if not _number(payload[field]):
                return False
            result[field] = payload[field]
    return True


def _validate_metadata_field(field: str, value: Any) -> bool:
    if field == 'measured_at':
        return bool(_number(value) and 0 < value < 253402300800)
    if field == 'sequence':
        return not isinstance(value, bool) and isinstance(value, int) and value >= 0
    if field == 'quality':
        return value in ('valid', 'suspect', 'invalid', 'unknown')
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 160


def _validate_metadata(payload, result):
    for field in METADATA_FIELDS:
        if field in payload:
            value = payload[field]
            if not _validate_metadata_field(field, value):
                return False
            result[field] = value
    return True


def _validate_waveform(payload, sensor_type, result):
    if 'waveform' not in payload:
        return True
    if sensor_type != 'accelerometer':
        return False
    wave = payload['waveform']
    if not isinstance(wave, dict) or not _number(wave.get('sample_rate_hz')) or not 0 < wave['sample_rate_hz'] <= 10000:
        return False
    if not _number(wave.get('start_at')) or not 0 < wave['start_at'] < 253402300800:
        return False
    axes = [wave.get(axis) for axis in ('x', 'y', 'z')]
    if any(not isinstance(axis, list) or not 1 <= len(axis) <= 1024 or any(not _number(v) for v in axis) for axis in axes):
        return False
    if len({len(axis) for axis in axes}) != 1:
        return False
    result['waveform'] = {field: wave[field] for field in ('start_at', 'sample_rate_hz', 'x', 'y', 'z')}
    return True


def process_monitoring_payload(sensor_type, payload, custom_unit=None):
    """Reject missing/non-finite channels and mismatched engineering units."""
    spec = SENSOR_CATALOG.get(sensor_type) if not is_custom_sensor(sensor_type) else {'unit': custom_unit, 'fields': ['value']}
    if spec is None or spec['unit'] is None or not isinstance(payload, dict):
        return None
    if payload.get('unit', spec['unit']) != spec['unit']:
        return None

    if sensor_type == 'extensometer':
        result = _process_extensometer_payload(payload, spec['unit'])
        if result is None:
            return None
    else:
        result = {'unit': spec['unit']}
        if not _validate_fields(payload, spec['fields'], result):
            return None

    if not _validate_optional_metrics(payload, spec.get('optional_metrics', []), result):
        return None
    if not _validate_metadata(payload, result):
        return None
    if not _validate_waveform(payload, sensor_type, result):
        return None

    return result
