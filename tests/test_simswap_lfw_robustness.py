from __future__ import annotations

import argparse
import builtins
import csv
import hashlib
import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from system.backend.simswap_evidence import validate_simswap_lfw_evidence
from system.scripts import run_simswap_lfw_robustness as benchmark


class _FakeSimSwapEngine:
    identity_dim = 512

    def __init__(self) -> None:
        self.swap_calls = 0
        self.provenance = {
            "engine": "SimSwap",
            "mode": "official_release_checkpoint",
            "source_path": "model-sources/SimSwap",
            "source_commit": benchmark.SIMSWAP_COMMIT,
            "source_tree": benchmark.SIMSWAP_TREE,
            "source_tracked_file_count": 147,
            "source_tracked_files_sha256": benchmark.SIMSWAP_TRACKED_FILES_SHA256,
            "checkpoint_archive_path": "weights/SimSwap/downloads/checkpoints.zip",
            "checkpoint_archive_sha256": benchmark.CHECKPOINT_ARCHIVE_SHA256,
            "generator_archive_member": benchmark.GENERATOR_ARCHIVE_MEMBER,
            "generator_checkpoint_path": "weights/SimSwap/checkpoints/people/latest_net_G.pth",
            "generator_checkpoint_sha256": benchmark.GENERATOR_SHA256,
            "arcface_checkpoint_path": "weights/SimSwap/downloads/arcface_checkpoint.tar",
            "arcface_checkpoint_sha256": benchmark.ARCFACE_SHA256,
            "generator_load_policy": "weights_only_true_after_exact_sha256",
            "arcface_load_policy": (
                "weights_only_false_after_exact_official_sha256_allowlist"
            ),
            "input_size": 224,
            "identity_embedding_dim": self.identity_dim,
        }

    def swap(self, source: np.ndarray, target: np.ndarray) -> np.ndarray:
        self.swap_calls += 1
        source_224 = benchmark._resize_rgb(source)
        target_224 = benchmark._resize_rgb(target)
        mixed = np.clip(
            source_224.astype(np.float32) * 0.75
            + target_224.astype(np.float32) * 0.25,
            0,
            255,
        ).astype(np.uint8)
        # Preserve the test watermark's LSB channel across the fake swap.
        source_bits = target.reshape(-1, 3)[:, 0] & 1
        output_pixels = mixed.reshape(-1, 3)
        limit = min(source_bits.size, output_pixels.shape[0])
        output_pixels[:limit, 0] = (
            output_pixels[:limit, 0] & np.uint8(0xFE)
        ) | source_bits[:limit]
        return mixed

    def identity_embedding(self, image: np.ndarray) -> np.ndarray:
        value = image.astype(np.float64)
        vector = np.zeros(self.identity_dim, dtype=np.float32)
        vector[:3] = value.mean(axis=(0, 1)) / 255.0
        vector[3:6] = value.std(axis=(0, 1)) / 255.0
        vector[6] = 1.0
        vector /= np.linalg.norm(vector)
        return vector


class _FakeWatermarkAdapter:
    def __init__(self, name: str, length: int, decoder: str, *, fail: bool = False) -> None:
        self.name = name
        self.message_length = length
        self.decoder = decoder
        self.fail = fail

    def encode(self, image: np.ndarray, message: np.ndarray) -> SimpleNamespace:
        if self.fail:
            raise RuntimeError("injected adapter failure")
        encoded = image.copy()
        pixels = encoded.reshape(-1, 3)
        pixels[: self.message_length, 0] = (
            pixels[: self.message_length, 0] & np.uint8(0xFE)
        ) | message.astype(np.uint8)
        return SimpleNamespace(
            image=encoded,
            message=message.copy(),
            metadata={"model": self.name},
        )

    def decode(self, image: np.ndarray) -> SimpleNamespace:
        pixels = image.reshape(-1, 3)
        bits = (pixels[: self.message_length, 0] & 1).astype(np.uint8)
        return SimpleNamespace(
            bits=bits,
            metadata={"primary_decoder": self.decoder},
        )


class SimSwapLfwRobustnessTests(unittest.TestCase):
    def _fixture(self, root: Path, *, fail_model: str | None = None):
        image_root = root / "lfw"
        image_root.mkdir()
        for index in range(10):
            identity = f"Person_{index:02d}"
            directory = image_root / identity
            directory.mkdir()
            base = 30 + index * 18
            image = np.empty((24, 24, 3), dtype=np.uint8)
            image[..., 0] = base
            image[..., 1] = base + 2
            image[..., 2] = base + 4
            Image.fromarray(image).save(directory / f"{identity}_0001.png")

        checkpoints = root / "checkpoints"
        checkpoints.mkdir()
        lengths = {
            "LIDMark": 16,
            "KAD-Net": 30,
            "SepMark": 128,
            "WaveGuard": 30,
        }
        decoders = {
            "LIDMark": "FHD_id_head",
            "KAD-Net": "ST_Decoder_C",
            "SepMark": "decoder_C",
            "WaveGuard": "tracer",
        }
        bindings: dict[str, benchmark.WatermarkBinding] = {}
        for model in benchmark.MODEL_ORDER:
            path = checkpoints / f"{model}.pth"
            path.write_bytes(f"fixture-{model}".encode("utf-8"))
            adapter = _FakeWatermarkAdapter(
                model,
                lengths[model],
                decoders[model],
                fail=model == fail_model,
            )
            bindings[model] = benchmark.WatermarkBinding(
                name=model,
                adapter=adapter,
                message_length=lengths[model],
                checkpoint_path=path,
                checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                primary_decoder=decoders[model],
            )
        args = argparse.Namespace(
            num_pairs=4,
            calibration_pairs=2,
            image_root=image_root,
            simswap_source=root / "unused-source",
            arcface_checkpoint=root / "unused-arcface",
            checkpoint_archive=root / "unused-archive",
            generator_checkpoint=root / "unused-generator",
            report_dir=root / "reports",
            asset_dir=root / "assets",
            device="cpu",
            seed=20260603,
            artifact_limit=1,
            flush_every=2,
        )
        return args, bindings

    def _run(
        self,
        args: argparse.Namespace,
        engine: _FakeSimSwapEngine,
        bindings: dict[str, benchmark.WatermarkBinding],
    ) -> int:
        with (
            mock.patch.object(benchmark, "parse_args", return_value=args),
            mock.patch.object(benchmark, "build_simswap_engine", return_value=engine),
            mock.patch.object(
                benchmark, "build_watermark_bindings", return_value=bindings
            ),
            mock.patch("builtins.print"),
        ):
            return benchmark.main()

    @staticmethod
    def _validate_evidence(
        args: argparse.Namespace,
        bindings: dict[str, benchmark.WatermarkBinding],
        *,
        require_signature: bool = False,
    ) -> dict:
        return validate_simswap_lfw_evidence(
            directory=args.report_dir,
            asset_directory=args.asset_dir,
            dataset_root=args.image_root,
            checkpoint_paths={
                model: binding.checkpoint_path for model, binding in bindings.items()
            },
            num_pairs=args.num_pairs,
            calibration_pairs=args.calibration_pairs,
            artifact_limit=args.artifact_limit,
            require_signature=require_signature,
            enforce_canonical_runtime=False,
        )

    def test_content_addressed_pairing_is_deterministic_and_identity_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, _ = self._fixture(root)
            first = benchmark.select_content_addressed_pairs(
                args.image_root, num_pairs=4, calibration_pairs=2, seed=args.seed
            )
            second = benchmark.select_content_addressed_pairs(
                args.image_root, num_pairs=4, calibration_pairs=2, seed=args.seed
            )
            self.assertEqual(first, second)
            self.assertEqual(first["identity_overlap_count"], 0)
            calibration = {
                identity
                for pair in first["pairs"]
                if pair["split"] == "calibration"
                for identity in (pair["source_identity"], pair["target_identity"])
            }
            holdout = {
                identity
                for pair in first["pairs"]
                if pair["split"] == "holdout"
                for identity in (pair["source_identity"], pair["target_identity"])
            }
            self.assertFalse(calibration & holdout)
            self.assertEqual(len(calibration | holdout), 8)
            self.assertTrue(
                all(pair["source_identity"] != pair["target_identity"] for pair in first["pairs"])
            )

    def test_fake_engine_writes_complete_four_model_control_evidence_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root)
            engine = _FakeSimSwapEngine()
            self.assertEqual(self._run(args, engine, bindings), 0)
            first_swap_calls = engine.swap_calls
            # Four clean swaps plus four watermarked swaps per pair.
            self.assertEqual(first_swap_calls, args.num_pairs * 5)

            summary = json.loads(
                (args.report_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["result_rows"], 16)
            self.assertEqual(summary["identity_embedding_rows"], 28)
            self.assertEqual(summary["identity_overlap_count"], 0)
            self.assertEqual(summary["run_class"], "custom_real_run")
            for model in benchmark.MODEL_ORDER:
                model_summary = summary["model_results"][model]
                self.assertEqual(model_summary["calibration"]["positive_count"], 2)
                self.assertEqual(model_summary["calibration"]["negative_count"], 6)
                self.assertEqual(model_summary["holdout"]["tar"]["total"], 2)
                self.assertEqual(model_summary["holdout"]["far"]["total"], 6)
                self.assertIn("wilson_95_low", model_summary["holdout"]["frr"])

            with (args.report_dir / "results.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 16)
            self.assertTrue(all(not row["error"] for row in rows))
            self.assertTrue(all(row["source_identity"] != row["target_identity"] for row in rows))
            self.assertTrue(all(row["registry_record_sha256"] for row in rows))
            self.assertTrue(all(row["cross_record_pair_id"] != row["pair_id"] for row in rows))
            self.assertTrue(all(row["source_embedding_sha256"] for row in rows))

            # A complete resume verifies evidence and performs no new swaps.
            self.assertEqual(self._run(args, engine, bindings), 0)
            self.assertEqual(engine.swap_calls, first_swap_calls)

            validation = self._validate_evidence(args, bindings)
            self.assertTrue(validation["valid"], validation["errors"])
            self.assertEqual(validation["result_rows"], 16)
            self.assertEqual(validation["identity_embedding_rows"], 28)
            self.assertEqual(validation["asset_count"], 11)

    def test_strict_evidence_validator_rejects_hidden_member_and_raw_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root)
            self.assertEqual(self._run(args, _FakeSimSwapEngine(), bindings), 0)

            hidden = args.report_dir / ".forged.json"
            hidden.write_text("{}", encoding="utf-8")
            hidden_result = self._validate_evidence(args, bindings)
            self.assertFalse(hidden_result["valid"])
            self.assertIn("membership is not exact", hidden_result["errors"][0])
            hidden.unlink()

            results_path = args.report_dir / "results.csv"
            with results_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fields = list(reader.fieldnames or [])
            rows[0]["registered_positive_score"] = "0.12345678"
            with results_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            tampered = self._validate_evidence(args, bindings)
            self.assertFalse(tampered["valid"])
            self.assertIn("control score mismatch", tampered["errors"][0])

    def test_strict_evidence_validator_recomputes_summary_and_signature_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root)
            self.assertEqual(self._run(args, _FakeSimSwapEngine(), bindings), 0)

            summary_path = args.report_dir / "summary.json"
            original_summary = summary_path.read_text(encoding="utf-8")
            summary = json.loads(original_summary)
            summary["model_results"]["LIDMark"]["holdout"]["tar"]["estimate"] = 0.123
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            tampered = self._validate_evidence(args, bindings)
            self.assertFalse(tampered["valid"])
            self.assertIn("recomputed raw evidence", tampered["errors"][0])
            summary_path.write_text(original_summary, encoding="utf-8")

            signature_manifest = root / "manifest.json"
            signature_bytes = b'{"files":[]}'
            signature_manifest.write_bytes(signature_bytes)
            with (
                mock.patch(
                    "system.backend.signing.MANIFEST_PATH",
                    signature_manifest,
                ),
                mock.patch(
                    "system.backend.signing.verify_evidence_bundle",
                    return_value={
                        "verified": True,
                        "profile": "release-core",
                        "signer_pinned": True,
                        "manifest_sha256": hashlib.sha256(signature_bytes).hexdigest(),
                    },
                ),
            ):
                unsigned_members = self._validate_evidence(
                    args,
                    bindings,
                    require_signature=True,
                )
            self.assertFalse(unsigned_members["valid"])
            self.assertIn("closure is not covered", unsigned_members["errors"][0])

    def test_error_rows_make_run_incomplete_and_return_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root, fail_model="WaveGuard")
            engine = _FakeSimSwapEngine()
            self.assertEqual(self._run(args, engine, bindings), 2)
            summary = json.loads(
                (args.report_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertEqual(summary["error_rows"], args.num_pairs)
            self.assertGreater(summary["missing_identity_embedding_rows"], 0)

    def test_incomplete_run_retries_only_failed_model_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root, fail_model="WaveGuard")
            engine = _FakeSimSwapEngine()
            self.assertEqual(self._run(args, engine, bindings), 2)
            self.assertEqual(engine.swap_calls, args.num_pairs * 4)

            bindings["WaveGuard"].adapter.fail = False
            self.assertEqual(self._run(args, engine, bindings), 0)
            # Resume recomputes each clean swap and only the failed watermark swap;
            # the three already complete model rows remain content-addressed evidence.
            self.assertEqual(engine.swap_calls, args.num_pairs * 6)
            summary = json.loads(
                (args.report_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["error_rows"], 0)
            self.assertEqual(summary["result_rows"], args.num_pairs * 4)
            self.assertEqual(summary["identity_embedding_rows"], args.num_pairs * 7)

    def test_result_resume_rejects_tampered_control_score(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, bindings = self._fixture(root)
            engine = _FakeSimSwapEngine()
            self.assertEqual(self._run(args, engine, bindings), 0)
            results_path = args.report_dir / "results.csv"
            with results_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fields = list(reader.fieldnames or [])
            rows[0]["registered_positive_score"] = "0.12345678"
            with results_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "control score mismatch"):
                self._run(args, engine, bindings)

    def test_calibration_threshold_does_not_read_holdout_rows(self) -> None:
        def evidence_row(split: str, positive: str, negative: str) -> dict[str, str]:
            return {
                "split": split,
                "registered_positive_score": positive,
                "unwatermarked_negative_score": negative,
                "wrong_message_negative_score": negative,
                "cross_record_negative_score": negative,
                "arcface_clean_identity_migrated": "1",
                "arcface_watermarked_identity_migrated": "1",
                "arcface_clean_identity_margin": "0.20",
                "arcface_watermarked_identity_margin": "0.18",
                "target_watermarked_psnr": "40.0",
                "target_watermarked_ssim": "0.99",
                "swapped_clean_vs_watermarked_psnr": "38.0",
                "swapped_clean_vs_watermarked_ssim": "0.98",
                "swapped_clean_vs_target_psnr": "20.0",
                "swapped_clean_vs_target_ssim": "0.80",
                "swapped_watermarked_vs_target_psnr": "19.8",
                "swapped_watermarked_vs_target_ssim": "0.79",
            }

        calibration = [
            {
                "registered_positive_score": "0.90",
                "unwatermarked_negative_score": "0.40",
                "wrong_message_negative_score": "0.45",
                "cross_record_negative_score": "0.50",
            },
            {
                "registered_positive_score": "0.85",
                "unwatermarked_negative_score": "0.35",
                "wrong_message_negative_score": "0.40",
                "cross_record_negative_score": "0.55",
            },
        ]
        baseline = benchmark.calibrate_threshold(calibration)
        calibration_rows = [
            evidence_row("calibration", "0.90", "0.40"),
            evidence_row("calibration", "0.85", "0.50"),
        ]
        self.assertEqual(baseline, benchmark.calibrate_threshold(calibration))
        favorable_holdout = [
            evidence_row("holdout", "1.00", "0.00"),
            evidence_row("holdout", "1.00", "0.00"),
        ]
        adversarial_holdout = [
            evidence_row("holdout", "0.00", "1.00"),
            evidence_row("holdout", "0.00", "1.00"),
        ]
        first = benchmark.summarize_model(
            calibration_rows + favorable_holdout,
            calibration_pairs=2,
            holdout_pairs=2,
        )
        second = benchmark.summarize_model(
            calibration_rows + adversarial_holdout,
            calibration_pairs=2,
            holdout_pairs=2,
        )
        self.assertEqual(first["calibration"], second["calibration"])
        self.assertNotEqual(first["holdout"]["tar"], second["holdout"]["tar"])

    def test_legacy_arcface_loader_rejects_wrong_hash_before_pickle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "arcface_checkpoint.tar"
            checkpoint.write_bytes(b"not-the-official-checkpoint")
            with mock.patch("torch.load") as loader:
                with self.assertRaisesRegex(RuntimeError, "checkpoint hash mismatch"):
                    benchmark._load_official_arcface_checkpoint(checkpoint)
            loader.assert_not_called()

    def test_kadnet_pyplot_stub_is_scoped_and_preserves_other_import_errors(self) -> None:
        original_import = builtins.__import__
        names = ("matplotlib", "matplotlib.pyplot")
        before = {name: sys.modules.get(name) for name in names}
        existed = {name: name in sys.modules for name in names}

        def missing_pyplot(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "matplotlib.pyplot":
                raise ModuleNotFoundError("missing matplotlib", name="matplotlib")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=missing_pyplot):
            with benchmark._kadnet_optional_import_stubs("KAD-Net"):
                self.assertIsInstance(sys.modules["matplotlib"], types.ModuleType)
                self.assertIsInstance(
                    sys.modules["matplotlib.pyplot"], types.ModuleType
                )

        for name in names:
            self.assertEqual(name in sys.modules, existed[name])
            if existed[name]:
                self.assertIs(sys.modules[name], before[name])

        def missing_transitive(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "matplotlib.pyplot":
                raise ModuleNotFoundError("missing kiwisolver", name="kiwisolver")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=missing_transitive):
            with self.assertRaises(ModuleNotFoundError) as raised:
                with benchmark._kadnet_optional_import_stubs("KAD-Net"):
                    self.fail("transitive dependency failure must be raised")
        self.assertEqual(raised.exception.name, "kiwisolver")

    def test_run_manifest_binds_all_project_owned_inference_components(self) -> None:
        manifest = benchmark._implementation_manifest()
        paths = [entry["path"] for entry in manifest]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("system/scripts/run_simswap_lfw_robustness.py", paths)
        self.assertIn("system/backend/model_adapters.py", paths)
        self.assertIn("system/evaluation/adapters/kadnet_adapter.py", paths)
        for entry in manifest:
            path = benchmark.PROJECT_DIR / entry["path"]
            self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_generator_loader_is_explicitly_weights_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "generator.pth"
            checkpoint.write_bytes(b"hash-constrained-generator-fixture")
            digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            with mock.patch("torch.load", return_value={"weight": object()}) as loader:
                result = benchmark._load_weights_only_checkpoint(
                    checkpoint, trusted_sha256=digest
                )
            self.assertIn("weight", result)
            self.assertTrue(loader.call_args.kwargs["weights_only"])


if __name__ == "__main__":
    unittest.main()
