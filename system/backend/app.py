from __future__ import annotations

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


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    logger.info("starting backend app assets_dir=%s", ASSETS)
    app = FastAPI(title="VPSG Deepfake Active Forensics Competition System")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/artifacts", StaticFiles(directory=str(ASSETS)), name="artifacts")
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()
