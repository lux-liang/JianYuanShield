from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    version: str = os.getenv("JYS_VERSION", "0.1.0")
    mode: str = os.getenv("JYS_MODE", "demo_simulation")
    log_level: str = os.getenv("JYS_LOG_LEVEL", "INFO")
    enable_demo: bool = _bool_env("JYS_ENABLE_DEMO", True)


settings = Settings()
