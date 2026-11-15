"""Hot PostgreSQL dumps and isolated recovery; live connections stay untouched."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import text

from ...config import settings
from ...database import auth_engine, config_engine, data_engine
from . import store

DATABASES = {'auth': auth_engine, 'config': config_engine, 'data': data_engine}
lock = asyncio.Lock()
logger = logging.getLogger(__name__)
BACKUP_ID_PATTERN = r'[0-9a-f]{32}'
MANIFEST_FILENAME = 'manifest.json'


def directory():
    if settings.BACKUP_DIR:
        path = Path(settings.BACKUP_DIR)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
    elif os.name == 'nt':
        path = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'Aitogy' / 'Landslide' / 'backups'
    else:
        path = Path(__file__).resolve().parents[4] / 'runtime' / 'operations' / 'backups'
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


def backup_path(identifier):
    if not re.fullmatch(BACKUP_ID_PATTERN, identifier):
        raise ValueError('Invalid backup identifier')
    return directory() / f'{identifier}.zip'


def sign(manifest):
    # Version 1 archives used SECRET_KEY. Keep validating them while new
    # archives use a dedicated key when configured.
    key = settings.BACKUP_SIGNING_KEY if manifest.get('version', 1) >= 2 else ''
    return hmac.new((key or settings.SECRET_KEY).encode(),
                    json.dumps(manifest, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def secure_file(path):
    # chmod(0o600) marks files read-only on Windows; use NTFS ACLs there.
    if os.name != 'nt':
        os.chmod(path, 0o600)


def digest(path):
    with open(path, 'rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def pg_environment(engine, database=None):
    url = engine.url
    env = os.environ.copy()
    # Do not put database passwords in process argv or task output.
    env.update(PGHOST=url.host or 'localhost', PGPORT=str(url.port or 5432),
               PGUSER=url.username or '', PGPASSWORD=url.password or '',
               PGDATABASE=database or url.database or '', PGCONNECT_TIMEOUT='10')
    for key in ('sslmode', 'sslcert', 'sslkey', 'sslrootcert', 'sslcrl', 'sslcrldir',
                'sslpassword', 'application_name', 'target_session_attrs', 'options'):
        value = url.query.get(key)
        if value:
            env['PG' + key.upper()] = str(value)
    return env


async def run_tool(name, args, env):
    binary = shutil.which(name)
    if not binary:
        raise RuntimeError(f'Install PostgreSQL client tools: {name} is unavailable')
    process = await asyncio.create_subprocess_exec(binary, *args, env=env,
                                                   stdout=asyncio.subprocess.DEVNULL,
                                                   stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(), timeout=6 * 60 * 60)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError(f'{name} exceeded the six-hour job limit') from exc
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        # Tool output may include sensitive data; retain only the failure code.
        raise RuntimeError(f'{name} failed (exit {process.returncode}); inspect PostgreSQL server logs')


def job(identifier, **updates):
    record = store.get_setting('job:' + identifier, {})
    record.update(updates, updated_at=int(time.time()))
    store.set_setting('job:' + identifier, record)
    return record


async def create(identifier, trigger='manual'):
    if trigger not in {'manual', 'scheduled'}:
        raise ValueError('Invalid backup trigger')
    async with lock:
        await asyncio.to_thread(job, identifier, kind='backup', trigger=trigger, status='running')
        partial = backup_path(identifier).with_suffix('.partial')
        try:
            with tempfile.TemporaryDirectory(dir=directory()) as temp:
                files = {}
                for label, engine in DATABASES.items():
                    filename = f'{label}.dump'
                    target = Path(temp) / filename
                    await run_tool('pg_dump', ['--format=custom', '--no-owner', '--no-acl', '--file', str(target)], pg_environment(engine))
                    await run_tool('pg_restore', ['--list', str(target)], pg_environment(engine))
                    files[filename] = {'sha256': await asyncio.to_thread(digest, target), 'bytes': target.stat().st_size}
                manifest = {'version': 2, 'created_at': int(time.time()), 'trigger': trigger,
                            'files': files, 'recovery_mode': 'isolated',
                            'snapshots': 'one snapshot per database'}
                def pack():
                    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_STORED) as archive:
                        archive.writestr(MANIFEST_FILENAME, json.dumps({'manifest': manifest, 'signature': sign(manifest)}))
                        for filename in files:
                            archive.write(Path(temp) / filename, filename)
                    secure_file(partial)
                    os.replace(partial, backup_path(identifier))
                await asyncio.to_thread(pack)
            # Verify the completed ZIP before reporting success or applying retention.
            await asyncio.to_thread(validate_archive, backup_path(identifier))
            await asyncio.to_thread(job, identifier, status='completed', backup_id=identifier, created_at=manifest['created_at'])
            await asyncio.to_thread(store.append, 'operation_log', 'backup.completed', {'backup_id': identifier})
            if trigger == 'scheduled':
                schedule = await asyncio.to_thread(store.get_setting, 'backup_schedule', {})
                try:
                    removed = await asyncio.to_thread(prune_scheduled_backups, schedule.get('retention_count', 30))
                    if removed:
                        await asyncio.to_thread(store.append, 'operation_log', 'backup.retention_pruned', {'removed': removed})
                except OSError:
                    await asyncio.to_thread(store.append, 'operation_log', 'backup.retention_failed')
        except BaseException as exc:
            partial.unlink(missing_ok=True)
            backup_path(identifier).unlink(missing_ok=True)
            await asyncio.to_thread(job, identifier, status='error', error=str(exc)[:500] or 'Interrupted')
            await asyncio.to_thread(store.append, 'operation_log', 'backup.failed', {'error': str(exc)[:500]})
            if isinstance(exc, asyncio.CancelledError):
                raise


def validate_archive(path, destination=None):
    with zipfile.ZipFile(path) as archive:
        base_files = {'auth.dump', 'config.dump', 'data.dump'}
        if archive.getinfo(MANIFEST_FILENAME).file_size > 16384:
            raise ValueError('Invalid manifest size')
        envelope = json.loads(archive.read(MANIFEST_FILENAME))
        manifest = envelope['manifest']
        version = manifest.get('version')
        if version not in (1, 2) or not hmac.compare_digest(sign(manifest), str(envelope.get('signature', ''))):
            raise ValueError('Backup signature invalid; restore only backups signed by this installation')
        files = set(manifest.get('files', {}))
        if (files != base_files and not (version == 1 and files == base_files | {'journal.sqlite3'})):
            raise ValueError('Invalid manifest files')
        if version == 2 and manifest.get('trigger') not in {'manual', 'scheduled'}:
            raise ValueError('Invalid backup metadata')
        if sorted(archive.namelist()) != sorted([MANIFEST_FILENAME, *files]):
            raise ValueError('Backup must contain exactly the manifest and its declared files')
        for name in files:
            info = archive.getinfo(name)
            if (info.compress_type != zipfile.ZIP_STORED or
                    info.file_size != manifest['files'][name]['bytes'] or
                    info.file_size > 50 * 1024**3):
                raise ValueError('Invalid dump size')
            sha = hashlib.sha256()
            with archive.open(name) as source:
                target = open(Path(destination) / name, 'wb') if destination else None
                try:
                    while chunk := source.read(1024 * 1024):
                        sha.update(chunk)
                        if target:
                            target.write(chunk)
                finally:
                    if target:
                        target.close()
            if sha.hexdigest() != manifest['files'][name]['sha256']:
                raise ValueError('Backup checksum mismatch')
        return manifest


async def restore(identifier, backup_id):
    """Recover into newly created DBs, never run uploaded SQL against live data."""
    async with lock:
        stages = {}
        await asyncio.to_thread(job, identifier, kind='restore', status='running', backup_id=backup_id)
        try:
            if not shutil.which('pg_restore'):
                raise RuntimeError('Install PostgreSQL client tools: pg_restore is unavailable')
            with tempfile.TemporaryDirectory(dir=directory()) as temp:
                await asyncio.to_thread(validate_archive, backup_path(backup_id), temp)
                for label, engine in DATABASES.items():
                    await run_tool('pg_restore', ['--list', str(Path(temp) / f'{label}.dump')],
                                   pg_environment(engine))
                for label, engine in DATABASES.items():
                    name = f'recovery_{identifier[:16]}_{label}'
                    async with engine.connect() as connection:
                        connection = await connection.execution_options(isolation_level='AUTOCOMMIT')
                        await connection.execute(text(f'CREATE DATABASE "{name}"'))
                    stages[label] = name
                    await asyncio.to_thread(job, identifier, recovered_databases=stages.copy())
                    await run_tool('pg_restore', ['--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                                                 '--dbname', name, str(Path(temp) / f'{label}.dump')], pg_environment(engine, name))
                legacy_journal = Path(temp) / 'journal.sqlite3'
                if legacy_journal.exists():
                    recovered_journal = directory() / f'recovery_{identifier}_journal.sqlite3'
                    await asyncio.to_thread(shutil.copyfile, legacy_journal, recovered_journal)
                    secure_file(recovered_journal)
                    await asyncio.to_thread(job, identifier, recovered_journal=recovered_journal.name)
            await asyncio.to_thread(job, identifier, status='completed', recovered_databases=stages, live_database_changed=False)
            await asyncio.to_thread(store.append, 'operation_log', 'restore.completed', {'databases': stages, 'live_database_changed': False})
        except BaseException as exc:
            await asyncio.to_thread(job, identifier, status='error', error=str(exc)[:500] or 'Interrupted', recovered_databases=stages)
            await asyncio.to_thread(store.append, 'operation_log', 'restore.failed', {'error': str(exc)[:500], 'partial_databases': stages})
            if isinstance(exc, asyncio.CancelledError):
                raise


def list_backups():
    return sorted([{'id': p.stem, 'bytes': p.stat().st_size, 'created_at': int(p.stat().st_mtime)}
                   for p in directory().glob('*.zip') if re.fullmatch(BACKUP_ID_PATTERN, p.stem)],
                  key=lambda item: item['created_at'], reverse=True)


def prune_scheduled_backups(retention_count):
    """Apply retention only to verified scheduled backups; keep manual copies."""
    retention_count = max(1, min(int(retention_count), 365))
    candidates = []
    for path in directory().glob('*.zip'):
        if not re.fullmatch(BACKUP_ID_PATTERN, path.stem):
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.getinfo(MANIFEST_FILENAME).file_size > 16384:
                    continue
                envelope = json.loads(archive.read(MANIFEST_FILENAME))
                manifest = envelope['manifest']
                if (manifest.get('version') == 2 and manifest.get('trigger') == 'scheduled'
                        and hmac.compare_digest(sign(manifest), str(envelope.get('signature', '')))):
                    candidates.append((int(manifest['created_at']), path))
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError):
            continue
    candidates.sort(reverse=True)
    removed = 0
    for _, path in candidates[retention_count:]:
        path.unlink()
        removed += 1
    return removed


def recover_interrupted_jobs():
    rows = store.setting_items('job:')
    for row in rows:
        record = row['value']
        if record.get('status') in {'pending', 'running'}:
            record.update(status='error', error='Service restarted before the job completed', updated_at=int(time.time()))
            store.set_setting(row['key'], record)


async def daemon():
    while True:
        try:
            now = int(time.time())
            if await asyncio.to_thread(store.claim_backup_schedule, now):
                await create(uuid.uuid4().hex, trigger='scheduled')
            if await asyncio.to_thread(store.claim_daily_log_cleanup, now):
                retention = max(30, min(int(settings.OPERATIONS_LOG_RETENTION_DAYS), 3650))
                cutoff = now - retention * 86400
                removed = await asyncio.to_thread(store.prune_logs_before, cutoff)
                old_jobs = await asyncio.to_thread(store.prune_old_jobs_before, cutoff)
                if any(removed.values()) or old_jobs:
                    await asyncio.to_thread(store.append, 'operation_log', 'operations.retention_pruned',
                                            {'logs': removed, 'jobs': old_jobs, 'retention_days': retention})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await asyncio.to_thread(store.append, 'operation_log', 'backup.scheduler_error',
                                        {'error': type(exc).__name__})
            except Exception:
                logger.exception('Backup scheduler failed and PostgreSQL logging is unavailable')
        await asyncio.sleep(30)
