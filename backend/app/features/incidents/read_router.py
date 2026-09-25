"""Incident read routes."""

from __future__ import annotations

import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_data_db
from ...models import auth as model_auth
from ...models import data as model_data
from .cases import PRIORITY_ORDER, VALID_PRIORITIES, VALID_STATUSES, case_project_ids, serialize_case
from .common import (_STATUS_ATTENTION_ORDER, _attention_rank, _base_scope_stmt, _canonical_filter_hash, _decode_cursor, _event_rows, _is_admin, _is_manager, _load_case, _private_headers, _scope_hash, _sign_cursor)

router = APIRouter(tags=["Incidents"])

@router.get("/api/incidents")
async def list_incidents(
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    source_severity: Optional[str] = None,
    signal_state: Optional[str] = None,
    source_kind: Optional[str] = None,
    project_id: Optional[int] = None,
    station_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    q: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    sort: str = Query("-updated_at"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_INCIDENTS)),
):
    _private_headers(response)
    if sort not in {"attention", "-updated_at", "updated_at", "opened_at"}:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SORT", "message": "Sort không được hỗ trợ"})
    scope_hash = _scope_hash(current_user)
    filter_payload = {
        "status": status_filter, "priority": priority, "source_severity": source_severity,
        "signal_state": signal_state, "source_kind": source_kind, "project_id": project_id,
        "station_id": station_id, "assigned_to": assigned_to, "q": q, "sort": sort,
    }
    filter_hash = _canonical_filter_hash(filter_payload)
    stmt = _base_scope_stmt(current_user)
    conditions = []
    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail={"code": "INVALID_STATUS", "message": "Status không hợp lệ"})
        conditions.append(model_data.IncidentCase.status == status_filter)
    if priority:
        if priority.upper() not in VALID_PRIORITIES:
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRIORITY", "message": "Priority không hợp lệ"})
        conditions.append(model_data.IncidentCase.priority == priority.upper())
    if source_severity:
        conditions.append(model_data.IncidentCase.source_severity == str(source_severity).upper())
    if signal_state:
        conditions.append(model_data.IncidentCase.signal_state == str(signal_state).upper())
    if source_kind:
        conditions.append(model_data.IncidentCase.source_kind == str(source_kind).upper())
    if project_id is not None:
        conditions.append(model_data.IncidentCase.project_id == project_id)
    if station_id is not None:
        conditions.append(model_data.IncidentCase.station_id == station_id)
    if assigned_to is not None:
        conditions.append(model_data.IncidentCase.assigned_to_user_id == assigned_to)
    if q and q.strip():
        pattern = f"%{q.strip()[:100]}%"
        conditions.append(or_(
            model_data.IncidentCase.reference.ilike(pattern),
            model_data.IncidentCase.title.ilike(pattern),
            model_data.IncidentCase.summary.ilike(pattern),
            model_data.IncidentCase.project_name_snapshot.ilike(pattern),
            model_data.IncidentCase.station_name_snapshot.ilike(pattern),
            model_data.IncidentCase.station_code_snapshot.ilike(pattern),
        ))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    attention_status = case(
        *[(model_data.IncidentCase.status == value, rank) for value, rank in _STATUS_ATTENTION_ORDER.items()],
        else_=0,
    )
    attention_priority = case(
        *[(model_data.IncidentCase.priority == value, rank) for value, rank in PRIORITY_ORDER.items()],
        else_=0,
    )
    attention_rank = attention_status * 10 + attention_priority
    if cursor:
        payload = _decode_cursor(cursor, scope_hash=scope_hash, filter_hash=filter_hash, sort=sort)
        cursor_id = int(payload.get("id"))
        if sort == "attention":
            cursor_rank = int(payload.get("rank"))
            cursor_updated_at = int(payload.get("updated_at"))
            stmt = stmt.where(or_(
                attention_rank < cursor_rank,
                and_(attention_rank == cursor_rank, model_data.IncidentCase.updated_at < cursor_updated_at),
                and_(attention_rank == cursor_rank, model_data.IncidentCase.updated_at == cursor_updated_at, model_data.IncidentCase.id < cursor_id),
            ))
        else:
            cursor_value = int(payload.get("value"))
            field = model_data.IncidentCase.opened_at if sort == "opened_at" else model_data.IncidentCase.updated_at
            if sort in {"-updated_at", "opened_at"}:
                stmt = stmt.where(or_(field < cursor_value, and_(field == cursor_value, model_data.IncidentCase.id < cursor_id)))
            else:
                stmt = stmt.where(or_(field > cursor_value, and_(field == cursor_value, model_data.IncidentCase.id > cursor_id)))
    field = model_data.IncidentCase.opened_at if sort == "opened_at" else model_data.IncidentCase.updated_at
    if sort == "attention":
        stmt = stmt.order_by(attention_rank.desc(), model_data.IncidentCase.updated_at.desc(), model_data.IncidentCase.id.desc())
    elif sort == "updated_at":
        stmt = stmt.order_by(field.asc(), model_data.IncidentCase.id.asc())
    else:
        stmt = stmt.order_by(field.desc(), model_data.IncidentCase.id.desc())
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (await db.execute(stmt.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        cursor_payload = {
            "v": 1, "scope_hash": scope_hash, "filter_hash": filter_hash, "sort": sort,
            "id": int(last.id),
        }
        if sort == "attention":
            cursor_payload.update({"rank": _attention_rank(last), "updated_at": int(last.updated_at)})
        else:
            cursor_payload["value"] = int(last.opened_at if sort == "opened_at" else last.updated_at)
        next_cursor = _sign_cursor(cursor_payload)
    event_watermark = int((await db.execute(select(func.max(model_data.IncidentEvent.id)))).scalar_one() or 0)
    return {
        "items": [serialize_case(row, include_private=_is_manager(current_user)) for row in rows],
        "total": total,
        "next_cursor": next_cursor,
        "snapshot_event_id": event_watermark,
        "authz_scope_hash": scope_hash,
        "server_time": int(time.time()),
    }


@router.get("/api/incidents/{incident_id}")
async def get_incident(
    incident_id: int,
    response: Response,
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_INCIDENTS)),
):
    _private_headers(response)
    case = await _load_case(db, current_user, incident_id)
    return {"case": serialize_case(case, include_private=_is_manager(current_user)), "events": await _event_rows(db, incident_id)}


@router.get("/api/incidents/{incident_id}/events")
async def get_incident_events(
    incident_id: int,
    response: Response,
    before_sequence: Optional[int] = None,
    after_sequence: Optional[int] = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_INCIDENTS)),
):
    if before_sequence is not None and after_sequence is not None:
        raise HTTPException(status_code=422, detail={"code": "EVENT_CURSOR_CONFLICT", "message": "Chỉ dùng before hoặc after"})
    _private_headers(response)
    case = await _load_case(db, current_user, incident_id)
    stmt = select(model_data.IncidentEvent).where(model_data.IncidentEvent.incident_id == int(case.id))
    if before_sequence is not None:
        stmt = stmt.where(model_data.IncidentEvent.sequence < before_sequence).order_by(desc(model_data.IncidentEvent.sequence))
    else:
        if after_sequence is not None:
            stmt = stmt.where(model_data.IncidentEvent.sequence > after_sequence)
        stmt = stmt.order_by(model_data.IncidentEvent.sequence.asc())
    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    return {"items": [
        {"id": int(row.id), "sequence": int(row.sequence), "event_type": row.event_type,
         "actor_kind": row.actor_kind, "actor_user_id": row.actor_user_id,
         "actor_username": row.actor_username if _is_manager(current_user) else None,
         "created_at": int(row.created_at), "note": row.note if _is_manager(current_user) else None,
         "payload": row.payload or {}}
        for row in rows
    ], "has_more": len(rows) >= limit}


@router.get("/api/incident-events")
async def list_incident_events(
    response: Response,
    after_event_id: int = Query(0, ge=0),
    project_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.VIEW_INCIDENTS)),
):
    """Bounded catch-up stream for reconnecting operations clients.

    The payload is intentionally a non-PII envelope; details stay behind the
    authenticated per-case endpoint.
    """
    _private_headers(response)
    stmt = (
        select(model_data.IncidentEvent, model_data.IncidentCase)
        .join(model_data.IncidentCase, model_data.IncidentCase.id == model_data.IncidentEvent.incident_id)
        .where(model_data.IncidentEvent.id > int(after_event_id))
        .order_by(model_data.IncidentEvent.id.asc())
        .limit(limit)
    )
    if not _is_admin(current_user):
        project_ids = case_project_ids(current_user)
        if not project_ids:
            return {"items": [], "next_after_event_id": int(after_event_id), "snapshot_event_id": 0}
        stmt = stmt.where(model_data.IncidentCase.project_id.in_(project_ids))
    if project_id is not None:
        stmt = stmt.where(model_data.IncidentCase.project_id == int(project_id))
    rows = (await db.execute(stmt)).all()
    watermark = int((await db.execute(select(func.max(model_data.IncidentEvent.id)))).scalar_one() or 0)
    return {
        "items": [{
            "event_id": int(event.id), "sequence": int(event.sequence),
            "incident_id": int(case.id), "incident_revision": int(case.revision),
            "workflow_version": int(case.version), "event_type": event.event_type,
            "project_id": case.project_id, "station_id": case.station_id,
            "updated_at": int(case.updated_at),
        } for event, case in rows],
        "next_after_event_id": int(rows[-1][0].id) if rows else int(after_event_id),
        "snapshot_event_id": watermark,
    }
