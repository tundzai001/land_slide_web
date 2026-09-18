"""Simulation request schemas."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

class SimulationCreate(BaseModel):
    mode: Literal["manual", "station_snapshot"] = "manual"
    project_id: Optional[int] = None
    station_id: Optional[int] = None
    display_name: Optional[str] = Field(default=None, max_length=240)
    duration_hours: int = Field(default=24, ge=1, le=168)
    seed: Optional[int] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
