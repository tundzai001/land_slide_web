"""Simulation report download routes."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ... import auth
from ...database import get_data_db
from ...models import auth as model_auth
from ...models import data as model_data
from ..data_export.reports.simulation import (
    build_json,
    build_pdf,
    build_xlsx,
)
from .service import _download_header, _safe_name

router = APIRouter(prefix="/api/simulations", tags=["Landslide simulations"])

@router.get("/runs/{run_id}/export", responses={404: {"description": "Not Found"}})
async def export_run(run_id: int, format: Literal["pdf", "xlsx", "json"] = "pdf", db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    builders = {"pdf": (build_pdf, "application/pdf"), "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), "json": (build_json, "application/json; charset=utf-8")}
    body = await asyncio.to_thread(builders[format][0], run)
    filename = f"{_safe_name(run.display_name, f'simulation_{run.id}')}.{format}"
    return StreamingResponse(BytesIO(body), media_type=builders[format][1], headers={"Content-Disposition": _download_header(filename, f"simulation_{run.id}.{format}"), "Cache-Control": "no-store"})


@router.get("/runs/{run_id}/bundle", responses={404: {"description": "Not Found"}})
async def export_bundle(run_id: int, db: AsyncSession = Depends(get_data_db), _user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_SIMULATIONS))):
    run = await db.get(model_data.SimulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần mô phỏng")
    files = await asyncio.gather(asyncio.to_thread(build_pdf, run), asyncio.to_thread(build_xlsx, run), asyncio.to_thread(build_json, run))
    folder = "/".join(["simulations", _safe_name(run.project_code, "MANUAL"), _safe_name(run.station_code, "manual"), f"{time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(run.created_at))}_{_safe_name(run.display_name, str(run.id))}"])
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, body in zip(("report.pdf", "results.xlsx", "data.json"), files):
            archive.writestr(f"{folder}/{name}", body)
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="simulation_{run.id}.zip"', "Cache-Control": "no-store"})
