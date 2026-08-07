from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ASSETS, ensure_runtime_dirs
from .errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from .logging_config import logger
from .infer import cleanup_expired_inference_artifacts
from .security import (
    ApiKeyAuthMiddleware,
    RequestBodyLimitMiddleware,
    RequestConcurrencyMiddleware,
    RequestRateLimitMiddleware,
    SecurityHeadersMiddleware,
    StorageCapacityMiddleware,
)
from .settings import settings, validate_server_settings
from .routes import router


def _warmup_adapters() -> None:
    """Pre-load all model adapters so first demo request is instant."""
    try:
        from .model_adapters import SepMarkAdapter, WaveGuardAdapter, LIDMarkAdapter, KADNetAdapter
        for cls in (LIDMarkAdapter, KADNetAdapter, WaveGuardAdapter, SepMarkAdapter):
            if cls.available():
                cls.get()
    except Exception as exc:
        logger.warning("adapter warmup error=%s", exc.__class__.__name__)


async def _artifact_janitor() -> None:
    interval = max(5, min(settings.artifact_ttl_seconds // 4, 300))
    while True:
        try:
            removed = await asyncio.to_thread(cleanup_expired_inference_artifacts)
            if removed:
                logger.info("expired inference artifacts removed count=%s", removed)
        except Exception as exc:
            logger.warning("artifact cleanup error: %s", exc.__class__.__name__)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    if settings.warmup_models:
        logger.info("adapter warmup started")
        await asyncio.to_thread(_warmup_adapters)
        logger.info("adapter warmup completed")
    janitor = asyncio.create_task(_artifact_janitor())
    try:
        yield
    finally:
        janitor.cancel()
        with suppress(asyncio.CancelledError):
            await janitor


def create_app() -> FastAPI:
    validate_server_settings(settings)
    ensure_runtime_dirs()
    logger.info("starting backend app assets_dir=assets")
    app = FastAPI(
        title="JianYuanShield Active Forensics Platform",
        version=settings.version,
        lifespan=lifespan,
        docs_url=None if settings.mode == "production" else "/docs",
        redoc_url=None if settings.mode == "production" else "/redoc",
        openapi_url=None if settings.mode == "production" else "/openapi.json",
    )
    cors_origins = list(settings.cors_origins)
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(RequestConcurrencyMiddleware)
    app.add_middleware(StorageCapacityMiddleware)
    app.add_middleware(ApiKeyAuthMiddleware)
    app.add_middleware(RequestRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-API-Key"],
    )
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
