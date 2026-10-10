"""Incident query, authorization, and event helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Optional
from fastapi import HTTPException, Response
from sqlalchemy import case, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...config import settings
from ...models import auth as model_auth
from ...models import data as model_data
from .cases import (
    PRIORITY_ORDER,
    case_project_ids,
    serialize_case,
)

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
        packed = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=") != value:
            raise ValueError
        # A SHA-256 signature is binary and can itself contain a period. Read
        # its fixed-size suffix instead of splitting on a byte inside the MAC.
        if len(packed) <= 33 or packed[-33:-32] != b".":
            raise ValueError
        raw, signature = packed[:-33], packed[-32:]
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
    from ...websocket import manager as ws_manager
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
