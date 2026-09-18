"""HTTP request models for the GNSS adjustment feature."""

from typing import Optional

from pydantic import BaseModel


class GnssAdjustmentStartRequest(BaseModel):
    project_id: int
    base_mountpoint: Optional[str] = None
    caster_address: Optional[str] = None
    new_base_station_id: Optional[int] = None
    # Persisted project clusters may contain station codes while map requests
    # contain numeric IDs. The cluster service resolves both forms.
    selected_clusters: Optional[list[list[int | str]]] = None
    run_id: Optional[int] = None
    cluster_index: Optional[int] = None
    source: str = "manual"


class GnssAdjustmentControlRequest(BaseModel):
    project_id: int
