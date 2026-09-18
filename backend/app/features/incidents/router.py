"""Incident routes composed by read and mutation responsibilities."""

from fastapi import APIRouter

from .common import (
    _attention_rank, _base_scope_stmt, _broadcast_case, _canonical_filter_hash,
    _decode_cursor, _event_rows, _existing_mutation, _fingerprint, _is_admin,
    _is_manager, _load_case, _mutation_key_or_error, _private_headers,
    _scope_hash, _sign_cursor,
)
from .read_router import (
    get_incident, get_incident_events, list_incident_events, list_incidents,
    router as read_router,
)
from .schemas import AcknowledgeBody, AssignBody, NoteBody, PriorityBody, ScopeBody, TransitionBody
from .write_router import (
    _mutate_case, acknowledge_incident, add_incident_note, assign_incident,
    router as write_router, set_incident_priority, set_incident_scope,
    transition_incident,
)

router = APIRouter()
router.include_router(read_router)
router.include_router(write_router)
