from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_config import logger


def error_payload(code: str, message: str, path: str, details: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "path": path,
    }
    if details is not None:
        error["details"] = details
    return {
        "ok": False,
        "error": error,
    }


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    message = str(exc.detail) if exc.detail else "HTTP error"
    logger.warning("http exception path=%s status=%s detail=%s", request.url.path, exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, request.url.path),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("validation error path=%s errors=%s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content=error_payload("validation_error", "Request validation failed", request.url.path, exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload("internal_error", "Internal server error", request.url.path),
    )
