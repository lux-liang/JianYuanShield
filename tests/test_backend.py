from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from system.backend.app import app
from system.backend.artifacts import artifacts_status_payload
from system.backend.benchmarks import (
    _artifact_claim_status,
    aggregate_benchmark_payload,
    hidden_lfw_full_payload,
    modules_payload,
)
from system.backend.claims import claims_payload
from system.backend.errors import http_exception_handler, validation_exception_handler
from system.backend.evidence import evidence_audit_payload
from system.backend.normalization import BENCHMARK_SCHEMA_VERSION, normalize_benchmark
from system.backend.routes import health
from system.backend import routes
from system.backend import benchmark_evidence
from system.evaluation import runtime as evaluation_runtime
from system.backend.settings import settings
from scripts.create_release_snapshot import build_snapshot


class BackendSmokeTests(unittest.TestCase):
    def test_waveguard_identity_dataset_manifest_is_structurally_audited(self) -> None:
        files = [
            {
                "path": "test/Alice_0001.jpg",
                "size_bytes": 10,
                "sha256": "a" * 64,
                "identity_sha256": "b" * 64,
            }
        ]
        distribution = [{"identity_sha256": "b" * 64, "image_count": 1}]
        payload = {
            "schema_version": "waveguard-dataset-manifest.v1",
            "sample_count": 1,
            "files": files,
            "files_digest_sha256": benchmark_evidence._canonical_sha256(files),
            "unique_identity_count": 1,
            "identity_distribution": distribution,
            "identity_distribution_sha256": benchmark_evidence._canonical_sha256(distribution),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dataset_manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(benchmark_evidence._load_dataset_manifest(path, 1))
            payload["identity_distribution"][0]["image_count"] = 2
            payload["identity_distribution_sha256"] = benchmark_evidence._canonical_sha256(
                payload["identity_distribution"]
            )
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(benchmark_evidence._load_dataset_manifest(path, 1))

    def test_app_imports_and_registers_core_routes(self) -> None:
        paths = set(app.openapi()["paths"])
        self.assertEqual(app.title, "JianYuanShield Active Forensics Platform")
        self.assertIn("/api/health", paths)
        self.assertIn("/api/system/gpu", paths)
        self.assertIn("/api/artifacts/status", paths)
        self.assertIn("/api/artifacts/{artifact_path}", paths)
        self.assertIn("/api/benchmark/aggregate", paths)
        self.assertIn("/api/competition-report", paths)
        self.assertIn("/api/evidence/audit", paths)
        self.assertIn("/api/evidence/signature", paths)
        self.assertIn("/api/evidence/signature/download/{file_name}", paths)
        self.assertIn("/api/competition-report/download/{format_name}", paths)
        self.assertIn("/api/provenance/protect", paths)
        self.assertIn("/api/provenance/verify", paths)
        self.assertIn("/api/collaboration/recommend", paths)
        self.assertIn("/api/claims", paths)
        self.assertIn("/api/benchmark/simswap-lfw", paths)

    def test_public_health_is_minimal(self) -> None:
        payload = health()
        self.assertTrue(payload["ok"])
        self.assertIn("version", payload)
        self.assertNotIn("started_at", payload)
        self.assertNotIn("uptime_seconds", payload)
        self.assertNotIn("log_file", payload)
        self.assertNotIn("settings", payload)
        self.assertNotIn("modules", payload)
        self.assertNotIn("root", payload)

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

    def test_timed_out_worker_keeps_inference_slot_until_it_exits(self) -> None:
        async def scenario() -> None:
            gate = asyncio.Event()

            async def fake_threadpool(_callable):
                await gate.wait()
                return "finished"

            semaphore = asyncio.Semaphore(1)
            configured = SimpleNamespace(inference_timeout_seconds=0.01)
            with (
                patch.object(routes, "_inference_slots", semaphore),
                patch.object(routes, "run_in_threadpool", fake_threadpool),
                patch.object(routes, "settings", configured),
            ):
                with self.assertRaises(asyncio.TimeoutError):
                    await routes._run_inference(lambda: None)
                self.assertTrue(semaphore.locked())

                queued = asyncio.create_task(routes._run_inference(lambda: None))
                await asyncio.sleep(0)
                self.assertFalse(queued.done())
                gate.set()
                self.assertEqual(await queued, "finished")

        asyncio.run(scenario())

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
        rendered = json.dumps(modules)
        self.assertNotIn("99.97", rendered)
        self.assertNotIn("all real checkpoints", rendered)

    def test_benchmark_claim_gate_requires_reproducibility_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root / "weights"
            data = root / "data"
            reports = root / "reports"
            configs = root / "configs"
            for path in (weights, data, reports, configs):
                path.mkdir()
            checkpoint = weights / "model.pth"
            checkpoint.write_bytes(b"checkpoint")
            protocol = configs / "protocol.json"
            protocol.write_text(
                json.dumps({
                    "schema_version": "evaluation_protocol.v1",
                    "seed": 1,
                    "success_threshold": 0.9,
                    "attack_ids": ["clean"],
                    "attacks": [
                        {"id": "clean", "type": "identity", "parameters": {}}
                    ],
                }) + "\n",
                encoding="utf-8",
            )
            dataset = data / "dataset_manifest.json"
            dataset_files = [
                {
                    "path": "face.jpg",
                    "size_bytes": 4,
                    "sha256": "f" * 64,
                    "message_sha256": "b" * 64,
                }
            ]
            dataset.write_text(json.dumps({
                "schema_version": "dataset-manifest.v1",
                "sample_count": 1,
                "files": dataset_files,
                "files_digest_sha256": hashlib.sha256(json.dumps(
                    dataset_files,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest(),
            }), encoding="utf-8")
            results = reports / "results.csv"
            quality = reports / "watermarked_quality.csv"
            source_manifest = reports / "source_manifest.json"
            checkpoint_manifest = reports / "checkpoint_manifest.json"
            environment_manifest = reports / "environment.json"
            context_hashes = reports / "hashes.sha256"
            summary_path = reports / "summary.json"
            incomplete = _artifact_claim_status(
                {"status": "complete", "num_images": 1},
                summary_path,
                results,
            )
            self.assertFalse(incomplete["claim_valid"])
            results.write_text(
                "image_id,source_path,attack_type,attack_config_sha256,message_sha256,"
                "bit_error,bit_accuracy,psnr,ssim,success,error\n"
                f"face.jpg,face.jpg,clean,{benchmark_evidence.ATTACKS['clean'].config_hash},"
                f"{'b' * 64},0.0,1.0,40.0,0.99,1,\n",
                encoding="utf-8",
            )
            quality.write_text(
                "image_id,source_path,message_sha256,watermarked_psnr,watermarked_ssim,error\n"
                f"face.jpg,face.jpg,{'b' * 64},40.0,0.99,\n",
                encoding="utf-8",
            )
            source_manifest.write_text('{"schema_version":"source-manifest.v1"}\n', encoding="utf-8")
            checkpoint_manifest.write_text(
                '{"schema_version":"checkpoint-manifest.v1"}\n',
                encoding="utf-8",
            )
            environment_manifest.write_text(
                '{"schema_version":"environment-manifest.v1"}\n',
                encoding="utf-8",
            )
            context_hashes.write_text("context\n", encoding="utf-8")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            summary = {
                "schema_version": "benchmark-summary.v2",
                "status": "complete",
                "num_images": 1,
                "sample_count": 1,
                "seed": 1,
                "method": "KAD-Net",
                "attack_ids": ["clean"],
                "attacks": {
                    "clean": {
                        "status": "complete",
                        "count": 1,
                        "valid_count": 1,
                        "error_count": 0,
                        "mean_bit_error": 0.0,
                        "mean_bit_accuracy": 1.0,
                        "mean_psnr": 40.0,
                        "mean_ssim": 0.99,
                        "success_rate": 1.0,
                    }
                },
                "watermarked_quality": {
                    "status": "complete",
                    "count": 1,
                    "valid_count": 1,
                    "error_count": 0,
                    "missing_count": 0,
                    "mean_psnr": 40.0,
                    "mean_ssim": 0.99,
                    "csv_path": "reports/watermarked_quality.csv",
                    "csv_sha256": digest(quality),
                },
                "watermarked_quality_csv_path": "reports/watermarked_quality.csv",
                "watermarked_quality_csv_sha256": digest(quality),
                "source_manifest_path": "reports/source_manifest.json",
                "source_manifest_sha256": digest(source_manifest),
                "checkpoint_manifest_path": "reports/checkpoint_manifest.json",
                "checkpoint_manifest_sha256": digest(checkpoint_manifest),
                "environment_path": "reports/environment.json",
                "environment_sha256": digest(environment_manifest),
                "experiment_context_hashes_path": "reports/hashes.sha256",
                "experiment_context_hashes_sha256": digest(context_hashes),
                "checkpoint": "weights/model.pth",
                "checkpoint_sha256": digest(checkpoint),
                "dataset_manifest_path": "data/dataset_manifest.json",
                "dataset_manifest_sha256": digest(dataset),
                "results_csv_path": "reports/results.csv",
                "results_csv_sha256": digest(results),
                "protocol_version": "evaluation_protocol.v1",
                "protocol_path": "configs/protocol.json",
                "protocol_sha256": digest(protocol),
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            evidence_manifest = reports / "manifest.json"
            evidence_manifest.write_text(json.dumps({
                "profile": "release",
                "files": [
                    {"path": path, "sha256": digest(actual)}
                    for path, actual in (
                        ("reports/summary.json", summary_path),
                        ("reports/results.csv", results),
                        ("reports/watermarked_quality.csv", quality),
                        ("reports/source_manifest.json", source_manifest),
                        ("reports/checkpoint_manifest.json", checkpoint_manifest),
                        ("reports/environment.json", environment_manifest),
                        ("reports/hashes.sha256", context_hashes),
                        ("weights/model.pth", checkpoint),
                        ("data/dataset_manifest.json", dataset),
                        ("configs/protocol.json", protocol),
                    )
                ],
            }), encoding="utf-8")
            signer_fingerprint = "c" * 64
            with (
                patch.object(evaluation_runtime, "PROJECT_ROOT", root),
                patch.object(evaluation_runtime, "WEIGHT_ROOT", weights),
                patch.object(evaluation_runtime, "DATA_ROOT", data),
                patch.object(evaluation_runtime, "REPORT_ROOT", reports),
                patch.object(benchmark_evidence, "MANIFEST_PATH", evidence_manifest),
                patch.object(benchmark_evidence, "settings", SimpleNamespace(evidence_public_key_fingerprint=signer_fingerprint)),
                patch.object(benchmark_evidence, "verify_evidence_bundle", return_value={
                    "verified": True,
                    "status": "verified",
                    "public_key_fingerprint_sha256": signer_fingerprint,
                }),
            ):
                complete = _artifact_claim_status(summary, summary_path, results)
            self.assertTrue(complete["claim_valid"])
            results.write_text("image_id,attack_type,error\nface,clean,tampered\n", encoding="utf-8")
            with (
                patch.object(evaluation_runtime, "PROJECT_ROOT", root),
                patch.object(evaluation_runtime, "WEIGHT_ROOT", weights),
                patch.object(evaluation_runtime, "DATA_ROOT", data),
                patch.object(evaluation_runtime, "REPORT_ROOT", reports),
                patch.object(benchmark_evidence, "MANIFEST_PATH", evidence_manifest),
                patch.object(benchmark_evidence, "settings", SimpleNamespace(evidence_public_key_fingerprint=signer_fingerprint)),
                patch.object(benchmark_evidence, "verify_evidence_bundle", return_value={
                    "verified": True,
                    "status": "verified",
                    "public_key_fingerprint_sha256": signer_fingerprint,
                }),
            ):
                tampered = _artifact_claim_status(summary, summary_path, results)
            self.assertFalse(tampered["claim_valid"])
            self.assertFalse(tampered["evidence_requirements"]["results_identity"])

    def test_raw_claim_gate_recomputes_metrics_success_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results.csv"
            header = (
                "image_id,source_path,attack_type,attack_config_sha256,message_sha256,"
                "bit_error,bit_accuracy,psnr,ssim,success,error\n"
            )
            results.write_text(
                header
                + f"a,a.jpg,clean,{'a' * 64},{'c' * 64},0.0,1.0,40.0,0.99,1,\n"
                + f"b,b.jpg,clean,{'a' * 64},{'d' * 64},0.2,0.8,30.0,0.90,0,\n",
                encoding="utf-8",
            )
            summary = {
                "method": "KAD-Net",
                "attacks": {
                    "clean": {
                        "status": "complete",
                        "count": 2,
                        "valid_count": 2,
                        "error_count": 0,
                        "mean_bit_error": 0.1,
                        "mean_bit_accuracy": 0.9,
                        "mean_psnr": 35.0,
                        "mean_ssim": 0.945,
                        "success_rate": 0.5,
                    }
                },
            }
            valid, audit = benchmark_evidence._csv_structure_valid(
                results,
                sample_count=2,
                attack_ids=["clean"],
                summary=summary,
                success_threshold=0.9,
            )
            self.assertTrue(valid, audit)

            altered_summary = json.loads(json.dumps(summary))
            altered_summary["attacks"]["clean"]["mean_bit_accuracy"] = 0.99
            valid, audit = benchmark_evidence._csv_structure_valid(
                results,
                sample_count=2,
                attack_ids=["clean"],
                summary=altered_summary,
                success_threshold=0.9,
            )
            self.assertFalse(valid)
            self.assertIn(
                "clean:mean_bit_accuracy",
                " ".join(audit["summary_mismatches"]),
            )

            results.write_text(
                header
                + f"a,a.jpg,clean,{'a' * 64},{'c' * 64},0.0,1.0,40.0,0.99,0,\n"
                + f"b,b.jpg,clean,{'a' * 64},{'d' * 64},0.2,0.8,30.0,0.90,0,\n",
                encoding="utf-8",
            )
            valid, audit = benchmark_evidence._csv_structure_valid(
                results,
                sample_count=2,
                attack_ids=["clean"],
                summary=summary,
                success_threshold=0.9,
            )
            self.assertFalse(valid)
            self.assertGreater(audit["success_errors"], 0)

    def test_evidence_audit_shape(self) -> None:
        payload = evidence_audit_payload()
        self.assertEqual(payload["schema_version"], "evidence-audit.v1")
        self.assertIn(payload["status"], {"verified", "review_required"})
        self.assertIn("ready_for_demo", payload)
        self.assertIn("ready_for_claims", payload)
        self.assertIn("blocking_findings", payload)
        self.assertIn("signature", payload)
        self.assertIn("integration_gates", payload)
        self.assertIn("protocol", payload)
        self.assertIn("findings", payload)
        self.assertIn("evidence_files", payload)
        self.assertIn("claims", payload)

    def test_claims_manifest_is_machine_readable_and_fail_closed(self) -> None:
        payload = claims_payload()
        self.assertEqual(payload["schema_version"], "claims-status.v1")
        self.assertGreaterEqual(payload["summary"]["total"], 5)
        self.assertFalse(payload["ready_for_claims"])
        self.assertGreater(payload["summary"]["blocked_required"], 0)

    def test_invalid_claims_manifest_fails_closed(self) -> None:
        from system.backend import claims
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "claims.json"
            invalid.write_text("not-json", encoding="utf-8")
            with patch.object(claims, "CLAIMS_MANIFEST", invalid):
                payload = claims.claims_payload()
        self.assertEqual(payload["status"], "manifest_invalid")
        self.assertFalse(payload["ready_for_claims"])

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
        self.assertEqual(normalized["evaluation_protocol"], "evaluation_protocol.v1")
        self.assertIn("ber", normalized["metric_semantics"])

    def test_normalize_lidmark_preserves_row_count_and_wilson_interval(self) -> None:
        normalized = normalize_benchmark(
            summary={
                "method": "LIDMark",
                "status": "complete",
                "sample_count": 1324,
                "attacks": {
                    "clean": {
                        "status": "complete",
                        "row_count": 1324,
                        "mean_ber": 0.01,
                        "success_rate_wilson95": {
                            "successes": 1300,
                            "total": 1324,
                            "lower": 0.97,
                            "upper": 0.99,
                        },
                    }
                },
            },
            progress={},
            method="LIDMark",
            checkpoint_type="selected_epoch20_identity_disjoint",
            data_type="lfw_identity_disjoint_test",
            results_csv_exists=True,
        )
        self.assertEqual(normalized["num_images"], 1324)
        attack = normalized["attacks"][0]
        self.assertEqual(attack["count"], 1324)
        self.assertEqual(
            attack["metrics"]["success_rate_wilson95"]["successes"],
            1300,
        )


if __name__ == "__main__":
    unittest.main()
