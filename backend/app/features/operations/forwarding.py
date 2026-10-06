"""Fail-closed approval for outbound RTK forwarding, including legacy configs."""
import hashlib
import hmac
import json
import time

from fastapi import HTTPException

from ...config import settings


def signature(station_id, config):
    material = {'station_id': station_id, 'config': {k: v for k, v in config.items() if k != 'approval'}}
    material['approval'] = {k: v for k, v in (config.get('approval') or {}).items() if k != 'signature'}
    return hmac.new(settings.SECRET_KEY.encode(), json.dumps(material, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def approved(station_id, config):
    if not isinstance(config, dict):
        return False
    approval = config.get('approval') or {}
    if not isinstance(approval, dict):
        return False
    return bool(config.get('enabled') is True and approval.get('reference') and approval.get('by') and
                hmac.compare_digest(signature(station_id, config), str(approval.get('signature', ''))))


def authorize(station_id, config, current_user, reference=''):
    if config.get('enabled') is not True:
        config['enabled'] = False
        config.pop('approval', None)
        return config
    if approved(station_id, config):
        return config
    if current_user.role != 'admin':
        raise HTTPException(403, 'Only admin can authorize data forwarding')
    reference = str(reference).strip()
    if not 5 <= len(reference) <= 500:
        raise HTTPException(422, 'Provide the owner written approval reference (5–500 characters) before enabling forwarding')
    config['approval'] = {'reference': reference, 'by': current_user.username, 'at': int(time.time())}
    config['approval']['signature'] = signature(station_id, config)
    return config
