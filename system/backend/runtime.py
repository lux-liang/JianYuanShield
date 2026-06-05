from __future__ import annotations

import time
from typing import Any

from .config import ROOT
from .logging_config import LOG_FILE
from .settings import settings


STARTED_AT = int(time.time())


def runtime_health() -> dict[str, Any]:
    now = int(time.time())
    return {
        "ok": True,
        "root": str(ROOT),
        "mode": settings.mode,
        "version": settings.version,
        "timestamp": now,
        "started_at": STARTED_AT,
        "uptime_seconds": now - STARTED_AT,
        "log_file": str(LOG_FILE),
        "settings": {
            "log_level": settings.log_level,
            "enable_demo": settings.enable_demo,
        },
        "modules": {
            "backend": "ok",
            "artifacts": "ok",
            "benchmarks": "ok",
            "demo": "ok",
        },
    }
