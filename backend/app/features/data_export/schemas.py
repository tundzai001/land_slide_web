"""HTTP request models for database exports."""

from typing import List, Optional

from pydantic import BaseModel


class ExportExcelRequest(BaseModel):
    """Scope and datasets accepted by the background export job."""

    tables: List[str]
    project_ids: Optional[List[int]] = None
    station_ids: Optional[List[int]] = None
    cluster_indices: Optional[List[int]] = None
    sensor_types: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

