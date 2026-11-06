from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from system.gateway import (
    GatewayConfiguration,
    GatewayConfigurationError,
    make_gateway_handler,
    read_api_key,
    safe_static_path,
)


class _UpstreamHandler(BaseHTTPRequestHandler):
    observed: list[dict[str, object]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.__class__.observed.append(
            {
                "body": body,
                "key": self.headers.get("X-API-Key"),
                "method": self.command,
                "path": self.path,
            }
        )
        payload = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = _respond
    do_HEAD = _respond
    do_POST = _respond
    do_OPTIONS = _respond


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        _UpstreamHandler.observed = []
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "index.html").write_text("<h1>offline</h1>", encoding="utf-8")
        (self.root / "app.js").write_text("window.ok=true;", encoding="utf-8")
        (self.root / "outside.txt").write_text("not a secret", encoding="utf-8")

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.upstream_thread = threading.Thread(
            target=self.upstream.serve_forever,
            daemon=True,
        )
        self.upstream_thread.start()
        configuration = GatewayConfiguration(
            static_root=self.root,
            upstream_host="127.0.0.1",
            upstream_port=self.upstream.server_address[1],
            api_key="s" * 40,
            max_body_bytes=1024,
            upstream_timeout_seconds=5,
        )
        self.gateway = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_gateway_handler(configuration),
        )
        self.gateway_thread = threading.Thread(
            target=self.gateway.serve_forever,
            daemon=True,
        )
        self.gateway_thread.start()

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        target: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.gateway.server_address[1],
            timeout=5,
        )
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, payload

    def enable_sessions(self, *, secure_cookie: bool = False) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        configuration = GatewayConfiguration(
            static_root=self.root,
            upstream_host="127.0.0.1",
            upstream_port=self.upstream.server_address[1],
            api_key="s" * 40,
            session_username="demo-user",
            session_password="right-password",
            session_cookie_secure=secure_cookie,
            max_body_bytes=1024,
            upstream_timeout_seconds=5,
        )
        self.gateway = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_gateway_handler(configuration),
        )
        self.gateway_thread = threading.Thread(
            target=self.gateway.serve_forever,
            daemon=True,
        )
        self.gateway_thread.start()

    def login(self) -> tuple[str, str]:
        status, headers, body = self.request(
            "POST",
            "/api/session/login",
            body=json.dumps({
                "username": "demo-user",
                "password": "right-password",
                "remember": False,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertIn("httponly", headers["set-cookie"].lower())
        self.assertIn("samesite=lax", headers["set-cookie"].lower())
        self.assertNotIn(b"right-password", body)
        payload = json.loads(body)
        self.assertEqual(payload["session"]["username"], "demo-user")
        return headers["set-cookie"].split(";", 1)[0], payload["csrf"]

    def test_session_login_unlocks_real_api_and_rejects_wrong_password(self) -> None:
        self.enable_sessions()
        status, _headers, _body = self.request("GET", "/api/session")
        self.assertEqual(status, 401)
        status, _headers, _body = self.request(
            "POST",
            "/api/session/login",
            body=b'{"username":"demo-user","password":"wrong"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401)
        cookie, csrf = self.login()
        status, _headers, body = self.request("GET", "/api/session", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["csrf"], csrf)
        status, _headers, _body = self.request("GET", "/api/modules")
        self.assertEqual(status, 401)
        status, _headers, _body = self.request("GET", "/api/modules", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(_UpstreamHandler.observed[-1]["path"], "/api/modules")

    def test_session_requires_csrf_for_writes_and_logout_revokes_cookie(self) -> None:
        self.enable_sessions()
        cookie, csrf = self.login()
        status, _headers, _body = self.request(
            "POST", "/api/provenance/protect", body=b"payload", headers={"Cookie": cookie},
        )
        self.assertEqual(status, 403)
        self.assertEqual(_UpstreamHandler.observed, [])
        status, _headers, _body = self.request(
            "POST", "/api/provenance/protect", body=b"payload",
            headers={"Cookie": cookie, "X-JYS-CSRF": csrf},
        )
        self.assertEqual(status, 200)
        status, headers, _body = self.request(
            "POST", "/api/session/logout", body=b"{}",
            headers={"Cookie": cookie, "X-JYS-CSRF": csrf},
        )
        self.assertEqual(status, 200)
        self.assertIn("max-age=0", headers["set-cookie"].lower())
        status, _headers, _body = self.request("GET", "/api/session", headers={"Cookie": cookie})
        self.assertEqual(status, 401)

    def test_session_endpoint_reports_missing_credentials(self) -> None:
        status, _headers, _body = self.request("GET", "/api/session")
        self.assertEqual(status, 503)

    def test_session_password_file_configures_login(self) -> None:
        password_file = self.root / "login-password"
        password_file.write_text("file-password\n", encoding="utf-8")
        with patch.dict(os.environ, {
            "JYS_GATEWAY_STATIC_ROOT": str(self.root),
            "JYS_GATEWAY_UPSTREAM": f"http://127.0.0.1:{self.upstream.server_address[1]}",
            "JYS_GATEWAY_USERNAME": "demo-user",
            "JYS_GATEWAY_PASSWORD": "",
            "JYS_GATEWAY_PASSWORD_FILE": str(password_file),
        }):
            configuration = GatewayConfiguration.from_environment()
        self.assertIsNotNone(configuration.sessions)
        result = configuration.sessions.login(
            "demo-user", "file-password", remember=False, client="127.0.0.1"
        )
        self.assertIsInstance(result, tuple)

    def test_runtime_configuration_rejects_missing_login_credentials(self) -> None:
        with patch.dict(os.environ, {
            "JYS_GATEWAY_STATIC_ROOT": str(self.root),
            "JYS_GATEWAY_UPSTREAM": f"http://127.0.0.1:{self.upstream.server_address[1]}",
            "JYS_GATEWAY_USERNAME": "",
            "JYS_GATEWAY_PASSWORD": "",
            "JYS_GATEWAY_PASSWORD_FILE": "",
        }):
            with self.assertRaises(GatewayConfigurationError):
                GatewayConfiguration.from_environment()

    def test_secure_session_cookie_for_tls_deployment(self) -> None:
        self.enable_sessions(secure_cookie=True)
        status, headers, _body = self.request(
            "POST", "/api/session/login",
            body=b'{"username":"demo-user","password":"right-password","remember":true}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertIn("secure", headers["set-cookie"].lower())

    def test_static_frontend_is_same_origin_and_hardened(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"offline", body)
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn("connect-src 'self'", headers["content-security-policy"])
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_api_proxy_replaces_browser_supplied_key(self) -> None:
        status, _headers, body = self.request(
            "POST",
            "/api/provenance/protect?mode=real",
            body=b"payload",
            headers={
                "Content-Type": "application/octet-stream",
                "X-API-Key": "attacker-controlled",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(
            _UpstreamHandler.observed,
            [
                {
                    "body": b"payload",
                    "key": "s" * 40,
                    "method": "POST",
                    "path": "/api/provenance/protect?mode=real",
                }
            ],
        )

    def test_gateway_is_not_an_open_proxy(self) -> None:
        status, _headers, _body = self.request("CONNECT", "example.com:443")
        self.assertEqual(status, 405)
        status, _headers, _body = self.request("POST", "/apiary", body=b"x")
        self.assertEqual(status, 405)
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_static_path_traversal_and_symlink_escape_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            safe_static_path(self.root, "/%2e%2e/etc/passwd")
        outside = self.root.parent / "outside-gateway-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "escape.txt"
        link.symlink_to(outside)
        try:
            with self.assertRaises(ValueError):
                safe_static_path(self.root, "/escape.txt")
        finally:
            link.unlink()
            outside.unlink()

    def test_api_body_limit_is_enforced_before_upstream(self) -> None:
        status, _headers, _body = self.request("POST", "/api/infer/single", body=b"x" * 1025)
        self.assertEqual(status, 413)
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_production_secret_reader_rejects_symlink_and_short_key(self) -> None:
        key = self.root / "api-key"
        key.write_text("short", encoding="utf-8")
        with self.assertRaises(GatewayConfigurationError):
            read_api_key(key, required=True)
        key.write_text("k" * 40, encoding="utf-8")
        link = self.root / "key-link"
        link.symlink_to(key)
        with self.assertRaises(GatewayConfigurationError):
            read_api_key(link, required=True)


if __name__ == "__main__":
    unittest.main()
