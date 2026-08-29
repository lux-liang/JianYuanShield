from __future__ import annotations

import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from system.backend.app import app
from system.backend import security


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)

    def test_health_is_public_and_does_not_expose_host_root(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertNotIn("log_file", payload)
        self.assertNotIn("settings", payload)
        self.assertNotIn("root", payload)

    def test_protected_endpoint_enforces_api_key_with_uniform_error(self) -> None:
        configured = SimpleNamespace(
            require_api_key=True,
            api_key="expected-test-key",
            max_upload_bytes=security.settings.max_upload_bytes,
            max_image_pixels=security.settings.max_image_pixels,
        )
        with patch.object(security, "settings", configured):
            denied = self.client.get("/api/artifacts/status")
            allowed = self.client.get(
                "/api/artifacts/status",
                headers={"X-API-Key": "expected-test-key"},
            )
        self.assertEqual(denied.status_code, 401)
        self.assertFalse(denied.json()["ok"])
        self.assertEqual(denied.json()["error"]["path"], "/api/artifacts/status")
        self.assertEqual(denied.headers["www-authenticate"], "ApiKey")
        self.assertEqual(allowed.status_code, 200)

    def test_request_body_limit_rejects_before_multipart_parsing(self) -> None:
        configured = SimpleNamespace(
            require_api_key=False,
            api_key=None,
            max_upload_bytes=8,
            max_batch_files=2,
            request_body_timeout_seconds=30,
        )
        with patch.object(security, "settings", configured):
            response = self.client.post(
                "/api/infer/single",
                content=b"x" * (64 * 1024 + 9),
                headers={"Content-Type": "application/octet-stream"},
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "payload_too_large")
        self.assertEqual(response.json()["error"]["path"], "/api/infer/single")

    def test_api_key_is_checked_before_multipart_parsing(self) -> None:
        configured = SimpleNamespace(
            require_api_key=True,
            api_key="expected-test-key",
            max_upload_bytes=1024,
            max_batch_files=2,
            request_body_timeout_seconds=30,
        )
        with patch.object(security, "settings", configured):
            response = self.client.post(
                "/api/infer/single",
                content=b"not-a-valid-multipart-body",
                headers={"Content-Type": "multipart/form-data; boundary=x"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")
        self.assertEqual(response.headers["www-authenticate"], "ApiKey")

    def test_demo_json_body_is_bounded(self) -> None:
        response = self.client.post(
            "/api/tasks/demo-run",
            content=b"x" * (64 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "payload_too_large")

    def test_upload_content_type_mismatch_fails_before_inference(self) -> None:
        response = self.client.post(
            "/api/infer/single",
            files={"file": ("sample.jpg", png_bytes(), "image/jpeg")},
            data={"model": "SepMark", "attack": "clean"},
        )
        self.assertEqual(response.status_code, 415)
        self.assertFalse(response.json()["ok"])

    def test_compliance_endpoint_is_explicitly_unavailable(self) -> None:
        response = self.client.post(
            "/api/compliance/batch",
            files=[("files", ("sample.png", png_bytes(), "image/png"))],
            data={"model": "SepMark"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "compliance-batch.v2")
        self.assertEqual(payload["mode"], "capability_unavailable")
        self.assertFalse(payload["claim_valid"])
        self.assertFalse(payload["capability_available"])
        self.assertEqual(payload["assessed"], 0)
        self.assertIsNone(payload["compliance_rate"])


if __name__ == "__main__":
    unittest.main()
