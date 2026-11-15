"""Incident mutation routes."""

from __future__ import annotations

import inspect
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_data_db
from ...models import auth as model_auth
from ...models import data as model_data
from .cases import PRIORITY_ORDER, VALID_PRIORITIES, VALID_STATUSES, append_event, serialize_case
from .common import _broadcast_case, _existing_mutation, _fingerprint, _is_admin, _is_manager, _load_case, _mutation_key_or_error
from .schemas import AcknowledgeBody, AssignBody, NoteBody, PriorityBody, ScopeBody, TransitionBody

router = APIRouter(tags=["Incidents"])

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
    mutate_result = mutate(case)
    if inspect.isawaitable(mutate_result):
        mutate_result = await mutate_result
    changed, event_type, event_note, event_payload = mutate_result
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

    def mutate(case):
        previous_project_id = case.project_id
        if case.project_id == body.project_id and case.station_id == body.station_id and case.scope_state == "SCOPED":
            return False, "scope_changed", None, {"project_id": body.project_id, "station_id": body.station_id}
        case.project_id = body.project_id
        case.station_id = body.station_id
        case.scope_state = "SCOPED" if body.project_id is not None else "LOOKUP_PENDING"
        case.version += 1
        return True, "scope_changed", None, {"project_id": body.project_id, "station_id": body.station_id, "previous_project_id": previous_project_id}

    return await _mutate_case(db, current_user, incident_id, "scope", body.model_dump(), idempotency_key, mutate)


@router.post("/api/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(
    incident_id: int,
    body: AcknowledgeBody,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_data_db),
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_INCIDENTS)),
):
    def mutate(case):
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
    def mutate(case):
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
    def mutate(case):
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
    def mutate(case):
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
    def mutate(case):
        return True, "note_added", body.message, {}
    return await _mutate_case(db, current_user, incident_id, "notes", body.model_dump(), idempotency_key, mutate)
