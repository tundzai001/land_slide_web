"""Hot PostgreSQL dumps and isolated recovery; live connections stay untouched."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
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


def directory():
    path = store.root() / 'backups'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def backup_path(identifier):
    if not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('Invalid backup identifier')
    return directory() / f'{identifier}.zip'


def sign(manifest):
    return hmac.new(settings.SECRET_KEY.encode(), json.dumps(manifest, sort_keys=True).encode(), hashlib.sha256).hexdigest()


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
    if url.query.get('sslmode'):
        env['PGSSLMODE'] = str(url.query['sslmode'])
    return env


async def run_tool(name, args, env):
    binary = shutil.which(name)
    if not binary:
        raise RuntimeError(f'Install PostgreSQL client tools: {name} is unavailable')
    process = await asyncio.create_subprocess_exec(binary, *args, env=env,
                                                   stdout=asyncio.subprocess.DEVNULL,
                                                   stderr=asyncio.subprocess.PIPE)
    try:
        _, error = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.terminate()
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


async def create(identifier):
    async with lock:
        await asyncio.to_thread(job, identifier, kind='backup', status='running')
        partial = backup_path(identifier).with_suffix('.partial')
        try:
            with tempfile.TemporaryDirectory(dir=directory()) as temp:
                files = {}
                for label, engine in DATABASES.items():
                    filename = f'{label}.dump'
                    target = Path(temp) / filename
                    await run_tool('pg_dump', ['--format=custom', '--no-owner', '--no-acl', '--file', str(target)], pg_environment(engine))
                    files[filename] = {'sha256': await asyncio.to_thread(digest, target), 'bytes': target.stat().st_size}
                journal = Path(temp) / 'journal.sqlite3'
                def snapshot_journal():
                    source = store.connect()
                    destination = sqlite3.connect(journal)
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
                        source.close()
                await asyncio.to_thread(snapshot_journal)
                files[journal.name] = {'sha256': await asyncio.to_thread(digest, journal), 'bytes': journal.stat().st_size}
                manifest = {'version': 1, 'created_at': int(time.time()), 'files': files,
                            'recovery_mode': 'isolated', 'snapshots': 'one snapshot per database'}
                def pack():
                    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_STORED) as archive:
                        archive.writestr('manifest.json', json.dumps({'manifest': manifest, 'signature': sign(manifest)}))
                        for filename in files:
                            archive.write(Path(temp) / filename, filename)
                    os.chmod(partial, 0o600)
                    os.replace(partial, backup_path(identifier))
                await asyncio.to_thread(pack)
            await asyncio.to_thread(job, identifier, status='completed', backup_id=identifier, created_at=manifest['created_at'])
            await asyncio.to_thread(store.append, 'operation_log', 'backup.completed', {'backup_id': identifier})
        except BaseException as exc:
            partial.unlink(missing_ok=True)
            await asyncio.to_thread(job, identifier, status='error', error=str(exc)[:500] or 'Interrupted')
            await asyncio.to_thread(store.append, 'operation_log', 'backup.failed', {'error': str(exc)[:500]})
            if isinstance(exc, asyncio.CancelledError):
                raise


def validate_archive(path, destination=None):
    with zipfile.ZipFile(path) as archive:
        base_files = {'auth.dump', 'config.dump', 'data.dump'}
        if archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('Invalid manifest size')
        envelope = json.loads(archive.read('manifest.json'))
        manifest = envelope['manifest']
        if manifest.get('version') != 1 or not hmac.compare_digest(sign(manifest), str(envelope.get('signature', ''))):
            raise ValueError('Backup signature invalid; restore only backups signed by this installation')
        files = set(manifest.get('files', {}))
        if files not in (base_files, base_files | {'journal.sqlite3'}):
            raise ValueError('Invalid manifest files')
        if sorted(archive.namelist()) != sorted(['manifest.json', *files]):
            raise ValueError('Backup must contain exactly the manifest and its declared files')
        for name in files:
            info = archive.getinfo(name)
            if info.file_size != manifest['files'][name]['bytes'] or info.file_size > 50 * 1024**3:
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
                    name = f'recovery_{identifier[:16]}_{label}'
                    async with engine.connect() as connection:
                        connection = await connection.execution_options(isolation_level='AUTOCOMMIT')
                        await connection.execute(text(f'CREATE DATABASE "{name}"'))
                    stages[label] = name
                    await asyncio.to_thread(job, identifier, recovered_databases=stages.copy())
                    await run_tool('pg_restore', ['--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                                                 '--dbname', name, str(Path(temp) / f'{label}.dump')], pg_environment(engine, name))
                journal = Path(temp) / 'journal.sqlite3'
                if journal.exists():
                    recovered_journal = directory() / f'recovery_{identifier}_journal.sqlite3'
                    await asyncio.to_thread(shutil.copyfile, journal, recovered_journal)
                    recovered_journal.chmod(0o600)
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
                   for p in directory().glob('*.zip') if re.fullmatch(r'[0-9a-f]{32}', p.stem)],
                  key=lambda item: item['created_at'], reverse=True)


def recover_interrupted_jobs():
    db = store.connect()
    try:
        rows = db.execute("SELECT key, value FROM settings WHERE key LIKE 'job:%'").fetchall()
    finally:
        db.close()
    for row in rows:
        record = json.loads(row['value'])
        if record.get('status') in {'pending', 'running'}:
            record.update(status='error', error='Service restarted before the job completed', updated_at=int(time.time()))
            store.set_setting(row['key'], record)


async def daemon():
    while True:
        try:
            schedule = await asyncio.to_thread(store.get_setting, 'backup_schedule', {'frequency': 'disabled'})
            period = {'daily': 86400, 'weekly': 604800}.get(schedule.get('frequency'))
            if period and time.time() >= schedule.get('next_at', 0):
                # Claim before starting to prevent retry storms after a utility/DB outage.
                schedule['next_at'] = int(time.time()) + period
                await asyncio.to_thread(store.set_setting, 'backup_schedule', schedule)
                await create(uuid.uuid4().hex)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.to_thread(store.append, 'operation_log', 'backup.scheduler_error', {'error': type(exc).__name__})
        await asyncio.sleep(30)
