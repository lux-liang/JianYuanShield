from __future__ import annotations

import time
import os
import shutil
from typing import Any

from .config import ASSETS, REPORTS, ROOT
from .logging_config import LOG_FILE
from .settings import settings


STARTED_AT = int(time.time())


def runtime_health(*, detailed: bool = True) -> dict[str, Any]:
    now = int(time.time())
    try:
        free_bytes = min(
            shutil.disk_usage(REPORTS).free,
            shutil.disk_usage(ASSETS).free,
        )
    except OSError:
        free_bytes = 0
    storage_writable = os.access(REPORTS, os.W_OK) and os.access(ASSETS, os.W_OK)
    authentication_ready = not settings.require_api_key or bool(settings.api_key)
    healthy = storage_writable and authentication_ready and free_bytes >= settings.min_free_disk_bytes
    payload = {
        "ok": healthy,
        "mode": settings.mode,
        "version": settings.version,
        "timestamp": now,
    }
    if not detailed:
        return payload
    payload.update({
        "started_at": STARTED_AT,
        "uptime_seconds": now - STARTED_AT,
        "log_file": (
            str(LOG_FILE.relative_to(ROOT))
            if LOG_FILE.is_relative_to(ROOT)
            else f"reports/{LOG_FILE.name}"
        ),
        "settings": {
            "log_level": settings.log_level,
            "enable_demo": settings.enable_demo,
            "authentication_required": settings.require_api_key,
            "authentication_configured": bool(settings.api_key),
            "max_upload_bytes": settings.max_upload_bytes,
            "max_image_pixels": settings.max_image_pixels,
            "max_batch_files": settings.max_batch_files,
            "max_concurrent_upload_requests": settings.max_concurrent_upload_requests,
            "request_body_timeout_seconds": settings.request_body_timeout_seconds,
            "max_concurrent_inference": settings.max_concurrent_inference,
            "max_queued_inference": settings.max_queued_inference,
            "inference_timeout_seconds": settings.inference_timeout_seconds,
            "rate_limit_requests": settings.rate_limit_requests,
            "rate_limit_window_seconds": settings.rate_limit_window_seconds,
            "artifact_ttl_seconds": settings.artifact_ttl_seconds,
            "warmup_models": settings.warmup_models,
            "min_free_disk_bytes": settings.min_free_disk_bytes,
            "artifact_write_reserve_bytes": settings.artifact_write_reserve_bytes,
            "provenance_secret_configured": bool(
                settings.provenance_secret and len(settings.provenance_secret) >= 32
            ),
            "evidence_signer_pinned": bool(settings.evidence_public_key_fingerprint),
        },
        "storage": {
            "writable": storage_writable,
            "free_bytes": free_bytes,
            "minimum_free_bytes": settings.min_free_disk_bytes,
        },
        "modules": {
            "backend": "ok" if healthy else "degraded",
            "artifacts": "writable" if storage_writable else "unavailable",
            "benchmarks": "not_assessed",
            "demo": "enabled" if settings.enable_demo else "disabled",
            "authentication": "ready" if authentication_ready else "misconfigured",
        },
    })
    return payload
