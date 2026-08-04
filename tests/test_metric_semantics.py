from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system.backend.demo import _primary_decode_metrics
from system.scripts import run_statistical_analysis as statistics_runner
from system.scripts.run_statistical_analysis import load_source


class MetricSemanticsTests(unittest.TestCase):
    def test_statistical_runner_exits_nonzero_without_complete_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_root = Path(directory)
            with (
                patch.object(statistics_runner, "SOURCES", {}),
                patch.object(statistics_runner, "REPORT_ROOT", report_root),
                patch("builtins.print"),
            ):
                result = statistics_runner.main()
            payload = json.loads(
                (report_root / "statistical_analysis" / "analysis.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(result, 2)
        self.assertEqual(payload["status"], "blocked_incomplete_sources")

    def test_sepmark_uses_decoder_c_as_primary(self) -> None:
        accuracy, ber = _primary_decode_metrics(
            "SepMark",
            {
                "bit_accuracy_c": 0.82,
                "ber_c": 0.18,
                "bit_accuracy_rf": 0.99,
                "ber_rf": 0.01,
            },
        )
        self.assertAlmostEqual(accuracy, 0.82)
        self.assertAlmostEqual(ber, 0.18)

    def test_waveguard_uses_tracer_as_primary(self) -> None:
        accuracy, ber = _primary_decode_metrics(
            "WaveGuard",
            {
                "bit_accuracy_tracer": 0.77,
                "ber_tracer": 0.23,
                "bit_accuracy_detector": 1.0,
                "ber_detector": 0.0,
            },
        )
        self.assertAlmostEqual(accuracy, 0.77)
        self.assertAlmostEqual(ber, 0.23)

    def test_statistics_candidate_order_prefers_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "image_id",
                        "attack_type",
                        "bit_accuracy_tracer",
                        "bit_accuracy_detector",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "image_id": "face-1",
                        "attack_type": "clean",
                        "bit_accuracy_tracer": "0.75",
                        "bit_accuracy_detector": "1.0",
                    }
                )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (path.parent / "summary.json").write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "num_images": 1,
                    "attack_ids": ["clean"],
                    "results_csv_path": "reports/results.csv",
                    "results_csv_sha256": digest,
                }),
                encoding="utf-8",
            )
            with patch(
                "system.scripts.run_statistical_analysis.resolve_logical_path",
                return_value=path,
            ):
                values, audit = load_source(
                    path,
                    ("bit_accuracy_tracer", "bit_accuracy_detector"),
                )
        self.assertEqual(values[("face-1", "clean")], 0.75)
        self.assertEqual(audit["rows"], 1)

    def test_statistics_rejects_row_level_decoder_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "image_id",
                        "attack_type",
                        "bit_accuracy_tracer",
                        "bit_accuracy_detector",
                        "error",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "image_id": "face-1",
                    "attack_type": "clean",
                    "bit_accuracy_tracer": "0.75",
                    "bit_accuracy_detector": "1.0",
                    "error": "",
                })
                writer.writerow({
                    "image_id": "face-2",
                    "attack_type": "clean",
                    "bit_accuracy_tracer": "",
                    "bit_accuracy_detector": "1.0",
                    "error": "",
                })
            (path.parent / "summary.json").write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "num_images": 2,
                    "attack_ids": ["clean"],
                    "results_csv_path": "reports/results.csv",
                    "results_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }),
                encoding="utf-8",
            )
            with patch(
                "system.scripts.run_statistical_analysis.resolve_logical_path",
                return_value=path,
            ):
                with self.assertRaisesRegex(ValueError, "primary metric"):
                    load_source(
                        path,
                        ("bit_accuracy_tracer", "bit_accuracy_detector"),
                    )

    def test_statistics_rejects_per_attack_sample_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["image_id", "attack_type", "bit_accuracy", "error"],
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
                        "bit_accuracy": "0.9",
                        "error": "",
                    })
            (path.parent / "summary.json").write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "num_images": 2,
                    "attack_ids": ["clean", "jpeg50"],
                    "results_csv_path": "reports/results.csv",
                    "results_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }),
                encoding="utf-8",
            )
            with patch(
                "system.scripts.run_statistical_analysis.resolve_logical_path",
                return_value=path,
            ):
                with self.assertRaisesRegex(ValueError, "sample set mismatch"):
                    load_source(path, ("bit_accuracy",))

    def test_statistics_rejects_non_object_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            path.write_text("image_id,attack_type,bit_accuracy\n", encoding="utf-8")
            (path.parent / "summary.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "summary must be an object"):
                load_source(path, ("bit_accuracy",))


if __name__ == "__main__":
    unittest.main()
