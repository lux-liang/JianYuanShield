from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from system.backend import artifacts, benchmarks, routes
from system.backend.app import app
from system.scripts import run_waveguard_single_smoke as waveguard_smoke


class BenchmarkApiContractTests(unittest.TestCase):
    def test_models_status_prefers_only_strict_provenance_ready_model(self) -> None:
        fake_adapters = types.ModuleType("system.backend.model_adapters")

        class Adapter:
            _instance = None

            @classmethod
            def available(cls) -> bool:
                return True

        for name in ("SepMarkAdapter", "WaveGuardAdapter", "LIDMarkAdapter", "KADNetAdapter"):
            setattr(fake_adapters, name, Adapter)
        for name in ("SEPMARK", "WAVEGUARD", "LIDMARK", "KADNET"):
            setattr(fake_adapters, f"{name}_CKPT", Path(f"/{name.lower()}.pth"))
            setattr(fake_adapters, f"{name}_CKPT_SHA256", name.lower()[0] * 64)

        def status(model, *_args, **_kwargs):
            ready = model == "KAD-Net"
            return {
                "available": True,
                "loaded": False,
                "checkpoint_sha256": "a" * 64,
                "registered": ready,
                "calibrated": ready,
                "trusted": ready,
                "provenance_ready": ready,
                "verification_threshold": 0.75 if ready else None,
                "reason_codes": [] if ready else [
                    "checkpoint_unregistered",
                    "calibration_unverified",
                    "weight_manifest_untrusted",
                ],
            }

        with (
            patch.dict(sys.modules, {"system.backend.model_adapters": fake_adapters}),
            patch.object(routes, "provenance_model_status", side_effect=status),
        ):
            payload = routes.models_status()

        self.assertEqual(payload["schema_version"], "model-provenance-status.v1")
        self.assertEqual(payload["preferred_model"], "KAD-Net")
        self.assertTrue(payload["KAD-Net"]["provenance_ready"])
        self.assertFalse(payload["LIDMark"]["provenance_ready"])

    def test_mea_payload_uses_only_the_canonical_signed_n256_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            report_dir = report_root / benchmarks.MEA_RUN_ID
            report_dir.mkdir()
            (report_dir / "summary.json").write_text(
                json.dumps({
                    "schema_version": "mea-matrix-summary.v1",
                    "images_per_cell": 256,
                    "models": ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"],
                    "coverage": {"valid_rows": 4096, "complete_cells": 16},
                    "matrix": {"LIDMark": {}},
                    "markdown_table": "| source | attacker |",
                }),
                encoding="utf-8",
            )
            with (
                patch.object(benchmarks, "REPORTS", report_root),
                patch.object(
                    benchmarks,
                    "validate_mea_matrix_evidence",
                    return_value={"valid": True, "status": "verified"},
                ) as validator,
            ):
                payload = benchmarks.mea_matrix_payload()

        self.assertTrue(payload["claim_valid"])
        self.assertEqual(payload["status"], "verified")
        self.assertEqual(payload["run_id"], benchmarks.MEA_RUN_ID)
        self.assertEqual(payload["coverage"]["valid_rows"], 4096)
        validator.assert_called_once_with(
            directory=report_dir,
            require_signature=True,
        )

    def test_simswap_payload_uses_only_the_signed_real_n256_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            report_dir = report_root / benchmarks.SIMSWAP_RUN_ID
            report_dir.mkdir()
            (report_dir / "summary.json").write_text(
                json.dumps({
                    "schema_version": "simswap-lfw-robustness-summary.v1",
                    "status": "complete",
                    "run_class": "real_n256_evidence",
                    "num_pairs": 256,
                    "calibration_pairs": 64,
                    "holdout_pairs": 192,
                    "result_rows": 1024,
                    "expected_result_rows": 1024,
                    "identity_embedding_rows": 1792,
                    "expected_identity_embedding_rows": 1792,
                    "error_rows": 0,
                    "identity_overlap_count": 0,
                    "models": ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"],
                    "model_results": {
                        model: {"status": "complete"}
                        for model in ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
                    },
                    "controls": [
                        "registered_positive",
                        "unwatermarked_negative",
                        "wrong_message_negative",
                        "cross_record_negative",
                    ],
                    "engine": {
                        "engine": "SimSwap",
                        "mode": "official_release_checkpoint",
                    },
                }),
                encoding="utf-8",
            )
            signature = {
                "schema_version": "evidence-signature-status.v1",
                "verified": True,
                "signature_valid": True,
                "status": "verified",
                "profile": "release-core",
                "signer_pinned": True,
                "mismatches": [],
            }
            validation = {
                "schema_version": "simswap-lfw-evidence-status.v1",
                "valid": True,
                "status": "verified",
                "run_id": benchmarks.SIMSWAP_RUN_ID,
                "num_pairs": 256,
                "calibration_pairs": 64,
                "holdout_pairs": 192,
                "result_rows": 1024,
                "identity_embedding_rows": 1792,
                "identity_overlap_count": 0,
                "asset_count": 176,
                "signature": signature,
            }
            with (
                patch.object(benchmarks, "REPORTS", report_root),
                patch.object(
                    benchmarks,
                    "validate_simswap_lfw_evidence",
                    return_value=validation,
                ) as validator,
            ):
                payload = benchmarks.simswap_lfw_payload()

        self.assertTrue(payload["claim_valid"])
        self.assertEqual(payload["status"], "verified")
        self.assertEqual(payload["run_id"], benchmarks.SIMSWAP_RUN_ID)
        self.assertEqual(payload["scope"]["num_pairs"], 256)
        self.assertEqual(payload["scope"]["identity_overlap_count"], 0)
        self.assertEqual(payload["schema_version"], "simswap-lfw-benchmark.v1")
        self.assertEqual(payload["coverage"]["result_rows"], 1024)
        self.assertEqual(payload["coverage"]["identity_embedding_rows"], 1792)
        self.assertTrue(payload["release_gate"]["implementation_hashes_verified"])
        self.assertTrue(payload["release_gate"]["signer_pinned"])
        validator.assert_called_once_with(
            directory=report_dir,
            require_signature=True,
        )
        self.assertIn("/api/benchmark/simswap-lfw", app.openapi()["paths"])

    def test_kadnet_uses_the_common_benchmark_payload_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            report_dir = report_root / "kadnet_lfw_benchmark"
            report_dir.mkdir()
            (report_dir / "summary.json").write_text(
                json.dumps({
                    "method": "KAD-Net",
                    "status": "complete",
                    "data_type": "real_lfw_images",
                    "attacks": {},
                }),
                encoding="utf-8",
            )
            (report_dir / "progress.json").write_text(
                json.dumps({"status": "complete", "processed_images": 1}),
                encoding="utf-8",
            )
            (report_dir / "results.csv").write_text(
                "image_id,attack_type,bit_accuracy\nface,clean,1.0\n",
                encoding="utf-8",
            )
            with (
                patch.object(benchmarks, "REPORTS", report_root),
                patch.object(
                    benchmarks,
                    "benchmark_claim_status",
                    return_value={"claim_valid": False, "claim_status": "fixture"},
                ),
            ):
                payload = benchmarks.kadnet_benchmark_payload()

        self.assertEqual(payload["method"], "KAD-Net")
        self.assertEqual(payload["checkpoint_type"], "official_epoch100_strict")
        self.assertEqual(payload["data_type"], "real_lfw_images")
        self.assertEqual(payload["progress"]["processed_images"], 1)
        self.assertTrue(payload["results_csv_exists"])
        self.assertEqual(len(payload["sample_results"]), 1)
        self.assertIn("normalized", payload)
        self.assertEqual(payload["claim_status"], "fixture")

    def test_lidmark_canonical_and_legacy_routes_share_one_payload(self) -> None:
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/benchmark/lidmark", paths)
        self.assertIn("/api/benchmark/lidmark-lfw-eval", paths)
        expected = {"method": "LIDMark", "status": "fixture"}
        with patch.object(routes, "lidmark_lfw_eval_payload", return_value=expected):
            self.assertIs(routes.lidmark_benchmark(), expected)
            self.assertIs(routes.lidmark_lfw_eval(), expected)

    def test_aggregate_asset_references_use_the_canonical_filename(self) -> None:
        with patch.object(benchmarks, "asset_if_exists", side_effect=lambda value: value):
            aggregate = benchmarks.aggregate_benchmark_payload()
            modules = benchmarks.modules_payload()
        canonical = "aggregate_real_benchmarks/attack_degradation.png"
        self.assertEqual(aggregate["degradation_curve"], canonical)
        self.assertTrue(any(item.get("sample") == canonical for item in modules))

        with tempfile.TemporaryDirectory() as directory:
            asset_root = Path(directory)
            image = asset_root / "aggregate_real_benchmarks/attack_degradation.png"
            image.parent.mkdir()
            image.write_bytes(b"png-fixture")
            with patch.object(artifacts, "ASSETS", asset_root):
                payload = artifacts.artifacts_status_payload()
        degradation = payload["assets"]["degradation_curve"]
        self.assertTrue(degradation["ready"])
        self.assertEqual(
            degradation["relative_path"],
            "system/assets/aggregate_real_benchmarks/attack_degradation.png",
        )

    def test_waveguard_smoke_output_is_isolated_from_formal_benchmark(self) -> None:
        self.assertEqual(
            waveguard_smoke.REPORT.relative_to(waveguard_smoke.REPORT_ROOT),
            Path("smoke/waveguard_single/single_smoke.json"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "reports/smoke/waveguard_single/single_smoke.json"
            formal_summary = root / "reports/waveguard_lfw_benchmark/summary.json"
            formal_summary.parent.mkdir(parents=True)
            formal_summary.write_text('{"status":"complete"}\n', encoding="utf-8")
            with patch.object(waveguard_smoke, "REPORT", target):
                waveguard_smoke.write_report({"status": "single_smoke_ok"})
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["status"],
                "single_smoke_ok",
            )
            self.assertEqual(
                json.loads(formal_summary.read_text(encoding="utf-8"))["status"],
                "complete",
            )


if __name__ == "__main__":
    unittest.main()
