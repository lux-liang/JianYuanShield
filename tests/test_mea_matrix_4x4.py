from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from scripts import run_mea_matrix_4x4 as runner
from system.backend.mea_evidence import validate_mea_matrix_evidence
from system.evaluation.adapters import DecodeResult, EmbeddingResult, ModelAdapter


MODEL_LENGTHS = {
    "LIDMark": 4,
    "KAD-Net": 5,
    "SepMark": 6,
    "WaveGuard": 7,
}
PRIMARY_DECODERS = {
    "LIDMark": "FHD_id_head",
    "KAD-Net": "ST_Decoder_C",
    "SepMark": "decoder_C",
    "WaveGuard": "tracer",
}


def write_protocol(path: Path, *, threshold: float = 0.75) -> None:
    source = Path("configs/evaluation_protocol.v1.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["success_threshold"] = threshold
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_images(root: Path, count: int = 2) -> None:
    root.mkdir(parents=True)
    for index in range(count):
        array = np.full((16, 16, 3), 80 + index * 20, dtype=np.uint8)
        array[index, index, :] = [10 + index, 20 + index, 30 + index]
        Image.fromarray(array).save(root / f"person_{index:02d}.png")


def make_adapter_class(
    model_name: str,
    slot: int,
    checkpoint: Path,
    *,
    fail: bool = False,
) -> type[ModelAdapter]:
    length = MODEL_LENGTHS[model_name]
    decoder = PRIMARY_DECODERS[model_name]

    class FakeAdapter(ModelAdapter):
        message_length = length
        expected_checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        checkpoint_selection = "unit_test_fixed_checkpoint"
        primary_decoder = decoder

        def __init__(self) -> None:
            self.name = model_name
            self._encode_count = 0

        def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
            if fail:
                raise RuntimeError("/tmp/private/checkpoint loader failed")
            self.validate_image(image)
            bits = self.validate_message(message)
            output = image.copy()
            flat = output.reshape(-1)
            offset = slot * 40
            flat[offset : offset + bits.size] = np.where(bits > 0, 240, 5)
            flat[offset + 20] = 40 if self._encode_count % 2 == 0 else 210
            self._encode_count += 1
            return EmbeddingResult(output, bits.copy(), {"model": self.name})

        def decode(self, image: np.ndarray) -> DecodeResult:
            self.validate_image(image)
            flat = image.reshape(-1)
            offset = slot * 40
            bits = (flat[offset : offset + self.message_length] > 127).astype(
                np.uint8
            )
            return DecodeResult(
                bits,
                {
                    "decoder": self.primary_decoder,
                    "primary_decoder": self.primary_decoder,
                },
            )

    FakeAdapter.__name__ = f"Fake{model_name.replace('-', '')}Adapter"
    FakeAdapter.checkpoint = str(checkpoint)
    return FakeAdapter


def make_adapters(root: Path, *, failing_model: str | None = None) -> dict[str, type[Any]]:
    adapters: dict[str, type[Any]] = {}
    for slot, name in enumerate(runner.TARGET_MODELS):
        checkpoint = root / f"{name.lower().replace('-', '')}.pth"
        checkpoint.write_bytes(f"checkpoint:{name}".encode("utf-8"))
        adapters[name] = make_adapter_class(
            name, slot, checkpoint, fail=name == failing_model
        )
    return adapters


def args_for(root: Path, *, resume: bool = False, count: int = 2) -> argparse.Namespace:
    return argparse.Namespace(
        images_per_cell=count,
        image_root=root / "images",
        output=root / "report",
        protocol=root / "protocol.json",
        device="cpu",
        resume=resume,
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class MEAMatrixEvidenceTests(unittest.TestCase):
    def prepare(self, root: Path, *, count: int = 2) -> dict[str, type[Any]]:
        write_protocol(root / "protocol.json")
        write_images(root / "images", count)
        return make_adapters(root)

    def test_formal_registry_paths_and_primary_decoders_are_frozen(self) -> None:
        from system.evaluation.adapters import get_mea_adapter_classes

        classes = get_mea_adapter_classes()
        self.assertEqual(tuple(classes), runner.TARGET_MODELS)
        expected_suffixes = {
            "LIDMark": "weights/lidmark/lfw-id-s20260603-128/checkpoint_epoch_20.pth",
            "KAD-Net": "weights/KAD-Net/ST/128/models/EC_100.pth",
            "SepMark": (
                "weights/MEA/models/SepMark/results/"
                "FullFineTuningWithOnlyMessage/models/EC_108.pth"
            ),
            "WaveGuard": (
                "weights/MEA/models/WaveGuard/exp_highpass/"
                "2025.07.24-20.10.50/model_state_16.pth"
            ),
        }
        expected_hashes = {
            "LIDMark": "762369c8e4e881c8d72fde08ebaf7fea3fd7a26354aa344aed288cb780ad3436",
            "KAD-Net": "3b298493ae3510e73fc85a5fcae2f470d8e6892e9e058aa9cca3a0d8d35f5079",
            "SepMark": "433992186176483bd92341fd033cf3c2fa2682f159aea7fe4542c4a6b88b5e55",
            "WaveGuard": "cd093467a834cde47a0abed1d90a3ed62120092a2affcbcb1ed2f7d72b346377",
        }
        for name, adapter_class in classes.items():
            checkpoint = Path(str(adapter_class.checkpoint)).as_posix()
            self.assertTrue(checkpoint.endswith(expected_suffixes[name]), checkpoint)
            self.assertEqual(
                adapter_class.expected_checkpoint_sha256, expected_hashes[name]
            )
            self.assertEqual(adapter_class.primary_decoder, PRIMARY_DECODERS[name])

    def test_content_addressed_sampling_and_stateless_messages_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first" / "images"
            second = root / "second" / "images"
            write_images(first, 3)
            write_images(second, 3)
            manifest_a = runner.build_dataset_manifest(first, 2, 20260603)
            manifest_b = runner.build_dataset_manifest(second, 2, 20260603)
            self.assertEqual(manifest_a["candidate_digest_sha256"], manifest_b["candidate_digest_sha256"])
            self.assertEqual(manifest_a["files"], manifest_b["files"])

            image_id = manifest_a["files"][0]["image_id"]
            source_a = runner.derive_message(20260603, "source", "LIDMark", image_id, 16)
            source_b = runner.derive_message(20260603, "source", "LIDMark", image_id, 16)
            attacker = runner.derive_message(20260603, "attacker", "LIDMark", image_id, 16)
            np.testing.assert_array_equal(source_a, source_b)
            self.assertFalse(np.array_equal(source_a, attacker))

    def test_full_fake_matrix_writes_auditable_exact_coverage_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapters = self.prepare(root)
            args = args_for(root)
            summary = runner.run_matrix(args, adapter_classes=adapters)
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["evidence_status"], "complete_unsigned")
            self.assertFalse(summary["claim_valid"])
            self.assertEqual(summary["coverage"]["expected_rows"], 32)
            self.assertEqual(summary["coverage"]["valid_rows"], 32)
            self.assertEqual(summary["coverage"]["complete_cells"], 16)

            rows = read_rows(root / "report/raw_results.csv")
            self.assertEqual(len(rows), 32)
            self.assertEqual(len({row["row_id"] for row in rows}), 32)
            self.assertTrue(all(row["status"] == "ok" for row in rows))
            for row in rows:
                self.assertEqual(
                    row["source_decoded_sha256"],
                    runner.bits_sha256(
                        runner.parse_bits(
                            row["source_decoded_bits"],
                            int(row["source_message_length"]),
                        )
                    ),
                )

            first_messages: dict[tuple[str, str], set[str]] = {}
            for row in rows:
                key = (row["source_model"], row["image_id"])
                first_messages.setdefault(key, set()).add(row["source_message_bits"])
            self.assertTrue(all(len(messages) == 1 for messages in first_messages.values()))

            for name in runner.EVIDENCE_FILES:
                path = root / "report" / name
                self.assertTrue(path.is_file(), name)
                if path.suffix == ".json":
                    runner.assert_no_absolute_paths(
                        json.loads(path.read_text(encoding="utf-8")), name
                    )
            self.assertFalse(list((root / "report").glob(".*.tmp")))

            def must_not_run(*_args: Any, **_kwargs: Any) -> Any:
                raise AssertionError("completed resume unexpectedly reran inference")

            resumed = runner.run_matrix(
                args_for(root, resume=True),
                adapter_classes=adapters,
                evaluator=must_not_run,
            )
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(len(read_rows(root / "report/raw_results.csv")), 32)

    def test_strict_validator_rejects_schema_membership_and_rehashed_raw_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapters = self.prepare(root)
            report = root / "report"
            runner.run_matrix(args_for(root), adapter_classes=adapters)

            valid = validate_mea_matrix_evidence(
                report,
                images_per_cell=2,
                require_cuda_determinism=False,
                enforce_canonical_checkpoints=False,
            )
            self.assertTrue(valid["valid"], valid.get("errors"))
            self.assertEqual(valid["row_count"], 32)
            self.assertEqual(set(valid["evidence_files"]), set(runner.EVIDENCE_FILES))

            summary_path = report / "summary.json"
            original_summary = summary_path.read_bytes()
            summary = json.loads(original_summary)
            summary["schema_version"] = "mea-matrix-summary.tampered"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            invalid_schema = validate_mea_matrix_evidence(
                report,
                images_per_cell=2,
                require_cuda_determinism=False,
                enforce_canonical_checkpoints=False,
            )
            self.assertFalse(invalid_schema["valid"])
            summary_path.write_bytes(original_summary)

            manifest_path = report / "dataset_manifest.json"
            original_manifest = manifest_path.read_bytes()
            manifest = json.loads(original_manifest)
            manifest["files"][0]["selection_score_sha256"] = "0" * 64
            manifest["files_digest_sha256"] = runner.canonical_sha256(
                manifest["files"]
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            invalid_digest_semantics = validate_mea_matrix_evidence(
                report,
                images_per_cell=2,
                require_cuda_determinism=False,
                enforce_canonical_checkpoints=False,
            )
            self.assertFalse(invalid_digest_semantics["valid"])
            self.assertTrue(
                any(
                    "dataset digest semantics mismatch" in error
                    for error in invalid_digest_semantics.get("errors", [])
                ),
                invalid_digest_semantics.get("errors"),
            )
            manifest_path.write_bytes(original_manifest)

            unexpected = report / ".untracked.json"
            unexpected.write_text("{}", encoding="utf-8")
            invalid_membership = validate_mea_matrix_evidence(
                report,
                images_per_cell=2,
                require_cuda_determinism=False,
                enforce_canonical_checkpoints=False,
            )
            self.assertFalse(invalid_membership["valid"])
            unexpected.unlink()

            raw_path = report / "raw_results.csv"
            rows = read_rows(raw_path)
            rows[0]["source_bit_accuracy"] = (
                "0" if rows[0]["source_bit_accuracy"] != "0" else "1"
            )
            with raw_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=runner.RAW_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            progress_path = report / "progress.json"
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            progress["raw_results"]["sha256"] = raw_sha
            progress_path.write_text(json.dumps(progress), encoding="utf-8")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["artifacts"]["raw_results"]["sha256"] = raw_sha
            summary_path.write_text(json.dumps(summary), encoding="utf-8")

            invalid_semantics = validate_mea_matrix_evidence(
                report,
                images_per_cell=2,
                require_cuda_determinism=False,
                enforce_canonical_checkpoints=False,
            )
            self.assertFalse(invalid_semantics["valid"])
            self.assertTrue(
                any(
                    "raw metric drift" in error
                    for error in invalid_semantics.get("errors", [])
                ),
                invalid_semantics.get("errors"),
            )

    def test_missing_model_is_fail_closed_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapters = self.prepare(root, count=1)
            del adapters["WaveGuard"]
            summary = runner.run_matrix(
                args_for(root, count=1), adapter_classes=adapters
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertIn("adapter_registry_missing:WaveGuard", summary["preflight_errors"])
            self.assertEqual(summary["coverage"]["valid_rows"], 0)
            self.assertEqual(summary["coverage"]["missing_rows"], 16)
            self.assertEqual(len(read_rows(root / "report/raw_results.csv")), 0)

    def test_sample_errors_keep_all_keys_and_block_completion_without_path_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_protocol(root / "protocol.json")
            write_images(root / "images", 1)
            adapters = make_adapters(root, failing_model="SepMark")
            summary = runner.run_matrix(
                args_for(root, count=1), adapter_classes=adapters
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertEqual(summary["coverage"]["observed_unique_expected_rows"], 16)
            self.assertGreater(summary["coverage"]["error_rows"], 0)
            self.assertEqual(summary["coverage"]["missing_rows"], 0)
            rows = read_rows(root / "report/raw_results.csv")
            self.assertEqual(len(rows), 16)
            error_rows = [row for row in rows if row["status"] == "error"]
            self.assertTrue(error_rows)
            self.assertTrue(
                all(row["error"] == "details_redacted_absolute_path" for row in error_rows)
            )
            self.assertNotIn(str(root), (root / "report/summary.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
