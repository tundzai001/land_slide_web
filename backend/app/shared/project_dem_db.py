"""Keep project DEM catalogs in the existing config database."""

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.config import GlobalConfig
from .project_dem import list_project_dems, project_dem_summary


def _key(project_id: int) -> str:
    return f"project_dem:{int(project_id)}"


async def get_project_dem_models(db: AsyncSession, project_id: int) -> list[dict]:
    row = await db.scalar(select(GlobalConfig).where(GlobalConfig.key == _key(project_id)))
    if row is None:
        return list_project_dems(project_id)  # One-time compatibility for existing file manifests.
    value = row.value if isinstance(row.value, dict) else {}
    return list_project_dems(project_id, value.get("models", []))


async def get_project_dem_summaries(db: AsyncSession, project_ids: list[int]) -> dict[int, dict]:
    if not project_ids:
        return {}
    keys = [_key(project_id) for project_id in project_ids]
    result = await db.execute(select(GlobalConfig).where(GlobalConfig.key.in_(keys)))
    rows = {row.key: row for row in result.scalars()}
    summaries = {}
    for project_id in project_ids:
        row = rows.get(_key(project_id))
        if row is None:
            models = list_project_dems(project_id)
        else:
            value = row.value if isinstance(row.value, dict) else {}
            models = list_project_dems(project_id, value.get("models", []))
        summaries[project_id] = project_dem_summary(project_id, models)
    return summaries


async def save_project_dem_catalog(db: AsyncSession, project_id: int, models: list[dict], updated_by: str | None = None) -> None:
    key = _key(project_id)
    row = await db.scalar(select(GlobalConfig).where(GlobalConfig.key == key))
    if row is None:
        row = GlobalConfig(key=key, value={"models": models}, updated_at=int(time.time()), updated_by=updated_by)
        db.add(row)
    else:
        row.value = {"models": models}
        row.updated_at = int(time.time())
        row.updated_by = updated_by


async def delete_project_dem_catalog(db: AsyncSession, project_id: int) -> None:
    row = await db.scalar(select(GlobalConfig).where(GlobalConfig.key == _key(project_id)))
    if row is not None:
        await db.delete(row)
