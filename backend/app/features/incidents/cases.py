"""Shared Incident & Response domain primitives.

The service intentionally stores only operational, non-PII snapshots.  Legacy
Alert and RescueRequest rows remain the source records; IncidentCase is the
workflow/read model that can be introduced additively and reconciled later.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import data as model_data


SOURCE_SEVERITY_ORDER = {
    "UNKNOWN": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "WARNING": 4,
    "HIGH": 5,
    "CRITICAL": 6,
    "EXTREME": 7,
}
PRIORITY_ORDER = {"UNTRIAGED": -1, "LOW": 0, "NORMAL": 1, "HIGH": 2, "URGENT": 3}
VALID_PRIORITIES = set(PRIORITY_ORDER)
VALID_STATUSES = {"new", "acknowledged", "in_progress", "monitoring", "resolved", "dismissed"}
SOURCE_KINDS = {"SENSOR_ALERT", "RESCUE_REQUEST"}


def normalize_severity(value: Any) -> str:
    normalized = str(value or "UNKNOWN").strip().upper()
    return normalized if normalized in SOURCE_SEVERITY_ORDER else "UNKNOWN"


def normalize_source_kind(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in SOURCE_KINDS:
        raise ValueError("unsupported incident source kind")
    return normalized


def priority_for_severity(value: Any) -> str:
    severity = normalize_severity(value)
    if severity in {"CRITICAL", "EXTREME", "HIGH"}:
        return "URGENT"
    if severity in {"MEDIUM", "WARNING"}:
        return "HIGH"
    if severity in {"INFO", "LOW"}:
        return "NORMAL"
    return "UNTRIAGED"


def normalize_episode_category(category: Any) -> str:
    """Canonicalize only known legacy suffixes; never strip arbitrary text."""

    value = re.sub(r"[^a-z0-9_:-]", "_", str(category or "unknown").strip().lower())
    explicit = {
        "tilt_warning": "tilt",
        "tilt_critical": "tilt",
        "gnss_velocity_warning": "gnss_velocity",
        "gnss_velocity_critical": "gnss_velocity",
    }
    return explicit.get(value, value or "unknown")


def incident_reference(source_kind: str, source_id: int, opened_at: int) -> str:
    prefix = "A" if normalize_source_kind(source_kind) == "SENSOR_ALERT" else "R"
    date = datetime.fromtimestamp(int(opened_at), timezone.utc).strftime("%Y%m%d")
    return f"INC-{date}-{prefix}{int(source_id)}"


def _text(value: Any, limit: int, default: str = "") -> str:
    value = str(value or default).strip()
    return value[:limit]


def _event_payload(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Keep event payload JSON-safe and explicitly non-PII."""

    if not isinstance(payload, dict):
        return {}
    allowed = {
        "source_kind", "source_id", "source_category", "source_severity",
        "signal_state", "priority", "status", "project_id", "station_id",
        "previous_project_id", "new_project_id", "reason", "legacy_reopen",
        "idempotent_replay",
    }
    return {key: payload[key] for key in allowed if key in payload}


async def append_event(
    db: AsyncSession,
    case: model_data.IncidentCase,
    event_type: str,
    *,
    actor_kind: str = "system",
    actor_user_id: Optional[int] = None,
    actor_username: Optional[str] = None,
    note: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    previous_project_id: Optional[int] = None,
    mutation_request_id: Optional[int] = None,
    now: Optional[int] = None,
) -> model_data.IncidentEvent:
    """Append one ordered event while holding the case row lock in callers."""

    timestamp = int(now or time.time())
    case.last_event_sequence = int(case.last_event_sequence or 0) + 1
    case.revision = int(case.revision or 0) + 1
    case.updated_at = timestamp
    event = model_data.IncidentEvent(
        incident_id=int(case.id),
        sequence=int(case.last_event_sequence),
        event_type=_text(event_type, 32, "updated"),
        actor_kind=_text(actor_kind, 16, "system"),
        actor_user_id=actor_user_id,
        actor_username=_text(actor_username, 150) or None,
        project_id_at_event=case.project_id,
        previous_project_id=previous_project_id,
        created_at=timestamp,
        note=_text(note, 4000) or None,
        payload=_event_payload(payload),
        mutation_request_id=mutation_request_id,
    )
    db.add(event)
    await db.flush()
    return event


async def get_case_for_source(
    db: AsyncSession,
    source_kind: str,
    source_id: int,
    *,
    for_update: bool = False,
) -> Optional[model_data.IncidentCase]:
    stmt = select(model_data.IncidentCase).where(
        model_data.IncidentCase.source_kind == normalize_source_kind(source_kind),
        model_data.IncidentCase.source_id == int(source_id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lock_source_key(db: AsyncSession, source_kind: str, source_id: int) -> None:
    """Serialize concurrent ingest workers for one source episode.

    Data and config use PostgreSQL in production.  The dialect guard keeps
    lightweight unit-test sessions and local SQLite tooling compatible while
    the transaction-scoped advisory lock prevents two MQTT workers from both
    observing a missing case and creating competing timelines.
    """
    try:
        bind = db.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
            return
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:incident_key, 0))"),
            {"incident_key": f"{normalize_source_kind(source_kind)}:{int(source_id)}"},
        )
    except (AttributeError, LookupError):
        return


async def ensure_incident_case(
    db: AsyncSession,
    *,
    source_kind: str,
    source_id: int,
    title: str,
    summary: str,
    source_severity: str = "UNKNOWN",
    signal_state: str = "UNKNOWN",
    project_id: Optional[int] = None,
    station_id: Optional[int] = None,
    project_name: Optional[str] = None,
    project_code: Optional[str] = None,
    station_name: Optional[str] = None,
    station_code: Optional[str] = None,
    now: Optional[int] = None,
) -> tuple[model_data.IncidentCase, bool, Optional[model_data.IncidentEvent]]:
    """Create or refresh a case in the caller's transaction.

    Repeated sensor samples update signal metadata without creating a timeline
    event unless severity/state actually changes.  This prevents the incident
    timeline from growing once per MQTT sample.
    """

    kind = normalize_source_kind(source_kind)
    timestamp = int(now or time.time())
    severity = normalize_severity(source_severity)
    signal = str(signal_state or "UNKNOWN").upper()
    if signal not in {"ACTIVE", "RETURNED", "UNKNOWN", "NOT_APPLICABLE"}:
        signal = "UNKNOWN"
    await _lock_source_key(db, kind, source_id)
    case = await get_case_for_source(db, kind, source_id, for_update=True)
    if case is None:
        if project_id is not None:
            scope_state = "SCOPED"
        elif kind == "RESCUE_REQUEST":
            scope_state = "UNSCOPED"
        else:
            scope_state = "LOOKUP_PENDING"
        case = model_data.IncidentCase(
            reference=incident_reference(kind, source_id, timestamp),
            source_kind=kind,
            source_id=int(source_id),
            project_id=project_id,
            station_id=station_id,
            scope_state=scope_state,
            project_name_snapshot=_text(project_name, 255) or None,
            project_code_snapshot=_text(project_code, 100) or None,
            station_name_snapshot=_text(station_name, 255) or None,
            station_code_snapshot=_text(station_code, 100) or None,
            title=_text(title, 255, "Sự cố vận hành"),
            summary=_text(summary, 4000),
            source_severity=severity,
            signal_state=signal,
            priority=priority_for_severity(severity),
            status="new",
            opened_at=timestamp,
            last_signal_at=timestamp,
            updated_at=timestamp,
            version=1,
            revision=0,
            last_event_sequence=0,
        )
        db.add(case)
        await db.flush()
        event = await append_event(
            db,
            case,
            "opened",
            payload={
                "source_kind": kind,
                "source_id": int(source_id),
                "source_severity": severity,
                "signal_state": signal,
                "priority": case.priority,
            },
            now=timestamp,
        )
        return case, True, event

    old_severity = normalize_severity(case.source_severity)
    old_signal = str(case.signal_state or "UNKNOWN").upper()
    case.last_signal_at = timestamp
    case.updated_at = timestamp
    case.title = _text(title, 255, case.title)
    case.summary = _text(summary, 4000)
    if project_id is not None:
        case.project_id = int(project_id)
        case.scope_state = "SCOPED"
    if station_id is not None:
        case.station_id = int(station_id)
    for field, value, limit in (
        ("project_name_snapshot", project_name, 255),
        ("project_code_snapshot", project_code, 100),
        ("station_name_snapshot", station_name, 255),
        ("station_code_snapshot", station_code, 100),
    ):
        if value:
            setattr(case, field, _text(value, limit))
    case.source_severity = severity if SOURCE_SEVERITY_ORDER[severity] >= SOURCE_SEVERITY_ORDER[old_severity] else old_severity
    case.signal_state = signal
    event = None
    if old_severity != case.source_severity:
        event = await append_event(
            db,
            case,
            "source_severity_changed",
            payload={"source_severity": case.source_severity},
            now=timestamp,
        )
    elif old_signal != signal:
        event = await append_event(
            db,
            case,
            "signal_returned" if signal == "RETURNED" else "signal_updated",
            payload={"signal_state": signal},
            now=timestamp,
        )
    return case, False, event


def serialize_case(case: model_data.IncidentCase, *, include_private: bool = False) -> dict[str, Any]:
    data = {
        "id": int(case.id),
        "reference": case.reference,
        "source_kind": case.source_kind,
        "source_id": int(case.source_id),
        "project_id": case.project_id,
        "station_id": case.station_id,
        "scope_state": case.scope_state,
        "project_name": case.project_name_snapshot,
        "project_code": case.project_code_snapshot,
        "station_name": case.station_name_snapshot,
        "station_code": case.station_code_snapshot,
        "title": case.title,
        "summary": case.summary,
        "source_severity": case.source_severity,
        "signal_state": case.signal_state,
        "priority": case.priority,
        "status": case.status,
        "assigned_to_user_id": case.assigned_to_user_id,
        "assigned_to_username": case.assigned_to_username,
        "opened_at": int(case.opened_at),
        "last_signal_at": int(case.last_signal_at),
        "acknowledged_at": case.acknowledged_at,
        "resolved_at": case.resolved_at,
        "updated_at": int(case.updated_at),
        "version": int(case.version),
        "revision": int(case.revision),
        "last_event_sequence": int(case.last_event_sequence),
    }
    if not include_private:
        data.pop("assigned_to_username", None)
    return data


def case_project_ids(user: Any) -> set[int]:
    values = getattr(user, "assigned_projects", None) or []
    return {int(value) for value in values if str(value).strip().lstrip("-").isdigit()}


def can_view_case(user: Any, case: model_data.IncidentCase) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    project_id = case.project_id
    return project_id is not None and int(project_id) in case_project_ids(user)
