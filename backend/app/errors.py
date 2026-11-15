"""Bounded API errors that never reflect submitted secret values or internals."""
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)
OPERATION_PHASE_LABELS = {
    "dependencies": "Kết nối hoặc xác thực dịch vụ",
    "validate_report": "Kiểm tra yêu cầu tải báo cáo",
    "resolve_project": "Tra cứu dự án",
    "list_projects": "Tra cứu danh sách dự án",
    "authorize_project": "Kiểm tra quyền truy cập dự án",
    "lookup_indexed_adjustment": "Tìm bản ghi bình sai",
    "lookup_adjustment_record": "Đọc bản ghi đã chọn",
    "lookup_legacy_adjustment": "Tìm bản ghi bình sai cũ",
    "load_adjustment_evidence": "Tải trị đo thô",
    "render_xlsx": "Dựng file Excel",
    "serialize_json": "Chuẩn bị file JSON",
}


def operation_phase_label(phase: str) -> str:
    return OPERATION_PHASE_LABELS.get(phase, "Xử lý yêu cầu")


def install_error_handlers(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError):
        await asyncio.sleep(0)
        # Pydantic's raw errors include `input` and `ctx`, potentially a password.
        errors = [{"loc": item.get("loc"), "msg": item.get("msg"),
                   "type": item.get("type")} for item in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(HTTPException)
    async def bounded_http_error(_request: Request, exc: HTTPException):
        await asyncio.sleep(0)
        detail = exc.detail if exc.status_code < 500 else "The request could not be completed."
        return JSONResponse({"detail": detail}, status_code=exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        await asyncio.sleep(0)
        phase = getattr(request.state, "operation_phase", "dependencies")
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled API failure request_id=%s method=%s path=%s phase=%s (%s) error=%s",
            request_id,
            request.method,
            request.url.path,
            phase,
            operation_phase_label(phase),
            exc.__class__.__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            {
                "detail": "The request could not be completed.",
                "phase": phase,
                "phase_label": operation_phase_label(phase),
                "request_id": request_id,
            },
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )
