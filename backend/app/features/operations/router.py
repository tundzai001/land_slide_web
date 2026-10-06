"""Admin-only operational tools and field gateway configuration."""
import asyncio
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ... import auth
from ...database import get_config_db
from ...models.config import Device
from . import backups, store
from .protocols import AcquisitionProfile, ntp_probe

router = APIRouter(prefix='/api/admin/operations', tags=['Operations'])
admin = auth.require_permission(auth.Permission.MANAGE_DATABASE)


@router.get('/logs')
async def logs(kind: Literal['audit_log', 'operation_log'] = 'audit_log', offset: int = Query(0, ge=0),
               limit: int = Query(50, ge=1, le=200), action: str = '', username: str = '',
               start: int = Query(0, ge=0), end: int = Query(0, ge=0), user=Depends(admin)):
    return await asyncio.to_thread(store.query, kind, offset, limit, action, username, start, end)


@router.get('/backups')
async def list_backups(user=Depends(admin)):
    return {'backups': await asyncio.to_thread(backups.list_backups),
            'schedule': await asyncio.to_thread(store.get_setting, 'backup_schedule', {'frequency': 'disabled'}),
            'recovery_mode': 'isolated'}


@router.post('/backups')
async def start_backup(tasks: BackgroundTasks, user=Depends(admin)):
    identifier = uuid.uuid4().hex
    await asyncio.to_thread(backups.job, identifier, kind='backup', status='pending')
    tasks.add_task(backups.create, identifier)
    return {'job_id': identifier}


@router.get('/jobs/{identifier}')
async def job_status(identifier: str, user=Depends(admin)):
    try:
        backups.backup_path(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    record = await asyncio.to_thread(store.get_setting, 'job:' + identifier)
    if not record:
        raise HTTPException(404, 'Job not found')
    return record


@router.get('/backups/{identifier}/download')
async def download_backup(identifier: str, user=Depends(admin)):
    try:
        path = backups.backup_path(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not path.is_file():
        raise HTTPException(404, 'Backup not found')
    return FileResponse(path, filename=f'landslide_{identifier}.zip', media_type='application/zip')


@router.post('/backups/upload')
async def upload_backup(file: UploadFile, user=Depends(admin)):
    identifier = uuid.uuid4().hex
    path = backups.backup_path(identifier)
    partial = path.with_suffix('.upload')
    size = 0
    try:
        with partial.open('xb') as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 2 * 1024**3:
                    raise HTTPException(413, 'Upload exceeds 2 GiB; use the server backup directory for larger archives')
                await asyncio.to_thread(target.write, chunk)
        await asyncio.to_thread(backups.validate_archive, partial)
        partial.chmod(0o600)
        partial.replace(path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, 'Invalid backup, checksum, or installation signature')
    finally:
        partial.unlink(missing_ok=True)
        await file.close()
    return {'backup_id': identifier}


class RestoreRequest(BaseModel):
    confirmation: Literal['RESTORE INTO ISOLATED DATABASES']


@router.post('/backups/{identifier}/restore')
async def restore_backup(identifier: str, body: RestoreRequest, tasks: BackgroundTasks, user=Depends(admin)):
    try:
        path = backups.backup_path(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not path.exists():
        raise HTTPException(404, 'Backup not found')
    job_id = uuid.uuid4().hex
    await asyncio.to_thread(backups.job, job_id, kind='restore', status='pending', backup_id=identifier)
    tasks.add_task(backups.restore, job_id, identifier)
    return {'job_id': job_id, 'live_database_changed': False}


class Schedule(BaseModel):
    frequency: Literal['disabled', 'daily', 'weekly'] = 'disabled'
    next_at: int = Field(default=0, ge=0)
    retention_count: int = Field(default=30, ge=1, le=365)


@router.put('/backup-schedule')
async def save_schedule(body: Schedule, user=Depends(admin)):
    value = body.model_dump()
    if not value['next_at']:
        value['next_at'] = int(time.time()) + {'daily': 86400, 'weekly': 604800}.get(body.frequency, 0)
    await asyncio.to_thread(store.set_setting, 'backup_schedule', value)
    await asyncio.to_thread(store.append, 'audit_log', 'backup.schedule', value, username=user.username, role=user.role)
    return value


class NTPConfig(BaseModel):
    server: str = Field(default='pool.ntp.org', min_length=1, max_length=253, pattern=r'^[A-Za-z0-9.-]+$')


@router.get('/ntp')
async def get_ntp(user=Depends(admin)):
    return {'config': await asyncio.to_thread(store.get_setting, 'ntp_config', {'server': 'pool.ntp.org'}),
            'last_check': await asyncio.to_thread(store.get_setting, 'ntp_status'), 'mode': 'measurement_only'}


@router.put('/ntp')
async def save_ntp(body: NTPConfig, user=Depends(admin)):
    await asyncio.to_thread(store.set_setting, 'ntp_config', body.model_dump())
    return body


@router.post('/ntp/check')
async def check_ntp(user=Depends(admin)):
    config = await asyncio.to_thread(store.get_setting, 'ntp_config', {'server': 'pool.ntp.org'})
    try:
        result = await asyncio.to_thread(ntp_probe, config['server'])
    except Exception as exc:
        await asyncio.to_thread(store.append, 'operation_log', 'ntp.failed', {'error': type(exc).__name__})
        raise HTTPException(502, 'NTP check failed; verify UDP/123 and the configured server')
    await asyncio.to_thread(store.set_setting, 'ntp_status', result)
    await asyncio.to_thread(store.append, 'operation_log', 'ntp.checked', result)
    return result


@router.get('/ntp/chrony-config', response_class=PlainTextResponse)
async def chrony_config(user=Depends(admin)):
    config = await asyncio.to_thread(store.get_setting, 'ntp_config', {'server': 'pool.ntp.org'})
    return f"# Apply on the server/gateway through your OS administrator\nserver {config['server']} iburst\nmakestep 1.0 3\nrtcsync\n"


@router.get('/devices')
async def devices(db=Depends(get_config_db), user=Depends(admin)):
    rows = (await db.execute(select(Device).order_by(Device.id))).scalars().all()
    return [{'id': d.id, 'name': d.name, 'device_type': d.device_type, 'mqtt_topic': d.mqtt_topic,
             'acquisition': (d.config or {}).get('acquisition', {'protocol': 'mqtt', 'enabled': False})} for d in rows]


@router.put('/devices/{device_id}/acquisition')
async def acquisition(device_id: int, body: AcquisitionProfile, db=Depends(get_config_db), user=Depends(admin)):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, 'Device not found')
    if body.protocol != 'mqtt' and device.device_type not in {'rain', 'water', 'imu'}:
        raise HTTPException(422, 'Industrial gateway maps rain/water/IMU; GNSS keeps the current MQTT/NMEA receiver')
    if body.protocol != 'mqtt' and not device.mqtt_topic:
        raise HTTPException(422, 'Configure the existing MQTT topic before enabling a gateway profile')
    if body.protocol != 'mqtt':
        required = {'water': {'water_level'}, 'rain': {'rainfall_mm'}, 'imu': {'roll', 'pitch', 'yaw'}}[device.device_type]
        if not required.issubset({point.field for point in body.points}):
            raise HTTPException(422, f'Mapping must include: {", ".join(sorted(required))}')
    device.config = {**(device.config or {}), 'acquisition': body.model_dump()}
    await db.commit()
    return {'status': 'saved', 'transport': 'mqtt', 'gateway_deployment_required': body.protocol != 'mqtt'}


@router.get('/gateway-config')
async def gateway_config(device_id: int = Query(..., ge=1), db=Depends(get_config_db), user=Depends(admin)):
    rows = (await db.execute(select(Device).where(Device.is_active.is_(True), Device.id == device_id))).scalars().all()
    if not rows:
        raise HTTPException(404, 'Active device not found')
    return {'version': 1, 'devices': [{'device_id': d.id, 'sensor_type': d.device_type, 'topic': d.mqtt_topic,
            'profile': (d.config or {})['acquisition']} for d in rows if (d.config or {}).get('acquisition', {}).get('enabled')]}


@router.get('/integration-guide', response_class=PlainTextResponse)
async def integration_guide(user=Depends(admin)):
    return (Path(__file__).resolve().parents[4] / 'docs' / 'OPERATIONS_INTEGRATION.md').read_text(encoding='utf-8')
