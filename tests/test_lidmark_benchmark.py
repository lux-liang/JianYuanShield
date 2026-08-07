from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from system.backend.benchmark_evidence import _csv_structure_valid
from system.evaluation.attacks import ATTACKS
from system.evaluation.protocol import load_protocol
from system.scripts import run_lidmark_lfw_benchmark as benchmark


class LIDMarkBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        benchmark.configure_input_expectations(None)
        self.protocol = load_protocol()
        self.attacks = benchmark.resolve_attacks(self.protocol)

    @staticmethod
    def _sample(root: Path) -> tuple[dict[str, object], dict[str, object]]:
        image_path = root / "image" / "Alice_0001.jpg"
        payload_path = root / "payload" / "Alice_0001.npy"
        image_path.parent.mkdir(parents=True)
        payload_path.parent.mkdir(parents=True)
        image = np.full(
            (benchmark.IMG_SIZE, benchmark.IMG_SIZE, 3), 128, dtype=np.uint8
        )
        Image.fromarray(image).save(image_path, quality=100, subsampling=0)
        payload = np.concatenate(
            [
                np.linspace(
                    0.1,
                    0.9,
                    benchmark.LANDMARK_LENGTH,
                    dtype=np.float32,
                ),
                np.asarray(
                    [1.0, -1.0] * (benchmark.IDENTITY_LENGTH // 2),
                    dtype=np.float32,
                ),
            ]
        ).astype(np.float32)
        np.save(payload_path, payload, allow_pickle=False)
        message = (payload[benchmark.LANDMARK_LENGTH :] > 0).astype(np.uint8)
        sample = {
            "sample_id": "test/Alice_0001.jpg",
            "identity": "Alice",
            "image_path": image_path,
            "payload_path": payload_path,
            "source_path": "image/lfw_128/test/Alice_0001.jpg",
            "payload_relative": "watermark_152/lfw/128/test/Alice_0001.npy",
            "image_sha256": benchmark.sha256_file(image_path),
            "image_size_bytes": image_path.stat().st_size,
            "payload_sha256": benchmark.sha256_file(payload_path),
            "payload_size_bytes": payload_path.stat().st_size,
            "message_sha256": benchmark.hashlib.sha256(message.tobytes()).hexdigest(),
        }
        proof = {
            "identity_disjoint": True,
            "overlap_counts": {"train_val": 0, "train_test": 0, "val_test": 0},
            "source_identity_counts": {"train": 1, "val": 1, "test": 1},
            "selected_test_identity_count": 1,
            "selected_identities_subset_of_test": True,
            "frozen_test_sample_count": benchmark.EXPECTED_TEST_SAMPLES,
        }
        return sample, proof

    @staticmethod
    def _args(
        root: Path,
        checkpoint: Path,
        *,
        resume: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            num_images=1,
            dataset_root=root / "dataset",
            checkpoint=checkpoint,
            selection_report=root / "model_selection.json",
            training_config=root / "config.yaml",
            source_root=root / "LIDMark",
            report_dir=root / "report",
            device="cuda:0",
            expected_physical_gpu=2,
            seed=20260603,
            flush_every=1,
            resume=resume,
        )

    @staticmethod
    def _source_evidence() -> dict[str, object]:
        return {
            "path": "model-sources/LIDMark",
            "commit": benchmark.EXPECTED_SOURCE_COMMIT,
            "clean": True,
            "tracked_file_count": 20,
            "tracked_tree_sha256": benchmark.EXPECTED_SOURCE_TREE_SHA256,
        }

    @staticmethod
    def _training_evidence() -> dict[str, object]:
        return {
            "path": "reports/lidmark-training/config.yaml",
            "sha256": benchmark.EXPECTED_TRAINING_CONFIG_SHA256,
            "architecture": {"watermark_length": benchmark.PAYLOAD_LENGTH},
        }

    @staticmethod
    def _checkpoint_evidence(checkpoint: Path) -> dict[str, object]:
        return {
            "selection_report": "reports/lidmark-training/model_selection.json",
            "selection_report_sha256": benchmark.EXPECTED_SELECTION_SHA256,
            "selected_epoch": 20,
            "checkpoint": benchmark.logical_path(checkpoint),
            "checkpoint_sha256": benchmark.sha256_file(checkpoint),
            "checkpoint_size_bytes": checkpoint.stat().st_size,
        }

    @staticmethod
    def _finalize(summary: dict[str, object], **kwargs: object) -> dict[str, object]:
        checkpoint = Path(str(kwargs["checkpoint"]))
        results = Path(str(kwargs["results_path"]))
        manifest = Path(str(kwargs["dataset_manifest_path"]))
        finalized = dict(summary)
        finalized.update(
            {
                "schema_version": "benchmark-summary.v2",
                "status": "complete",
                "checkpoint": benchmark.logical_path(checkpoint),
                "checkpoint_sha256": benchmark.sha256_file(checkpoint),
                "dataset_manifest_path": benchmark.logical_path(manifest),
                "dataset_manifest_sha256": benchmark.sha256_file(manifest),
                "results_csv_path": benchmark.logical_path(results),
                "results_csv_sha256": benchmark.sha256_file(results),
                "protocol_version": "evaluation_protocol.v1",
                "protocol_path": "configs/evaluation_protocol.v1.json",
                "protocol_sha256": benchmark.sha256_file(
                    benchmark.PROJECT_DIR / "configs" / "evaluation_protocol.v1.json"
                ),
                "seed": kwargs["seed"],
                "num_images": kwargs["sample_count"],
                "attack_ids": kwargs["attack_ids"],
            }
        )
        return finalized

    def _main_patches(
        self,
        args: argparse.Namespace,
        sample: dict[str, object],
        proof: dict[str, object],
        model: object,
    ) -> tuple[object, ...]:
        return (
            mock.patch.object(benchmark, "parse_args", return_value=args),
            mock.patch.object(benchmark, "require_device_contract"),
            mock.patch.object(
                benchmark,
                "verify_source",
                return_value=self._source_evidence(),
            ),
            mock.patch.object(
                benchmark,
                "verify_training_config",
                return_value=self._training_evidence(),
            ),
            mock.patch.object(
                benchmark,
                "verify_checkpoint_selection",
                return_value=self._checkpoint_evidence(args.checkpoint),
            ),
            mock.patch.object(
                benchmark,
                "prepare_dataset",
                return_value=([sample], proof),
            ),
            mock.patch.object(benchmark, "build_model", return_value=model),
            mock.patch.object(
                benchmark,
                "finalize_benchmark_summary",
                side_effect=self._finalize,
            ),
            mock.patch("builtins.print"),
        )

    def test_protocol_requires_all_fifteen_canonical_attacks_in_order(self) -> None:
        self.assertEqual(len(self.attacks), benchmark.CANONICAL_ATTACK_COUNT)
        self.assertEqual(
            self.attacks,
            [str(entry["id"]) for entry in self.protocol["attacks"]],
        )
        self.assertEqual(set(self.attacks), set(ATTACKS))

        truncated = dict(self.protocol)
        truncated["attacks"] = list(self.protocol["attacks"][:-1])
        truncated["attack_ids"] = list(self.protocol["attack_ids"][:-1])
        with self.assertRaisesRegex(ValueError, "15 attacks"):
            benchmark.resolve_attacks(truncated)

        drifted = json.loads(json.dumps(self.protocol))
        jpeg = next(entry for entry in drifted["attacks"] if entry["id"] == "jpeg50")
        jpeg["parameters"]["quality"] = 49
        with self.assertRaisesRegex(ValueError, "parameter drift"):
            benchmark.resolve_attacks(drifted)

    def test_candidate_manifest_is_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "inputs.json"
            payload = {
                "schema_version": benchmark.INPUT_MANIFEST_SCHEMA,
                "selection_sha256": "a" * 64,
                "checkpoint_sha256": "b" * 64,
                "checkpoint_size_bytes": 71,
                "selected_epoch": 93,
                "training_config_sha256": "c" * 64,
                "training_seed": 20260813,
            }
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            benchmark.configure_input_expectations(manifest)
            self.assertEqual(benchmark.input_expectation("selected_epoch", 20), 93)
            payload["checkpoint_sha256"] = "unsafe"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                benchmark.configure_input_expectations(manifest)

    def test_identity_disjoint_proof_rejects_overlap_and_non_test_selection(self) -> None:
        splits = {
            "identity_disjoint": True,
            "splits": {
                "train": {"identities": ["Alice"], "identity_count": 1},
                "val": {"identities": ["Bob"], "identity_count": 1},
                "test": {"identities": ["Carol"], "identity_count": 1},
            },
        }
        identities = [
            {"identity": "Alice", "split": "train"},
            {"identity": "Bob", "split": "val"},
            {"identity": "Carol", "split": "test"},
        ]
        proof = benchmark.identity_disjoint_proof(splits, identities, {"Carol"})
        self.assertTrue(proof["identity_disjoint"])
        self.assertEqual(proof["overlap_counts"], {
            "train_val": 0,
            "train_test": 0,
            "val_test": 0,
        })

        overlapping = json.loads(json.dumps(splits))
        overlapping["splits"]["train"]["identities"].append("Carol")
        overlapping["splits"]["train"]["identity_count"] = 2
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            benchmark.identity_disjoint_proof(
                overlapping,
                identities,
                {"Carol"},
            )
        with self.assertRaisesRegex(RuntimeError, "non-test identity"):
            benchmark.identity_disjoint_proof(splits, identities, {"Alice"})

    def test_wilson95_has_finite_bounded_intervals(self) -> None:
        zero = benchmark.wilson95(0, 10)
        full = benchmark.wilson95(10, 10)
        mixed = benchmark.wilson95(3, 10)
        self.assertEqual(zero["lower"], 0.0)
        self.assertEqual(full["upper"], 1.0)
        self.assertLess(mixed["lower"], mixed["estimate"])
        self.assertGreater(mixed["upper"], mixed["estimate"])
        for interval in (zero, full, mixed):
            self.assertTrue(0.0 <= interval["lower"] <= interval["upper"] <= 1.0)
            self.assertTrue(
                all(
                    np.isfinite(float(interval[field]))
                    for field in ("estimate", "lower", "upper")
                )
            )
        for successes, total in ((0, 0), (-1, 2), (3, 2)):
            with self.subTest(successes=successes, total=total):
                with self.assertRaises(ValueError):
                    benchmark.wilson95(successes, total)

    def test_raw_results_reject_duplicates_nonfinite_metrics_and_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample, _ = self._sample(root)
            path = root / "raw_results.csv"
            row = benchmark._base_row(sample, "clean", self.protocol, 20260603)
            row.update(
                {
                    "bit_errors": "0",
                    "ber": "0.0000000000",
                    "bit_accuracy": "1.0000000000",
                    "identity_exact_match": "1",
                    "landmark_aed_px": "0.0000000000",
                    "watermarked_psnr": "48.0000000000",
                    "watermarked_ssim": "0.9990000000",
                    "psnr": "48.0000000000",
                    "ssim": "0.9990000000",
                    "success": "1",
                }
            )
            benchmark._atomic_write_csv(path, benchmark.RAW_RESULT_FIELDS, [row])
            loaded = benchmark.load_result_rows(
                path,
                [sample],
                ["clean"],
                self.protocol,
                20260603,
                0.9,
            )
            self.assertEqual(set(loaded), {("test/Alice_0001.jpg", "clean")})

            benchmark._atomic_write_csv(path, benchmark.RAW_RESULT_FIELDS, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate raw result"):
                benchmark.load_result_rows(
                    path,
                    [sample],
                    ["clean"],
                    self.protocol,
                    20260603,
                    0.9,
                )

            nonfinite = dict(row, psnr="nan")
            benchmark._atomic_write_csv(
                path, benchmark.RAW_RESULT_FIELDS, [nonfinite]
            )
            with self.assertRaisesRegex(ValueError, "non-finite"):
                benchmark.load_result_rows(
                    path,
                    [sample],
                    ["clean"],
                    self.protocol,
                    20260603,
                    0.9,
                )

            absolute = dict(row, source_path="/srv/private/Alice_0001.jpg")
            benchmark._atomic_write_csv(path, benchmark.RAW_RESULT_FIELDS, [absolute])
            with self.assertRaisesRegex(ValueError, "absolute host path"):
                benchmark.load_result_rows(
                    path,
                    [sample],
                    ["clean"],
                    self.protocol,
                    20260603,
                    0.9,
                )

            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(benchmark.RAW_RESULT_FIELDS)
                writer.writerow([*(row[field] for field in benchmark.RAW_RESULT_FIELDS), "x"])
            with self.assertRaisesRegex(ValueError, "outside the declared schema"):
                benchmark.load_result_rows(
                    path,
                    [sample],
                    ["clean"],
                    self.protocol,
                    20260603,
                    0.9,
                )

    def test_manifest_and_run_config_are_content_bound_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample, proof = self._sample(root)
            manifest_path = root / "dataset_manifest.json"
            manifest = benchmark.dataset_manifest_payload(
                root,
                [sample],
                proof,
                20260603,
            )
            benchmark.ensure_dataset_manifest(manifest_path, manifest, True)
            self.assertEqual(manifest["schema_version"], "dataset-manifest.v1")
            self.assertEqual(manifest["sample_count"], 1)
            self.assertEqual(manifest["files"][0]["path"], sample["source_path"])
            self.assertNotIn(str(root.resolve()), json.dumps(manifest))

            with self.assertRaisesRegex(RuntimeError, "pass --resume"):
                benchmark.ensure_dataset_manifest(manifest_path, manifest, False)
            mutated_manifest = json.loads(json.dumps(manifest))
            mutated_manifest["seed"] = 7
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                benchmark.ensure_dataset_manifest(
                    manifest_path,
                    mutated_manifest,
                    True,
                )

            config_path = root / "run_config.json"
            config = {"schema_version": "v1", "seed": 20260603}
            benchmark._ensure_run_config(
                config_path,
                config,
                resume=False,
                result_state_exists=False,
            )
            benchmark._ensure_run_config(
                config_path,
                config,
                resume=True,
                result_state_exists=True,
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                benchmark._ensure_run_config(
                    config_path,
                    {**config, "seed": 7},
                    resume=True,
                    result_state_exists=True,
                )

    def test_main_writes_complete_fifteen_attack_evidence_and_resumes(self) -> None:
        class FakeModel:
            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = checkpoint
                self.payload = np.zeros(benchmark.PAYLOAD_LENGTH, dtype=np.float32)
                self.encode_calls = 0
                self.decode_calls = 0

            def encode(self, image: np.ndarray, payload: np.ndarray) -> np.ndarray:
                self.encode_calls += 1
                self.payload = payload.copy()
                return np.clip(image.astype(np.int16) + 1, 0, 255).astype(np.uint8)

            def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                self.decode_calls += 1
                return {
                    "landmarks": self.payload[: benchmark.LANDMARK_LENGTH].copy(),
                    "identity_logits": self.payload[
                        benchmark.LANDMARK_LENGTH :
                    ].copy(),
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample, proof = self._sample(root)
            checkpoint = root / "checkpoint_epoch_20.pth"
            checkpoint.write_bytes(b"lidmark-epoch-20-test-fixture")
            args = self._args(root, checkpoint)
            model = FakeModel(checkpoint)
            patches = self._main_patches(args, sample, proof, model)
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], patches[6], patches[7] as finalizer, patches[8]:
                exit_code = benchmark.main()
            self.assertEqual(exit_code, 0)
            self.assertEqual(model.encode_calls, 1)
            self.assertEqual(model.decode_calls, benchmark.CANONICAL_ATTACK_COUNT)
            finalizer.assert_called_once()
            self.assertEqual(
                finalizer.call_args.kwargs["attack_ids"],
                self.attacks,
            )

            report_dir = args.report_dir
            with (report_dir / "raw_results.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), benchmark.CANONICAL_ATTACK_COUNT)
            self.assertEqual([row["attack"] for row in rows], self.attacks)
            self.assertEqual([row["attack_type"] for row in rows], self.attacks)
            self.assertTrue(all(row["success"] == "1" for row in rows))
            self.assertTrue(all(not row["error"] for row in rows))
            self.assertTrue(all(float(row["ber"]) == 0.0 for row in rows))
            self.assertTrue(
                all(row["message_sha256"] == sample["message_sha256"] for row in rows)
            )

            summary = json.loads(
                (report_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["schema_version"], "benchmark-summary.v2")
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["expected_result_rows"], 15)
            self.assertEqual(summary["error_rows"], 0)
            self.assertRegex(summary["results_csv_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(summary["run_config_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(summary["identity_disjoint_proof"]["identity_disjoint"])
            for attack in self.attacks:
                interval = summary["attacks"][attack]["success_rate_wilson95"]
                self.assertEqual(interval["successes"], 1)
                self.assertEqual(interval["total"], 1)
            claim_rows_valid, claim_audit = _csv_structure_valid(
                report_dir / "raw_results.csv",
                sample_count=1,
                attack_ids=self.attacks,
                summary=summary,
                success_threshold=float(self.protocol["success_threshold"]),
            )
            self.assertTrue(claim_rows_valid, claim_audit)

            manifest = json.loads(
                (report_dir / "dataset_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], "dataset-manifest.v1")
            self.assertEqual(len(manifest["files"]), 1)
            self.assertNotIn(str(root.resolve()), json.dumps(manifest))

            class ResumeModel(FakeModel):
                def encode(self, image: np.ndarray, payload: np.ndarray) -> np.ndarray:
                    raise AssertionError("completed rows must not be recomputed")

                def decode(self, _image: np.ndarray) -> dict[str, np.ndarray]:
                    raise AssertionError("completed rows must not be recomputed")

            resume_args = self._args(root, checkpoint, resume=True)
            resume_model = ResumeModel(checkpoint)
            resume_patches = self._main_patches(
                resume_args,
                sample,
                proof,
                resume_model,
            )
            with resume_patches[0], resume_patches[1], resume_patches[2], \
                    resume_patches[3], resume_patches[4], resume_patches[5], \
                    resume_patches[6], resume_patches[7], resume_patches[8]:
                resumed_exit_code = benchmark.main()
            self.assertEqual(resumed_exit_code, 0)

    def test_decode_errors_are_recorded_and_block_finalization(self) -> None:
        class FailingModel:
            def __init__(self, checkpoint: Path) -> None:
                self.checkpoint = checkpoint

            @staticmethod
            def encode(image: np.ndarray, _payload: np.ndarray) -> np.ndarray:
                return np.clip(image.astype(np.int16) + 1, 0, 255).astype(np.uint8)

            @staticmethod
            def decode(_image: np.ndarray) -> dict[str, np.ndarray]:
                raise RuntimeError("fixture decoder failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample, proof = self._sample(root)
            checkpoint = root / "checkpoint_epoch_20.pth"
            checkpoint.write_bytes(b"lidmark-epoch-20-test-fixture")
            args = self._args(root, checkpoint)
            model = FailingModel(checkpoint)
            patches = self._main_patches(args, sample, proof, model)
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], patches[6], patches[7] as finalizer, patches[8]:
                exit_code = benchmark.main()
            self.assertEqual(exit_code, 2)
            finalizer.assert_not_called()

            with (args.report_dir / "raw_results.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), benchmark.CANONICAL_ATTACK_COUNT)
            self.assertTrue(all(row["success"] == "0" for row in rows))
            self.assertTrue(
                all(row["error"] == "attack_or_decode:RuntimeError" for row in rows)
            )
            summary = json.loads(
                (args.report_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "incomplete")
            self.assertEqual(summary["error_rows"], benchmark.CANONICAL_ATTACK_COUNT)
            self.assertEqual(
                summary["input_integrity_audit"]["status"],
                "verified",
            )


if __name__ == "__main__":
    unittest.main()
