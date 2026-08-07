from __future__ import annotations

import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from system.evaluation.attacks import ATTACKS
from system.evaluation.protocol import load_protocol
from system.scripts import run_kadnet_lfw_benchmark as benchmark


class KADNetBenchmarkTests(unittest.TestCase):
    def test_message_derivation_is_image_scoped_and_resume_order_independent(self) -> None:
        first = benchmark.message_for_image(17, "person/a.jpg")
        repeated = benchmark.message_for_image(17, "person/a.jpg")
        other_image = benchmark.message_for_image(17, "person/b.jpg")
        other_seed = benchmark.message_for_image(18, "person/a.jpg")

        np.testing.assert_array_equal(first, repeated)
        self.assertFalse(np.array_equal(first, other_image))
        self.assertFalse(np.array_equal(first, other_seed))
        self.assertEqual(first.shape, (benchmark.MSG_LEN,))
        self.assertEqual(set(first.tolist()) <= {0, 1}, True)

    def test_attack_selection_uses_only_canonical_protocol_ids(self) -> None:
        protocol = load_protocol()
        expected = [entry["id"] for entry in protocol["attacks"]]
        self.assertEqual(benchmark.resolve_attacks(None, protocol), expected)
        self.assertEqual(benchmark.resolve_attacks(["clean", "jpeg70"], protocol), ["clean", "jpeg70"])
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            benchmark.resolve_attacks(["resize"], protocol)
        with self.assertRaisesRegex(ValueError, "unique"):
            benchmark.resolve_attacks(["clean", "clean"], protocol)

    def test_result_csv_rejects_duplicates_and_absolute_paths(self) -> None:
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
            "bit_error": "0.00000000",
            "bit_accuracy": "1.00000000",
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

            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate result key"):
                benchmark.load_result_rows(path, {(identifier, attack)}, 9)

            absolute = dict(row, source_path="/srv/private/lfw/a.jpg")
            benchmark._atomic_write_csv(path, benchmark.RESULT_FIELDS, [absolute])
            with self.assertRaisesRegex(ValueError, "absolute host path"):
                benchmark.load_result_rows(path, {(identifier, attack)}, 9)

    def test_run_config_refuses_existing_result_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run_config.json"
            benchmark._ensure_run_config(path, {"schema_version": "v1", "seed": 1}, False)
            benchmark._ensure_run_config(path, {"schema_version": "v1", "seed": 1}, True)
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                benchmark._ensure_run_config(path, {"schema_version": "v1", "seed": 2}, True)

            missing = Path(temporary) / "missing.json"
            with self.assertRaisesRegex(RuntimeError, "refusing to mix"):
                benchmark._ensure_run_config(missing, {"schema_version": "v1"}, True)

    def test_main_writes_complete_hashed_evidence_with_attacked_quality(self) -> None:
        class FakeAdapter:
            available = True
            blocker = None

            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = str(checkpoint)
                self._message = np.zeros(benchmark.MSG_LEN, dtype=np.uint8)

            def encode(self, image: np.ndarray, message: np.ndarray) -> SimpleNamespace:
                self._message = message.copy()
                encoded = np.clip(image.astype(np.int16) + 1, 0, 255).astype(np.uint8)
                return SimpleNamespace(
                    image=encoded,
                    metadata={"checkpoint": self.checkpoint},
                )

            def decode(self, image: np.ndarray) -> SimpleNamespace:
                return SimpleNamespace(bits=self._message.copy())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            reports = root / "reports"
            assets = root / "assets"
            images.mkdir()
            array = np.full((16, 16, 3), 160, dtype=np.uint8)
            Image.fromarray(array).save(images / "face.png")
            checkpoint = root / "EC_100.pth"
            checkpoint.write_bytes(b"real-checkpoint-fixture")
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

            fake_adapter = FakeAdapter(checkpoint)
            with (
                mock.patch.object(benchmark, "parse_args", return_value=args),
                mock.patch.object(benchmark, "build_adapter", return_value=fake_adapter),
                mock.patch.object(benchmark, "finalize_benchmark_summary", side_effect=finalize) as finalizer,
                mock.patch.object(benchmark.sys, "argv", ["run_kadnet_lfw_benchmark.py"]),
                mock.patch("builtins.print"),
            ):
                benchmark.main()

            finalizer.assert_called_once()
            call = finalizer.call_args
            self.assertEqual(call.kwargs["sample_count"], 1)
            self.assertEqual(call.kwargs["attack_ids"], ["clean", "brightness_0.85"])
            self.assertEqual(call.kwargs["checkpoint"], checkpoint.resolve())

            with (reports / "results.csv").open(encoding="utf-8", newline="") as handle:
                result_rows = list(csv.DictReader(handle))
            self.assertEqual(len(result_rows), 2)
            self.assertTrue(all(row["source_path"] == "face.png" for row in result_rows))
            psnr = {row["attack_type"]: float(row["psnr"]) for row in result_rows}
            self.assertNotEqual(psnr["clean"], psnr["brightness_0.85"])

            with (reports / "watermarked_quality.csv").open(encoding="utf-8", newline="") as handle:
                quality_rows = list(csv.DictReader(handle))
            self.assertEqual(len(quality_rows), 1)
            self.assertEqual(quality_rows[0]["source_path"], "face.png")
            self.assertNotEqual(quality_rows[0]["watermarked_psnr"], "")

            summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["expected_result_rows"], 2)
            self.assertRegex(summary["watermarked_quality_csv_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(summary["run_config_sha256"], r"^[0-9a-f]{64}$")

            manifest = json.loads((reports / "dataset_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"][0]["path"], "face.png")
            self.assertFalse(any(str(root.resolve()) in path for path in manifest["files"][0].values() if isinstance(path, str)))


if __name__ == "__main__":
    unittest.main()
