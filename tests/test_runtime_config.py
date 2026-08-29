from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from system.evaluation.run_metadata import build_run_metadata, sanitize_command


ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_uses_environment_roots(self) -> None:
        env = os.environ.copy()
        env["JYS_PROJECT_ROOT"] = "/tmp/jys-project"
        env["JYS_MODEL_SOURCE_ROOT"] = "/tmp/jys-models"
        env["JYS_WEIGHT_ROOT"] = "/tmp/jys-weights"
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "from system.evaluation.runtime import PROJECT_ROOT, MODEL_SOURCE_ROOT, WEIGHT_ROOT;"
                    "print(PROJECT_ROOT); print(MODEL_SOURCE_ROOT); print(WEIGHT_ROOT)"
                ),
            ],
            cwd=ROOT,
            env=env,
            text=True,
        ).splitlines()
        self.assertEqual(
            output,
            [
                str(Path("/tmp/jys-project").resolve()),
                str(Path("/tmp/jys-models").resolve()),
                str(Path("/tmp/jys-weights").resolve()),
            ],
        )

    def test_benchmark_scripts_do_not_contain_legacy_absolute_root(self) -> None:
        legacy_root = re.compile(
            r"/(?:home|data[0-9]*)/[^/\s]+/work/vpsg_competition_candidates"
        )
        offenders = []
        for path in [*(ROOT / "system" / "scripts").glob("run_*"), *(ROOT / "scripts").glob("*")]:
            if path.is_file() and legacy_root.search(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
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
        self.assertEqual(metadata["project_root"], ".")
        self.assertFalse(Path(metadata["protocol_path"]).is_absolute())
        self.assertIsNone(metadata["checkpoint_sha256"])

    def test_run_metadata_redacts_credentials_and_host_paths(self) -> None:
        command = sanitize_command([
            "runner",
            "--api-key",
            "do-not-record",
            "JYS_PROVENANCE_SECRET=also-secret",
            f"--output={ROOT / 'system' / 'reports' / 'result.json'}",
        ])
        rendered = " ".join(command)
        self.assertNotIn("do-not-record", rendered)
        self.assertNotIn("also-secret", rendered)
        self.assertNotIn(str(ROOT), rendered)
        self.assertIn("<redacted>", rendered)

    def test_formal_pipeline_uses_explicit_lanes_and_unique_outputs(self) -> None:
        script = (ROOT / "system" / "scripts" / "run_award_level_pipeline_tmux.sh")
        source = script.read_text(encoding="utf-8")
        self.assertNotIn("CUDA_VISIBLE_DEVICES=0", source)
        self.assertIn('JYS_GPU_LANE_2:-2', source)
        self.assertIn('JYS_GPU_LANE_7:-7', source)
        self.assertIn('JYS_RUN_ID', source)
        self.assertIn('run ID already has report output', source)
        self.assertIn('JYS_MIN_FREE_GPU_MIB', source)
        self.assertNotIn('while true', source)


if __name__ == "__main__":
    unittest.main()
