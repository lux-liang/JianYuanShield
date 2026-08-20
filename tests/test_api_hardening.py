from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from PIL import Image

from system.backend import artifacts, demo, errors, infer, routes, security, settings as settings_module
from system.backend.utils import (
    EPHEMERAL_ARTIFACT_MARKER,
    atomic_write_json,
    create_ephemeral_artifact_directory,
)


def png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


class ApiHardeningTests(unittest.TestCase):
    def test_invalid_boolean_environment_value_is_rejected(self) -> None:
        with patch.dict(os.environ, {"JYS_TEST_BOOLEAN": "tru"}):
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                settings_module._bool_env("JYS_TEST_BOOLEAN", False)

    def test_invalid_runtime_mode_is_rejected(self) -> None:
        with patch.dict(os.environ, {"JYS_MODE": "prodution"}):
            with self.assertRaisesRegex(ValueError, "JYS_MODE must be one of"):
                settings_module._mode_env()

    def test_api_key_with_surrounding_whitespace_is_rejected(self) -> None:
        with patch.dict(os.environ, {"JYS_API_KEY": " secret"}):
            with self.assertRaisesRegex(ValueError, "surrounding whitespace"):
                settings_module._api_key_env()

    def test_api_key_can_be_loaded_from_a_bounded_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "api-key"
            secret_path.write_text("a" * 32 + "\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"JYS_API_KEY_FILE": str(secret_path)},
                clear=True,
            ):
                self.assertEqual(settings_module._api_key_env(), "a" * 32)

    def test_direct_and_file_api_keys_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "api-key"
            secret_path.write_text("b" * 32, encoding="utf-8")
            with patch.dict(
                os.environ,
                {"JYS_API_KEY": "a" * 32, "JYS_API_KEY_FILE": str(secret_path)},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                    settings_module._api_key_env()

    def test_secret_file_rejects_symlinks_oversize_and_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("a" * 32, encoding="utf-8")
            link = root / "api-key"
            link.symlink_to(target)
            with patch.dict(os.environ, {"JYS_API_KEY_FILE": str(link)}, clear=True):
                with self.assertRaisesRegex(ValueError, "cannot be read"):
                    settings_module._api_key_env()

            target.write_bytes(b"a" * 4097)
            with patch.dict(os.environ, {"JYS_API_KEY_FILE": str(target)}, clear=True):
                with self.assertRaisesRegex(ValueError, "4096 byte limit"):
                    settings_module._api_key_env()

            with patch.dict(os.environ, {"JYS_API_KEY": "a" * 32 + "\ninside"}, clear=True):
                with self.assertRaisesRegex(ValueError, "control characters"):
                    settings_module._api_key_env()

    def test_production_server_settings_require_strong_key_and_https_cors(self) -> None:
        base = {
            "mode": "production",
            "require_api_key": True,
            "api_key": "a" * 32,
            "cors_origins": ("https://console.example",),
            "cors_allow_credentials": False,
        }
        settings_module.validate_server_settings(SimpleNamespace(**base))
        for updates, message in (
            ({"api_key": "weak"}, "at least 32"),
            ({"cors_origins": ("http://console.example",)}, "must use HTTPS"),
            ({"cors_origins": ("*",)}, "wildcard"),
            ({"cors_origins": ()}, "must not be empty"),
        ):
            configured = SimpleNamespace(**{**base, **updates})
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, message):
                settings_module.validate_server_settings(configured)

    def test_display_filename_strips_both_path_styles_and_controls(self) -> None:
        self.assertEqual(
            security.safe_display_filename(
                "C:\\Users\\judge\\secret\\proof.png",
                fallback="upload.png",
            ),
            "proof.png",
        )
        self.assertEqual(
            security.safe_display_filename(
                "/home/judge/\u202ereport.png\n",
                fallback="upload.png",
            ),
            "report.png",
        )
        self.assertEqual(
            security.safe_display_filename("../", fallback="upload.png"),
            "upload.png",
        )

    def test_media_type_is_case_insensitive_and_parameters_are_ignored(self) -> None:
        payload = png_bytes()
        self.assertIs(
            security.validate_image_bytes(payload, media_type="Image/PNG; charset=binary"),
            payload,
        )

    def test_too_small_image_is_rejected_before_inference(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            security.validate_image_bytes(png_bytes((4, 8)), media_type="image/png")
        self.assertEqual(raised.exception.status_code, 422)

    def test_truncated_image_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            security.validate_image_bytes(png_bytes()[:-10], media_type="image/png")
        self.assertEqual(raised.exception.status_code, 422)

    def test_image_validation_decodes_raster_data_after_container_verification(self) -> None:
        # Pillow accepts this JPEG's container in ``verify`` but rejects its
        # truncated scan data during ``load``.
        with self.assertRaises(HTTPException) as raised:
            security.validate_image_bytes(jpeg_bytes()[:-1], media_type="image/jpeg")
        self.assertEqual(raised.exception.status_code, 422)

    def test_resolve_path_within_rejects_traversal_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "assets"
            root.mkdir()
            inside = root / "safe.png"
            inside.write_bytes(b"safe")
            outside = Path(directory) / "secret.png"
            outside.write_bytes(b"secret")
            (root / "escape.png").symlink_to(outside)
            self.assertEqual(security.resolve_path_within(root, "safe.png"), inside)
            for value in ("../secret.png", "/etc/passwd", "..\\secret.png", "escape.png"):
                with self.subTest(value=value):
                    self.assertIsNone(security.resolve_path_within(root, value))

    def test_atomic_json_rejects_nonfinite_values_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            with self.assertRaises(ValueError):
                atomic_write_json(target, {"metric": float("nan")})
            self.assertFalse(target.exists())

    def test_queue_capacity_rejects_without_waiting(self) -> None:
        async def scenario() -> None:
            with (
                patch.object(routes, "_inference_capacity", asyncio.Semaphore(0)),
                patch.object(routes, "_inference_slots", asyncio.Semaphore(1)),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await routes._run_inference(lambda: None)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(raised.exception.headers["Retry-After"], "1")

        asyncio.run(scenario())

    def test_non_ascii_wrong_api_key_returns_unauthorized(self) -> None:
        configured = SimpleNamespace(require_api_key=True, api_key="expected")
        with patch.object(security, "settings", configured):
            with self.assertRaises(HTTPException) as raised:
                security.require_api_key("错误密钥")
        self.assertEqual(raised.exception.status_code, 401)

    def test_chunked_body_limit_is_enforced_without_content_length(self) -> None:
        async def scenario() -> list[dict]:
            chunks = [
                {"type": "http.request", "body": b"a" * 40_000, "more_body": True},
                {"type": "http.request", "body": b"b" * 40_000, "more_body": False},
            ]
            sent: list[dict] = []

            async def receive() -> dict:
                return chunks.pop(0)

            async def send(message: dict) -> None:
                sent.append(message)

            async def downstream(_scope: dict, receive_body, send_body) -> None:
                while True:
                    message = await receive_body()
                    if not message.get("more_body"):
                        break
                await send_body({"type": "http.response.start", "status": 204, "headers": []})
                await send_body({"type": "http.response.body", "body": b""})

            configured = SimpleNamespace(
                max_upload_bytes=1,
                max_batch_files=1,
                request_body_timeout_seconds=30,
            )
            middleware = security.RequestBodyLimitMiddleware(downstream)
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/infer/single",
                "raw_path": b"/api/infer/single",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("test", 80),
            }
            with patch.object(security, "settings", configured):
                await middleware(scope, receive, send)
            return sent

        messages = asyncio.run(scenario())
        self.assertEqual(messages[0]["status"], 413)
        body = json.loads(messages[1]["body"])
        self.assertEqual(body["error"]["code"], "payload_too_large")

    def test_request_body_has_an_end_to_end_receive_timeout(self) -> None:
        async def scenario() -> list[dict]:
            sent: list[dict] = []
            never = asyncio.Event()

            async def receive() -> dict:
                await never.wait()
                raise AssertionError("unreachable")

            async def send(message: dict) -> None:
                sent.append(message)

            async def downstream(_scope: dict, receive_body, _send_body) -> None:
                await receive_body()

            configured = SimpleNamespace(
                max_upload_bytes=1024,
                max_batch_files=1,
                request_body_timeout_seconds=0.01,
            )
            middleware = security.RequestBodyLimitMiddleware(downstream)
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/infer/single",
                "headers": [],
            }
            with patch.object(security, "settings", configured):
                await middleware(scope, receive, send)
            return sent

        messages = asyncio.run(scenario())
        self.assertEqual(messages[0]["status"], 408)
        body = json.loads(messages[1]["body"])
        self.assertEqual(body["error"]["code"], "request_timeout")

    def test_request_concurrency_is_bounded_before_body_parsing(self) -> None:
        async def scenario() -> list[dict]:
            entered = asyncio.Event()
            release = asyncio.Event()
            sent_second: list[dict] = []

            async def downstream(_scope: dict, _receive, send) -> None:
                entered.set()
                await release.wait()
                await send({"type": "http.response.start", "status": 204, "headers": []})
                await send({"type": "http.response.body", "body": b""})

            async def receive() -> dict:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def discard(_message: dict) -> None:
                return None

            async def collect(message: dict) -> None:
                sent_second.append(message)

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/infer/single",
                "headers": [],
            }
            configured = SimpleNamespace(max_concurrent_upload_requests=1)
            with patch.object(security, "settings", configured):
                middleware = security.RequestConcurrencyMiddleware(downstream)
            first = asyncio.create_task(middleware(scope, receive, discard))
            await entered.wait()
            await middleware(scope, receive, collect)
            release.set()
            await first
            return sent_second

        messages = asyncio.run(scenario())
        self.assertEqual(messages[0]["status"], 503)
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"retry-after"], b"1")

    def test_api_rate_limit_is_enforced_per_client(self) -> None:
        async def scenario() -> tuple[list[dict], list[dict], list[dict]]:
            async def downstream(_scope: dict, _receive, send) -> None:
                await send({"type": "http.response.start", "status": 204, "headers": []})
                await send({"type": "http.response.body", "body": b""})

            async def receive() -> dict:
                return {"type": "http.request", "body": b"", "more_body": False}

            configured = SimpleNamespace(
                rate_limit_requests=1,
                rate_limit_window_seconds=60,
                max_rate_limit_clients=100,
            )
            with patch.object(security, "settings", configured):
                middleware = security.RequestRateLimitMiddleware(downstream)

            async def request(client: str) -> list[dict]:
                sent: list[dict] = []

                async def send(message: dict) -> None:
                    sent.append(message)

                await middleware(
                    {
                        "type": "http",
                        "method": "GET",
                        "path": "/api/claims",
                        "client": (client, 1),
                    },
                    receive,
                    send,
                )
                return sent

            return await request("192.0.2.1"), await request("192.0.2.1"), await request("192.0.2.2")

        first, limited, other_client = asyncio.run(scenario())
        self.assertEqual(first[0]["status"], 204)
        self.assertEqual(limited[0]["status"], 429)
        self.assertEqual(dict(limited[0]["headers"])[b"retry-after"], b"60")
        self.assertEqual(other_client[0]["status"], 204)

    def test_api_security_headers_cover_errors_and_https_hsts(self) -> None:
        async def scenario() -> list[dict]:
            sent: list[dict] = []

            async def downstream(_scope: dict, _receive, send) -> None:
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b""})

            async def receive() -> dict:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict) -> None:
                sent.append(message)

            with patch.object(security, "settings", SimpleNamespace(mode="production")):
                middleware = security.SecurityHeadersMiddleware(downstream)
                await middleware(
                    {
                        "type": "http",
                        "method": "GET",
                        "path": "/api/private",
                        "scheme": "https",
                    },
                    receive,
                    send,
                )
            return sent

        messages = asyncio.run(scenario())
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(headers[b"x-frame-options"], b"DENY")
        self.assertEqual(headers[b"strict-transport-security"], b"max-age=31536000")

    def test_low_storage_reserve_rejects_writes_before_body_parsing(self) -> None:
        async def scenario() -> tuple[list[dict], bool]:
            sent: list[dict] = []
            downstream_called = False

            async def downstream(_scope: dict, _receive, _send) -> None:
                nonlocal downstream_called
                downstream_called = True

            async def receive() -> dict:
                raise AssertionError("body must not be read when storage is below reserve")

            async def send(message: dict) -> None:
                sent.append(message)

            configured = SimpleNamespace(
                min_free_disk_bytes=100,
                artifact_write_reserve_bytes=50,
            )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with (
                    patch.object(security, "settings", configured),
                    patch.object(security, "ASSETS", root),
                    patch.object(security, "REPORTS", root),
                    patch.object(
                        security.shutil,
                        "disk_usage",
                        return_value=SimpleNamespace(free=149),
                    ),
                ):
                    middleware = security.StorageCapacityMiddleware(downstream)
                    await middleware(
                        {
                            "type": "http",
                            "method": "POST",
                            "path": "/api/infer/single",
                        },
                        receive,
                        send,
                    )
            return sent, downstream_called

        messages, downstream_called = asyncio.run(scenario())
        self.assertFalse(downstream_called)
        self.assertEqual(messages[0]["status"], 503)
        self.assertEqual(dict(messages[0]["headers"])[b"retry-after"], b"30")

    def test_degraded_health_uses_http_503_for_orchestrators(self) -> None:
        configured = SimpleNamespace(mode="production")
        with (
            patch.object(routes, "settings", configured),
            patch.object(
                routes,
                "runtime_health",
                return_value={"ok": False, "mode": "production"},
            ),
        ):
            response = routes.health()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body), {"ok": False, "mode": "production"})

    def test_queue_wait_is_included_in_end_to_end_timeout(self) -> None:
        async def scenario() -> None:
            occupied = asyncio.Semaphore(1)
            await occupied.acquire()
            capacity = asyncio.Semaphore(2)
            configured = SimpleNamespace(inference_timeout_seconds=0.01)
            called = False

            def worker() -> None:
                nonlocal called
                called = True

            with (
                patch.object(routes, "_inference_capacity", capacity),
                patch.object(routes, "_inference_slots", occupied),
                patch.object(routes, "settings", configured),
            ):
                with self.assertRaises(asyncio.TimeoutError):
                    await routes._run_inference(worker)
            self.assertFalse(called)
            self.assertEqual(capacity._value, 2)
            occupied.release()

        asyncio.run(scenario())

    def test_clean_simulation_writes_strict_json_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            configured = SimpleNamespace(
                artifact_ttl_seconds=3600,
                enable_demo=True,
                max_image_pixels=1_000_000,
            )
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(infer, "get_adapter", return_value=None),
            ):
                payload = infer.run_single_infer(
                    png_bytes(),
                    model="SepMark",
                    attack="clean",
                    return_b64=False,
                )
            self.assertIsNone(payload["metrics"]["psnr"])
            report = reports_root / f"{payload['task_id']}.json"
            parsed = json.loads(
                report.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            self.assertEqual(parsed["task_id"], payload["task_id"])
            self.assertTrue(
                (assets_root / payload["task_id"] / EPHEMERAL_ARTIFACT_MARKER).is_file()
            )
            self.assertEqual(
                stat.S_IMODE((assets_root / payload["task_id"]).stat().st_mode),
                0o700,
            )

    def test_base64_response_is_not_persisted_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            configured = SimpleNamespace(
                artifact_ttl_seconds=3600,
                enable_demo=True,
                max_image_pixels=1_000_000,
            )
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(infer, "get_adapter", return_value=None),
            ):
                payload = infer.run_single_infer(
                    png_bytes(),
                    model="SepMark",
                    attack="clean",
                    return_b64=True,
                )
            self.assertTrue(payload["artifacts_b64"]["original"])
            persisted = json.loads(
                (reports_root / f"{payload['task_id']}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["artifacts_b64"], {})
            self.assertFalse(persisted["privacy"]["base64_persisted"])

    def test_failed_report_write_removes_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            configured = SimpleNamespace(
                artifact_ttl_seconds=3600,
                enable_demo=True,
                max_image_pixels=1_000_000,
            )
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(infer, "get_adapter", return_value=None),
                patch.object(infer, "atomic_write_json", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(OSError):
                    infer.run_single_infer(png_bytes(), attack="clean", return_b64=False)
            self.assertEqual(list(assets_root.iterdir()), [])
            self.assertFalse(reports_root.exists() and any(reports_root.iterdir()))

    def test_sample_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "samples"
            samples.mkdir()
            outside = root / "outside.png"
            outside.write_bytes(png_bytes())
            (samples / "sample_face_001.png").symlink_to(outside)
            with patch.object(demo, "DATASETS", samples):
                with self.assertRaises(RuntimeError):
                    demo.ensure_sample("sample_face_001")

    def test_validation_error_details_do_not_echo_sensitive_input(self) -> None:
        exc = RequestValidationError([{
            "loc": ("body", "creator_ref"),
            "msg": "String should have at most 128 characters",
            "type": "string_too_long",
            "input": "private-creator-reference",
        }])
        rendered = json.dumps(errors._safe_validation_errors(exc))
        self.assertNotIn("private-creator-reference", rendered)
        self.assertIn("creator_ref", rendered)

    def test_expired_artifact_is_not_served(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            task_id, task_dir = create_ephemeral_artifact_directory(assets_root)
            (task_dir / "derived.png").write_bytes(png_bytes())
            reports_root.mkdir()
            (reports_root / f"{task_id}.json").write_text(
                json.dumps({"schema_version": "infer-single.v1", "task_id": task_id}),
                encoding="utf-8",
            )
            os.utime(task_dir, (1, 1))
            configured = SimpleNamespace(artifact_ttl_seconds=10)
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(routes, "ASSETS", assets_root),
            ):
                with self.assertRaises(HTTPException) as raised:
                    routes.artifact_file(f"{task_id}/derived.png")
            self.assertEqual(raised.exception.status_code, 404)
            self.assertFalse(task_dir.exists())
            self.assertFalse((reports_root / f"{task_id}.json").exists())

    def test_expired_artifact_is_denied_even_when_deletion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            task_id, task_dir = create_ephemeral_artifact_directory(assets_root)
            (task_dir / "derived.png").write_bytes(png_bytes())
            reports_root.mkdir()
            (reports_root / f"{task_id}.json").write_text(
                json.dumps({"schema_version": "infer-single.v1", "task_id": task_id}),
                encoding="utf-8",
            )
            os.utime(task_dir, (1, 1))
            configured = SimpleNamespace(artifact_ttl_seconds=10)
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(routes, "ASSETS", assets_root),
                patch.object(infer.shutil, "rmtree", side_effect=OSError("read-only")),
            ):
                with self.assertRaises(HTTPException) as raised:
                    routes.artifact_file(f"{task_id}/derived.png")
            self.assertEqual(raised.exception.status_code, 404)
            self.assertTrue(task_dir.exists())

    def test_expired_orphan_report_is_denied_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets_root = root / "assets"
            reports_root = root / "reports"
            assets_root.mkdir()
            reports_root.mkdir()
            task_id = "0123456789ab"
            report_path = reports_root / f"{task_id}.json"
            report_path.write_text(
                json.dumps({"schema_version": "infer-single.v1", "task_id": task_id}),
                encoding="utf-8",
            )
            os.utime(report_path, (1, 1))
            configured = SimpleNamespace(artifact_ttl_seconds=10)
            with (
                patch.object(infer, "ASSETS", assets_root),
                patch.object(infer, "REPORTS", reports_root),
                patch.object(infer, "settings", configured),
                patch.object(demo, "REPORTS", reports_root),
            ):
                with self.assertRaises(HTTPException) as raised:
                    routes.report(task_id)
            self.assertEqual(raised.exception.status_code, 404)
            self.assertFalse(report_path.exists())

    def test_malformed_weight_manifest_path_is_not_scanned_or_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights_root = root / "weights"
            weights_root.mkdir()
            manifest = weights_root / "WEIGHT_MANIFEST.json"
            manifest.write_text(
                json.dumps({
                    "items": [{
                        "model": "forged",
                        "file": "/etc/passwd",
                        "status": "verified",
                    }],
                }),
                encoding="utf-8",
            )
            with (
                patch.object(artifacts, "MANIFEST", manifest),
                patch.object(artifacts, "WEIGHT_ROOT", weights_root),
            ):
                payload = artifacts.artifacts_status_payload()
            item = payload["manifest"][0]
            self.assertFalse(item["path_valid"])
            self.assertEqual(item["status"], "invalid_path")
            self.assertIsNone(item["target_dir"])
            self.assertNotIn("/etc/passwd", json.dumps(item))

    def test_artifact_status_uses_only_canonical_lidmark_and_waveguard_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            lidmark = report_root / "lidmark_lfw_identity_test_epoch20_protocol_v1"
            waveguard = report_root / "waveguard_lfw_benchmark"
            lidmark.mkdir()
            waveguard.mkdir()
            (lidmark / "raw_results.csv").write_text(
                "image_id,attack_type,error\nface,clean,\n",
                encoding="utf-8",
            )
            (waveguard / "results.csv").write_text(
                "image_id,attack_type,error\nface,clean,\n",
                encoding="utf-8",
            )
            with patch.object(artifacts, "REPORTS", report_root):
                payload = artifacts.artifacts_status_payload()
            benchmarks = payload["benchmarks"]
            self.assertEqual(
                benchmarks["lidmark_lfw_eval"]["results_file"],
                "raw_results.csv",
            )
            self.assertTrue(benchmarks["lidmark_lfw_eval"]["results_csv_exists"])
            self.assertTrue(benchmarks["waveguard_lfw"]["results_csv_exists"])
            self.assertNotIn("waveguard_smoke", benchmarks)
            self.assertNotIn("waveguard_small", benchmarks)
            self.assertNotIn("waveguard_full", benchmarks)

    def test_benchmark_status_does_not_follow_evidence_file_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_root = root / "reports"
            benchmark_dir = report_root / "benchmark"
            benchmark_dir.mkdir(parents=True)
            outside_summary = root / "outside.json"
            outside_results = root / "outside.csv"
            outside_summary.write_text(
                json.dumps({"status": "complete", "mode": "host-secret"}),
                encoding="utf-8",
            )
            outside_results.write_text("image_id\nsecret\n", encoding="utf-8")
            (benchmark_dir / "summary.json").symlink_to(outside_summary)
            (benchmark_dir / "results.csv").symlink_to(outside_results)
            with patch.object(artifacts, "REPORTS", report_root):
                payload = artifacts.benchmark_status("benchmark", benchmark_dir)
            self.assertFalse(payload["ready"])
            self.assertFalse(payload["summary_exists"])
            self.assertFalse(payload["results_csv_exists"])
            self.assertEqual(payload["result_rows"], 0)
            self.assertIsNone(payload["mode"])

    def test_progress_cannot_promote_incomplete_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            benchmark_dir = report_root / "benchmark"
            benchmark_dir.mkdir(parents=True)
            (benchmark_dir / "summary.json").write_text(
                json.dumps({"status": "running"}),
                encoding="utf-8",
            )
            (benchmark_dir / "progress.json").write_text(
                json.dumps({"status": "complete"}),
                encoding="utf-8",
            )
            (benchmark_dir / "results.csv").write_text(
                "image_id,attack_type,error\nface,clean,\n",
                encoding="utf-8",
            )
            with patch.object(artifacts, "REPORTS", report_root):
                payload = artifacts.benchmark_status("benchmark", benchmark_dir)
            self.assertFalse(payload["complete"])
            self.assertEqual(payload["status"], "running")

    def test_dataset_status_does_not_count_files_outside_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_root = root / "data"
            dataset = data_root / "dataset"
            dataset.mkdir(parents=True)
            outside = root / "outside.png"
            outside.write_bytes(png_bytes())
            (dataset / "escape.png").symlink_to(outside)
            with patch.object(artifacts, "DATA_ROOT", data_root):
                payload = artifacts.dataset_status("dataset", dataset)
            self.assertTrue(payload["path_valid"])
            self.assertEqual(payload["image_count"], 0)
            self.assertFalse(payload["ready"])

    def test_formal_dataset_readiness_requires_both_signed_benchmark_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            protocol = data_root / "lfw/processed/image/lfw_128/test"
            lidmark = (
                data_root
                / "lfw/lidmark_identity_disjoint/image/lfw_128/test"
            )
            protocol.mkdir(parents=True)
            (protocol / "protocol.jpg").write_bytes(png_bytes())
            with patch.object(artifacts, "DATA_ROOT", data_root):
                incomplete = artifacts.artifacts_status_payload()
            self.assertFalse(incomplete["checks"]["formal_dataset_ready"])

            lidmark.mkdir(parents=True)
            (lidmark / "lidmark.jpg").write_bytes(png_bytes())
            with patch.object(artifacts, "DATA_ROOT", data_root):
                complete = artifacts.artifacts_status_payload()
            self.assertTrue(complete["checks"]["formal_dataset_ready"])
            self.assertTrue(complete["checks"]["dataset_ready"])


if __name__ == "__main__":
    unittest.main()
