#!/usr/bin/env python3
"""Minimal same-origin static/API gateway for the competition deployment.

The browser never receives the backend API key.  Only requests whose path is
``/api`` or starts with ``/api/`` are forwarded to the fixed internal API
origin; every other supported request is served from the immutable frontend
tree.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.cookies import SimpleCookie
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
SESSION_COOKIE = "jys_session"
SESSION_SECONDS = 12 * 60 * 60
REMEMBER_SESSION_SECONDS = 30 * 24 * 60 * 60
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 60
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
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


@dataclass(frozen=True)
class GatewaySession:
    username: str
    csrf: str
    expires_at: int


class GatewaySessions:
    """Keep browser sessions and failed-login counters in gateway memory."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self._password_digest = hashlib.sha256(password.encode("utf-8")).digest()
        self._sessions: dict[str, GatewaySession] = {}
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def login(self, username: str, password: str, *, remember: bool, client: str) -> tuple[str, GatewaySession] | str:
        now = time.time()
        with self._lock:
            failures = [when for when in self._failures.get(client, []) if now - when < LOGIN_FAILURE_WINDOW_SECONDS]
            if len(failures) >= LOGIN_FAILURE_LIMIT:
                self._failures[client] = failures
                return "rate_limited"
            username_valid = hmac.compare_digest(username, self.username)
            password_valid = hmac.compare_digest(
                hashlib.sha256(password.encode("utf-8")).digest(), self._password_digest
            )
            valid = username_valid and password_valid
            if not valid:
                failures.append(now)
                self._failures[client] = failures
                return "invalid"
            self._failures.pop(client, None)
            token = secrets.token_urlsafe(32)
            session = GatewaySession(
                username=self.username,
                csrf=secrets.token_urlsafe(32),
                expires_at=int(now + (REMEMBER_SESSION_SECONDS if remember else SESSION_SECONDS)),
            )
            self._sessions[token] = session
            return token, session

    def get(self, token: str | None) -> GatewaySession | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session and session.expires_at <= time.time():
                self._sessions.pop(token, None)
                return None
            return session

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


def _positive_int(value: str, *, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GatewayConfigurationError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise GatewayConfigurationError(f"{label} must be positive")
    return parsed


def read_api_key(path: Path, *, required: bool) -> str | None:
    """Read a deployment secret without accepting symlinks or empty values."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        if not required:
            return None
        raise GatewayConfigurationError("gateway API key file is missing") from exc
    except OSError as exc:
        raise GatewayConfigurationError("gateway API key path must be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise GatewayConfigurationError("gateway API key path must be a regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = handle.read().strip()
    except (OSError, UnicodeError) as exc:
        raise GatewayConfigurationError("gateway API key file is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not value:
        raise GatewayConfigurationError("gateway API key file is empty")
    if required and len(value) < 32:
        raise GatewayConfigurationError("gateway API key must contain at least 32 characters")
    return value


class GatewayConfiguration:
    """Validated immutable gateway settings."""

    def __init__(
        self,
        *,
        static_root: Path,
        upstream_host: str,
        upstream_port: int,
        api_key: str | None,
        session_username: str | None = None,
        session_password: str | None = None,
        session_cookie_secure: bool = False,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        upstream_timeout_seconds: int = 180,
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
        if max_body_bytes <= 0 or upstream_timeout_seconds <= 0:
            raise GatewayConfigurationError("gateway limits must be positive")
        if bool(session_username) != bool(session_password):
            raise GatewayConfigurationError("gateway session username and password must be set together")
        self.static_root = root
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.api_key = api_key
        self.session_cookie_secure = session_cookie_secure
        self.sessions = (
            GatewaySessions(session_username, session_password)
            if session_username and session_password
            else None
        )
        self.max_body_bytes = max_body_bytes
        self.upstream_timeout_seconds = upstream_timeout_seconds

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
        require_key = os.getenv("JYS_GATEWAY_REQUIRE_API_KEY", "false").strip().lower()
        if require_key not in {"true", "false"}:
            raise GatewayConfigurationError(
                "JYS_GATEWAY_REQUIRE_API_KEY must be true or false"
            )
        key_path_value = os.getenv("JYS_GATEWAY_API_KEY_FILE", "").strip()
        if require_key == "true" and not key_path_value:
            raise GatewayConfigurationError("JYS_GATEWAY_API_KEY_FILE is required")
        api_key = (
            read_api_key(Path(key_path_value), required=require_key == "true")
            if key_path_value
            else None
        )
        session_password = os.getenv("JYS_GATEWAY_PASSWORD") or None
        session_password_file = os.getenv("JYS_GATEWAY_PASSWORD_FILE", "").strip()
        if session_password and session_password_file:
            raise GatewayConfigurationError(
                "JYS_GATEWAY_PASSWORD and JYS_GATEWAY_PASSWORD_FILE are mutually exclusive"
            )
        if session_password_file:
            session_password = read_api_key(Path(session_password_file), required=False)
            if session_password is None:
                raise GatewayConfigurationError("gateway session password file is missing")
        session_username = os.getenv("JYS_GATEWAY_USERNAME", "").strip()
        if not session_username or not session_password or not session_password.strip():
            raise GatewayConfigurationError(
                "JYS_GATEWAY_USERNAME and a gateway session password are required"
            )
        secure_cookie_value = os.getenv("JYS_GATEWAY_COOKIE_SECURE", "false").strip().lower()
        if secure_cookie_value not in {"true", "false"}:
            raise GatewayConfigurationError("JYS_GATEWAY_COOKIE_SECURE must be true or false")
        return cls(
            static_root=Path(
                os.getenv("JYS_GATEWAY_STATIC_ROOT", "/app/system/frontend")
            ),
            upstream_host=upstream.hostname,
            upstream_port=upstream_port,
            api_key=api_key,
            session_username=session_username,
            session_password=session_password,
            session_cookie_secure=secure_cookie_value == "true",
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


def make_gateway_handler(configuration: GatewayConfiguration) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one validated configuration."""

    class GatewayHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "JianYuanShield-Gateway/1"
        sys_version = ""
        config: ClassVar[GatewayConfiguration] = configuration

        def log_message(self, format: str, *args: object) -> None:
            # Avoid logging query strings, uploaded metadata or credentials.
            del format, args
            path = urlsplit(self.path).path if self.path else "/"
            print(
                f"gateway client={self.client_address[0]} method={self.command} path={path}",
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

        def _session_json(
            self, status: int, payload: dict[str, object], *, cookie: str | None = None
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(body)

        def _session_error(self, status: int, code: str, message: str) -> None:
            self._session_json(status, {"error": {"code": code, "message": message}})

        def _cookie_token(self) -> str | None:
            values = self.headers.get_all("Cookie", [])
            if len(values) != 1:
                return None
            try:
                cookies = SimpleCookie()
                cookies.load(values[0])
                token = cookies[SESSION_COOKIE].value
            except (KeyError, ValueError):
                return None
            return token if re.fullmatch(r"[A-Za-z0-9_-]{20,100}", token) else None

        def _authorized_session(self, *, require_csrf: bool) -> tuple[str, GatewaySession] | None:
            sessions = self.config.sessions
            token = self._cookie_token()
            session = sessions.get(token) if sessions else None
            if session is None:
                self._session_error(401, "unauthorized", "请先登录")
                return None
            if require_csrf:
                values = self.headers.get_all("X-JYS-CSRF", [])
                if len(values) != 1 or not hmac.compare_digest(values[0], session.csrf):
                    self._session_error(403, "invalid_csrf", "会话校验失败")
                    return None
            return token, session

        def _session_payload(self, session: GatewaySession) -> dict[str, object]:
            return {
                "session": {
                    "username": session.username,
                    "display_name": "鉴源管理员",
                    "role": "管理员",
                    "expires_at": session.expires_at,
                },
                "csrf": session.csrf,
            }

        def _session_endpoint(self, path: str) -> None:
            sessions = self.config.sessions
            if sessions is None:
                self._session_error(503, "session_unavailable", "登录服务未配置")
                return
            if path == "/api/session" and self.command == "GET":
                authorized = self._authorized_session(require_csrf=False)
                if authorized:
                    self._session_json(200, self._session_payload(authorized[1]))
                return
            if path == "/api/session/login" and self.command == "POST":
                if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                    self._session_error(415, "invalid_content_type", "需要 JSON 请求")
                    return
                try:
                    body = self._request_body()
                    if len(body) > 4096:
                        raise OverflowError
                    payload = json.loads(body)
                except OverflowError:
                    self._session_error(413, "body_too_large", "登录请求过大")
                    return
                except (OSError, ValueError, UnicodeError):
                    self._session_error(400, "invalid_json", "登录请求无效")
                    return
                if not isinstance(payload, dict):
                    self._session_error(400, "invalid_json", "登录请求无效")
                    return
                username = payload.get("username")
                password = payload.get("password")
                remember = payload.get("remember", False)
                if (
                    not isinstance(username, str) or not isinstance(password, str)
                    or not isinstance(remember, bool)
                    or len(username) > 128 or len(password) > 1024
                ):
                    self._session_error(400, "invalid_credentials", "登录请求无效")
                    return
                result = sessions.login(username, password, remember=remember, client=self.client_address[0])
                if result == "rate_limited":
                    self._session_error(429, "rate_limited", "尝试次数过多，请稍后再试")
                    return
                if result == "invalid":
                    self._session_error(401, "unauthorized", "账号或访问口令有误")
                    return
                token, session = result
                cookie = f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/"
                if remember:
                    cookie += f"; Max-Age={REMEMBER_SESSION_SECONDS}"
                if self.config.session_cookie_secure:
                    cookie += "; Secure"
                self._session_json(200, self._session_payload(session), cookie=cookie)
                return
            if path == "/api/session/logout" and self.command == "POST":
                authorized = self._authorized_session(require_csrf=True)
                if not authorized:
                    return
                try:
                    self._request_body()
                except OverflowError:
                    self._session_error(413, "body_too_large", "请求过大")
                    return
                except (OSError, ValueError):
                    self._session_error(400, "invalid_request", "请求无效")
                    return
                sessions.revoke(authorized[0])
                cookie = f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
                if self.config.session_cookie_secure:
                    cookie += "; Secure"
                self._session_json(200, {"ok": True}, cookie=cookie)
                return
            self._session_error(405, "method_not_allowed", "请求方法不支持")

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

        def _request_body(self) -> bytes:
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
            if length < 0 or length > self.config.max_body_bytes:
                raise OverflowError("request body exceeds gateway limit")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete request body")
            return body

        def _proxy_headers(self, body: bytes) -> dict[str, str]:
            connection_headers = _connection_tokens(self.headers.get_all("Connection", []))
            forbidden = _HOP_BY_HOP | connection_headers | {
                "host", "x-api-key", "cookie", "x-jys-csrf"
            }
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
            if self.config.api_key is not None:
                headers["X-API-Key"] = self.config.api_key
            return headers

        def _proxy(self) -> None:
            try:
                path, query = _request_target(self.path)
                if not _is_api_path(path):
                    raise ValueError("non-API proxy target")
                if self.config.sessions and not self._authorized_session(
                    require_csrf=self.command not in {"GET", "HEAD", "OPTIONS"}
                ):
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
                forbidden = _HOP_BY_HOP | connection_headers
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
            path = urlsplit(self.path).path
            if path in {"/api/session", "/api/session/login", "/api/session/logout"}:
                self._session_endpoint(path)
            else:
                self._proxy() if _is_api_path(path) else self._static(head_only=False)

        def do_HEAD(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path in {"/api/session", "/api/session/login", "/api/session/logout"}:
                self._session_endpoint(path)
            else:
                self._proxy() if _is_api_path(path) else self._static(head_only=True)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path in {"/api/session", "/api/session/login", "/api/session/logout"}:
                self._session_endpoint(path)
            else:
                self._proxy() if _is_api_path(path) else self._plain_error(405, "method not allowed")

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
