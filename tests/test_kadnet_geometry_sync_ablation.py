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

from system.scripts import run_kadnet_geometry_sync_ablation as ablation


class FakeKADAdapter:
    name = "KAD-Net"
    message_length = 8
    available = True
    blocker = None

    def __init__(self, checkpoint: Path) -> None:
        self.checkpoint = str(checkpoint)

    def encode(self, image: np.ndarray, message: np.ndarray) -> SimpleNamespace:
        encoded = image.copy()
        encoded.reshape(-1)[: self.message_length] = (
            np.asarray(message, dtype=np.uint8) * 255
        )
        return SimpleNamespace(
            image=encoded,
            message=np.asarray(message, dtype=np.uint8),
            metadata={"checkpoint": self.checkpoint},
        )

    def decode(self, image: np.ndarray) -> SimpleNamespace:
        bits = (image.reshape(-1)[: self.message_length] > 127).astype(np.uint8)
        return SimpleNamespace(bits=bits, metadata={"decoder": "fake"})


def make_fixture(root: Path) -> tuple[Path, Path]:
    image_root = root / "images"
    for index, identity in enumerate(("alice", "bob", "carol", "dave")):
        path = image_root / identity / f"{identity}_0001.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        array = np.full((20, 20, 3), 50 + index * 40, dtype=np.uint8)
        array[4:16, 5:15, 0] = 220 - index * 10
        Image.fromarray(array).save(path)
    checkpoint = root / "EC_100.pth"
    checkpoint.write_bytes(b"kadnet-geometry-sync-test-checkpoint")
    return image_root, checkpoint


def fake_args(root: Path, image_root: Path, checkpoint: Path) -> argparse.Namespace:
    return argparse.Namespace(
        num_images=4,
        image_root=image_root,
        checkpoint=checkpoint,
        report_dir=root / "reports",
        asset_dir=root / "assets",
        device="cpu",
        seed=20260603,
        target_far=1.0,
        artifact_limit=0,
        flush_every=2,
    )


def calibration_row(
    *,
    index: int,
    split: str,
    control: str,
    direct: float,
    sync: float,
) -> dict[str, str]:
    return {
        "sample_id": f"sample-{index}",
        "split": split,
        "label": "positive" if control == "registered_roundtrip" else "negative",
        "control": control,
        "attack_type": "clean",
        "identity_sha256": f"identity-{index}",
        "direct_bit_accuracy": str(direct),
        "sync_bit_accuracy": str(sync),
        "error": "",
    }


class KADNetGeometrySyncAblationTests(unittest.TestCase):
    def test_cli_defaults_fix_scope_without_mutating_protocol(self) -> None:
        args = ablation.parse_args([])
        self.assertEqual(args.num_images, 256)
        self.assertEqual(
            ablation.ATTACK_IDS,
            ("clean", "crop_center_0.8", "rotate_5"),
        )
        self.assertEqual(
            ablation.NEGATIVE_CONTROLS,
            ("unwatermarked", "wrong_message", "cross_record_watermarked"),
        )
        self.assertTrue(
            args.image_root.as_posix().endswith(
                "lfw/processed/image/lfw_128"
            )
        )
        self.assertEqual(args.checkpoint.name, "EC_100.pth")

    def test_identity_split_and_cross_record_pairing_are_isolated(self) -> None:
        identifiers = [
            "test/Alice_0001.jpg",
            "test/Alice_0002.jpg",
            "test/Bob_0001.jpg",
            "test/Carol_0001.jpg",
            "test/Dave_0001.jpg",
        ]
        assignments = ablation.deterministic_identity_splits(identifiers, 7)
        repeated = ablation.deterministic_identity_splits(
            list(reversed(identifiers)),
            7,
        )
        self.assertEqual(assignments, repeated)
        self.assertEqual(
            assignments["test/Alice_0001.jpg"],
            assignments["test/Alice_0002.jpg"],
        )
        calibration_identities = {
            ablation.identity_sha256(identifier)
            for identifier, split in assignments.items()
            if split == "calibration"
        }
        holdout_identities = {
            ablation.identity_sha256(identifier)
            for identifier, split in assignments.items()
            if split == "holdout"
        }
        self.assertFalse(calibration_identities & holdout_identities)

        sources = ablation.cross_record_sources(identifiers, assignments, 7)
        for target, source in sources.items():
            self.assertEqual(assignments[target], assignments[source])
            self.assertNotEqual(
                ablation.identity_sha256(target),
                ablation.identity_sha256(source),
            )

    def test_thresholds_use_calibration_only_for_direct_and_sync(self) -> None:
        rows = []
        index = 0
        for split in ("calibration", "holdout"):
            values = {
                "registered_roundtrip": (0.90, 0.95),
                "unwatermarked": (0.60, 0.70),
                "wrong_message": (0.50, 0.55),
                "cross_record_watermarked": (0.40, 0.45),
            }
            for control, (direct, sync) in values.items():
                rows.append(calibration_row(
                    index=index,
                    split=split,
                    control=control,
                    direct=direct,
                    sync=sync,
                ))
                index += 1

        direct_threshold, direct_selection, _ = ablation.select_threshold(
            rows,
            "direct_bit_accuracy",
            0.0,
        )
        sync_threshold, sync_selection, _ = ablation.select_threshold(
            rows,
            "sync_bit_accuracy",
            0.0,
        )
        self.assertFalse(direct_selection["holdout_used_for_selection"])
        self.assertFalse(sync_selection["holdout_used_for_selection"])
        self.assertEqual(
            set(direct_selection["required_negative_controls"]),
            set(ablation.NEGATIVE_CONTROLS),
        )

        changed = [dict(row) for row in rows]
        for row in changed:
            if row["split"] == "holdout":
                row["direct_bit_accuracy"] = "1.0"
                row["sync_bit_accuracy"] = "0.0"
        changed_direct, _, _ = ablation.select_threshold(
            changed,
            "direct_bit_accuracy",
            0.0,
        )
        changed_sync, _, _ = ablation.select_threshold(
            changed,
            "sync_bit_accuracy",
            0.0,
        )
        self.assertEqual(changed_direct, direct_threshold)
        self.assertEqual(changed_sync, sync_threshold)

        missing_cross_control = [
            row
            for row in rows
            if not (
                row["split"] == "calibration"
                and row["control"] == "cross_record_watermarked"
            )
        ]
        with self.assertRaisesRegex(ValueError, "cross_record_watermarked"):
            ablation.select_threshold(
                missing_cross_control,
                "direct_bit_accuracy",
                0.0,
            )

    def test_cpu_fake_adapter_writes_complete_hashed_ablation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root, checkpoint = make_fixture(root)
            args = fake_args(root, image_root, checkpoint)
            with mock.patch.object(
                ablation,
                "build_adapter",
                return_value=FakeKADAdapter(checkpoint),
            ):
                summary = ablation.run_ablation(args)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["mode"], "experimental_non_claim_ablation")
            self.assertFalse(summary["formal_claim_eligible"])
            self.assertFalse(summary["claim_valid"])
            self.assertEqual(summary["sample_count"], 4)
            self.assertEqual(summary["expected_result_rows"], 48)
            self.assertTrue(summary["coverage"]["complete"])
            self.assertEqual(summary["identity_split"]["identity_overlap"], 0)
            for field in (
                "checkpoint_sha256",
                "dataset_manifest_sha256",
                "protocol_sha256",
                "attack_contract_sha256",
                "search_contract_sha256",
                "results_csv_sha256",
                "run_config_sha256",
            ):
                self.assertRegex(summary[field], r"^[0-9a-f]{64}$")

            with (root / "reports" / "results.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 48)
            self.assertEqual({row["attack_type"] for row in rows}, set(ablation.ATTACK_IDS))
            self.assertEqual({row["control"] for row in rows}, set(ablation.CONTROLS))
            self.assertTrue(all(not row["error"] for row in rows))
            self.assertTrue(all(row["direct_bit_accuracy"] for row in rows))
            self.assertTrue(all(row["sync_bit_accuracy"] for row in rows))
            self.assertTrue(all(
                len(json.loads(row["sync_candidate_scores_json"])) == 4
                for row in rows
            ))
            corrupted = dict(rows[0], direct_bit_accuracy="nan")
            expected = ablation.bits_from_text(
                corrupted["registered_message_bits"],
                FakeKADAdapter.message_length,
            )
            with self.assertRaisesRegex(ValueError, "direct bit-accuracy"):
                ablation._validate_scored_row(
                    corrupted,
                    expected,
                    FakeKADAdapter.message_length,
                )

            for method in ("direct", "sync"):
                analysis = summary["analysis"][method]
                self.assertFalse(
                    analysis["threshold_selection"]["holdout_used_for_selection"]
                )
                holdout = analysis["holdout_metrics"]
                self.assertEqual(set(holdout["rates"]), {"TAR", "FAR", "FRR"})
                self.assertEqual(set(holdout["wilson_95"]), {"TAR", "FAR", "FRR"})
                self.assertEqual(
                    set(holdout["negative_control_metrics"]),
                    set(ablation.NEGATIVE_CONTROLS),
                )
                self.assertEqual(
                    set(analysis["holdout_by_attack"]),
                    set(ablation.ATTACK_IDS),
                )

            serialized = (root / "reports" / "summary.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(str(root.resolve()), serialized)
            manifest = json.loads(
                (root / "reports" / "dataset_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["sample_count"], 4)
            self.assertFalse(any(
                entry["identity_sha256"]
                == next(
                    item["identity_sha256"]
                    for item in manifest["files"]
                    if item["image_id"] == entry["cross_record_source_image_id"]
                )
                for entry in manifest["files"]
            ))

    def test_decode_errors_are_rows_and_block_complete_status(self) -> None:
        class FailingAdapter(FakeKADAdapter):
            def decode(self, image: np.ndarray) -> SimpleNamespace:
                raise RuntimeError("intentional decode failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root, checkpoint = make_fixture(root)
            args = fake_args(root, image_root, checkpoint)
            with mock.patch.object(
                ablation,
                "build_adapter",
                return_value=FailingAdapter(checkpoint),
            ):
                summary = ablation.run_ablation(args)

            self.assertEqual(summary["status"], "incomplete")
            self.assertFalse(summary["coverage"]["complete"])
            self.assertEqual(summary["coverage"]["error_rows"], 48)
            self.assertFalse(summary["analysis"])
            with (root / "reports" / "results.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 48)
            self.assertTrue(all(row["error"] == "direct_decode:RuntimeError" for row in rows))
            self.assertTrue(all(not row["direct_bit_accuracy"] for row in rows))
            self.assertRegex(summary["results_csv_sha256"], r"^[0-9a-f]{64}$")

    def test_wilson_interval_contains_empirical_rate(self) -> None:
        interval = ablation.wilson_interval(3, 10)
        self.assertLessEqual(interval["lower"], 0.3)
        self.assertGreaterEqual(interval["upper"], 0.3)
        self.assertEqual(interval["confidence_level"], 0.95)


if __name__ == "__main__":
    unittest.main()
