from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system.scripts import aggregate_real_benchmarks as aggregate


class AggregateBenchmarkTests(unittest.TestCase):
    def test_incomplete_sources_exit_nonzero_and_remove_stale_curve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            output = reports / "aggregate_real_benchmarks"
            assets = root / "assets" / "aggregate_real_benchmarks"
            assets.mkdir(parents=True)
            stale = assets / "attack_degradation.png"
            stale.write_bytes(b"OLD_COMPLETE_CURVE")

            with (
                patch.object(aggregate, "REPORT_ROOT", reports),
                patch.object(aggregate, "OUT", output),
                patch.object(aggregate, "ASSETS", assets),
                patch("builtins.print"),
            ):
                result = aggregate.main()

            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(summary["status"], "incomplete")
            self.assertFalse(stale.exists())
            self.assertEqual(summary["complete_methods"], [])


if __name__ == "__main__":
    unittest.main()
