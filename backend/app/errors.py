"""Bounded API errors that never reflect submitted secret values or internals."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError):
        # Pydantic's raw errors include `input` and `ctx`, potentially a password.
        errors = [{"loc": item.get("loc"), "msg": item.get("msg"),
                   "type": item.get("type")} for item in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(HTTPException)
    async def bounded_http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if exc.status_code < 500 else "The request could not be completed."
        return JSONResponse({"detail": detail}, status_code=exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("Unhandled API failure at %s: %s", request.url.path,
                     exc.__class__.__name__)
        return JSONResponse({"detail": "The request could not be completed."},
                            status_code=500, headers={"Cache-Control": "no-store"})
