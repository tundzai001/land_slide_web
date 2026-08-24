"""Incident & Response API.

This is additive to the legacy Alert/Rescue endpoints.  The serializer never
returns Rescue PII or precise coordinates; source detail remains role-scoped in
the legacy routes until the scoped Incident image/source adapters are enabled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..config import settings
from ..database import get_data_db
from ..models import auth as model_auth
from ..models import data as model_data
from ..services.incident_cases import (
    PRIORITY_ORDER,
    VALID_PRIORITIES,
    VALID_STATUSES,
    append_event,
    can_view_case,
    case_project_ids,
    serialize_case,
)

router = APIRouter(tags=["Incidents"])

_STATUS_ATTENTION_ORDER = {
    "new": 3,
    "acknowledged": 2,
    "in_progress": 2,
    "monitoring": 1,
    "resolved": 0,
    "dismissed": 0,
}


def _attention_rank(case_row: model_data.IncidentCase) -> int:
    return _STATUS_ATTENTION_ORDER.get(str(case_row.status or "").lower(), 0) * 10 + PRIORITY_ORDER.get(str(case_row.priority or "").upper(), -1)


class AcknowledgeBody(BaseModel):
    expected_version: int = Field(ge=1)
    assign_to_self: bool = True


class PriorityBody(BaseModel):
    priority: str
    note: Optional[str] = Field(default=None, max_length=4000)
    expected_version: int = Field(ge=1)


class AssignBody(BaseModel):
    assignee_user_id: Optional[int] = None
    expected_version: int = Field(ge=1)


class ScopeBody(BaseModel):
    project_id: Optional[int] = None
    station_id: Optional[int] = None
    expected_version: int = Field(ge=1)


class TransitionBody(BaseModel):
    to_status: str
    note: Optional[str] = Field(default=None, max_length=4000)
    expected_version: int = Field(ge=1)


class NoteBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _scope_hash(user: model_auth.User) -> str:
    projects = sorted(case_project_ids(user))
    material = ":".join([
        str(user.id),
        str(bool(user.is_active)).lower(),
        str(user.role or ""),
        ",".join(str(project_id) for project_id in projects),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _is_admin(user: model_auth.User) -> bool:
    return str(user.role or "").lower() == auth.Role.ADMIN


def _is_manager(user: model_auth.User) -> bool:
    return _is_admin(user) or str(user.role or "").lower() == auth.Role.OPERATOR


def _private_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _canonical_filter_hash(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sign_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + b"." + signature).decode("ascii").rstrip("=")


def _decode_cursor(value: str, *, scope_hash: str, filter_hash: str, sort: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        packed = base64.urlsafe_b64decode(padded.encode("ascii"))
        raw, signature = packed.rsplit(b".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw.decode("utf-8"))
        if (
            payload.get("v") != 1
            or payload.get("scope_hash") != scope_hash
            or payload.get("filter_hash") != filter_hash
            or payload.get("sort") != sort
        ):
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeError):
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Cursor không hợp lệ hoặc đã hết hạn"})


def _base_scope_stmt(user: model_auth.User):
    stmt = select(model_data.IncidentCase)
    if not _is_admin(user):
        project_ids = case_project_ids(user)
        if not project_ids:
            return stmt.where(False)
        stmt = stmt.where(model_data.IncidentCase.project_id.in_(project_ids))
    return stmt


async def _load_case(
    db: AsyncSession,
    user: model_auth.User,
    incident_id: int,
    *,
    for_update: bool = False,
) -> model_data.IncidentCase:
    stmt = select(model_data.IncidentCase).where(model_data.IncidentCase.id == int(incident_id))
    if for_update:
        stmt = stmt.with_for_update()
    case = (await db.execute(stmt)).scalar_one_or_none()
    # 404 outside scope avoids leaking whether an id exists.
    if case is None or not can_view_case(user, case):
        raise HTTPException(status_code=404, detail="Incident not found")
    return case


async def _event_rows(db: AsyncSession, case_id: int, limit: int = 50):
    rows = (await db.execute(
        select(model_data.IncidentEvent)
        .where(model_data.IncidentEvent.incident_id == int(case_id))
        .order_by(desc(model_data.IncidentEvent.sequence), desc(model_data.IncidentEvent.id))
        .limit(min(max(limit, 1), 100))
    )).scalars().all()
    return [
        {
            "id": int(row.id),
            "incident_id": int(row.incident_id),
            "sequence": int(row.sequence),
            "event_type": row.event_type,
            "actor_kind": row.actor_kind,
            "actor_user_id": row.actor_user_id,
            "actor_username": row.actor_username,
            "project_id_at_event": row.project_id_at_event,
            "previous_project_id": row.previous_project_id,
            "created_at": int(row.created_at),
            "note": row.note,
            "payload": row.payload or {},
        }
        for row in reversed(rows)
    ]


def _mutation_key_or_error(value: Optional[str]) -> str:
    key = str(value or "").strip()
    if not 1 <= len(key) <= 64:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Thiếu Idempotency-Key"})
    return key


def _fingerprint(action: str, body: Any) -> str:
    payload = json.dumps({"action": action, "body": body}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _existing_mutation(
    db: AsyncSession,
    case_id: int,
    actor_id: int,
    key: str,
    action: str,
    fingerprint: str,
):
    row = (await db.execute(select(model_data.IncidentMutationRequest).where(
        model_data.IncidentMutationRequest.incident_id == int(case_id),
        model_data.IncidentMutationRequest.actor_user_id == int(actor_id),
        model_data.IncidentMutationRequest.idempotency_key == key,
    ))).scalar_one_or_none()
    if row is None:
        return None
    if row.action != action or row.request_fingerprint != fingerprint:
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency-Key đã được dùng cho mutation khác"})
    return row


async def _broadcast_case(case: model_data.IncidentCase, event: Optional[model_data.IncidentEvent], action: str = "updated"):
    if event is None:
        return
    # Import lazily to keep model/router imports cheap during migrations/tests.
    from ..websocket import manager as ws_manager
    await ws_manager.broadcast_operations({
        "protocol": 2,
        "type": "incident_changed",
        "event_id": int(event.id),
        "sequence_from": int(event.sequence),
        "sequence_to": int(event.sequence),
        "incident_id": int(case.id),
        "incident_revision": int(case.revision),
        "workflow_version": int(case.version),
        "action": action,
        "project_id": case.project_id,
        "station_id": case.station_id,
        "summary": serialize_case(case),
    })


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


@router.post("/api/incidents/{incident_id}/scope")
async def set_incident_scope(
    incident_id: int,
    body: ScopeBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Chỉ admin được đổi scope incident")

    async def mutate(case):
        previous_project_id = case.project_id
        if case.project_id == body.project_id and case.station_id == body.station_id and case.scope_state == "SCOPED":
            return False, "scope_changed", None, {"project_id": body.project_id, "station_id": body.station_id}
        case.project_id = body.project_id
        case.station_id = body.station_id
        case.scope_state = "SCOPED" if body.project_id is not None else "LOOKUP_PENDING"
        case.version += 1
        return True, "scope_changed", None, {"project_id": body.project_id, "station_id": body.station_id, "previous_project_id": previous_project_id}

    return await _mutate_case(db, current_user, incident_id, "scope", body.model_dump(), idempotency_key, mutate)


async def _mutate_case(
    db: AsyncSession,
    user: model_auth.User,
    incident_id: int,
    action: str,
    body: dict[str, Any],
    idempotency_key: Optional[str],
    mutate,
):
    key = _mutation_key_or_error(idempotency_key)
    case = await _load_case(db, user, incident_id, for_update=True)
    fingerprint = _fingerprint(action, body)
    existing = await _existing_mutation(db, incident_id, int(user.id), key, action, fingerprint)
    if existing:
        await db.commit()
        return {"case": serialize_case(case, include_private=_is_manager(user)), "events": [], "changed": bool(existing.changed), "idempotent_replay": True, "version": case.version, "revision": case.revision}
    expected = body.get("expected_version")
    if expected is not None and int(expected) != int(case.version):
        raise HTTPException(status_code=409, detail={"code": "VERSION_CONFLICT", "message": "Incident đã được cập nhật", "current": serialize_case(case, include_private=_is_manager(user))})
    before_sequence = int(case.last_event_sequence or 0) + 1
    changed, event_type, event_note, event_payload = await mutate(case)
    events = []
    if changed:
        event = await append_event(db, case, event_type, actor_kind="user", actor_user_id=int(user.id), actor_username=getattr(user, "username", None), note=event_note, payload=event_payload)
        events = [event]
    ledger = model_data.IncidentMutationRequest(
        incident_id=int(case.id), actor_user_id=int(user.id), idempotency_key=key,
        action=action, request_fingerprint=fingerprint,
        sequence_from=events[0].sequence if events else None,
        sequence_to=events[-1].sequence if events else None,
        result_revision=int(case.revision), result_version=int(case.version), changed=bool(changed), created_at=int(time.time()),
    )
    db.add(ledger)
    try:
        await db.flush()
        for event in events:
            event.mutation_request_id = int(ledger.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_RACE", "message": "Mutation đang được xử lý, vui lòng retry cùng key"})
    for event in events:
        await db.refresh(event)
    await _broadcast_case(case, events[-1] if events else None)
    return {"case": serialize_case(case, include_private=_is_manager(user)), "events": [
        {"id": int(event.id), "sequence": int(event.sequence), "event_type": event.event_type, "created_at": int(event.created_at)} for event in events
    ], "changed": changed, "idempotent_replay": False, "version": case.version, "revision": case.revision}


@router.post("/api/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(
    incident_id: int,
    body: AcknowledgeBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    async def mutate(case):
        changed = case.status == "new"
        if body.assign_to_self and case.assigned_to_user_id is None:
            case.assigned_to_user_id = int(current_user.id); case.assigned_to_username = current_user.username; changed = True
        if case.status == "new":
            case.status = "acknowledged"; case.acknowledged_at = int(time.time())
        if changed: case.version += 1
        return changed, "acknowledged", None, {"status": case.status, "assigned_to_user_id": case.assigned_to_user_id}
    return await _mutate_case(db, current_user, incident_id, "acknowledge", body.model_dump(), idempotency_key, mutate)


@router.post("/api/incidents/{incident_id}/priority")
async def set_incident_priority(
    incident_id: int,
    body: PriorityBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    requested = body.priority.strip().upper()
    if requested not in VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PRIORITY", "message": "Priority không hợp lệ"})
    async def mutate(case):
        if case.priority == requested:
            return False, "priority_changed", body.note, {"priority": requested}
        if case.priority != "UNTRIAGED" and PRIORITY_ORDER[requested] < PRIORITY_ORDER[case.priority] and not body.note:
            raise HTTPException(status_code=422, detail={"code": "NOTE_REQUIRED", "message": "Giảm mức ưu tiên cần ghi chú"})
        case.priority = requested; case.version += 1
        return True, "priority_changed", body.note, {"priority": requested}
    return await _mutate_case(db, current_user, incident_id, "priority", body.model_dump(), idempotency_key, mutate)


@router.post("/api/incidents/{incident_id}/assign")
async def assign_incident(
    incident_id: int,
    body: AssignBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    if not _is_admin(current_user) and body.assignee_user_id not in {None, int(current_user.id)}:
        raise HTTPException(status_code=403, detail="Operator chỉ được tự nhận hoặc bỏ nhận sự cố")
    async def mutate(case):
        if case.assigned_to_user_id == body.assignee_user_id:
            return False, "assigned", None, {"assigned_to_user_id": body.assignee_user_id}
        case.assigned_to_user_id = body.assignee_user_id
        case.assigned_to_username = current_user.username if body.assignee_user_id == current_user.id else None
        case.version += 1
        return True, "assigned", None, {"assigned_to_user_id": body.assignee_user_id}
    return await _mutate_case(db, current_user, incident_id, "assign", body.model_dump(), idempotency_key, mutate)


@router.post("/api/incidents/{incident_id}/transition")
async def transition_incident(
    incident_id: int,
    body: TransitionBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    target = body.to_status.strip().lower()
    if target not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail={"code": "INVALID_STATUS", "message": "Status không hợp lệ"})
    async def mutate(case):
        if case.status == target:
            return False, "status_changed", body.note, {"status": target}
        allowed = {
            "new": {"acknowledged", "dismissed"},
            "acknowledged": {"in_progress", "monitoring", "resolved", "dismissed"},
            "in_progress": {"monitoring", "resolved", "dismissed"},
            "monitoring": {"in_progress", "resolved", "dismissed"},
            "resolved": {"in_progress"},
            "dismissed": {"in_progress"},
        }
        if target not in allowed.get(case.status, set()):
            raise HTTPException(status_code=422, detail={"code": "INVALID_TRANSITION", "message": "Chuyển trạng thái không hợp lệ"})
        if target in {"resolved", "dismissed", "in_progress"} and case.status in {"resolved", "dismissed"} and not body.note:
            raise HTTPException(status_code=422, detail={"code": "NOTE_REQUIRED", "message": "Thao tác này cần ghi chú"})
        if target in {"in_progress", "monitoring", "resolved"} and case.priority == "UNTRIAGED":
            raise HTTPException(status_code=422, detail={"code": "TRIAGE_REQUIRED", "message": "Cần phân loại ưu tiên trước"})
        case.status = target; case.version += 1; case.resolved_at = int(time.time()) if target == "resolved" else None
        if target == "acknowledged" and case.acknowledged_at is None: case.acknowledged_at = int(time.time())
        return True, "status_changed", body.note, {"status": target}
    return await _mutate_case(db, current_user, incident_id, "transition", body.model_dump(), idempotency_key, mutate)


@router.post("/api/incidents/{incident_id}/notes")
async def add_incident_note(
    incident_id: int,
    body: NoteBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    async def mutate(case):
        return True, "note_added", body.message, {}
    return await _mutate_case(db, current_user, incident_id, "notes", body.model_dump(), idempotency_key, mutate)
