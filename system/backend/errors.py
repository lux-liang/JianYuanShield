from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_config import logger


HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    408: "request_timeout",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "capability_unavailable",
    504: "timeout",
}


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    safe_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        safe_errors.append({
            key: value
            for key, value in error.items()
            if key in {"loc", "msg", "type", "url"}
        })
    return jsonable_encoder(safe_errors)


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
    code = HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else "HTTP error"
    details = None if isinstance(exc.detail, str) else jsonable_encoder(exc.detail)
    logger.warning(
        "http exception path=%r status=%s detail=%r",
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, request.url.path, details),
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = _safe_validation_errors(exc)
    logger.warning(
        "validation error path=%r fields=%s",
        request.url.path,
        [error.get("loc") for error in safe_errors],
    )
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "validation_error",
            "Request validation failed",
            request.url.path,
            safe_errors,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception path=%r", request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload("internal_error", "Internal server error", request.url.path),
    )
