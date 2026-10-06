"""HTTP request models for database exports."""

from typing import List, Optional, Literal
from datetime import date

from pydantic import BaseModel, model_validator


class ExportExcelRequest(BaseModel):
    """Scope and datasets accepted by the background export job."""

    tables: List[str]
    format: Literal['csv', 'both'] = 'csv'
    project_ids: Optional[List[int]] = None
    station_ids: Optional[List[int]] = None
    cluster_indices: Optional[List[int]] = None
    sensor_types: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @model_validator(mode='after')
    def validate_dates(self):
        start = date.fromisoformat(self.start_date) if self.start_date else None
        end = date.fromisoformat(self.end_date) if self.end_date else None
        if start and end and start > end:
            raise ValueError('Start date must not be later than end date')
        return self
