"""Operational paths tested without touching deployment databases or credentials."""
import asyncio
import copy
import io
import json
import socket
import struct
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import auth
from app.config import settings
from app.models.auth import BaseAuth, User
from app.models.data import BaseData
from app.features.operations import store, backups
from app.features.operations.audit import AuditMiddleware
from app.features.operations.forwarding import approved, authorize
from app.features.operations.protocols import AcquisitionProfile, ntp_probe
from app.features.operations.router import router
from app.features.data_export.database.formats import add_excel_files
from app.features.data_export.schemas import ExportExcelRequest


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'BACKUP_DIR', str(tmp_path / 'operations' / 'backups'))
    monkeypatch.setattr(settings, 'SECRET_KEY', 'test-only-signing-key-with-at-least-32-characters')
    monkeypatch.setattr(settings, 'BACKUP_SIGNING_KEY', 'separate-backup-signing-key-for-tests')
    engine = create_engine(f"sqlite:///{tmp_path / 'operations.sqlite3'}")
    BaseData.metadata.create_all(engine)
    previous = store.configure_engine(engine)
    yield
    store.configure_engine(previous)
    engine.dispose()


def client(role='admin'):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(AuditMiddleware)
    def current_user():
        user = SimpleNamespace(username='tester', role=role, is_active=True)
        store.actor(user)
        return user
    app.dependency_overrides[auth.get_current_user] = current_user
    return TestClient(app)


def test_ntp_source_is_environment_and_not_mutable_from_browser(monkeypatch):
    monkeypatch.setattr(settings, 'NTP_SERVER', 'ntp.example.internal')
    store.set_setting('ntp_config', {'server': 'obsolete.example.internal'})
    with client() as browser:
        result = browser.get('/api/admin/operations/ntp').json()
        assert result['config'] == {'server': 'ntp.example.internal'}
        assert result['config_source'] == 'environment'
        assert browser.put('/api/admin/operations/ntp', json={'server': 'new.example.internal'}).status_code == 409
        with patch('app.features.operations.router.ntp_probe', return_value={'offset_ms': 1}) as probe:
            assert browser.post('/api/admin/operations/ntp/check', json={}).status_code == 200
        probe.assert_called_once_with('ntp.example.internal')


def test_admin_only_and_persistent_schedule_with_audit():
    with client('viewer') as browser:
        assert browser.get('/api/admin/operations/backups').status_code == 403
        assert browser.put('/api/admin/operations/backup-schedule', json={'frequency': 'daily'}).status_code == 403
    with client() as browser:
        response = browser.put('/api/admin/operations/backup-schedule', json={'frequency': 'daily', 'next_at': 1800000000})
        assert response.status_code == 200
        assert browser.get('/api/admin/operations/backups').json()['schedule']['next_at'] == 1800000000
        assert browser.put('/api/admin/operations/backup-schedule', json={'frequency': 'hourly'}).status_code == 422
        result = browser.get('/api/admin/operations/logs?username=tester&limit=2').json()
        assert result['total'] >= 2 and len(result['rows']) == 2
    assert store.get_setting('backup_schedule')['frequency'] == 'daily'
    assert any(row['details']['changes'] for row in store.query('audit_log', limit=100)['rows'] if row['action'].startswith('PUT'))


def test_audit_before_after_bulk_and_rollback_are_redacted():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    BaseAuth.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(username='subject', hashed_password='password-secret', role='viewer', is_active=True))
        db.commit()
    app = FastAPI()
    app.add_middleware(AuditMiddleware)
    @app.post('/api/admin/change')
    def change():
        store.actor(SimpleNamespace(username='admin', role='admin'))
        with Session(engine) as db:
            user = db.scalars(select(User)).one()
            user.role = 'operator'
            user.hashed_password = 'new-secret'
            db.commit()
            db.execute(update(User).where(User.id == user.id).values(full_name='Changed'))
            db.commit()
            user.role = 'admin'
            db.flush()
            db.rollback()
            db.execute(delete(User).where(User.id == user.id))
            db.commit()
        return {'ok': True}
    with TestClient(app) as browser:
        assert browser.post('/api/admin/change').status_code == 200
    log = store.query('audit_log')['rows'][0]
    encoded = json.dumps(log)
    assert 'password-secret' not in encoded and 'new-secret' not in encoded
    changes = log['details']['changes']
    assert changes[0]['changes']['role'] == {'old': 'viewer', 'new': 'operator'}
    assert changes[1]['old'][0]['full_name'] is None
    assert changes[1]['new'][0]['full_name'] == 'Changed'
    assert changes[-1]['operation'] == 'bulk_delete'
    assert len(changes) == 3  # rolled-back admin role never appears as committed


def test_forwarding_requires_admin_document_and_exact_signed_config():
    admin = SimpleNamespace(username='owner-admin', role='admin')
    operator = SimpleNamespace(username='operator', role='operator')
    config = {'enabled': True, 'host': 'broker.internal', 'port': 1883, 'rtk_topic': 'out/data'}
    assert not approved(7, config)
    assert not approved(7, None)
    assert not approved(7, {'enabled': True, 'approval': 'invalid'})
    with pytest.raises(HTTPException):
        authorize(7, dict(config), operator, 'Owner document 123')
    with pytest.raises(HTTPException):
        authorize(7, dict(config), admin)
    signed = authorize(7, dict(config), admin, 'Owner document 123')
    assert approved(7, signed)
    assert not approved(8, signed)
    changed = copy.deepcopy(signed)
    changed['host'] = 'another.example'
    assert not approved(7, changed)
    changed = copy.deepcopy(signed)
    changed['approval']['reference'] = 'Forged document'
    assert not approved(7, changed)
    assert authorize(7, {'enabled': False}, operator) == {'enabled': False}


def make_backup(path, tamper=False, traversal=False):
    values = {name + '.dump': (name + ' data').encode() for name in ['auth', 'config', 'data']}
    import hashlib
    manifest = {'version': 1, 'files': {name: {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)} for name, value in values.items()}}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'manifest': manifest, 'signature': backups.sign(manifest)}))
        for name, value in values.items():
            archive.writestr(name, b'x' * len(value) if tamper else value)
        if traversal:
            archive.writestr('../escape', 'bad')


def test_backup_validation_and_signed_upload(tmp_path):
    path = tmp_path / 'test.zip'
    make_backup(path)
    assert backups.validate_archive(path)['version'] == 1
    with client() as browser:
        response = browser.post('/api/admin/operations/backups/upload', files={'file': ('test.zip', path.read_bytes(), 'application/zip')})
        assert response.status_code == 200
        identifier = response.json()['backup_id']
        assert browser.get(f'/api/admin/operations/backups/{identifier}/download').content == path.read_bytes()
    make_backup(path, tamper=True)
    with pytest.raises(ValueError, match='checksum'):
        backups.validate_archive(path)
    make_backup(path, traversal=True)
    with pytest.raises(ValueError, match='exactly'):
        backups.validate_archive(path)
    with pytest.raises(ValueError):
        backups.backup_path('../escape')


def test_postgres_store_json_schedule_lock_and_scheduled_retention():
    store.append('audit_log', 'POST /api/admin/example', {'database_url': 'postgres://user:secret@db/app',
                                                          'not_finite': float('nan')}, username='tester')
    row = store.query('audit_log', username='tester')['rows'][0]
    assert row['details'] == {'database_url': '[REDACTED]', 'not_finite': 'nan'}
    now = 1_900_000_000
    store.set_setting('backup_schedule', {'frequency': 'daily', 'next_at': now, 'retention_count': 1})
    assert store.claim_backup_schedule(now) is True
    assert store.claim_backup_schedule(now) is False
    assert store.get_setting('backup_schedule')['next_at'] == now + 86400

    import hashlib
    for identifier, trigger, created_at in [('1' * 32, 'scheduled', 10),
                                             ('2' * 32, 'manual', 20),
                                             ('3' * 32, 'scheduled', 30)]:
        values = {name: b'postgres dump' for name in ('auth.dump', 'config.dump', 'data.dump')}
        manifest = {'version': 2, 'trigger': trigger, 'created_at': created_at,
                    'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                              for name, data in values.items()}}
        with zipfile.ZipFile(backups.backup_path(identifier), 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', json.dumps({'manifest': manifest, 'signature': backups.sign(manifest)}))
            for name, data in values.items():
                archive.writestr(name, data)
    assert backups.prune_scheduled_backups(1) == 1
    assert not backups.backup_path('1' * 32).exists()
    assert backups.backup_path('2' * 32).exists()
    assert backups.backup_path('3' * 32).exists()


def test_backup_failure_and_restart_are_observable():
    async def run():
        with patch.object(backups, 'run_tool', AsyncMock(side_effect=RuntimeError('pg_dump missing'))):
            await backups.create('a' * 32)
    asyncio.run(run())
    assert backups.job('a' * 32)['status'] == 'error'
    assert not backups.backup_path('a' * 32).exists()
    backups.job('b' * 32, status='running')
    backups.recover_interrupted_jobs()
    assert backups.job('b' * 32)['status'] == 'error'


def test_backup_creation_and_isolated_restore_never_target_live_database():
    async def run():
        async def fake_dump(name, args, env):
            if '--file' in args:
                Path(args[args.index('--file') + 1]).write_bytes(b'dump')
            else:
                assert args[0] == '--list'
        with patch.object(backups, 'run_tool', side_effect=fake_dump):
            await backups.create('c' * 32)
        assert backups.job('c' * 32)['status'] == 'completed'
        class Connection:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def execution_options(self, **kwargs): return self
            async def execute(self, statement):
                assert str(statement).startswith('CREATE DATABASE "recovery_')
        engine = SimpleNamespace(connect=lambda: Connection(), url=backups.auth_engine.url)
        calls = []
        async def fake_restore(name, args, env):
            if '--dbname' in args:
                calls.append(env['PGDATABASE'])
                assert env['PGDATABASE'].startswith('recovery_')
            else:
                assert args[0] == '--list'
        with patch.object(backups, 'DATABASES', {key: engine for key in ['auth','config','data']}), patch.object(backups.shutil, 'which', return_value='/pg_restore'), patch.object(backups, 'run_tool', side_effect=fake_restore):
            await backups.restore('d' * 32, 'c' * 32)
        result = backups.job('d' * 32)
        assert result['status'] == 'completed' and result['live_database_changed'] is False
        assert len(calls) == 3
    asyncio.run(run())


def test_ntp_rejects_spoofed_originate_and_unsynchronized_server():
    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect(self, value): pass
        def send(self, value): self.request = value
        def recv(self, size):
            packet = bytearray(48)
            packet[0] = 0x24
            packet[1] = 2
            packet[24:32] = self.request[40:48]
            packet[32:40] = self.request[40:48]
            packet[40:48] = self.request[40:48]
            if self.invalid:
                packet[24] ^= 1
            return bytes(packet)
    fake = FakeSocket()
    with patch.object(socket, 'getaddrinfo', return_value=[(socket.AF_INET, 2, 0, '', ('127.0.0.1', 123))]), patch.object(socket, 'socket', return_value=fake):
        fake.invalid = False
        result = ntp_probe('test.local')
        assert result['clock_changed'] is False and result['stratum'] == 2
        fake.invalid = True
        with pytest.raises(ValueError, match='originate'):
            ntp_probe('test.local')


def test_ntp_retries_an_unreachable_pool_peer():
    class PeerSocket:
        def __init__(self): self.address = None
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect(self, address): self.address = address
        def send(self, request): self.request = request
        def recv(self, size):
            if self.address[0] == '192.0.2.1':
                raise TimeoutError()
            packet = bytearray(48)
            packet[0], packet[1] = 0x24, 2
            packet[24:32] = packet[32:40] = packet[40:48] = self.request[40:48]
            return bytes(packet)
    peers = [(socket.AF_INET, 2, 0, '', (ip, 123)) for ip in ['192.0.2.1', '192.0.2.2']]
    with patch.object(socket, 'getaddrinfo', return_value=peers), patch.object(socket, 'socket', side_effect=lambda *args: PeerSocket()):
        assert ntp_probe('pool.test')['stratum'] == 2


def test_ntp_timeout_returns_actionable_error():
    with client() as browser, patch('app.features.operations.router.ntp_probe', side_effect=TimeoutError()):
        result = browser.post('/api/admin/operations/ntp/check', json={})
        assert result.status_code == 502
        assert 'UDP cổng 123' in result.json()['detail']


def test_industrial_profile_rejects_invalid_mapping_and_keeps_mqtt_default():
    assert AcquisitionProfile(protocol='mqtt', enabled=True).enabled is False
    with pytest.raises(ValidationError):
        AcquisitionProfile(protocol='modbus_tcp', host='plc.local', points=[])
    with pytest.raises(ValidationError):
        AcquisitionProfile(protocol='opcua', endpoint='http://bad', points=[{'field':'water_level'}])
    with pytest.raises(ValidationError):
        AcquisitionProfile(protocol='modbus_tcp', host='plc.local', points=[{'field':'water_level','address':65535,'data_type':'float32'}])


def test_csv_excel_scope_unicode_formula_and_invalid_dates(tmp_path):
    request = ExportExcelRequest(tables=['sensor_data'], format='both', station_ids=[7], sensor_types=['water'], start_date='2026-10-01', end_date='2026-10-06')
    assert request.station_ids == [7] and request.format == 'both'
    with pytest.raises(ValidationError):
        ExportExcelRequest(tables=['sensor_data'], start_date='2026-10-07', end_date='2026-10-01')
    path = tmp_path / 'export.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('station/water.csv', '\ufeffname,value\nĐiểm đo,=1+1\n'.encode())
    add_excel_files(path)
    with zipfile.ZipFile(path) as archive:
        workbook = load_workbook(io.BytesIO(archive.read('station/water.xlsx')))
        assert workbook.active['A2'].value == 'Điểm đo'
        assert workbook.active['B2'].value == '=1+1'
        assert workbook.active['B2'].data_type == 's'
        assert 'station/water.csv' in archive.namelist()


def test_log_filters_combine_actor_action_and_http_method():
    store.append('audit_log', 'POST /api/users', username='admin')
    store.append('audit_log', 'GET /api/export', username='admin')
    store.append('audit_log', 'POST /api/users', username='operator')
    with client() as browser:
        result = browser.get('/api/admin/operations/logs', params={
            'kind': 'audit_log', 'username': 'admin', 'action': 'POST /api/users', 'method': 'POST'}).json()
        assert result['total'] == 1
        assert result['rows'][0]['username'] == 'admin'
        assert browser.get('/api/admin/operations/logs', params={'method': 'GET'}).json()['total'] == 1
        assert browser.get('/api/admin/operations/logs', params={'method': 'INVALID'}).status_code == 422
    assert store.log_options()['audit_log']['usernames'] == ['admin', 'operator']


def test_log_options_returns_current_accounts_and_backup_location():
    from app.database import get_auth_db
    from unittest.mock import AsyncMock
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [
        {'username': 'new-user', 'full_name': 'New User', 'is_active': True}]))))
    with client() as browser:
        browser.app.dependency_overrides[get_auth_db] = lambda: db
        response = browser.get('/api/admin/operations/log-options')
        assert response.status_code == 200
        assert response.json()['accounts'][0]['username'] == 'new-user'
        backup = browser.get('/api/admin/operations/backups').json()
        assert backup['storage']['format'] == 'ZIP'
        assert backup['storage']['directory'] == str(backups.directory().resolve())


def test_relative_backup_directory_is_anchored_to_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'BACKUP_DIR', 'backups')
    monkeypatch.setattr(backups, '__file__', str(tmp_path / 'backend/app/features/operations/backups.py'))
    monkeypatch.chdir(tmp_path)
    assert backups.directory() == tmp_path / 'backend/backups'
