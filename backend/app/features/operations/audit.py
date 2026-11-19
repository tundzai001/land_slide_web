"""Request journal plus committed ORM changes; never persist credentials."""
import asyncio
import copy
import logging

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from . import store

logger = logging.getLogger(__name__)


@event.listens_for(Session, 'loaded_as_persistent')
def remember_original(session, obj):
    if store.current_audit() is not None:
        state = inspect(obj)
        session.info.setdefault('audit_original', {})[id(obj)] = store.redact(copy.deepcopy({
            column.key: state.dict.get(column.key) for column in state.mapper.column_attrs
        }))


def _extract_object_changes(operation: str, state, original: dict) -> dict:
    changes = {}
    for column in state.mapper.column_attrs:
        attribute = state.attrs[column.key]
        history = attribute.history
        if operation == 'update' and not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else original.get(column.key)
        if operation == 'delete':
            old = state.dict.get(column.key)
        changes[column.key] = {
            'old': old,
            'new': state.dict.get(column.key) if operation != 'delete' else None,
        }
    return changes


def _process_audit_objects(pending: list, operation: str, objects, original_map: dict) -> None:
    for obj in objects:
        state = inspect(obj)
        original = original_map.get(id(obj), {})
        changes = _extract_object_changes(operation, state, original)
        if changes:
            pending.append({
                'table': state.mapper.local_table.name,
                'operation': operation,
                'identity': state.identity,
                'changes': store.redact(changes),
                '_object': obj,
            })


@event.listens_for(Session, 'before_flush')
def capture_changes(session, *_):
    context = store.current_audit()
    if context is None:
        return
    pending = session.info.setdefault('audit_pending', [])
    original_map = session.info.get('audit_original', {})
    for operation, objects in [('create', session.new), ('update', session.dirty), ('delete', session.deleted)]:
        _process_audit_objects(pending, operation, objects, original_map)


@event.listens_for(Session, 'do_orm_execute')
def capture_bulk(execution):
    if store.current_audit() is None or not (execution.is_update or execution.is_delete):
        return
    statement = execution.statement
    table = statement.table
    query = select(*table.c)
    if statement.whereclause is not None:
        query = query.where(statement.whereclause)
    # Large bulk maintenance records a bounded sample and affected row count.
    before = execution.session.execute(query.limit(100), execution.parameters or {}).mappings().all()
    result = execution.invoke_statement()
    after = []
    if execution.is_update and before:
        primary = list(table.primary_key.columns)
        if len(primary) == 1:
            after = execution.session.execute(select(*table.c).where(primary[0].in_([r[primary[0].name] for r in before]))).mappings().all()
    execution.session.info.setdefault('audit_pending', []).append({
        'table': table.name, 'operation': 'bulk_update' if execution.is_update else 'bulk_delete',
        'rowcount': getattr(result, 'rowcount', None), 'sample_limit': 100,
        'old': store.redact([dict(row) for row in before]), 'new': store.redact([dict(row) for row in after]),
    })
    return result


@event.listens_for(Session, 'after_commit')
def committed(session):
    pending = session.info.pop('audit_pending', [])
    session.info.pop('audit_original', None)
    for change in pending:
        obj = change.pop('_object', None)
        if obj is not None:
            change['identity'] = inspect(obj).identity
    context = store.current_audit()
    if context is not None:
        context.setdefault('changes', []).extend(pending)


@event.listens_for(Session, 'after_rollback')
def rolled_back(session):
    session.info.pop('audit_pending', None)
    session.info.pop('audit_original', None)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        tracked = path.startswith('/api/') and (
            request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} or
            'export' in path or 'download' in path or '/report' in path)
        if not tracked or path.startswith('/api/field/heartbeat'):
            return await call_next(request)
        context = {'changes': [], 'active': True}
        token = store.request_audit.set(context)
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            context['active'] = False
            try:
                await asyncio.to_thread(store.append, 'audit_log', f'{request.method} {path}',
                                        {'changes': context['changes']},
                                        username=context.get('username'), role=context.get('role'),
                                        object=path, ip=request.client.host if request.client else None, status=status)
            except Exception:
                logger.critical('Audit journal unavailable for %s %s', request.method, path, exc_info=True)
            store.request_audit.reset(token)
