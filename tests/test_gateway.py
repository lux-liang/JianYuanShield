from __future__ import annotations

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
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
                "forwarded": self.headers.get("Forwarded"),
                "forwarded_for": self.headers.get("X-Forwarded-For"),
                "forwarded_proto": self.headers.get("X-Forwarded-Proto"),
                "real_ip": self.headers.get("X-Real-IP"),
                "cookie": self.headers.get("Cookie"),
                "csrf": self.headers.get("X-JYS-CSRF"),
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

        self.session_secret = "t" * 64
        self.session_username = "operator"
        self.session_password = "correct horse battery staple"
        authenticated_configuration = GatewayConfiguration(
            static_root=self.root,
            upstream_host="127.0.0.1",
            upstream_port=self.upstream.server_address[1],
            api_key="s" * 40,
            max_body_bytes=1024,
            upstream_timeout_seconds=5,
            require_ui_session=True,
            ui_username=self.session_username,
            ui_password=self.session_password,
            session_secret=self.session_secret,
            session_ttl_seconds=60,
            remember_ttl_seconds=600,
            session_cookie_path="/jianyuanshield/",
            ui_display_name="鉴源盾管理员",
            ui_role="administrator",
        )
        self.auth_gateway = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_gateway_handler(authenticated_configuration),
        )
        self.auth_gateway_thread = threading.Thread(
            target=self.auth_gateway.serve_forever,
            daemon=True,
        )
        self.auth_gateway_thread.start()

        development_configuration = GatewayConfiguration(
            static_root=self.root,
            upstream_host="127.0.0.1",
            upstream_port=self.upstream.server_address[1],
            api_key=None,
            max_body_bytes=1024,
            upstream_timeout_seconds=5,
            require_ui_session=False,
            development_ui_bypass=True,
        )
        self.development_gateway = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_gateway_handler(development_configuration),
        )
        self.development_gateway_thread = threading.Thread(
            target=self.development_gateway.serve_forever,
            daemon=True,
        )
        self.development_gateway_thread.start()

    def tearDown(self) -> None:
        self.development_gateway.shutdown()
        self.development_gateway.server_close()
        self.auth_gateway.shutdown()
        self.auth_gateway.server_close()
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
        authenticated_gateway: bool = False,
        development_gateway: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        gateway = (
            self.development_gateway
            if development_gateway
            else self.auth_gateway if authenticated_gateway else self.gateway
        )
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            gateway.server_address[1],
            timeout=5,
        )
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, payload

    def login(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        remember: bool = False,
    ) -> tuple[int, dict[str, str], dict[str, object]]:
        document = {
            "username": username if username is not None else self.session_username,
            "password": password if password is not None else self.session_password,
            "remember": remember,
        }
        status, headers, body = self.request(
            "POST",
            "/api/session/login",
            body=json.dumps(document).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            authenticated_gateway=True,
        )
        return status, headers, json.loads(body)

    @staticmethod
    def cookie_pair(set_cookie: str) -> str:
        return set_cookie.split(";", 1)[0]

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
                    "forwarded": None,
                    "forwarded_for": "127.0.0.1",
                    "forwarded_proto": "https",
                    "real_ip": None,
                    "cookie": None,
                    "csrf": None,
                }
            ],
        )

    def test_gateway_rebuilds_forwarding_identity_from_edge_header(self) -> None:
        status, _headers, _body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            headers={
                "Forwarded": "for=203.0.113.99;proto=http",
                "X-Forwarded-For": "203.0.113.99, 198.51.100.2",
                "X-Forwarded-Proto": "http",
                "X-Real-IP": "203.0.113.99",
                "X-JYS-Client-IP": "198.51.100.24",
            },
        )
        self.assertEqual(status, 200)
        observed = _UpstreamHandler.observed[-1]
        self.assertIsNone(observed["forwarded"])
        self.assertIsNone(observed["real_ip"])
        self.assertEqual(observed["forwarded_for"], "198.51.100.24")
        self.assertEqual(observed["forwarded_proto"], "https")

    def test_gateway_rejects_proxy_chain_in_edge_identity_header(self) -> None:
        status, _headers, _body = self.request(
            "GET",
            "/api/system/gpu",
            headers={"X-JYS-Client-IP": "198.51.100.24, 203.0.113.9"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(_UpstreamHandler.observed[-1]["forwarded_for"], "127.0.0.1")

    def test_gateway_is_not_an_open_proxy(self) -> None:
        status, _headers, _body = self.request("CONNECT", "example.com:443")
        self.assertEqual(status, 405)
        status, _headers, _body = self.request("POST", "/apiary", body=b"x")
        self.assertEqual(status, 405)
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_gateway_injects_secret_only_for_public_competition_routes(self) -> None:
        status, _headers, _body = self.request("GET", "/api/system/gpu")
        self.assertEqual(status, 200)
        self.assertEqual(len(_UpstreamHandler.observed), 1)

        blocked_requests = (
            ("GET", "/api/health/details"),
            ("GET", "/api/provenance/records/example"),
            ("POST", "/api/creator/challenges"),
            ("POST", "/api/provenance/example/revoke"),
            ("GET", "/api/not-a-real-route"),
        )
        for method, path in blocked_requests:
            with self.subTest(method=method, path=path):
                status, _headers, _body = self.request(method, path, body=b"{}")
                self.assertEqual(status, 403)
        self.assertEqual(len(_UpstreamHandler.observed), 1)

    def test_gateway_allows_frontend_dynamic_download_routes(self) -> None:
        allowed = (
            "/api/artifacts/task/output.png",
            "/api/samples/example/image",
            "/api/reports/task-123",
            "/api/evidence/signature/download/manifest.json",
            "/api/competition-report/download/json",
        )
        for path in allowed:
            with self.subTest(path=path):
                status, _headers, _body = self.request("GET", path)
                self.assertEqual(status, 200)
        self.assertEqual(len(_UpstreamHandler.observed), len(allowed))

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

    def test_session_login_get_and_cookie_security(self) -> None:
        status, headers, document = self.login(remember=True)
        self.assertEqual(status, 200)
        self.assertTrue(document["authenticated"])
        self.assertEqual(document["session"]["username"], self.session_username)
        self.assertEqual(document["session"]["display_name"], "鉴源盾管理员")
        self.assertNotIn("password", json.dumps(document))
        self.assertNotIn(self.session_secret, json.dumps(document))
        self.assertEqual(headers["cache-control"], "no-store")
        set_cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/jianyuanshield/", set_cookie)
        self.assertIn("Max-Age=600", set_cookie)

        status, response_headers, response_body = self.request(
            "GET",
            "/api/session",
            headers={"Cookie": self.cookie_pair(set_cookie)},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(response_headers["cache-control"], "no-store")
        current = json.loads(response_body)
        self.assertEqual(current["csrf"], document["csrf"])
        self.assertEqual(current["session"], document["session"])
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_development_bypass_returns_an_explicit_anonymous_session(self) -> None:
        status, headers, body = self.request(
            "GET",
            "/api/session",
            development_gateway=True,
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", headers)
        document = json.loads(body)
        self.assertTrue(document["authenticated"])
        self.assertEqual(
            document["authentication_mode"],
            "local-development-bypass",
        )
        self.assertFalse(document["csrf_enforced"])
        self.assertGreaterEqual(len(document["csrf"]), 32)
        self.assertEqual(document["session"]["role"], "local-development")
        self.assertEqual(
            document["session"]["username"],
            "anonymous-local-development",
        )

        status, _headers, body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            headers={"X-JYS-CSRF": document["csrf"]},
            development_gateway=True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertIsNone(_UpstreamHandler.observed[-1]["key"])

    def test_development_bypass_rejects_credential_login_and_logout_consistently(self) -> None:
        responses: list[dict[str, object]] = []
        for path in ("/api/session/login", "/api/session/logout"):
            status, headers, body = self.request(
                "POST",
                path,
                body=b"{}",
                headers={"Content-Type": "application/json"},
                development_gateway=True,
            )
            self.assertEqual(status, 409)
            self.assertNotIn("set-cookie", headers)
            responses.append(json.loads(body))

        self.assertEqual(responses[0], responses[1])
        self.assertEqual(
            responses[0]["error"]["code"],
            "development_ui_bypass_active",
        )

    def test_session_login_failure_is_generic_and_rate_limited(self) -> None:
        errors: list[dict[str, object]] = []
        attempts = (
            ("unknown-user", self.session_password),
            (self.session_username, "wrong-password-value"),
            ("unknown-user", "wrong-password-value"),
            (self.session_username, "wrong-password-value"),
            ("unknown-user", self.session_password),
        )
        for username, password in attempts:
            status, headers, document = self.login(
                username=username,
                password=password,
            )
            self.assertEqual(status, 401)
            self.assertNotIn("set-cookie", headers)
            errors.append(document)
        self.assertTrue(all(error == errors[0] for error in errors))

        status, headers, document = self.login(password="wrong-password-value")
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
        self.assertEqual(document["error"]["code"], "login_rate_limited")
        self.assertEqual(_UpstreamHandler.observed, [])

    def test_session_protects_public_posts_with_cookie_and_csrf(self) -> None:
        status, _headers, _body = self.request(
            "GET",
            "/api/system/gpu",
            authenticated_gateway=True,
        )
        self.assertEqual(status, 200, "public GET routes must remain public")
        _UpstreamHandler.observed = []

        status, _headers, body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            authenticated_gateway=True,
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "authentication_required")

        login_status, login_headers, login_document = self.login()
        self.assertEqual(login_status, 200)
        cookie = self.cookie_pair(login_headers["set-cookie"])
        status, _headers, body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            headers={"Cookie": cookie},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "csrf_validation_failed")

        status, _headers, _body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            headers={
                "Cookie": cookie,
                "X-JYS-CSRF": "attacker-controlled",
            },
            authenticated_gateway=True,
        )
        self.assertEqual(status, 403)

        status, _headers, body = self.request(
            "POST",
            "/api/provenance/verify",
            body=b"payload",
            headers={
                "Cookie": cookie,
                "X-JYS-CSRF": login_document["csrf"],
            },
            authenticated_gateway=True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(len(_UpstreamHandler.observed), 1)
        self.assertIsNone(_UpstreamHandler.observed[0]["cookie"])
        self.assertIsNone(_UpstreamHandler.observed[0]["csrf"])

    def test_session_rejects_tampered_and_expired_tokens_and_logs_out(self) -> None:
        status, headers, document = self.login()
        self.assertEqual(status, 200)
        cookie_name, token = self.cookie_pair(headers["set-cookie"]).split("=", 1)
        encoded_payload, encoded_signature = token.split(".")
        changed = "A" if encoded_signature[0] != "A" else "B"
        tampered = f"{encoded_payload}.{changed}{encoded_signature[1:]}"
        status, _headers, body = self.request(
            "GET",
            "/api/session",
            headers={"Cookie": f"{cookie_name}={tampered}"},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "authentication_required")

        now = int(time.time()) - 120
        expired_claims = {
            "csrf": "c" * 43,
            "display_name": "鉴源盾管理员",
            "exp": now + 60,
            "iat": now,
            "remember": False,
            "role": "administrator",
            "username": self.session_username,
        }
        payload_bytes = json.dumps(
            expired_claims,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        expired_payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=")
        expired_signature = hmac.new(
            self.session_secret.encode("utf-8"),
            expired_payload,
            hashlib.sha256,
        ).digest()
        expired_token = (
            expired_payload.decode("ascii")
            + "."
            + base64.urlsafe_b64encode(expired_signature).rstrip(b"=").decode("ascii")
        )
        status, _headers, _body = self.request(
            "GET",
            "/api/session",
            headers={"Cookie": f"{cookie_name}={expired_token}"},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 401)

        valid_cookie = self.cookie_pair(headers["set-cookie"])
        status, _headers, _body = self.request(
            "POST",
            "/api/session/logout",
            headers={"Cookie": valid_cookie},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 403)
        status, logout_headers, logout_body = self.request(
            "POST",
            "/api/session/logout",
            body=b"{}",
            headers={
                "Cookie": valid_cookie,
                "Content-Type": "application/json",
                "X-JYS-CSRF": document["csrf"],
            },
            authenticated_gateway=True,
        )
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(logout_body)["authenticated"])
        self.assertIn("Max-Age=0", logout_headers["set-cookie"])
        self.assertIn("Expires=Thu, 01 Jan 1970 00:00:00 GMT", logout_headers["set-cookie"])

    def test_session_json_limit_and_configuration_fail_closed(self) -> None:
        status, headers, document = self.request(
            "POST",
            "/api/session/login",
            body=b"x" * (16 * 1024 + 1),
            headers={"Content-Type": "application/json"},
            authenticated_gateway=True,
        )
        self.assertEqual(status, 413)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(json.loads(document)["error"]["code"], "request_too_large")

        password_file = self.root / "ui-password"
        secret_file = self.root / "session-secret"
        password_file.write_text(self.session_password, encoding="utf-8")
        secret_file.write_text(self.session_secret, encoding="utf-8")
        environment = {
            "JYS_GATEWAY_STATIC_ROOT": str(self.root),
            "JYS_GATEWAY_UPSTREAM": "http://127.0.0.1:8026",
            "JYS_GATEWAY_REQUIRE_UI_SESSION": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(GatewayConfigurationError):
                GatewayConfiguration.from_environment()

        environment.update(
            {
                "JYS_GATEWAY_UI_USERNAME": self.session_username,
                "JYS_GATEWAY_UI_PASSWORD_FILE": str(password_file),
                "JYS_GATEWAY_SESSION_SECRET_FILE": str(secret_file),
                "JYS_GATEWAY_SESSION_TTL_SECONDS": "60",
                "JYS_GATEWAY_REMEMBER_TTL_SECONDS": "600",
                "JYS_GATEWAY_SESSION_COOKIE_PATH": "/",
            }
        )
        with patch.dict(os.environ, environment, clear=True):
            configured = GatewayConfiguration.from_environment()
        self.assertTrue(configured.require_ui_session)
        self.assertEqual(configured.ui_username, self.session_username)
        self.assertEqual(configured.session_cookie_path, "/")

        password_file.write_text("too-short", encoding="utf-8")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(GatewayConfigurationError):
                GatewayConfiguration.from_environment()

        password_file.write_text(self.session_password, encoding="utf-8")
        secret_file.write_text("short-session-secret", encoding="utf-8")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(GatewayConfigurationError):
                GatewayConfiguration.from_environment()

    def test_development_bypass_configuration_is_fail_closed(self) -> None:
        common = {
            "static_root": self.root,
            "upstream_host": "127.0.0.1",
            "upstream_port": 8026,
            "development_ui_bypass": True,
        }
        with self.assertRaises(GatewayConfigurationError):
            GatewayConfiguration(
                **common,
                api_key="k" * 40,
            )
        with self.assertRaises(GatewayConfigurationError):
            GatewayConfiguration(
                **common,
                api_key=None,
                require_ui_session=True,
                ui_username=self.session_username,
                ui_password=self.session_password,
                session_secret=self.session_secret,
            )
        with self.assertRaises(GatewayConfigurationError):
            GatewayConfiguration(
                **common,
                api_key=None,
                ui_username=self.session_username,
            )

        environment = {
            "JYS_GATEWAY_STATIC_ROOT": str(self.root),
            "JYS_GATEWAY_UPSTREAM": "http://127.0.0.1:8026",
            "JYS_GATEWAY_REQUIRE_API_KEY": "false",
            "JYS_GATEWAY_REQUIRE_UI_SESSION": "false",
            "JYS_GATEWAY_DEVELOPMENT_UI_BYPASS": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            configured = GatewayConfiguration.from_environment()
        self.assertTrue(configured.development_ui_bypass)
        self.assertFalse(configured.require_ui_session)
        self.assertIsNone(configured.api_key)

        key_file = self.root / "development-api-key"
        key_file.write_text("k" * 40, encoding="utf-8")
        environment["JYS_GATEWAY_API_KEY_FILE"] = str(key_file)
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(GatewayConfigurationError):
                GatewayConfiguration.from_environment()

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
