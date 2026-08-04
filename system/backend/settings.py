from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import stat
from urllib.parse import urlsplit


ALLOWED_MODES = frozenset({"demo", "real_inference", "production"})


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _secret_env(name: str) -> str | None:
    direct = os.getenv(name)
    file_value = os.getenv(f"{name}_FILE")
    has_direct = direct is not None and bool(direct.strip())
    has_file = file_value is not None and bool(file_value.strip())
    if has_direct and has_file:
        raise ValueError(f"{name} and {name}_FILE are mutually exclusive")
    if has_file:
        configured_path = Path(file_value.strip()).expanduser()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(configured_path, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"{name}_FILE must reference a regular file")
            if metadata.st_size > 4096:
                raise ValueError(f"{name}_FILE exceeds the 4096 byte limit")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                encoded = handle.read(4097)
        except OSError as exc:
            raise ValueError(f"{name}_FILE cannot be read") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(encoded) > 4096:
            raise ValueError(f"{name}_FILE exceeds the 4096 byte limit")
        try:
            value = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name}_FILE must contain UTF-8 text") from exc
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
    else:
        value = direct
    if value is None or not value.strip():
        return None
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _api_key_env() -> str | None:
    return _secret_env("JYS_API_KEY")


def _mode_env() -> str:
    mode = os.getenv("JYS_MODE", "real_inference").strip().lower()
    if mode not in ALLOWED_MODES:
        raise ValueError(
            "JYS_MODE must be one of: " + ", ".join(sorted(ALLOWED_MODES))
        )
    return mode


def _production_mode() -> bool:
    return _mode_env() == "production"


def _validate_cors_origin(origin: str, *, production: bool) -> None:
    if origin == "*":
        if production:
            raise ValueError("production CORS cannot use a wildcard origin")
        return
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid CORS origin: {origin}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(f"invalid CORS origin: {origin}")
    if production and parsed.scheme != "https":
        raise ValueError("production CORS origins must use HTTPS")


@dataclass(frozen=True)
class Settings:
    version: str = os.getenv("JYS_VERSION", "0.1.0")
    mode: str = _mode_env()
    log_level: str = os.getenv("JYS_LOG_LEVEL", "INFO")
    enable_demo: bool = (not _production_mode()) and _bool_env("JYS_ENABLE_DEMO", True)
    api_key: str | None = _api_key_env()
    require_api_key: bool = _production_mode() or _bool_env("JYS_REQUIRE_API_KEY", False)
    max_upload_bytes: int = _positive_int_env("JYS_MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
    max_image_pixels: int = _positive_int_env("JYS_MAX_IMAGE_PIXELS", 16_000_000)
    max_batch_files: int = _positive_int_env("JYS_MAX_BATCH_FILES", 16)
    max_concurrent_upload_requests: int = _positive_int_env(
        "JYS_MAX_CONCURRENT_UPLOAD_REQUESTS",
        4,
    )
    request_body_timeout_seconds: int = _positive_int_env(
        "JYS_REQUEST_BODY_TIMEOUT_SECONDS",
        30,
    )
    max_concurrent_inference: int = _positive_int_env("JYS_MAX_CONCURRENT_INFERENCE", 1)
    max_queued_inference: int = _positive_int_env("JYS_MAX_QUEUED_INFERENCE", 8)
    inference_timeout_seconds: int = _positive_int_env("JYS_INFERENCE_TIMEOUT_SECONDS", 120)
    rate_limit_requests: int = _positive_int_env("JYS_RATE_LIMIT_REQUESTS", 120)
    rate_limit_window_seconds: int = _positive_int_env("JYS_RATE_LIMIT_WINDOW_SECONDS", 60)
    max_rate_limit_clients: int = _positive_int_env("JYS_MAX_RATE_LIMIT_CLIENTS", 10_000)
    artifact_ttl_seconds: int = _positive_int_env("JYS_ARTIFACT_TTL_SECONDS", 3600)
    warmup_models: bool = _bool_env("JYS_WARMUP_MODELS", False)
    min_free_disk_bytes: int = _positive_int_env("JYS_MIN_FREE_DISK_BYTES", 512 * 1024 * 1024)
    artifact_write_reserve_bytes: int = _positive_int_env(
        "JYS_ARTIFACT_WRITE_RESERVE_BYTES",
        128 * 1024 * 1024,
    )
    cors_origins: tuple[str, ...] = _csv_env(
        "JYS_CORS_ORIGINS",
        ("http://127.0.0.1:8027", "http://localhost:8027"),
    )
    cors_allow_credentials: bool = _bool_env("JYS_CORS_ALLOW_CREDENTIALS", False)
    evidence_private_key: str | None = os.getenv("JYS_EVIDENCE_PRIVATE_KEY") or None
    evidence_public_key_fingerprint: str | None = (
        os.getenv("JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT") or None
    )
    provenance_db: str | None = os.getenv("JYS_PROVENANCE_DB") or None
    provenance_secret: str | None = _secret_env("JYS_PROVENANCE_SECRET")
    audit_anchor: str | None = os.getenv("JYS_AUDIT_ANCHOR") or None
    content_producer: str = os.getenv("JYS_CONTENT_PRODUCER", "JianYuanShield-VPSG")
    creator_challenge_ttl_seconds: int = _positive_int_env(
        "JYS_CREATOR_CHALLENGE_TTL_SECONDS", 300
    )


def validate_server_settings(config: Settings) -> None:
    if len(config.cors_origins) != len(set(config.cors_origins)):
        raise ValueError("JYS_CORS_ORIGINS cannot contain duplicates")
    for origin in config.cors_origins:
        _validate_cors_origin(origin, production=config.mode == "production")
    if "*" in config.cors_origins and config.cors_allow_credentials:
        raise ValueError("credentialed CORS cannot use a wildcard origin")
    if config.mode == "production":
        if not config.cors_origins:
            raise ValueError("production JYS_CORS_ORIGINS must not be empty")
        if not config.require_api_key:
            raise ValueError("production mode must require API authentication")
        if not config.api_key or len(config.api_key) < 32:
            raise ValueError("production JYS_API_KEY must contain at least 32 characters")


settings = Settings()
