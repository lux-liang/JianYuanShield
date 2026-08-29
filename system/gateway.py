#!/usr/bin/env python3
"""Minimal same-origin static/API gateway for the competition deployment.

The browser never receives the backend API key.  Only requests whose path is
``/api`` or starts with ``/api/`` are forwarded to the fixed internal API
origin; every other supported request is served from the immutable frontend
tree.
"""

from __future__ import annotations

import argparse
import base64
from collections import OrderedDict
from http.cookies import CookieError, SimpleCookie
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import stat
import threading
import time
from typing import ClassVar
from urllib.parse import unquote, urlsplit


API_PREFIX = "/api"
DEFAULT_MAX_BODY_BYTES = 96 * 1024 * 1024
DEFAULT_CLIENT_TIMEOUT_SECONDS = 30
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
DEFAULT_REMEMBER_TTL_SECONDS = 30 * 24 * 60 * 60
SESSION_JSON_MAX_BODY_BYTES = 16 * 1024
SESSION_COOKIE_NAME = "jys_session"
SESSION_CSRF_HEADER = "X-JYS-CSRF"
EDGE_CLIENT_IP_HEADER = "X-JYS-Client-IP"
_PUBLIC_API_GET_PATHS = frozenset(
    {
        "/api/health",
        "/api/projects",
        "/api/artifacts/status",
        "/api/samples",
        "/api/real-evals",
        "/api/benchmark/hidden-lfw-full",
        "/api/benchmark/lidmark-lfw-eval",
        "/api/benchmark/lidmark",
        "/api/benchmark/sepmark",
        "/api/benchmark/waveguard",
        "/api/benchmark/mea-matrix",
        "/api/benchmark/simswap-lfw",
        "/api/benchmark/kadnet",
        "/api/benchmark/aggregate",
        "/api/competition-report",
        "/api/evidence/audit",
        "/api/claims",
        "/api/evidence/signature",
        "/api/modules",
        "/api/models/status",
        "/api/system/gpu",
    }
)
_PUBLIC_API_GET_PREFIXES = (
    "/api/artifacts/",
    "/api/samples/",
    "/api/reports/",
    "/api/evidence/signature/download/",
    "/api/competition-report/download/",
)
_PUBLIC_API_POST_PATHS = frozenset(
    {
        "/api/tasks/demo-run",
        "/api/collaboration/recommend",
        "/api/infer/single",
        "/api/compliance/batch",
        "/api/provenance/protect",
        "/api/provenance/verify",
    }
)
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_UI_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_UNTRUSTED_PROXY_HEADERS = frozenset(
    {
        "forwarded",
        "via",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-real-ip",
        "cookie",
        SESSION_CSRF_HEADER.lower(),
        EDGE_CLIENT_IP_HEADER.lower(),
    }
)
_STATIC_SECURITY_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class GatewayConfigurationError(ValueError):
    """Raised when the gateway is not configured fail-closed."""


def _positive_int(value: str, *, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GatewayConfigurationError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise GatewayConfigurationError(f"{label} must be positive")
    return parsed


def _boolean(value: str, *, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise GatewayConfigurationError(f"{label} must be true or false")
    return normalized == "true"


def _read_secret_file(
    path: Path,
    *,
    label: str,
    required: bool,
    minimum_length: int,
) -> str | None:
    """Read a text secret from one regular, non-symlink file."""

    try:
        if path.is_symlink():
            raise GatewayConfigurationError(f"{label} path must be a regular file")
    except OSError as exc:
        raise GatewayConfigurationError(f"{label} path is unreadable") from exc

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        if not required:
            return None
        raise GatewayConfigurationError(f"{label} file is missing") from exc
    except OSError as exc:
        raise GatewayConfigurationError(f"{label} path must be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise GatewayConfigurationError(f"{label} path must be a regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = handle.read().strip()
    except (OSError, UnicodeError) as exc:
        raise GatewayConfigurationError(f"{label} file is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not value:
        raise GatewayConfigurationError(f"{label} file is empty")
    if len(value) < minimum_length:
        raise GatewayConfigurationError(
            f"{label} must contain at least {minimum_length} characters"
        )
    return value


def read_api_key(path: Path, *, required: bool) -> str | None:
    """Read a deployment secret without accepting symlinks or empty values."""

    return _read_secret_file(
        path,
        label="gateway API key",
        required=required,
        minimum_length=32 if required else 1,
    )


class GatewayConfiguration:
    """Validated immutable gateway settings."""

    def __init__(
        self,
        *,
        static_root: Path,
        upstream_host: str,
        upstream_port: int,
        api_key: str | None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        upstream_timeout_seconds: int = 180,
        client_timeout_seconds: int = DEFAULT_CLIENT_TIMEOUT_SECONDS,
        require_ui_session: bool = False,
        development_ui_bypass: bool = False,
        ui_username: str | None = None,
        ui_password: str | None = None,
        session_secret: str | bytes | None = None,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        remember_ttl_seconds: int = DEFAULT_REMEMBER_TTL_SECONDS,
        session_cookie_path: str = "/",
        ui_display_name: str | None = None,
        ui_role: str = "administrator",
    ) -> None:
        expanded_root = static_root.expanduser()
        if expanded_root.is_symlink():
            raise GatewayConfigurationError("static root must not be a symlink")
        root = expanded_root.resolve(strict=True)
        if not root.is_dir():
            raise GatewayConfigurationError("static root must be a real directory")
        if not _HOST_RE.fullmatch(upstream_host) or upstream_host in {"0.0.0.0", "::"}:
            raise GatewayConfigurationError("upstream host is invalid")
        if not 1 <= upstream_port <= 65535:
            raise GatewayConfigurationError("upstream port is invalid")
        if (
            max_body_bytes <= 0
            or upstream_timeout_seconds <= 0
            or client_timeout_seconds <= 0
            or session_ttl_seconds <= 0
            or remember_ttl_seconds <= 0
        ):
            raise GatewayConfigurationError("gateway limits must be positive")
        if remember_ttl_seconds < session_ttl_seconds:
            raise GatewayConfigurationError(
                "remember session lifetime must not be shorter than session lifetime"
            )
        normalized_username = (ui_username or "").strip()
        if normalized_username and not _UI_USERNAME_RE.fullmatch(normalized_username):
            raise GatewayConfigurationError("gateway UI username is invalid")
        normalized_password = ui_password or ""
        normalized_secret = (
            session_secret.encode("utf-8")
            if isinstance(session_secret, str)
            else session_secret or b""
        )
        if normalized_password and len(normalized_password) < 12:
            raise GatewayConfigurationError(
                "gateway UI password must contain at least 12 characters"
            )
        if normalized_secret and len(normalized_secret) < 32:
            raise GatewayConfigurationError(
                "gateway session secret must contain at least 32 bytes"
            )
        if require_ui_session and not (
            normalized_username and normalized_password and normalized_secret
        ):
            raise GatewayConfigurationError(
                "UI session protection requires username, password and signing secret"
            )
        if development_ui_bypass and require_ui_session:
            raise GatewayConfigurationError(
                "development UI bypass cannot be combined with UI session protection"
            )
        if development_ui_bypass and api_key is not None:
            raise GatewayConfigurationError(
                "development UI bypass cannot be combined with a gateway API key"
            )
        if development_ui_bypass and (
            normalized_username or normalized_password or normalized_secret
        ):
            raise GatewayConfigurationError(
                "development UI bypass cannot be combined with UI session credentials"
            )
        if (
            not session_cookie_path.startswith("/")
            or any(ord(character) < 33 for character in session_cookie_path)
            or any(character in session_cookie_path for character in ";,\\")
        ):
            raise GatewayConfigurationError("gateway session cookie path is invalid")
        normalized_display_name = (ui_display_name or normalized_username).strip()
        normalized_role = ui_role.strip()
        if len(normalized_display_name) > 128 or not normalized_role or len(normalized_role) > 64:
            raise GatewayConfigurationError("gateway UI identity metadata is invalid")
        self.static_root = root
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.api_key = api_key
        self.max_body_bytes = max_body_bytes
        self.upstream_timeout_seconds = upstream_timeout_seconds
        self.client_timeout_seconds = client_timeout_seconds
        self.require_ui_session = require_ui_session
        self.development_ui_bypass = development_ui_bypass
        self.ui_username = normalized_username
        self.ui_password = normalized_password
        self.session_secret = normalized_secret
        self.session_ttl_seconds = session_ttl_seconds
        self.remember_ttl_seconds = remember_ttl_seconds
        self.session_cookie_path = session_cookie_path
        self.ui_display_name = normalized_display_name
        self.ui_role = normalized_role

    @classmethod
    def from_environment(cls) -> "GatewayConfiguration":
        upstream = urlsplit(os.getenv("JYS_GATEWAY_UPSTREAM", "http://api:8026"))
        try:
            upstream_port = upstream.port or 80
        except ValueError as exc:
            raise GatewayConfigurationError("gateway upstream port is invalid") from exc
        if (
            upstream.scheme != "http"
            or not upstream.hostname
            or upstream.username is not None
            or upstream.password is not None
            or upstream.path
            or upstream.query
            or upstream.fragment
        ):
            raise GatewayConfigurationError(
                "JYS_GATEWAY_UPSTREAM must be an http origin without credentials or path"
            )
        require_key = _boolean(
            os.getenv("JYS_GATEWAY_REQUIRE_API_KEY", "false"),
            label="JYS_GATEWAY_REQUIRE_API_KEY",
        )
        key_path_value = os.getenv("JYS_GATEWAY_API_KEY_FILE", "").strip()
        if require_key and not key_path_value:
            raise GatewayConfigurationError("JYS_GATEWAY_API_KEY_FILE is required")
        api_key = (
            read_api_key(Path(key_path_value), required=require_key)
            if key_path_value
            else None
        )
        require_ui_session = _boolean(
            os.getenv("JYS_GATEWAY_REQUIRE_UI_SESSION", "false"),
            label="JYS_GATEWAY_REQUIRE_UI_SESSION",
        )
        development_ui_bypass = _boolean(
            os.getenv("JYS_GATEWAY_DEVELOPMENT_UI_BYPASS", "false"),
            label="JYS_GATEWAY_DEVELOPMENT_UI_BYPASS",
        )
        ui_username = os.getenv("JYS_GATEWAY_UI_USERNAME", "").strip()
        password_path_value = os.getenv(
            "JYS_GATEWAY_UI_PASSWORD_FILE", ""
        ).strip()
        secret_path_value = os.getenv(
            "JYS_GATEWAY_SESSION_SECRET_FILE", ""
        ).strip()
        if require_ui_session and not ui_username:
            raise GatewayConfigurationError("JYS_GATEWAY_UI_USERNAME is required")
        if require_ui_session and not password_path_value:
            raise GatewayConfigurationError(
                "JYS_GATEWAY_UI_PASSWORD_FILE is required"
            )
        if require_ui_session and not secret_path_value:
            raise GatewayConfigurationError(
                "JYS_GATEWAY_SESSION_SECRET_FILE is required"
            )
        ui_password = (
            _read_secret_file(
                Path(password_path_value),
                label="gateway UI password",
                required=require_ui_session,
                minimum_length=12,
            )
            if password_path_value
            else None
        )
        session_secret = (
            _read_secret_file(
                Path(secret_path_value),
                label="gateway session secret",
                required=require_ui_session,
                minimum_length=32,
            )
            if secret_path_value
            else None
        )
        return cls(
            static_root=Path(
                os.getenv("JYS_GATEWAY_STATIC_ROOT", "/app/system/frontend")
            ),
            upstream_host=upstream.hostname,
            upstream_port=upstream_port,
            api_key=api_key,
            max_body_bytes=_positive_int(
                os.getenv(
                    "JYS_GATEWAY_MAX_BODY_BYTES",
                    str(DEFAULT_MAX_BODY_BYTES),
                ),
                label="JYS_GATEWAY_MAX_BODY_BYTES",
            ),
            upstream_timeout_seconds=_positive_int(
                os.getenv("JYS_GATEWAY_TIMEOUT_SECONDS", "180"),
                label="JYS_GATEWAY_TIMEOUT_SECONDS",
            ),
            client_timeout_seconds=_positive_int(
                os.getenv(
                    "JYS_GATEWAY_CLIENT_TIMEOUT_SECONDS",
                    str(DEFAULT_CLIENT_TIMEOUT_SECONDS),
                ),
                label="JYS_GATEWAY_CLIENT_TIMEOUT_SECONDS",
            ),
            require_ui_session=require_ui_session,
            development_ui_bypass=development_ui_bypass,
            ui_username=ui_username or None,
            ui_password=ui_password,
            session_secret=session_secret,
            session_ttl_seconds=_positive_int(
                os.getenv(
                    "JYS_GATEWAY_SESSION_TTL_SECONDS",
                    str(DEFAULT_SESSION_TTL_SECONDS),
                ),
                label="JYS_GATEWAY_SESSION_TTL_SECONDS",
            ),
            remember_ttl_seconds=_positive_int(
                os.getenv(
                    "JYS_GATEWAY_REMEMBER_TTL_SECONDS",
                    str(DEFAULT_REMEMBER_TTL_SECONDS),
                ),
                label="JYS_GATEWAY_REMEMBER_TTL_SECONDS",
            ),
            session_cookie_path=os.getenv(
                "JYS_GATEWAY_SESSION_COOKIE_PATH",
                os.getenv("JYS_GATEWAY_COOKIE_PATH", "/"),
            ).strip(),
            ui_display_name=os.getenv(
                "JYS_GATEWAY_UI_DISPLAY_NAME", ui_username
            ).strip(),
            ui_role=os.getenv("JYS_GATEWAY_UI_ROLE", "administrator").strip(),
        )


def _request_target(raw_target: str) -> tuple[str, str]:
    """Return raw path/query after rejecting absolute-form and control chars."""

    if any(ord(character) < 32 for character in raw_target) or "\\" in raw_target:
        raise ValueError("invalid request target")
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("absolute or fragmented request target is forbidden")
    path = parsed.path or "/"
    try:
        decoded = unquote(path, errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid request-target encoding") from exc
    segments = PurePosixPath(decoded).parts
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("dot segments are forbidden")
    query = f"?{parsed.query}" if parsed.query else ""
    return path, query


def _is_api_path(path: str) -> bool:
    try:
        decoded = unquote(path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    return decoded == API_PREFIX or decoded.startswith(f"{API_PREFIX}/")


def _public_api_request_allowed(method: str, path: str) -> bool:
    """Limit secret injection to the API surface required by the public UI."""

    try:
        decoded = unquote(path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    normalized_method = method.upper()
    get_allowed = decoded in _PUBLIC_API_GET_PATHS or any(
        decoded.startswith(prefix) and len(decoded) > len(prefix)
        for prefix in _PUBLIC_API_GET_PREFIXES
    )
    if normalized_method in {"GET", "HEAD"}:
        return get_allowed
    if normalized_method == "POST":
        return decoded in _PUBLIC_API_POST_PATHS
    if normalized_method == "OPTIONS":
        return get_allowed or decoded in _PUBLIC_API_POST_PATHS
    return False


def safe_static_path(static_root: Path, raw_target: str) -> Path:
    """Resolve a static request without directory listings or traversal."""

    path, _query = _request_target(raw_target)
    decoded = unquote(path, errors="strict")
    relative = decoded.lstrip("/") or "index.html"
    candidate = (static_root / relative).resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError as exc:
        raise ValueError("static path escapes frontend root") from exc
    if candidate.is_dir():
        candidate = (candidate / "index.html").resolve()
        try:
            candidate.relative_to(static_root)
        except ValueError as exc:
            raise ValueError("static directory escapes frontend root") from exc
    if not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _connection_tokens(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(part.strip().lower() for part in value.split(",") if part.strip())
    return tokens


def _normalized_client_ip(value: str | None, fallback: str) -> str:
    """Return one canonical client IP without accepting proxy chains.

    The public Caddy edge overwrites ``X-JYS-Client-IP`` with ``{remote_host}``.
    The reverse tunnel is loopback-only, so the H100 gateway accepts exactly
    one address from that header and rebuilds the standard forwarding headers.
    Any malformed or comma-separated value fails closed to the socket peer.
    """

    candidate = (value or "").strip()
    if not candidate or "," in candidate:
        candidate = fallback
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        try:
            return ipaddress.ip_address(fallback).compressed
        except ValueError:
            return "127.0.0.1"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not value or len(value) > 4096:
        raise ValueError("invalid encoded value")
    encoded = value.encode("ascii")
    return base64.b64decode(
        encoded + b"=" * (-len(encoded) % 4),
        altchars=b"-_",
        validate=True,
    )


def _issue_session_token(
    configuration: GatewayConfiguration,
    *,
    remember: bool,
) -> tuple[str, dict[str, object], int]:
    now = int(time.time())
    lifetime = (
        configuration.remember_ttl_seconds
        if remember
        else configuration.session_ttl_seconds
    )
    claims: dict[str, object] = {
        "csrf": secrets.token_urlsafe(32),
        "display_name": configuration.ui_display_name,
        "exp": now + lifetime,
        "iat": now,
        "remember": remember,
        "role": configuration.ui_role,
        "username": configuration.ui_username,
    }
    payload = json.dumps(
        claims,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded_payload = _base64url_encode(payload)
    signature = hmac.new(
        configuration.session_secret,
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}", claims, lifetime


def _decode_session_token(
    configuration: GatewayConfiguration,
    token: str,
) -> dict[str, object] | None:
    if not configuration.session_secret or len(token) > 4096:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".")
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            configuration.session_secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expected_string_claims = {
        "username": configuration.ui_username,
        "display_name": configuration.ui_display_name,
        "role": configuration.ui_role,
    }
    for name, expected in expected_string_claims.items():
        supplied = payload.get(name)
        if not isinstance(supplied, str) or not hmac.compare_digest(
            supplied.encode("utf-8"), expected.encode("utf-8")
        ):
            return None
    csrf = payload.get("csrf")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    remember = payload.get("remember")
    if (
        not isinstance(csrf, str)
        or not 32 <= len(csrf) <= 128
        or type(issued_at) is not int
        or type(expires_at) is not int
        or type(remember) is not bool
    ):
        return None
    now = int(time.time())
    maximum_lifetime = (
        configuration.remember_ttl_seconds
        if remember
        else configuration.session_ttl_seconds
    )
    if (
        issued_at > now + 30
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > maximum_lifetime
        or issued_at < now - configuration.remember_ttl_seconds - 30
    ):
        return None
    return payload


class _LoginFailureLimiter:
    """Small, bounded fixed-window limiter for failed login attempts."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 5 * 60,
        max_entries: int = 2048,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        expired = [
            client_ip
            for client_ip, (started_at, _count) in self._entries.items()
            if now - started_at >= self.window_seconds
        ]
        for client_ip in expired:
            self._entries.pop(client_ip, None)

    def allowed(self, client_ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            entry = self._entries.get(client_ip)
            if entry is None or entry[1] < self.max_failures:
                return True, 0
            self._entries.move_to_end(client_ip)
            retry_after = max(1, int(self.window_seconds - (now - entry[0])) + 1)
            return False, retry_after

    def record_failure(self, client_ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            started_at, count = self._entries.get(client_ip, (now, 0))
            self._entries[client_ip] = (started_at, count + 1)
            self._entries.move_to_end(client_ip)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def record_success(self, client_ip: str) -> None:
        with self._lock:
            self._entries.pop(client_ip, None)


def make_gateway_handler(configuration: GatewayConfiguration) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one validated configuration."""

    class GatewayHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "JianYuanShield-Gateway/1"
        sys_version = ""
        config: ClassVar[GatewayConfiguration] = configuration
        login_limiter: ClassVar[_LoginFailureLimiter] = _LoginFailureLimiter()
        development_csrf_token: ClassVar[str] = secrets.token_urlsafe(32)

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(self.config.client_timeout_seconds)

        def _client_ip(self) -> str:
            return _normalized_client_ip(
                self.headers.get(EDGE_CLIENT_IP_HEADER),
                self.client_address[0],
            )

        def log_message(self, format: str, *args: object) -> None:
            # Avoid logging query strings, uploaded metadata or credentials.
            del format, args
            path = urlsplit(self.path).path if self.path else "/"
            print(
                f"gateway client={self._client_ip()} method={self.command} path={path}",
                flush=True,
            )

        def _plain_error(self, status: int, message: str) -> None:
            body = (message + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json_response(
            self,
            status: int,
            payload: dict[str, object],
            *,
            headers: dict[str, str] | None = None,
            close: bool = False,
        ) -> None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json_error(
            self,
            status: int,
            code: str,
            message: str,
            *,
            headers: dict[str, str] | None = None,
            close: bool = False,
        ) -> None:
            self._json_response(
                status,
                {"error": {"code": code, "message": message}},
                headers=headers,
                close=close,
            )

        def _session_ready(self) -> bool:
            return bool(
                self.config.ui_username
                and self.config.ui_password
                and self.config.session_secret
            )

        def _session_cookie_value(self) -> str | None:
            values = self.headers.get_all("Cookie", [])
            if len(values) != 1:
                return None
            raw_cookie = values[0]
            matching_names = [
                part.partition("=")[0].strip()
                for part in raw_cookie.split(";")
                if "=" in part
            ]
            if matching_names.count(SESSION_COOKIE_NAME) != 1:
                return None
            try:
                cookies = SimpleCookie()
                cookies.load(raw_cookie)
            except CookieError:
                return None
            morsel = cookies.get(SESSION_COOKIE_NAME)
            return morsel.value if morsel and morsel.value else None

        def _authenticated_session(self) -> dict[str, object] | None:
            token = self._session_cookie_value()
            if token is None:
                return None
            return _decode_session_token(self.config, token)

        def _csrf_valid(self, claims: dict[str, object]) -> bool:
            values = self.headers.get_all(SESSION_CSRF_HEADER, [])
            expected = claims.get("csrf")
            return (
                len(values) == 1
                and isinstance(expected, str)
                and hmac.compare_digest(
                    values[0].encode("utf-8"), expected.encode("utf-8")
                )
            )

        def _public_session_payload(
            self,
            claims: dict[str, object],
        ) -> dict[str, object]:
            return {
                "authenticated": True,
                "csrf": claims["csrf"],
                "session": {
                    "display_name": claims["display_name"],
                    "expires_at": claims["exp"],
                    "role": claims["role"],
                    "username": claims["username"],
                },
            }

        def _development_session_payload(self) -> dict[str, object]:
            return {
                "authenticated": True,
                "authentication_mode": "local-development-bypass",
                "csrf": self.development_csrf_token,
                "csrf_enforced": False,
                "session": {
                    "display_name": "本机匿名开发会话",
                    "expires_at": 0,
                    "role": "local-development",
                    "username": "anonymous-local-development",
                },
            }

        def _development_bypass_conflict(self) -> None:
            self._json_error(
                409,
                "development_ui_bypass_active",
                "credential login and logout are disabled by the local development UI bypass",
                close=True,
            )

        def _cookie_header(
            self,
            token: str,
            *,
            max_age: int | None = None,
            expire: bool = False,
        ) -> str:
            parts = [
                f"{SESSION_COOKIE_NAME}={token}",
                f"Path={self.config.session_cookie_path}",
                "HttpOnly",
                "Secure",
                "SameSite=Strict",
            ]
            if max_age is not None:
                parts.append(f"Max-Age={max_age}")
            if expire:
                parts.extend(
                    ["Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
                )
            return "; ".join(parts)

        def _static(self, *, head_only: bool) -> None:
            if self.command not in {"GET", "HEAD"}:
                self._plain_error(405, "method not allowed")
                return
            try:
                path = safe_static_path(self.config.static_root, self.path)
                size = path.stat().st_size
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                with path.open("rb") as handle:
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(size))
                    for name, value in _STATIC_SECURITY_HEADERS.items():
                        self.send_header(name, value)
                    self.end_headers()
                    if not head_only:
                        while chunk := handle.read(1024 * 1024):
                            self.wfile.write(chunk)
            except FileNotFoundError:
                self._plain_error(404, "not found")
            except (OSError, ValueError):
                self._plain_error(400, "invalid static path")

        def _request_body(self, *, max_bytes: int | None = None) -> bytes:
            transfer_encoding = self.headers.get_all("Transfer-Encoding", [])
            if transfer_encoding:
                raise ValueError("transfer-encoded requests are forbidden")
            lengths = [value.strip() for value in self.headers.get_all("Content-Length", [])]
            if not lengths:
                return b""
            if len(set(lengths)) != 1:
                raise ValueError("conflicting Content-Length headers")
            try:
                length = int(lengths[0])
            except ValueError as exc:
                raise ValueError("invalid Content-Length header") from exc
            effective_limit = self.config.max_body_bytes if max_bytes is None else max_bytes
            if length < 0 or length > effective_limit:
                raise OverflowError("request body exceeds gateway limit")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete request body")
            return body

        def _session_login(self) -> None:
            if self.config.development_ui_bypass:
                self._development_bypass_conflict()
                return
            if not self._session_ready():
                self._json_error(
                    503,
                    "session_unavailable",
                    "session authentication is unavailable",
                    close=True,
                )
                return
            allowed, retry_after = self.login_limiter.allowed(self._client_ip())
            if not allowed:
                self._json_error(
                    429,
                    "login_rate_limited",
                    "too many login attempts",
                    headers={"Retry-After": str(retry_after)},
                    close=True,
                )
                return
            try:
                content_type = self.headers.get("Content-Type", "").partition(";")[0]
                if content_type.strip().lower() != "application/json":
                    raise ValueError("login body must be JSON")
                body = self._request_body(max_bytes=SESSION_JSON_MAX_BODY_BYTES)
                document = json.loads(body.decode("utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("login body must be an object")
                username = document.get("username")
                password = document.get("password")
                remember = document.get("remember", False)
                if (
                    not isinstance(username, str)
                    or not isinstance(password, str)
                    or type(remember) is not bool
                ):
                    raise ValueError("login fields are invalid")
            except OverflowError:
                self._json_error(
                    413,
                    "request_too_large",
                    "login request is too large",
                    close=True,
                )
                return
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                self._json_error(
                    400,
                    "invalid_request",
                    "invalid login request",
                    close=True,
                )
                return

            username_matches = hmac.compare_digest(
                username.encode("utf-8"),
                self.config.ui_username.encode("utf-8"),
            )
            password_matches = hmac.compare_digest(
                password.encode("utf-8"),
                self.config.ui_password.encode("utf-8"),
            )
            if not (username_matches and password_matches):
                self.login_limiter.record_failure(self._client_ip())
                self._json_error(
                    401,
                    "invalid_credentials",
                    "invalid username or password",
                    close=True,
                )
                return

            self.login_limiter.record_success(self._client_ip())
            token, claims, lifetime = _issue_session_token(
                self.config,
                remember=remember,
            )
            cookie_max_age = lifetime if remember else None
            self._json_response(
                200,
                self._public_session_payload(claims),
                headers={
                    "Set-Cookie": self._cookie_header(
                        token,
                        max_age=cookie_max_age,
                    )
                },
            )

        def _session_status(self) -> None:
            if self.config.development_ui_bypass:
                self._json_response(200, self._development_session_payload())
                return
            if not self._session_ready():
                self._json_error(
                    503,
                    "session_unavailable",
                    "session authentication is unavailable",
                )
                return
            claims = self._authenticated_session()
            if claims is None:
                self._json_error(
                    401,
                    "authentication_required",
                    "authentication is required",
                )
                return
            self._json_response(200, self._public_session_payload(claims))

        def _session_logout(self) -> None:
            if self.config.development_ui_bypass:
                self._development_bypass_conflict()
                return
            if not self._session_ready():
                self._json_error(
                    503,
                    "session_unavailable",
                    "session authentication is unavailable",
                )
                return
            try:
                body = self._request_body(max_bytes=SESSION_JSON_MAX_BODY_BYTES)
                if body:
                    content_type = self.headers.get("Content-Type", "").partition(";")[0]
                    if content_type.strip().lower() != "application/json":
                        raise ValueError("logout body must be JSON")
                    document = json.loads(body.decode("utf-8"))
                    if not isinstance(document, dict):
                        raise ValueError("logout body must be an object")
            except OverflowError:
                self._json_error(
                    413,
                    "request_too_large",
                    "logout request is too large",
                    close=True,
                )
                return
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                self._json_error(
                    400,
                    "invalid_request",
                    "invalid logout request",
                    close=True,
                )
                return
            claims = self._authenticated_session()
            if claims is None:
                self._json_error(
                    401,
                    "authentication_required",
                    "authentication is required",
                    close=True,
                )
                return
            if not self._csrf_valid(claims):
                self._json_error(
                    403,
                    "csrf_validation_failed",
                    "CSRF validation failed",
                    close=True,
                )
                return
            self._json_response(
                200,
                {"authenticated": False},
                headers={"Set-Cookie": self._cookie_header("", expire=True)},
            )

        def _proxy_headers(self, body: bytes) -> dict[str, str]:
            connection_headers = _connection_tokens(self.headers.get_all("Connection", []))
            forbidden = (
                _HOP_BY_HOP
                | _UNTRUSTED_PROXY_HEADERS
                | connection_headers
                | {"host", "x-api-key"}
            )
            headers: dict[str, str] = {}
            seen: set[str] = set()
            for name in self.headers:
                lowered = name.lower()
                if lowered in forbidden or lowered in seen:
                    continue
                values = self.headers.get_all(name, [])
                if len(values) == 1:
                    headers[name] = values[0]
                    seen.add(lowered)
            headers["Host"] = f"{self.config.upstream_host}:{self.config.upstream_port}"
            headers["Content-Length"] = str(len(body))
            headers["X-Forwarded-For"] = self._client_ip()
            headers["X-Forwarded-Proto"] = "https"
            if self.config.api_key is not None:
                headers["X-API-Key"] = self.config.api_key
            return headers

        def _proxy(self) -> None:
            try:
                path, query = _request_target(self.path)
                if not _is_api_path(path):
                    raise ValueError("non-API proxy target")
                if not _public_api_request_allowed(self.command, path):
                    self._plain_error(403, "API route is not exposed by the public gateway")
                    return
                if self.command == "POST" and self.config.require_ui_session:
                    claims = self._authenticated_session()
                    if claims is None:
                        self._json_error(
                            401,
                            "authentication_required",
                            "authentication is required",
                            close=True,
                        )
                        return
                    if not self._csrf_valid(claims):
                        self._json_error(
                            403,
                            "csrf_validation_failed",
                            "CSRF validation failed",
                            close=True,
                        )
                        return
                body = self._request_body()
                headers = self._proxy_headers(body)
            except OverflowError:
                self._plain_error(413, "request body too large")
                return
            except (OSError, ValueError):
                self._plain_error(400, "invalid API request")
                return

            connection = http.client.HTTPConnection(
                self.config.upstream_host,
                self.config.upstream_port,
                timeout=self.config.upstream_timeout_seconds,
            )
            response_started = False
            try:
                connection.request(self.command, f"{path}{query}", body=body, headers=headers)
                response = connection.getresponse()
                connection_headers = _connection_tokens(
                    response.headers.get_all("Connection", [])
                )
                forbidden = _HOP_BY_HOP | connection_headers | {"set-cookie"}
                self.send_response(response.status, response.reason)
                response_started = True
                has_length = False
                for name, value in response.getheaders():
                    lowered = name.lower()
                    if lowered in forbidden:
                        continue
                    if lowered == "content-length":
                        has_length = True
                    self.send_header(name, value)
                if not has_length:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if self.command != "HEAD":
                    while chunk := response.read(1024 * 1024):
                        self.wfile.write(chunk)
            except (ConnectionError, http.client.HTTPException, OSError, socket.timeout):
                if not response_started and not self.wfile.closed:
                    try:
                        self._plain_error(502, "API upstream unavailable")
                    except OSError:
                        pass
                else:
                    self.close_connection = True
            finally:
                connection.close()

        def do_GET(self) -> None:  # noqa: N802
            try:
                path, _query = _request_target(self.path)
                normalized_path = unquote(path, errors="strict")
            except (UnicodeDecodeError, ValueError):
                self._json_error(400, "invalid_request", "invalid request target")
                return
            if normalized_path == "/api/session":
                self._session_status()
            elif _is_api_path(path):
                self._proxy()
            else:
                self._static(head_only=False)

        def do_HEAD(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            self._proxy() if _is_api_path(path) else self._static(head_only=True)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path, _query = _request_target(self.path)
                normalized_path = unquote(path, errors="strict")
            except (UnicodeDecodeError, ValueError):
                self._json_error(400, "invalid_request", "invalid request target")
                return
            if normalized_path == "/api/session/login":
                self._session_login()
            elif normalized_path == "/api/session/logout":
                self._session_logout()
            elif _is_api_path(path):
                self._proxy()
            else:
                self._plain_error(405, "method not allowed")

        def do_OPTIONS(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            self._proxy() if _is_api_path(path) else self._plain_error(405, "method not allowed")

        def do_CONNECT(self) -> None:  # noqa: N802
            self._plain_error(405, "CONNECT is forbidden")

        def handle_expect_100(self) -> bool:
            self._plain_error(417, "Expect is not supported")
            return False

    return GatewayHandler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("JYS_GATEWAY_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=_positive_int(
            os.getenv("JYS_GATEWAY_PORT", "8027"),
            label="JYS_GATEWAY_PORT",
        ),
    )
    args = parser.parse_args()
    configuration = GatewayConfiguration.from_environment()
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_gateway_handler(configuration),
    )
    print(
        f"gateway listening={args.host}:{args.port} "
        f"upstream={configuration.upstream_host}:{configuration.upstream_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
