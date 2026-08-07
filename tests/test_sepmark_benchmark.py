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

from system.evaluation.attacks import ATTACKS
from system.evaluation.protocol import load_protocol
from system.scripts import run_sepmark_lfw_benchmark as benchmark


class SepMarkBenchmarkTests(unittest.TestCase):
    def test_default_checkpoint_is_fixed_ec108(self) -> None:
        self.assertEqual(benchmark.DEFAULT_CHECKPOINT.name, "EC_108.pth")
        self.assertNotIn("glob", benchmark.DEFAULT_CHECKPOINT.as_posix().lower())
        self.assertRegex(benchmark.DEFAULT_CHECKPOINT_SHA256, r"^[0-9a-f]{64}$")

    def test_default_dataset_is_the_frozen_13233_image_lfw256_tree(self) -> None:
        self.assertTrue(
            benchmark.DEFAULT_IMAGE_ROOT.as_posix().endswith(
                "lfw/processed/image/lfw_256"
            )
        )
        with mock.patch.object(benchmark.sys, "argv", ["runner"]):
            args = benchmark.parse_args()
        self.assertEqual(args.image_root, benchmark.DEFAULT_IMAGE_ROOT)
        self.assertEqual(args.num_images, 13233)

    def test_default_checkpoint_is_bound_to_frozen_selection_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "EC_108.pth"
            checkpoint.write_bytes(b"checkpoint")
            checkpoint_hash = benchmark.sha256_file(checkpoint)
            self.assertIsNotNone(checkpoint_hash)
            evidence = root / "summary.json"
            evidence.write_text(json.dumps({
                "status": "complete",
                "run_id": "sepmark-official-smoke-test",
                "recommended_checkpoint_for_full_lfw_evaluation": {
                    "epoch": 108,
                    "path": "weights/MEA/models/SepMark/EC_108.pth",
                    "sha256": checkpoint_hash,
                },
            }), encoding="utf-8")
            with (
                mock.patch.object(benchmark, "DEFAULT_CHECKPOINT", checkpoint),
                mock.patch.object(
                    benchmark,
                    "DEFAULT_CHECKPOINT_SHA256",
                    checkpoint_hash,
                ),
                mock.patch.object(
                    benchmark,
                    "DEFAULT_SELECTION_EVIDENCE",
                    evidence,
                ),
            ):
                selection = benchmark.checkpoint_selection_evidence(
                    checkpoint,
                    checkpoint_hash,
                )
            self.assertEqual(selection["selected_epoch"], 108)
            self.assertFalse(selection["auto_select_latest"])
            self.assertRegex(selection["evidence_sha256"], r"^[0-9a-f]{64}$")

    def test_message_derivation_is_128_bit_image_scoped_and_resume_independent(self) -> None:
        first = benchmark.message_for_image(17, "person/a.jpg")
        repeated = benchmark.message_for_image(17, "person/a.jpg")
        other_image = benchmark.message_for_image(17, "person/b.jpg")
        other_seed = benchmark.message_for_image(18, "person/a.jpg")

        np.testing.assert_array_equal(first, repeated)
        self.assertFalse(np.array_equal(first, other_image))
        self.assertFalse(np.array_equal(first, other_seed))
        self.assertEqual(first.shape, (128,))
        self.assertTrue(set(first.tolist()) <= {0, 1})

    def test_attack_selection_defaults_to_every_canonical_protocol_id(self) -> None:
        protocol = load_protocol()
        expected = [entry["id"] for entry in protocol["attacks"]]
        self.assertEqual(benchmark.resolve_attacks(None, protocol), expected)
        self.assertEqual(
            benchmark.resolve_attacks(["clean", "jpeg70"], protocol),
            ["clean", "jpeg70"],
        )
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            benchmark.resolve_attacks(["resize"], protocol)
        with self.assertRaisesRegex(ValueError, "unique"):
            benchmark.resolve_attacks(["clean", "clean"], protocol)

    def test_checkpoint_requires_encoder_and_both_decoders(self) -> None:
        complete = {
            "encoder.weight": object(),
            "decoder_C.weight": object(),
            "decoder_RF.weight": object(),
            "noise.unused": object(),
        }
        components = benchmark._checkpoint_components(complete)
        self.assertEqual(set(components), {"encoder", "decoder_C", "decoder_RF"})
        self.assertEqual(set(components["decoder_RF"]), {"weight"})

        for missing in ("encoder", "decoder_C", "decoder_RF"):
            state = {
                key: value
                for key, value in complete.items()
                if not key.startswith(f"{missing}.")
            }
            with self.assertRaisesRegex(RuntimeError, missing):
                benchmark._checkpoint_components(state)

    def test_result_csv_uses_c_success_and_rejects_duplicates_or_host_paths(self) -> None:
        identifier = "person/a.jpg"
        attack = "clean"
        message = benchmark.message_for_image(9, identifier)
        row = {
            "image_id": identifier,
            "source_path": identifier,
            "attack_type": attack,
            "attack_config_sha256": ATTACKS[attack].config_hash,
            "message_bits": benchmark.message_bits(message),
            "message_sha256": benchmark.message_sha256(message),
            "primary_decoder": "decoder_C",
            "bit_error_c": "0.00000000",
            "bit_accuracy_c": "1.00000000",
            "bit_error_rf": "1.00000000",
            "bit_accuracy_rf": "0.00000000",
            "psnr": "40.00000000",
            "ssim": "0.99000000",
            "success": "1",
            "error": "",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [row])
            loaded = benchmark.load_result_rows(path, {(identifier, attack)}, 9)
            self.assertEqual(set(loaded), {(identifier, attack)})

            rf_only_success = dict(
                row,
                bit_accuracy_c="0.00000000",
                bit_error_c="1.00000000",
                bit_accuracy_rf="1.00000000",
                bit_error_rf="0.00000000",
            )
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [rf_only_success])
            with self.assertRaisesRegex(ValueError, "decoder_C success threshold"):
                benchmark.load_result_rows(path, {(identifier, attack)}, 9)

            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate result key"):
                benchmark.load_result_rows(path, {(identifier, attack)}, 9)

            absolute = dict(row, source_path="/srv/private/lfw/a.jpg")
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [absolute])
            with self.assertRaisesRegex(ValueError, "absolute host path"):
                benchmark.load_result_rows(path, {(identifier, attack)}, 9)

    def test_run_config_refuses_resume_mismatch(self) -> None:
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

    def test_main_writes_hashed_complete_dual_decoder_evidence(self) -> None:
        class FakeModel:
            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = checkpoint
                self.message = np.zeros(benchmark.MSG_LEN, dtype=np.uint8)

            def encode(self, image: np.ndarray, message: np.ndarray) -> np.ndarray:
                self.message = message.copy()
                return np.clip(image.astype(np.int16) + 1, 0, 255).astype(np.uint8)

            def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                return {
                    "decoder_C": self.message.copy(),
                    "decoder_RF": 1 - self.message,
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            reports = root / "reports"
            assets = root / "assets"
            images.mkdir()
            Image.fromarray(np.full((16, 16, 3), 160, dtype=np.uint8)).save(
                images / "face.png"
            )
            checkpoint = root / "EC_108.pth"
            checkpoint.write_bytes(b"real-sepmark-checkpoint-fixture")
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

            def finalize(summary: dict, **kwargs: object) -> dict:
                finalized = dict(summary)
                finalized.update({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "checkpoint": benchmark.logical_path(checkpoint),
                    "checkpoint_sha256": benchmark.sha256_file(checkpoint),
                })
                return finalized

            with (
                mock.patch.object(benchmark, "parse_args", return_value=args),
                mock.patch.object(
                    benchmark,
                    "build_model",
                    return_value=FakeModel(checkpoint),
                ),
                mock.patch.object(
                    benchmark,
                    "finalize_benchmark_summary",
                    side_effect=finalize,
                ) as finalizer,
                mock.patch.object(
                    benchmark.sys,
                    "argv",
                    ["run_sepmark_lfw_benchmark.py"],
                ),
                mock.patch("builtins.print"),
            ):
                benchmark.main()

            finalizer.assert_called_once()
            call = finalizer.call_args
            self.assertEqual(call.kwargs["sample_count"], 1)
            self.assertEqual(
                call.kwargs["attack_ids"],
                ["clean", "brightness_0.85"],
            )
            self.assertEqual(call.kwargs["checkpoint"], checkpoint.resolve())

            with (reports / "results.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                result_rows = list(csv.DictReader(handle))
            self.assertEqual(len(result_rows), 2)
            self.assertTrue(
                all(row["source_path"] == "face.png" for row in result_rows)
            )
            self.assertTrue(all(row["primary_decoder"] == "decoder_C" for row in result_rows))
            self.assertTrue(all(row["success"] == "1" for row in result_rows))
            self.assertTrue(all(float(row["bit_accuracy_c"]) == 1.0 for row in result_rows))
            self.assertTrue(all(float(row["bit_accuracy_rf"]) == 0.0 for row in result_rows))
            attacked_psnr = {
                row["attack_type"]: float(row["psnr"])
                for row in result_rows
            }
            self.assertNotEqual(
                attacked_psnr["clean"],
                attacked_psnr["brightness_0.85"],
            )

            with (reports / "watermarked_quality.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                quality_rows = list(csv.DictReader(handle))
            self.assertEqual(len(quality_rows), 1)
            self.assertEqual(quality_rows[0]["source_path"], "face.png")
            self.assertNotEqual(quality_rows[0]["watermarked_psnr"], "")

            summary = json.loads(
                (reports / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["primary_decoder"], "decoder_C")
            self.assertEqual(summary["expected_result_rows"], 2)
            self.assertEqual(
                summary["attacks"]["clean"]["mean_bit_accuracy"],
                1.0,
            )
            self.assertRegex(
                summary["watermarked_quality_csv_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(summary["run_config_sha256"], r"^[0-9a-f]{64}$")

            manifest = json.loads(
                (reports / "dataset_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["files"][0]["path"], "face.png")
            self.assertNotIn(str(root.resolve()), json.dumps(manifest))

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
            Image.fromarray(np.full((16, 16, 3), 100, dtype=np.uint8)).save(
                images / "face.png"
            )
            checkpoint = root / "EC_108.pth"
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
