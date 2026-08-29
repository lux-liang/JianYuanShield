"""Thread-safe in-process snapshots for expensive deterministic payloads."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
import time
from typing import Any, Callable

from .logging_config import logger


PayloadLoader = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class SnapshotStatus:
    ready: bool
    age_seconds: float | None
    ttl_seconds: int


class SnapshotCache:
    """Coalesce cache misses and return defensive copies of JSON payloads."""

    def __init__(self, loader: PayloadLoader, *, ttl_seconds: int, name: str) -> None:
        if ttl_seconds <= 0:
            raise ValueError("snapshot TTL must be positive")
        self._loader = loader
        self._ttl_seconds = ttl_seconds
        self._name = name
        self._lock = Lock()
        self._value: dict[str, Any] | None = None
        self._loaded_at = 0.0

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        value = self._value
        if value is not None and now - self._loaded_at < self._ttl_seconds:
            return deepcopy(value)
        with self._lock:
            now = time.monotonic()
            if self._value is None or now - self._loaded_at >= self._ttl_seconds:
                started = time.monotonic()
                loaded = self._loader()
                if not isinstance(loaded, dict):
                    raise TypeError(f"{self._name} snapshot loader must return an object")
                self._value = deepcopy(loaded)
                self._loaded_at = time.monotonic()
                logger.info(
                    "public snapshot refreshed name=%s elapsed_ms=%d",
                    self._name,
                    int((self._loaded_at - started) * 1000),
                )
            return deepcopy(self._value)

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._loaded_at = 0.0

    def status(self) -> SnapshotStatus:
        value = self._value
        return SnapshotStatus(
            ready=value is not None,
            age_seconds=(
                max(0.0, time.monotonic() - self._loaded_at)
                if value is not None
                else None
            ),
            ttl_seconds=self._ttl_seconds,
        )
