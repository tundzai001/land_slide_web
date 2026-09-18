"""Incident mutation request schemas."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
from pydantic import BaseModel, Field

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
