from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ASSETS, ensure_runtime_dirs
from .errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from .logging_config import logger
from .routes import (
    aggregate_benchmark,
    artifacts_status,
    competition_report,
    demo_run,
    evidence_audit,
    health,
    hidden_lfw_full,
    lidmark_lfw_eval,
    modules,
    projects,
    real_evals,
    report,
    competition_report_download,
    router,
    sample_image,
    samples,
    sepmark_benchmark,
    waveguard_benchmark,
)


def _warmup_adapters() -> None:
    """Pre-load all model adapters so first demo request is instant."""
    try:
        from .model_adapters import SepMarkAdapter, WaveGuardAdapter, LIDMarkAdapter, KADNetAdapter
        for cls in (LIDMarkAdapter, KADNetAdapter, WaveGuardAdapter, SepMarkAdapter):
            if cls.available():
                cls.get()
    except Exception as exc:
        logger.warning("adapter warmup error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    thread = threading.Thread(target=_warmup_adapters, daemon=True, name="adapter-warmup")
    thread.start()
    logger.info("adapter warmup thread started")
    yield


# 安全：CORS 显式 origin 白名单（从 env 读，默认 localhost），
# 避免 allow_origins=["*"] + allow_credentials=True 的违规组合。
_DEFAULT_CORS_ORIGINS = [
    "http://localhost",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]


def _cors_origins() -> list[str]:
    raw = os.getenv("JYS_CORS_ORIGINS")
    if not raw:
        return _DEFAULT_CORS_ORIGINS
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or _DEFAULT_CORS_ORIGINS


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    logger.info("starting backend app assets_dir=%s", ASSETS)
    app = FastAPI(title="VPSG Deepfake Active Forensics Competition System", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.mount("/artifacts", StaticFiles(directory=str(ASSETS)), name="artifacts")
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
