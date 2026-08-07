from __future__ import annotations

import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from system.evaluation.attacks import ATTACKS, derived_seed
from system.evaluation.protocol import load_protocol
from system.scripts import run_waveguard_lfw_benchmark as benchmark
from system.scripts import run_waveguard_lfw_small_benchmark as compatibility


class WaveGuardBenchmarkTests(unittest.TestCase):
    def test_defaults_pin_full_lfw_and_content_addressed_checkpoint(self) -> None:
        self.assertTrue(
            benchmark.DEFAULT_IMAGE_ROOT.as_posix().endswith(
                "lfw/processed/image/lfw_256"
            )
        )
        self.assertEqual(benchmark.DEFAULT_CHECKPOINT.name, "model_state_16.pth")
        self.assertRegex(benchmark.DEFAULT_CHECKPOINT_SHA256, r"^[0-9a-f]{64}$")
        with mock.patch.object(benchmark.sys, "argv", ["runner"]):
            args = benchmark.parse_args()
        self.assertEqual(args.image_root, benchmark.DEFAULT_IMAGE_ROOT)
        self.assertEqual(args.num_images, 13233)
        self.assertIsNone(args.attacks)

    def test_compatibility_entrypoint_delegates_to_evidence_runner(self) -> None:
        self.assertIs(compatibility.main, benchmark.main)

    def test_message_is_30_bit_image_scoped_and_resume_independent(self) -> None:
        first = benchmark.message_for_image(17, "test/Alice_Example_0001.jpg")
        repeated = benchmark.message_for_image(17, "test/Alice_Example_0001.jpg")
        other_image = benchmark.message_for_image(
            17,
            "test/Alice_Example_0002.jpg",
        )
        other_seed = benchmark.message_for_image(
            18,
            "test/Alice_Example_0001.jpg",
        )
        np.testing.assert_array_equal(first, repeated)
        self.assertFalse(np.array_equal(first, other_image))
        self.assertFalse(np.array_equal(first, other_seed))
        self.assertEqual(first.shape, (30,))
        self.assertTrue(set(first.tolist()) <= {0, 1})

    def test_identity_evidence_groups_lfw_ordinals_without_exposing_names(self) -> None:
        first = "test/Alice_Example_0001.jpg"
        second = "train/Alice_Example_0002.jpg"
        third = "test/Bob_Example_0001.jpg"
        self.assertEqual(benchmark.lfw_identity_label(first), "Alice_Example")
        self.assertEqual(
            benchmark.identity_sha256(first),
            benchmark.identity_sha256(second),
        )
        self.assertNotEqual(
            benchmark.identity_sha256(first),
            benchmark.identity_sha256(third),
        )
        with self.assertRaisesRegex(ValueError, "non-canonical LFW"):
            benchmark.lfw_identity_label("face.png")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            paths = []
            for filename in (
                "Alice_Example_0001.png",
                "Alice_Example_0002.png",
                "Bob_Example_0001.png",
            ):
                path = images / filename
                Image.fromarray(np.full((8, 8, 3), 100, dtype=np.uint8)).save(path)
                paths.append(path)
            manifest_path = root / "manifest.json"
            manifest = benchmark.build_dataset_manifest(
                image_root=images,
                images=paths,
                output_path=manifest_path,
                seed=9,
            )
            self.assertEqual(manifest["sample_count"], 3)
            self.assertEqual(manifest["unique_identity_count"], 2)
            self.assertEqual(
                sorted(entry["image_count"] for entry in manifest["identity_distribution"]),
                [1, 2],
            )
            serialized = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root.resolve()), serialized)
            self.assertNotIn("Alice_Example\"", serialized)
            benchmark._validate_dataset_manifest(manifest_path, images, paths, 9)

    def test_attack_selection_defaults_to_all_15_canonical_ids(self) -> None:
        protocol = load_protocol()
        expected = [entry["id"] for entry in protocol["attacks"]]
        self.assertEqual(len(expected), 15)
        self.assertEqual(benchmark.resolve_attacks(None, protocol), expected)
        self.assertEqual(
            benchmark.resolve_attacks(["clean", "jpeg70"], protocol),
            ["clean", "jpeg70"],
        )
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            benchmark.resolve_attacks(["resize"], protocol)
        with self.assertRaisesRegex(ValueError, "unique"):
            benchmark.resolve_attacks(["clean", "clean"], protocol)

    def test_checkpoint_requires_encoder_tracer_and_detector_namespaces(self) -> None:
        complete = {
            "encoder.weight": object(),
            "decoder_t.weight": object(),
            "decoder_d.weight": object(),
            "gnn.weight": object(),
        }
        components = benchmark._checkpoint_components(complete)
        self.assertEqual(set(components), {"encoder", "decoder_t", "decoder_d"})
        for missing in ("encoder", "decoder_t", "decoder_d"):
            state = {
                key: value
                for key, value in complete.items()
                if not key.startswith(f"{missing}.")
            }
            with self.assertRaisesRegex(RuntimeError, missing):
                benchmark._checkpoint_components(state)
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            benchmark._checkpoint_components({**complete, "unknown.weight": object()})

    def test_default_checkpoint_policy_rejects_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "model_state_16.pth"
            checkpoint.write_bytes(b"waveguard-checkpoint")
            digest = benchmark.sha256_file(checkpoint)
            self.assertIsNotNone(digest)
            with (
                mock.patch.object(benchmark, "DEFAULT_CHECKPOINT", checkpoint),
                mock.patch.object(benchmark, "DEFAULT_CHECKPOINT_SHA256", digest),
            ):
                evidence = benchmark.checkpoint_selection_evidence(
                    checkpoint,
                    str(digest),
                )
                self.assertEqual(
                    evidence["policy"],
                    "fixed_content_addressed_checkpoint",
                )
                self.assertFalse(evidence["auto_select_latest"])
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    benchmark.checkpoint_selection_evidence(checkpoint, "0" * 64)

    def test_result_csv_uses_tracer_success_and_rejects_tampering(self) -> None:
        identifier = "test/Alice_Example_0001.jpg"
        attack = "clean"
        seed = 9
        message = benchmark.message_for_image(seed, identifier)
        row = {
            "image_id": identifier,
            "source_path": identifier,
            "identity_sha256": benchmark.identity_sha256(identifier),
            "attack_type": attack,
            "attack_config_sha256": ATTACKS[attack].config_hash,
            "attack_derived_seed": str(derived_seed(seed, identifier, attack)),
            "message_bits": benchmark.message_bits(message),
            "message_sha256": benchmark.message_sha256(message),
            "primary_decoder": "tracer",
            "bit_error_tracer": "0.00000000",
            "bit_accuracy_tracer": "1.00000000",
            "bit_error_detector": "1.00000000",
            "bit_accuracy_detector": "0.00000000",
            "psnr": "40.00000000",
            "ssim": "0.99000000",
            "success": "1",
            "error": "",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [row])
            loaded = benchmark.load_result_rows(path, {(identifier, attack)}, seed)
            self.assertEqual(set(loaded), {(identifier, attack)})

            detector_only = dict(
                row,
                bit_error_tracer="1.00000000",
                bit_accuracy_tracer="0.00000000",
                bit_error_detector="0.00000000",
                bit_accuracy_detector="1.00000000",
            )
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [detector_only])
            with self.assertRaisesRegex(ValueError, "tracer success threshold"):
                benchmark.load_result_rows(path, {(identifier, attack)}, seed)

            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate result key"):
                benchmark.load_result_rows(path, {(identifier, attack)}, seed)

            absolute = dict(row, source_path="/srv/private/lfw/a.jpg")
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [absolute])
            with self.assertRaisesRegex(ValueError, "absolute host path"):
                benchmark.load_result_rows(path, {(identifier, attack)}, seed)

    def test_run_config_refuses_resume_mismatch_and_unbound_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run_config.json"
            benchmark._ensure_run_config(
                path,
                {"schema_version": "v1", "seed": 1},
                False,
            )
            benchmark._ensure_run_config(
                path,
                {"schema_version": "v1", "seed": 1},
                True,
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                benchmark._ensure_run_config(
                    path,
                    {"schema_version": "v1", "seed": 2},
                    True,
                )
            missing = Path(temporary) / "missing.json"
            with self.assertRaisesRegex(RuntimeError, "refusing to mix"):
                benchmark._ensure_run_config(
                    missing,
                    {"schema_version": "v1"},
                    True,
                )

    def test_main_writes_complete_hashed_identity_aware_dual_decoder_evidence(self) -> None:
        class FakeModel:
            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = checkpoint
                self.message = np.zeros(benchmark.MSG_LEN, dtype=np.uint8)

            def encode(self, image: np.ndarray, message: np.ndarray) -> np.ndarray:
                self.message = message.copy()
                return np.clip(image.astype(np.int16) + 1, 0, 255).astype(np.uint8)

            def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                return {
                    "tracer": self.message.copy(),
                    "detector": 1 - self.message,
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            reports = root / "reports"
            assets = root / "assets"
            images.mkdir()
            Image.fromarray(np.full((20, 20, 3), 160, dtype=np.uint8)).save(
                images / "Alice_Example_0001.png"
            )
            checkpoint = root / "model_state_16.pth"
            checkpoint.write_bytes(b"real-waveguard-checkpoint-fixture")
            args = argparse.Namespace(
                num_images=1,
                attacks=["clean", "brightness_0.85"],
                image_root=images,
                checkpoint=checkpoint,
                report_dir=reports,
                asset_dir=assets,
                device="cpu",
                seed=20260603,
                artifact_limit=0,
                flush_every=1,
            )
            with (
                mock.patch.object(benchmark, "parse_args", return_value=args),
                mock.patch.object(
                    benchmark,
                    "build_model",
                    return_value=FakeModel(checkpoint),
                ),
                mock.patch.object(
                    benchmark.sys,
                    "argv",
                    ["run_waveguard_lfw_benchmark.py"],
                ),
                mock.patch("builtins.print"),
            ):
                benchmark.main()

            with (reports / "results.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                result_rows = list(csv.DictReader(handle))
            self.assertEqual(len(result_rows), 2)
            self.assertTrue(
                all(
                    row["source_path"] == "Alice_Example_0001.png"
                    for row in result_rows
                )
            )
            self.assertTrue(all(row["primary_decoder"] == "tracer" for row in result_rows))
            self.assertTrue(all(row["success"] == "1" for row in result_rows))
            self.assertTrue(
                all(float(row["bit_accuracy_tracer"]) == 1.0 for row in result_rows)
            )
            self.assertTrue(
                all(float(row["bit_accuracy_detector"]) == 0.0 for row in result_rows)
            )
            attacked_psnr = {
                row["attack_type"]: float(row["psnr"])
                for row in result_rows
            }
            self.assertNotEqual(
                attacked_psnr["clean"],
                attacked_psnr["brightness_0.85"],
            )

            summary = json.loads(
                (reports / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["schema_version"], "benchmark-summary.v2")
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["primary_decoder"], "tracer")
            self.assertEqual(summary["secondary_decoder"], "detector")
            self.assertEqual(summary["expected_result_rows"], 2)
            self.assertEqual(summary["attacks"]["clean"]["mean_bit_accuracy"], 1.0)
            self.assertEqual(
                summary["dataset_identity_evidence"]["unique_identity_count"],
                1,
            )
            for field in (
                "checkpoint_sha256",
                "dataset_manifest_sha256",
                "results_csv_sha256",
                "watermarked_quality_csv_sha256",
                "run_config_sha256",
                "artifact_manifest_sha256",
                "progress_sha256",
                "runner_sha256",
            ):
                self.assertRegex(str(summary[field]), r"^[0-9a-f]{64}$")

            manifest = json.loads(
                (reports / "dataset_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], "waveguard-dataset-manifest.v1")
            self.assertEqual(manifest["unique_identity_count"], 1)
            self.assertEqual(
                manifest["files"][0]["path"],
                "Alice_Example_0001.png",
            )
            self.assertRegex(manifest["files"][0]["identity_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn(str(root.resolve()), json.dumps(manifest))
            progress = json.loads(
                (reports / "progress.json").read_text(encoding="utf-8")
            )
            self.assertEqual(progress["status"], "complete")

            results_before_resume = (reports / "results.csv").read_bytes()
            quality_before_resume = (reports / "watermarked_quality.csv").read_bytes()

            class NoInferenceOnResume:
                def __init__(self, bound_checkpoint: Path) -> None:
                    self.checkpoint = bound_checkpoint

                def encode(self, _image: np.ndarray, _message: np.ndarray) -> np.ndarray:
                    raise AssertionError("valid rows must not be recomputed")

                def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                    raise AssertionError("valid rows must not be recomputed")

            with (
                mock.patch.object(benchmark, "parse_args", return_value=args),
                mock.patch.object(
                    benchmark,
                    "build_model",
                    return_value=NoInferenceOnResume(checkpoint),
                ),
                mock.patch.object(
                    benchmark.sys,
                    "argv",
                    ["run_waveguard_lfw_benchmark.py"],
                ),
                mock.patch("builtins.print"),
            ):
                benchmark.main()
            self.assertEqual((reports / "results.csv").read_bytes(), results_before_resume)
            self.assertEqual(
                (reports / "watermarked_quality.csv").read_bytes(),
                quality_before_resume,
            )

    def test_decode_error_is_a_raw_row_and_prevents_finalization(self) -> None:
        class FailingModel:
            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = checkpoint

            def encode(self, image: np.ndarray, _message: np.ndarray) -> np.ndarray:
                return image.copy()

            def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                raise RuntimeError("fixture decoder failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            Image.fromarray(np.full((20, 20, 3), 100, dtype=np.uint8)).save(
                images / "Alice_Example_0001.png"
            )
            checkpoint = root / "model_state_16.pth"
            checkpoint.write_bytes(b"checkpoint")
            reports = root / "reports"
            args = argparse.Namespace(
                num_images=1,
                attacks=["clean"],
                image_root=images,
                checkpoint=checkpoint,
                report_dir=reports,
                asset_dir=root / "assets",
                device="cpu",
                seed=20260603,
                artifact_limit=0,
                flush_every=1,
            )
            with (
                mock.patch.object(benchmark, "parse_args", return_value=args),
                mock.patch.object(
                    benchmark,
                    "build_model",
                    return_value=FailingModel(checkpoint),
                ),
                mock.patch.object(
                    benchmark,
                    "finalize_benchmark_summary",
                ) as finalizer,
                mock.patch("builtins.print"),
            ):
                with self.assertRaisesRegex(SystemExit, "2"):
                    benchmark.main()
            finalizer.assert_not_called()
            with (reports / "results.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["success"], "0")
            self.assertEqual(rows[0]["error"], "attack_or_decode:RuntimeError")
            summary = json.loads(
                (reports / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertEqual(summary["error_rows"], 1)


if __name__ == "__main__":
    unittest.main()
