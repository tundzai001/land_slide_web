"""Local durable operational journal, independent of the measured-data database."""
import contextvars
import json
import os
import sqlite3
import time
from pathlib import Path

from ...config import settings

request_audit = contextvars.ContextVar('request_audit', default=None)


def current_audit():
    context = request_audit.get()
    return context if context is not None and context.get('active', True) else None


def root():
    path = Path(settings.OPERATIONS_DIR or Path(__file__).resolve().parents[4] / 'runtime' / 'operations')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def connect():
    path = root() / 'journal.sqlite3'
    db = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    for table in ('audit_log', 'operation_log'):
        db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL, username TEXT,
            role TEXT, action TEXT NOT NULL, object TEXT, ip TEXT, status INTEGER,
            details TEXT NOT NULL)''')
        db.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_time ON {table}(timestamp, id)')
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return db


def redact(value):
    if isinstance(value, dict):
        return {str(k): ('[REDACTED]' if any(part in str(k).lower() for part in
                ('password', 'secret', 'token', 'credential', 'private_key')) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return value[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def actor(user):
    context = current_audit()
    if context is not None:
        context.update(username=user.username, role=user.role)


def append(table, action, details=None, **fields):
    if table not in ('audit_log', 'operation_log'):
        raise ValueError('Unknown journal')
    with connect() as db:
        db.execute(f'INSERT INTO {table} (timestamp, username, role, action, object, ip, status, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                   (int(time.time()), fields.get('username'), fields.get('role'), action,
                    fields.get('object'), fields.get('ip'), fields.get('status'),
                    json.dumps(redact(details or {}), ensure_ascii=False)))
    db.close()


def query(table, offset=0, limit=50, action='', username='', start=0, end=0):
    if table not in ('audit_log', 'operation_log'):
        raise ValueError('Unknown journal')
    clauses, params = [], []
    for name, value in [('action', action), ('username', username)]:
        if value:
            clauses.append(f'{name} = ?')
            params.append(value)
    if start:
        clauses.append('timestamp >= ?')
        params.append(start)
    if end:
        clauses.append('timestamp <= ?')
        params.append(end)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    db = connect()
    try:
        total = db.execute(f'SELECT COUNT(*) FROM {table}{where}', params).fetchone()[0]
        rows = db.execute(f'SELECT * FROM {table}{where} ORDER BY id DESC LIMIT ? OFFSET ?',
                          [*params, limit, offset]).fetchall()
        return {'total': total, 'offset': offset, 'rows': [dict(r, details=json.loads(r['details'])) for r in rows]}
    finally:
        db.close()


def get_setting(key, default=None):
    db = connect()
    try:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default
    finally:
        db.close()


def set_setting(key, value):
    context = current_audit()
    tracked = context is not None and key in {'backup_schedule', 'ntp_config'}
    previous = get_setting(key) if tracked else None
    with connect() as db:
        db.execute('INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps(value, ensure_ascii=False)))
    db.close()
    if tracked:
        context.setdefault('changes', []).append({'table': 'settings', 'identity': key,
                                                 'old': redact(previous), 'new': redact(value)})
