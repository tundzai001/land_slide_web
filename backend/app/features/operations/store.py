"""PostgreSQL-backed audit, operations, and settings store."""
import contextvars
import copy
import math
import time

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from ...config import settings
from ...models.operations import AuditLog, OperationLog, OperationsSetting

request_audit = contextvars.ContextVar('request_audit', default=None)


def current_audit():
    context = request_audit.get()
    return context if context is not None and context.get('active', True) else None


def _sync_engine(url):
    parsed = make_url(url)
    if parsed.drivername.startswith('postgresql'):
        parsed = parsed.set(drivername='postgresql+psycopg2')
        return create_engine(parsed, pool_pre_ping=True, pool_recycle=1800,
                            pool_size=2, max_overflow=2, pool_timeout=10,
                            connect_args={'connect_timeout': 10})
    if parsed.drivername.startswith('sqlite'):
        return create_engine(parsed.set(drivername='sqlite'))
    raise RuntimeError('Operational records require PostgreSQL')


_engine = _sync_engine(settings.DATA_DB_URL)
_sessions = sessionmaker(_engine, expire_on_commit=False)


def configure_engine(engine):
    """Allow isolated SQLite engines in tests; production uses DATA_DB_URL."""
    global _engine, _sessions
    previous = _engine
    _engine = engine
    _sessions = sessionmaker(engine, expire_on_commit=False)
    return previous


def redact(value):
    if isinstance(value, dict):
        return {str(k): ('[REDACTED]' if any(part in str(k).lower() for part in
                ('password', 'secret', 'token', 'credential', 'private_key',
                 'authorization', 'connection_string', 'database_url', 'dsn')) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def actor(user):
    context = current_audit()
    if context is not None:
        context.update(username=user.username, role=user.role)


def _without_request_audit():
    return request_audit.set(None)


def append(table, action, details=None, **fields):
    model = {'audit_log': AuditLog, 'operation_log': OperationLog}.get(table)
    if model is None:
        raise ValueError('Unknown journal')
    token = _without_request_audit()
    try:
        with _sessions.begin() as db:
            db.add(model(timestamp=int(time.time()), username=str(fields['username'])[:150] if fields.get('username') else None,
                         role=str(fields['role'])[:32] if fields.get('role') else None,
                         action=str(action)[:255], object=str(fields['object'])[:500] if fields.get('object') else None,
                         ip=str(fields['ip'])[:64] if fields.get('ip') else None, status=fields.get('status'),
                         details=redact(details or {})))
    finally:
        request_audit.reset(token)


def query(table, offset=0, limit=50, action='', username='', start=0, end=0, method=''):
    model = {'audit_log': AuditLog, 'operation_log': OperationLog}.get(table)
    if model is None:
        raise ValueError('Unknown journal')
    filters = []
    if action:
        filters.append(model.action == action)
    if method:
        filters.append(model.action.startswith(method + ' '))
    if username:
        filters.append(model.username == username)
    if start:
        filters.append(model.timestamp >= start)
    if end:
        filters.append(model.timestamp <= end)
    with _sessions() as db:
        total = db.scalar(select(func.count()).select_from(model).where(*filters)) or 0
        rows = db.scalars(select(model).where(*filters).order_by(model.id.desc())
                          .offset(offset).limit(limit)).all()
        return {'total': total, 'offset': offset, 'rows': [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in rows]}


def log_options():
    with _sessions() as db:
        return {name: {
            'actions': list(db.scalars(select(model.action).distinct().order_by(model.action))),
            'usernames': list(db.scalars(select(model.username).where(model.username.is_not(None)).distinct().order_by(model.username))),
        } for name, model in [('audit_log', AuditLog), ('operation_log', OperationLog)]}


def get_setting(key, default=None):
    with _sessions() as db:
        row = db.get(OperationsSetting, key)
        return copy.deepcopy(row.value) if row else default


def set_setting(key, value):
    context = current_audit()
    tracked = context is not None and key in {'backup_schedule', 'ntp_config'}
    previous = get_setting(key) if tracked else None
    token = _without_request_audit()
    try:
        with _sessions.begin() as db:
            row = db.get(OperationsSetting, key)
            if row is None:
                db.add(OperationsSetting(key=key, value=copy.deepcopy(value)))
            else:
                row.value = copy.deepcopy(value)
    finally:
        request_audit.reset(token)
    if tracked:
        context.setdefault('changes', []).append({'table': 'operations_settings', 'identity': key,
                                                  'old': redact(previous), 'new': redact(value)})


def setting_items(prefix=''):
    with _sessions() as db:
        rows = db.scalars(select(OperationsSetting).where(
            OperationsSetting.key.like(prefix + '%'))).all()
        return [{'key': row.key, 'value': copy.deepcopy(row.value)} for row in rows]


def claim_backup_schedule(now):
    """Claim one due backup atomically across workers sharing the PostgreSQL DB."""
    with _sessions.begin() as db:
        row = db.scalar(select(OperationsSetting).where(
            OperationsSetting.key == 'backup_schedule').with_for_update())
        if row is None or not isinstance(row.value, dict):
            return False
        period = {'daily': 86400, 'weekly': 604800}.get(row.value.get('frequency'))
        if not period or now < row.value.get('next_at', 0):
            return False
        row.value = {**row.value, 'next_at': now + period}
        return True


def claim_daily_log_cleanup(now):
    key = 'operations_log_cleanup'
    with _sessions.begin() as db:
        row = db.scalar(select(OperationsSetting).where(
            OperationsSetting.key == key).with_for_update())
        if row and now < (row.value or {}).get('next_at', 0):
            return False
        value = {'next_at': now + 86400}
        if row is None:
            db.add(OperationsSetting(key=key, value=value))
        else:
            row.value = value
        return True


def prune_logs_before(timestamp):
    with _sessions.begin() as db:
        audit = db.execute(delete(AuditLog).where(AuditLog.timestamp < timestamp)).rowcount
        operations = db.execute(delete(OperationLog).where(
            OperationLog.timestamp < timestamp)).rowcount
        return {'audit_log': audit or 0, 'operation_log': operations or 0}


def prune_old_jobs_before(timestamp):
    with _sessions.begin() as db:
        rows = db.scalars(select(OperationsSetting).where(
            OperationsSetting.key.like('job:%'))).all()
        expired = [row.key for row in rows
                   if (row.value or {}).get('updated_at', 0) < timestamp]
        if expired:
            db.execute(delete(OperationsSetting).where(OperationsSetting.key.in_(expired)))
        return len(expired)


def dispose():
    _engine.dispose()
