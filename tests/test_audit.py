from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

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
            result = analyze_csv("test", path)
            self.assertEqual(result["duplicate_keys"], 1)
            self.assertEqual(result["ber_accuracy_pair_mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
