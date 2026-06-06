from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

from system.evaluation.run_metadata import build_run_metadata


ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_uses_environment_roots(self) -> None:
        env = os.environ.copy()
        env["JYS_PROJECT_ROOT"] = "/tmp/jys-project"
        env["JYS_MODEL_SOURCE_ROOT"] = "/tmp/jys-models"
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "from system.evaluation.runtime import PROJECT_ROOT, MODEL_SOURCE_ROOT;"
                    "print(PROJECT_ROOT); print(MODEL_SOURCE_ROOT)"
                ),
            ],
            cwd=ROOT,
            env=env,
            text=True,
        ).splitlines()
        self.assertEqual(output, ["/tmp/jys-project", "/tmp/jys-models"])

    def test_benchmark_scripts_do_not_contain_legacy_absolute_root(self) -> None:
        legacy = "/home/luxliang/work/vpsg_competition_candidates"
        offenders = []
        for path in (ROOT / "system" / "scripts").glob("run_*"):
            if path.is_file() and legacy in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_run_metadata_has_reproducibility_fields(self) -> None:
        metadata = build_run_metadata(model="unit-test", checkpoint=None, seed=7, command=["test"])
        for key in (
            "schema_version",
            "model",
            "seed",
            "command",
            "evaluation_protocol",
            "protocol_sha256",
            "python",
            "torch",
            "cuda_available",
        ):
            self.assertIn(key, metadata)
        self.assertEqual(metadata["seed"], 7)
        self.assertIsNone(metadata["checkpoint_sha256"])


if __name__ == "__main__":
    unittest.main()
