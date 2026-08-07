from __future__ import annotations

import argparse
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

from system.scripts import calibrate_provenance_threshold as calibration


def score_row(split: str, control: str, score: float, index: int) -> dict[str, object]:
    return {
        "sample_id": f"sample-{index}",
        "image_id": f"person-{index}/image.jpg",
        "split": split,
        "attack_id": "clean",
        "control": control,
        "label": "positive" if control == "registered_roundtrip" else "negative",
        "bit_accuracy": score,
    }


class ThresholdCalibrationTests(unittest.TestCase):
    def test_flat_lfw_paths_derive_real_identity_not_split_directory(self) -> None:
        first = calibration.identity_sha256("test/Zafarullah_Khan_Jamali_0001.jpg")
        second = calibration.identity_sha256("test/Zafarullah_Khan_Jamali_0002.jpg")
        other = calibration.identity_sha256("test/Zhang_Ziyi_0001.jpg")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_identity_split_is_deterministic_and_has_no_leakage(self) -> None:
        identifiers = [
            "alice/one.jpg",
            "alice/two.jpg",
            "bob/one.jpg",
            "carol/one.jpg",
            "dave/one.jpg",
        ]
        first = calibration.deterministic_splits(identifiers, 41)
        second = calibration.deterministic_splits(list(reversed(identifiers)), 41)
        self.assertEqual(first, second)
        self.assertEqual(first["alice/one.jpg"], first["alice/two.jpg"])
        self.assertEqual(set(first.values()), {"calibration", "holdout"})

    def test_threshold_is_selected_only_from_calibration_split(self) -> None:
        samples = [
            score_row("calibration", "registered_roundtrip", 0.90, 1),
            score_row("calibration", "unwatermarked", 0.80, 2),
            score_row("calibration", "wrong_message", 0.70, 3),
            score_row("holdout", "registered_roundtrip", 0.10, 4),
            score_row("holdout", "unwatermarked", 0.99, 5),
            score_row("holdout", "wrong_message", 0.98, 6),
        ]
        threshold, metadata, metrics = calibration.select_threshold(samples, 0.0)
        self.assertEqual(threshold, math.nextafter(0.8, math.inf))
        self.assertEqual(metadata["split"], "calibration")
        self.assertEqual(metrics["true_accept_rate"], 1.0)
        self.assertEqual(metrics["false_accept_rate"], 0.0)

        changed_holdout = [dict(row) for row in samples]
        for row in changed_holdout:
            if row["split"] == "holdout":
                row["bit_accuracy"] = 0.5
        changed_threshold, _, _ = calibration.select_threshold(changed_holdout, 0.0)
        self.assertEqual(changed_threshold, threshold)

    def test_wilson_interval_contains_empirical_rate(self) -> None:
        interval = calibration.wilson_interval(3, 10)
        self.assertLessEqual(interval["lower"], 0.3)
        self.assertGreaterEqual(interval["upper"], 0.3)
        self.assertEqual(interval["confidence_level"], 0.95)
        self.assertEqual(calibration.wilson_interval(0, 10)["lower"], 0.0)
        self.assertEqual(calibration.wilson_interval(10, 10)["upper"], 1.0)

    def test_fake_adapter_writes_complete_three_control_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root = root / "images"
            output = root / "calibration.json"
            checkpoint = root / "checkpoint.pth"
            checkpoint.write_bytes(b"real-checkpoint-identity")
            for index, identity in enumerate(("alice", "bob", "carol", "dave")):
                path = image_root / identity / "one.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(np.full((8, 8, 3), 127 + index, dtype=np.uint8)).save(path)

            class FakeAdapter:
                name = "Fake"
                message_length = 4
                available = True
                blocker = None

                @property
                def checkpoint(self) -> str:
                    return str(checkpoint)

                def validate_image(self, image: np.ndarray) -> None:
                    if image.shape != (8, 8, 3) or image.dtype != np.uint8:
                        raise ValueError("bad image")

                def encode(self, image: np.ndarray, message: np.ndarray) -> SimpleNamespace:
                    encoded = image.copy()
                    encoded.reshape(-1)[:4] = np.asarray(message, dtype=np.uint8) * 255
                    return SimpleNamespace(image=encoded, message=message, metadata={"checkpoint": str(checkpoint)})

                def decode(self, image: np.ndarray) -> SimpleNamespace:
                    bits = (image.reshape(-1)[:4] > 127).astype(np.uint8)
                    return SimpleNamespace(bits=bits, metadata={})

            args = argparse.Namespace(
                model="Fake",
                image_root=image_root,
                output=output,
                num_images=4,
                attacks=["clean"],
                device="cpu",
                seed=123,
                target_far=1.0,
                flush_every=2,
            )
            with mock.patch.object(calibration, "get_available_adapters", return_value={"Fake": FakeAdapter}):
                artifact = calibration.run_calibration(args)

            self.assertEqual(artifact["status"], "complete")
            self.assertEqual(artifact["schema_version"], "threshold-calibration.v1")
            self.assertEqual(
                artifact["dataset_manifest"]["identity_derivation"],
                calibration.IDENTITY_DERIVATION,
            )
            self.assertEqual(artifact["coverage"]["expected_rows"], 12)
            self.assertEqual(artifact["coverage"]["actual_rows"], 12)
            self.assertTrue(artifact["coverage"]["complete"])
            self.assertFalse(artifact["errors"])
            self.assertEqual({row["control"] for row in artifact["samples"]}, set(calibration.CONTROLS))
            self.assertEqual(artifact["metrics"]["split"], "holdout")
            self.assertEqual(
                artifact["metrics"]["negative_samples"],
                2 * artifact["metrics"]["positive_samples"],
            )
            by_identity: dict[str, set[str]] = {}
            for row in artifact["samples"]:
                by_identity.setdefault(str(row["identity_sha256"]), set()).add(str(row["split"]))
            self.assertTrue(all(len(splits) == 1 for splits in by_identity.values()))
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn(str(root), serialized)
            self.assertEqual(json.loads(serialized), artifact)

            partial = dict(artifact)
            partial["status"] = "incomplete"
            partial["samples"] = list(artifact["samples"][:-1])
            partial["threshold"] = None
            partial["threshold_selection"] = None
            partial["calibration_metrics"] = None
            partial["metrics"] = None
            partial["errors"] = []
            partial["coverage"] = calibration.coverage_report(
                partial["samples"],
                [item["image_id"] for item in artifact["dataset_manifest"]["files"]],
                {
                    item["image_id"]: item["split"]
                    for item in artifact["dataset_manifest"]["files"]
                },
                ["clean"],
                model="Fake",
                seed=123,
            )
            output.write_text(json.dumps(partial), encoding="utf-8")
            with mock.patch.object(calibration, "get_available_adapters", return_value={"Fake": FakeAdapter}):
                resumed = calibration.run_calibration(args)
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(resumed["coverage"]["actual_rows"], 12)

    def test_missing_row_fails_strict_coverage(self) -> None:
        identifiers = ["alice/a.jpg", "bob/b.jpg"]
        assignments = calibration.deterministic_splits(identifiers, 3)
        samples = [
            {
                "image_id": identifier,
                "attack_id": "clean",
                "control": control,
                "split": assignments[identifier],
            }
            for identifier in identifiers
            for control in calibration.CONTROLS
        ]
        complete = calibration.coverage_report(samples, identifiers, assignments, ["clean"])
        self.assertTrue(complete["complete"])
        incomplete = calibration.coverage_report(samples[:-1], identifiers, assignments, ["clean"])
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["expected_rows"], 6)
        self.assertEqual(incomplete["actual_rows"], 5)


if __name__ == "__main__":
    unittest.main()
