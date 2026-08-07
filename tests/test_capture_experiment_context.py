from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.capture_experiment_context import (
    atomic_json,
    attach_context_to_summary,
    repository_record,
    sanitize_remote,
)
from system.evaluation.run_metadata import sha256_file
from system.evaluation.runtime import logical_path


class CaptureExperimentContextTests(unittest.TestCase):
    def test_remote_credentials_and_query_are_removed(self) -> None:
        self.assertEqual(
            sanitize_remote("https://token@example.com/org/repo.git?access_token=secret"),
            "https://example.com/org/repo.git",
        )
        self.assertEqual(
            sanitize_remote("git@github.com:vpsg-research/LIDMark.git"),
            "ssh://github.com/vpsg-research/LIDMark.git",
        )

    def test_repository_record_binds_uncommitted_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            source = root / "source.py"
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "source.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
            clean = repository_record(root)
            source.write_text("value = 2\n", encoding="utf-8")
            dirty = repository_record(root)
            self.assertFalse(clean["dirty"])
            self.assertTrue(dirty["dirty"])
            self.assertNotEqual(clean["source_tree_sha256"], dirty["source_tree_sha256"])

    def test_context_attachment_binds_matching_checkpoint_and_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "context"
            output.mkdir()
            checkpoint = root / "checkpoint.pth"
            dataset = root / "dataset_manifest.json"
            checkpoint.write_bytes(b"checkpoint")
            dataset.write_text('{"schema_version":"dataset-manifest.v1"}', encoding="utf-8")
            outputs = {
                "source_manifest.json": {"schema_version": "source-manifest.v1"},
                "checkpoint_manifest.json": {
                    "schema_version": "checkpoint-manifest.v1",
                    "checkpoints": [{
                        "path": logical_path(checkpoint),
                        "sha256": sha256_file(checkpoint),
                        "size_bytes": checkpoint.stat().st_size,
                    }],
                },
                "environment.json": {
                    "schema_version": "environment-manifest.v1",
                    "dataset_manifest": {
                        "path": logical_path(dataset),
                        "sha256": sha256_file(dataset),
                        "size_bytes": dataset.stat().st_size,
                    },
                },
            }
            for name, payload in outputs.items():
                atomic_json(output / name, payload)
            (output / "hashes.sha256").write_text("context hashes\n", encoding="utf-8")
            summary_path = root / "summary.json"
            atomic_json(summary_path, {
                "schema_version": "benchmark-summary.v2",
                "status": "complete",
                "checkpoint": logical_path(checkpoint),
                "checkpoint_sha256": sha256_file(checkpoint),
                "dataset_manifest_path": logical_path(dataset),
                "dataset_manifest_sha256": sha256_file(dataset),
            })
            attached = attach_context_to_summary(summary_path, output, outputs)
            for field in (
                "source_manifest",
                "checkpoint_manifest",
                "environment",
                "experiment_context_hashes",
            ):
                path = output / {
                    "source_manifest": "source_manifest.json",
                    "checkpoint_manifest": "checkpoint_manifest.json",
                    "environment": "environment.json",
                    "experiment_context_hashes": "hashes.sha256",
                }[field]
                self.assertEqual(attached[f"{field}_sha256"], sha256_file(path))
            self.assertEqual(json.loads(summary_path.read_text()), attached)

            outputs["environment.json"]["dataset_manifest"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "dataset manifest"):
                attach_context_to_summary(summary_path, output, outputs)


if __name__ == "__main__":
    unittest.main()
