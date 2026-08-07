from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "system" / "scripts" / "aggregate_lidmark_training.py"
SPEC = importlib.util.spec_from_file_location("aggregate_lidmark_training", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def selection(run: str, ber: float, psnr: float, aed: float, loss: float) -> dict:
    return {
        "run_id": run,
        "epoch": 9,
        "checkpoint_sha256": "a" * 64,
        "checkpoint_size_bytes": 7,
        "selection_sha256": "b" * 64,
        "val": {
            "id_ber": ber,
            "psnr": psnr,
            "landmark_aed": aed,
            "g_loss": loss,
        },
    }


class AggregateLIDMarkTrainingTests(unittest.TestCase):
    def test_summary_is_deterministic_and_computes_cross_seed_statistics(self) -> None:
        first = selection("seed-b", 0.02, 32.0, 1.4, 0.2)
        second = selection("seed-a", 0.0, 34.0, 1.2, 0.1)
        result = MODULE.summarize([first, second])
        reordered = MODULE.summarize([second, first])
        self.assertEqual(result, reordered)
        self.assertEqual(result["completed_run_count"], 2)
        self.assertAlmostEqual(result["aggregate"]["id_ber"]["mean"], 0.01)
        self.assertAlmostEqual(result["identity_bit_accuracy"]["mean"], 0.99)
        self.assertEqual(result["identity_bit_accuracy"]["zero_ber_run_count"], 1)
        self.assertEqual([item["run_id"] for item in result["runs"]], ["seed-a", "seed-b"])

    def test_duplicate_runs_fail_closed(self) -> None:
        duplicate = selection("same", 0.0, 33.0, 1.0, 0.1)
        with self.assertRaisesRegex(ValueError, "duplicate run_id"):
            MODULE.summarize([duplicate, duplicate])

    def test_unverified_selector_output_is_rejected(self) -> None:
        document = {
            "status": "selected",
            "all_checkpoint_integrity_verified": False,
            "selected": {},
        }
        with self.assertRaisesRegex(ValueError, "integrity"):
            MODULE.validate_selection(document, Path("run/selection.json"))


if __name__ == "__main__":
    unittest.main()
