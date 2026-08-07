from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system.evaluation import runtime
from system.evaluation.evidence import build_dataset_manifest, finalize_benchmark_summary


class EvaluationEvidenceTests(unittest.TestCase):
    def test_dataset_manifest_is_content_addressed_and_host_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            images = data / "lfw"
            images.mkdir(parents=True)
            first = images / "a.jpg"
            second = images / "nested" / "b.jpg"
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output = data / "manifest.json"
            with (
                patch.object(runtime, "PROJECT_ROOT", root),
                patch.object(runtime, "DATA_ROOT", data),
            ):
                manifest = build_dataset_manifest(
                    image_root=images,
                    images=[first, second],
                    output_path=output,
                    seed=7,
                    selection="sorted_first_n",
                )
            self.assertEqual(manifest["sample_count"], 2)
            self.assertEqual([item["path"] for item in manifest["files"]], ["a.jpg", "nested/b.jpg"])
            self.assertNotIn(str(root), output.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files_digest_sha256"]), 64)

    def test_finalize_binds_checkpoint_dataset_protocol_and_raw_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            weights = root / "weights"
            reports = root / "reports"
            configs = root / "configs"
            for path in (data, weights, reports, configs):
                path.mkdir()
            checkpoint = weights / "model.pth"
            checkpoint.write_bytes(b"checkpoint")
            dataset = data / "manifest.json"
            dataset.write_text('{"schema_version":"dataset-manifest.v1"}\n', encoding="utf-8")
            results = reports / "results.csv"
            results.write_text("image_id,attack_type\na,clean\n", encoding="utf-8")
            protocol = configs / "evaluation_protocol.v1.json"
            source_protocol = Path(__file__).resolve().parents[1] / "configs" / "evaluation_protocol.v1.json"
            protocol.write_bytes(source_protocol.read_bytes())
            with (
                patch.object(runtime, "PROJECT_ROOT", root),
                patch.object(runtime, "DATA_ROOT", data),
                patch.object(runtime, "WEIGHT_ROOT", weights),
                patch.object(runtime, "REPORT_ROOT", reports),
                patch("system.evaluation.protocol.DEFAULT_PROTOCOL", protocol),
                patch("system.evaluation.protocol.protocol_path", return_value=protocol),
            ):
                from system.evaluation.protocol import load_protocol

                load_protocol.cache_clear()
                summary = finalize_benchmark_summary(
                    {"method": "test"},
                    model="test",
                    checkpoint=checkpoint,
                    results_path=results,
                    dataset_manifest_path=dataset,
                    sample_count=1,
                    seed=7,
                    attack_ids=["clean"],
                    command=["runner"],
                )
                load_protocol.cache_clear()
            self.assertEqual(summary["schema_version"], "benchmark-summary.v2")
            self.assertEqual(summary["checkpoint"], "weights/model.pth")
            self.assertEqual(summary["dataset_manifest_path"], "data/manifest.json")
            self.assertEqual(summary["results_csv_path"], "reports/results.csv")
            self.assertEqual(summary["expected_result_rows"], 1)
            self.assertEqual(len(summary["checkpoint_sha256"]), 64)
            self.assertEqual(len(summary["results_csv_sha256"]), 64)
            self.assertNotIn(str(root), json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
