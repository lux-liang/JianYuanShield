from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from system.scripts.aggregate_common_intersection import (
    CommonIntersectionError,
    aggregate,
)


ATTACKS = ["clean", "jpeg50"]
MODELS = {
    "LIDMark": ("bit_accuracy", "identity"),
    "KAD-Net": ("bit_accuracy", None),
    "SepMark": ("bit_accuracy_c", None),
    "WaveGuard": ("bit_accuracy_tracer", None),
}


class CommonIntersectionTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        reports = root / "reports"
        model_config = {}
        for index, (model, (metric, identity_field)) in enumerate(MODELS.items()):
            directory = reports / model
            directory.mkdir(parents=True)
            fieldnames = [
                "image_id",
                "attack_type",
                "attack_config_sha256",
                metric,
                "success",
                "error",
            ]
            if identity_field:
                fieldnames.append(identity_field)
            rows = []
            for image_index, image in enumerate(("test/A_0001.jpg", "test/B_0001.jpg")):
                for attack_index, attack in enumerate(ATTACKS):
                    success = int(not (index == 3 and image_index == 1 and attack_index == 1))
                    row = {
                        "image_id": image,
                        "attack_type": attack,
                        "attack_config_sha256": hashlib.sha256(attack.encode()).hexdigest(),
                        metric: "1.0" if success else "0.5",
                        "success": str(success),
                        "error": "",
                    }
                    if identity_field:
                        row[identity_field] = image.split("/")[1].rsplit("_", 1)[0]
                    rows.append(row)
            results = directory / "results.csv"
            with results.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            digest = hashlib.sha256(results.read_bytes()).hexdigest()
            (directory / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "attack_ids": ATTACKS,
                        "error_rows": 0,
                        "missing_rows": 0,
                        "expected_result_rows": 4,
                        "result_rows": 4,
                        "results_csv_sha256": digest,
                        "checkpoint_sha256": hashlib.sha256(model.encode()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            entry = {
                "summary": f"reports/{model}/summary.json",
                "results": f"reports/{model}/results.csv",
                "image_field": "image_id",
                "attack_field": "attack_type",
                "bit_accuracy_field": metric,
                "success_field": "success",
                "error_field": "error",
            }
            if identity_field:
                entry["identity_field"] = identity_field
            model_config[model] = entry
        config = {
            "schema_version": "common-intersection-protocol.v1",
            "protocol_id": "test-common",
            "reference_model": "LIDMark",
            "expected_common_images": 2,
            "expected_identity_clusters": 2,
            "attack_ids": ATTACKS,
            "models": model_config,
            "attack_config_field": "attack_config_sha256",
            "statistics": {
                "confidence_level": 0.95,
                "bootstrap_repetitions": 128,
                "seed": 7,
            },
            "comparison_policy": {"cross_model_metric": "protocol_threshold_success"},
        }
        path = root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_exact_intersection_and_joint_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._fixture(root)
            summary, csv_bytes, report_bytes = aggregate(
                config_path=config,
                evidence_root=root,
            )
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["common_images"], 2)
            self.assertEqual(summary["identity_clusters"], 2)
            self.assertEqual(
                summary["attacks"]["jpeg50"]["models"]["WaveGuard"]["success_rate"],
                0.5,
            )
            self.assertEqual(
                summary["attacks"]["jpeg50"]["all_models_joint"]["success_rate"],
                0.5,
            )
            self.assertIn(b"ALL_MODELS", csv_bytes)
            self.assertIn("四模型联合通过".encode(), report_bytes)

    def test_results_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._fixture(root)
            results = root / "reports" / "KAD-Net" / "results.csv"
            results.write_bytes(results.read_bytes() + b"\n")
            with self.assertRaisesRegex(CommonIntersectionError, "results hash mismatch"):
                aggregate(config_path=config, evidence_root=root)


if __name__ == "__main__":
    unittest.main()
