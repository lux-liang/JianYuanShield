from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

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
