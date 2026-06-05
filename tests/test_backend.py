from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from system.backend.app import app
from system.backend.artifacts import artifacts_status_payload
from system.backend.benchmarks import aggregate_benchmark_payload, hidden_lfw_full_payload, modules_payload
from system.backend.errors import http_exception_handler, validation_exception_handler
from system.backend.normalization import BENCHMARK_SCHEMA_VERSION, normalize_benchmark
from system.backend.routes import health
from system.backend.settings import settings
from scripts.create_release_snapshot import build_snapshot


class BackendSmokeTests(unittest.TestCase):
    def test_app_imports_and_registers_core_routes(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertEqual(app.title, "VPSG Deepfake Active Forensics Competition System")
        self.assertIn("/api/health", paths)
        self.assertIn("/api/artifacts/status", paths)
        self.assertIn("/api/benchmark/aggregate", paths)
        self.assertIn("/api/competition-report", paths)

    def test_health_includes_runtime_fields(self) -> None:
        payload = health()
        self.assertTrue(payload["ok"])
        self.assertIn("version", payload)
        self.assertIn("started_at", payload)
        self.assertIn("uptime_seconds", payload)
        self.assertIn("log_file", payload)
        self.assertIn("settings", payload)
        self.assertEqual(payload["modules"]["backend"], "ok")
        self.assertEqual(payload["settings"]["enable_demo"], settings.enable_demo)

    def test_default_settings_shape(self) -> None:
        self.assertTrue(settings.version)
        self.assertTrue(settings.mode)
        self.assertTrue(settings.log_level)
        self.assertIsInstance(settings.enable_demo, bool)

    def test_exception_handlers_are_registered(self) -> None:
        self.assertIn(StarletteHTTPException, app.exception_handlers)
        self.assertIn(RequestValidationError, app.exception_handlers)
        self.assertIn(Exception, app.exception_handlers)

    def test_http_exception_handler_uses_uniform_error_shape(self) -> None:
        request = SimpleNamespace(url=SimpleNamespace(path="/api/reports/not-a-real-report"))
        response = asyncio.run(http_exception_handler(request, StarletteHTTPException(status_code=404, detail="report not found")))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["path"], "/api/reports/not-a-real-report")

    def test_validation_exception_handler_uses_uniform_error_shape(self) -> None:
        request = SimpleNamespace(url=SimpleNamespace(path="/api/tasks/demo-run"))
        exc = RequestValidationError([{"loc": ("body",), "msg": "Field required", "type": "missing"}])
        response = asyncio.run(validation_exception_handler(request, exc))
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertEqual(payload["error"]["path"], "/api/tasks/demo-run")
        self.assertIn("details", payload["error"])

    def test_release_snapshot_shape(self) -> None:
        snapshot = build_snapshot()
        self.assertEqual(snapshot["schema_version"], "release_snapshot.v1")
        self.assertIn("git", snapshot)
        self.assertIn("runtime", snapshot)
        self.assertIn("artifacts", snapshot)
        self.assertIn("reports", snapshot)
        self.assertIn("ready_for_demo", snapshot["artifacts"])

    def test_artifacts_status_shape(self) -> None:
        payload = artifacts_status_payload()
        self.assertIn("ready_for_demo", payload)
        self.assertIn("checks", payload)
        self.assertIn("datasets", payload)
        self.assertIn("weights", payload)
        self.assertIn("benchmarks", payload)
        self.assertIn("reports", payload)
        self.assertIsInstance(payload["missing"], list)

    def test_benchmark_payloads_are_missing_tolerant(self) -> None:
        hidden = hidden_lfw_full_payload()
        aggregate = aggregate_benchmark_payload()
        self.assertIn("summary", hidden)
        self.assertIn("progress", hidden)
        self.assertIn("results_csv_exists", hidden)
        self.assertIn("normalized", hidden)
        self.assertEqual(hidden["normalized"]["schema_version"], BENCHMARK_SCHEMA_VERSION)
        self.assertIn("comparison", aggregate)
        self.assertIsInstance(aggregate["comparison"], list)

    def test_modules_payload_shape(self) -> None:
        modules = modules_payload()
        self.assertGreaterEqual(len(modules), 6)
        for item in modules:
            self.assertIn("name", item)
            self.assertIn("function", item)
            self.assertIn("result", item)

    def test_normalize_benchmark_maps_attacks_to_stable_shape(self) -> None:
        normalized = normalize_benchmark(
            summary={
                "method": "SepMark",
                "mode": "real_checkpoint",
                "status": "complete",
                "num_images": 12,
                "attacks": {
                    "clean": {
                        "status": "complete",
                        "count": 12,
                        "mean_bit_error": 0.01,
                        "mean_bit_accuracy": "0.99",
                    }
                },
            },
            progress={},
            method="SepMark",
            checkpoint_type="official",
            data_type="lfw",
            results_csv_exists=True,
        )
        self.assertEqual(normalized["schema_version"], BENCHMARK_SCHEMA_VERSION)
        self.assertEqual(normalized["method"], "SepMark")
        self.assertEqual(normalized["status"], "complete")
        self.assertEqual(normalized["num_images"], 12)
        self.assertEqual(normalized["attacks"][0]["attack"], "clean")
        self.assertEqual(normalized["attacks"][0]["metrics"]["mean_bit_accuracy"], 0.99)


if __name__ == "__main__":
    unittest.main()
