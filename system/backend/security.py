from __future__ import annotations

import asyncio
import hmac
import io
import math
import re
import shutil
import unicodedata
from pathlib import Path

from fastapi import Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .settings import settings
from .config import ASSETS, REPORTS


ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MIN_IMAGE_DIMENSION = 8
UPLOAD_ENDPOINTS = frozenset({
    "/api/infer/single",
    "/api/provenance/protect",
    "/api/provenance/verify",
})
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_JSON_BODY_LIMIT_BYTES = 64 * 1024
BOUNDED_REQUEST_PATHS = UPLOAD_ENDPOINTS | frozenset({
    "/api/compliance/batch",
    "/api/tasks/demo-run",
})
STORAGE_MUTATION_PATHS = frozenset({
    "/api/infer/single",
    "/api/provenance/protect",
    "/api/provenance/verify",
    "/api/tasks/demo-run",
})


class _RequestBodyTooLarge(Exception):
    pass


class _RequestBodyTimedOut(Exception):
    pass


def _request_body_limit(path: str) -> int | None:
    if path == "/api/tasks/demo-run":
        return _JSON_BODY_LIMIT_BYTES
    if path in UPLOAD_ENDPOINTS:
        return settings.max_upload_bytes + _MULTIPART_OVERHEAD_BYTES
    if path == "/api/compliance/batch":
        return (
            settings.max_batch_files * settings.max_upload_bytes
            + _MULTIPART_OVERHEAD_BYTES
        )
    return None


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": {"code": code, "message": message, "path": path},
        },
        headers=headers,
    )


class ApiKeyAuthMiddleware:
    """Authenticate protected API requests before FastAPI parses their bodies."""

    PUBLIC_API_PATHS = frozenset({"/api/health", "/api/projects", "/api/claims"})

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or not str(scope.get("path") or "").startswith("/api/")
            or str(scope.get("path") or "") in self.PUBLIC_API_PATHS
            or not settings.require_api_key
        ):
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        values = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"x-api-key"
        ]
        provided = None
        if len(values) == 1:
            try:
                provided = values[0].decode("latin-1")
            except UnicodeDecodeError:
                provided = None
        try:
            require_api_key(provided)
        except HTTPException as exc:
            code = "unauthorized" if exc.status_code == 401 else "capability_unavailable"
            response = _error_response(
                status_code=exc.status_code,
                code=code,
                message=str(exc.detail),
                path=path,
                headers=exc.headers,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Reject oversized upload bodies before multipart parsing or disk spooling."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        limit = _request_body_limit(path)
        if limit is None:
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value.strip()
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        if content_lengths:
            if len(set(content_lengths)) != 1:
                response = _error_response(
                    status_code=400,
                    code="bad_request",
                    message="conflicting Content-Length headers",
                    path=path,
                )
                await response(scope, receive, send)
                return
            try:
                declared_length = int(content_lengths[0].decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                declared_length = -1
            if declared_length < 0:
                response = _error_response(
                    status_code=400,
                    code="bad_request",
                    message="invalid Content-Length header",
                    path=path,
                )
                await response(scope, receive, send)
                return
            if declared_length > limit:
                response = _error_response(
                    status_code=413,
                    code="payload_too_large",
                    message="request body exceeds the configured upload limit",
                    path=path,
                )
                await response(scope, receive, send)
                return

        received = 0
        response_started = False
        body_complete = False
        deadline = (
            asyncio.get_running_loop().time()
            + settings.request_body_timeout_seconds
        )

        async def limited_receive() -> Message:
            nonlocal body_complete, received
            if body_complete:
                return await receive()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise _RequestBodyTimedOut
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise _RequestBodyTimedOut from exc
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
                body_complete = not message.get("more_body", False)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            response = _error_response(
                status_code=413,
                code="payload_too_large",
                message="request body exceeds the configured upload limit",
                path=path,
            )
            await response(scope, receive, send)
        except _RequestBodyTimedOut:
            if response_started:
                raise
            response = _error_response(
                status_code=408,
                code="request_timeout",
                message="request body was not received within the configured timeout",
                path=path,
            )
            await response(scope, receive, send)


class RequestConcurrencyMiddleware:
    """Bound body parsing and image validation before requests enter GPU queues."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.slots = asyncio.Semaphore(settings.max_concurrent_upload_requests)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path") or "") if scope["type"] == "http" else ""
        if path not in BOUNDED_REQUEST_PATHS:
            await self.app(scope, receive, send)
            return
        if self.slots.locked():
            response = _error_response(
                status_code=503,
                code="capability_unavailable",
                message="request processing capacity is full",
                path=path,
                headers={"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        await self.slots.acquire()
        try:
            await self.app(scope, receive, send)
        finally:
            self.slots.release()


class StorageCapacityMiddleware:
    """Reject artifact/database writes before body parsing when reserve is low."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.required_free_bytes = (
            settings.min_free_disk_bytes + settings.artifact_write_reserve_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path") or "") if scope["type"] == "http" else ""
        if path not in STORAGE_MUTATION_PATHS:
            await self.app(scope, receive, send)
            return
        try:
            roots = {ASSETS.resolve(), REPORTS.resolve()}
            sufficient = all(
                shutil.disk_usage(root).free >= self.required_free_bytes
                for root in roots
            )
        except OSError:
            sufficient = False
        if not sufficient:
            response = _error_response(
                status_code=503,
                code="capability_unavailable",
                message="artifact storage reserve is unavailable",
                path=path,
                headers={"Retry-After": "30"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequestRateLimitMiddleware:
    """Per-client token bucket for every API route, including auth failures."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.capacity = float(settings.rate_limit_requests)
        self.window = float(settings.rate_limit_window_seconds)
        self.maximum_clients = settings.max_rate_limit_clients
        self.buckets: dict[str, tuple[float, float]] = {}
        self.request_count = 0

    def _client_key(self, scope: Scope, now: float) -> str:
        client = scope.get("client")
        key = str(client[0]) if isinstance(client, tuple) and client else "unknown"
        if key in self.buckets or len(self.buckets) < self.maximum_clients:
            return key
        cutoff = now - self.window
        self.buckets = {
            bucket_key: state
            for bucket_key, state in self.buckets.items()
            if state[1] >= cutoff
        }
        return key if len(self.buckets) < self.maximum_clients else "overflow"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path") or "") if scope["type"] == "http" else ""
        if not path.startswith("/api/") or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        now = asyncio.get_running_loop().time()
        key = self._client_key(scope, now)
        tokens, updated_at = self.buckets.get(key, (self.capacity, now))
        refill_rate = self.capacity / self.window
        tokens = min(self.capacity, tokens + max(0.0, now - updated_at) * refill_rate)
        if tokens < 1.0:
            retry_after = max(1, math.ceil((1.0 - tokens) / refill_rate))
            response = _error_response(
                status_code=429,
                code="rate_limited",
                message="request rate limit exceeded",
                path=path,
                headers={
                    "Retry-After": str(retry_after),
                    "RateLimit-Limit": str(int(self.capacity)),
                    "RateLimit-Remaining": "0",
                },
            )
            await response(scope, receive, send)
            return
        tokens -= 1.0
        self.buckets[key] = (tokens, now)
        self.request_count += 1
        if self.request_count % 256 == 0:
            cutoff = now - self.window
            self.buckets = {
                bucket_key: state
                for bucket_key, state in self.buckets.items()
                if state[1] >= cutoff
            }

        async def rate_limited_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"ratelimit-limit", str(int(self.capacity)).encode("ascii")),
                    (b"ratelimit-remaining", str(max(0, int(tokens))).encode("ascii")),
                ])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, rate_limited_send)


class SecurityHeadersMiddleware:
    """Attach browser and cache protections to API responses, including errors."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path") or "") if scope["type"] == "http" else ""
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _value in headers}
                additions = [
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                ]
                if getattr(settings, "mode", None) == "production" and scope.get("scheme") == "https":
                    additions.append((b"strict-transport-security", b"max-age=31536000"))
                headers.extend((key, value) for key, value in additions if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, secured_send)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Protect compute-heavy endpoints when authentication is enabled.

    Local competition demos remain usable by default. Production mode enables the
    requirement automatically and refuses to start inference with an unset key.
    """

    if not settings.require_api_key:
        return
    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is required but JYS_API_KEY is not configured",
        )
    provided = (x_api_key or "").encode("utf-8", errors="surrogatepass")
    expected = settings.api_key.encode("utf-8", errors="surrogatepass")
    if x_api_key is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def validate_identifier(value: str, *, field: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail=f"invalid {field}",
        )
    return value


def safe_display_filename(value: str | None, *, fallback: str) -> str:
    """Return a display-only basename without trusting client supplied paths."""

    # Browsers may submit either POSIX or Windows client paths.  Treat both
    # separators as paths and strip control/format characters (including bidi
    # overrides) before returning a value that a UI may display.
    name = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        character
        for character in name
        if not unicodedata.category(character).startswith("C")
    ).strip()
    if not name or name in {".", ".."}:
        return fallback
    return name[:128]


def resolve_path_within(root: Path, relative: str | Path) -> Path | None:
    """Resolve an untrusted relative path without leaving ``root``."""

    raw_value = str(relative)
    if not raw_value or "\x00" in raw_value or "\\" in raw_value:
        return None
    raw = Path(raw_value)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / raw).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def validate_image_bytes(data: bytes, *, media_type: str | None) -> bytes:
    normalized_media_type = (media_type or "").split(";", 1)[0].strip().lower()
    if normalized_media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="supported image types are JPEG, PNG and WebP",
        )
    if not data:
        raise HTTPException(status_code=422, detail="empty image")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"image exceeds {settings.max_upload_bytes} byte limit",
        )
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            actual_format = (image.format or "").upper()
            if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "image dimensions must be at least "
                        f"{MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} pixels"
                    ),
                )
            if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                raise HTTPException(
                    status_code=413,
                    detail=f"decoded image exceeds {settings.max_image_pixels} pixel limit",
                )
            expected_formats = {
                "image/jpeg": {"JPEG"},
                "image/png": {"PNG"},
                "image/webp": {"WEBP"},
            }
            if actual_format not in expected_formats[normalized_media_type]:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="declared media type does not match image content",
                )
            image.verify()
        # ``verify`` validates container structure but intentionally does not
        # decode raster data. Re-open and load so truncated scan data cannot
        # cross the validation boundary and fail later inside a GPU worker.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail="invalid or unsafe image payload",
        ) from exc
    return data


async def read_validated_upload(upload: UploadFile) -> bytes:
    media_type = upload.content_type
    try:
        data = await upload.read(settings.max_upload_bytes + 1)
    finally:
        await upload.close()
    return await run_in_threadpool(
        validate_image_bytes,
        data,
        media_type=media_type,
    )
