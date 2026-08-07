from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system.scripts.audit_benchmark_results import analyze_csv, metric_summary, wilson


class AuditTests(unittest.TestCase):
    def test_metric_summary_has_confidence_interval(self) -> None:
        summary = metric_summary([0.1, 0.2, 0.3])
        self.assertEqual(summary["count"], 3)
        self.assertLess(summary["ci95_low"], summary["mean"])
        self.assertGreater(summary["ci95_high"], summary["mean"])

    def test_wilson_interval(self) -> None:
        low, high = wilson(90, 100)
        self.assertLess(low, 0.9)
        self.assertGreater(high, 0.9)

    def test_csv_audit_detects_duplicate_and_pair_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["image_id", "attack_type", "bit_error", "bit_accuracy", "success"])
                writer.writeheader()
                writer.writerow({"image_id": "a", "attack_type": "clean", "bit_error": 0.1, "bit_accuracy": 0.9, "success": 1})
                writer.writerow({"image_id": "a", "attack_type": "clean", "bit_error": 0.2, "bit_accuracy": 0.7, "success": 0})
            (path.parent / "summary.json").write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "num_images": 1,
                    "attack_ids": ["clean"],
                    "results_csv_path": "reports/results.csv",
                    "results_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }),
                encoding="utf-8",
            )
            with patch(
                "system.scripts.audit_benchmark_results.resolve_logical_path",
                return_value=path,
            ):
                result = analyze_csv("test", path)
            self.assertEqual(result["duplicate_keys"], 1)
            self.assertEqual(result["ber_accuracy_pair_mismatches"], 1)

    def test_csv_audit_rejects_missing_metrics_and_attack_sample_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["image_id", "attack_type", "error"],
                )
                writer.writeheader()
                for image_id, attack in (
                    ("a", "clean"),
                    ("b", "clean"),
                    ("c", "jpeg50"),
                    ("d", "jpeg50"),
                ):
                    writer.writerow({
                        "image_id": image_id,
                        "attack_type": attack,
                        "error": "",
                    })
            (root / "summary.json").write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "sample_count": 2,
                    "attack_ids": ["clean", "jpeg50"],
                    "results_csv_path": "reports/results.csv",
                    "results_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }),
                encoding="utf-8",
            )
            with patch(
                "system.scripts.audit_benchmark_results.resolve_logical_path",
                return_value=path,
            ):
                result = analyze_csv("KAD-Net", path)
        codes = {finding["code"] for finding in result["findings"]}
        self.assertEqual(result["status"], "review_required")
        self.assertIn("primary_metric_schema_missing", codes)
        self.assertIn("per_attack_sample_set_mismatch", codes)

    def test_csv_audit_rejects_fractional_success_and_corrupt_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "results.csv"
            path.write_text(
                "image_id,attack_type,bit_accuracy,error,success\n"
                "a,clean,0.9,,0.5\n",
                encoding="utf-8",
            )
            summary_path = root / "summary.json"
            summary_path.write_text(json.dumps({
                "schema_version": "benchmark-summary.v2",
                "status": "complete",
                "sample_count": 1,
                "attack_ids": ["clean"],
                "results_csv_path": "reports/results.csv",
                "results_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            with patch(
                "system.scripts.audit_benchmark_results.resolve_logical_path",
                return_value=path,
            ):
                result = analyze_csv("KAD-Net", path)
            self.assertEqual(result["status"], "review_required")
            self.assertIn(
                "invalid_success",
                {finding["code"] for finding in result["findings"]},
            )

            summary_path.write_bytes(b"\xff\xfe")
            corrupt = analyze_csv("KAD-Net", path)
            self.assertEqual(corrupt["status"], "invalid_summary")
            self.assertEqual(corrupt["findings"][0]["code"], "summary_invalid")


if __name__ == "__main__":
    unittest.main()
