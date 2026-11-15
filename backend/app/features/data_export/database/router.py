"""Database export HTTP routes."""

from __future__ import annotations

import logging
import os
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from .... import auth
from ....models import auth as model_auth
from ..schemas import ExportExcelRequest
from .job import EXPORT_TASKS, _export_excel_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin Console"])

@router.get("/db/export-excel/{task_id}/download")
async def download_export_excel(
    task_id: str,
    background_tasks: BackgroundTasks,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Tải file ZIP đã xuất xong."""
    if task_id not in EXPORT_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = EXPORT_TASKS[task_id]
    if task["status"] != "completed" or not task["file_path"]:
        raise HTTPException(status_code=400, detail="Export not completed yet")

    filepath = task["file_path"]
    filename = task["filename"]

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    def cleanup_file():
        try:
            os.remove(filepath)
            del EXPORT_TASKS[task_id]
        except Exception as e:
            logger.error(f"Failed to delete temp export file {filepath}: {e}")

    background_tasks.add_task(cleanup_file)

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/zip"
    )


@router.get("/db/export-excel/{task_id}/progress")
async def get_export_progress(
    task_id: str,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Lấy tiến độ của tác vụ xuất."""
    if task_id not in EXPORT_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return EXPORT_TASKS[task_id]


@router.post("/db/export-excel/start")
async def start_export_database_excel(
    request: ExportExcelRequest,
    background_tasks: BackgroundTasks,
    current_user: model_auth.User = Depends(auth.require_permission(auth.Permission.MANAGE_USERS))
):
    """Bắt đầu tác vụ xuất Excel chạy ngầm."""
    allowed = {'projects', 'stations', 'devices', 'sensor_data', 'gnss_adjustments', 'alerts', 'simulations'}
    selected = [table for table in request.tables if table in allowed]
    if not selected:
        raise HTTPException(status_code=400, detail="No valid export table selected")

    task_id = str(uuid.uuid4())
    EXPORT_TASKS[task_id] = {
        "status": "pending",
        "percent": 0,
        "message": "Đang chuẩn bị...",
        "file_path": None,
        "filename": None,
        "error": None
    }

    background_tasks.add_task(_export_excel_task, task_id, request, selected)
    return {"task_id": task_id}
