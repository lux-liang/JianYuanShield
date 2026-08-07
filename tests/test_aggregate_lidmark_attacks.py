from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "system" / "scripts" / "aggregate_lidmark_attacks.py"
SPEC = importlib.util.spec_from_file_location("aggregate_lidmark_attacks", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def report(name: str, digest: str, clean: float, crop: float) -> dict:
    def metrics(value: float) -> dict:
        return {"mean_bit_accuracy": value, "identity_exact_match_rate": value, "success_rate": value, "mean_ber": 1 - value}
    attack_ids = [f"attack-{index}" for index in range(13)] + ["clean", "crop"]
    attacks = {attack: metrics(clean) for attack in attack_ids}
    attacks["crop"] = metrics(crop)
    return {"run_id": name, "checkpoint_sha256": digest * 64, "sample_count": 10, "result_rows": 150, "attack_ids": attack_ids, "attacks": attacks, "summary_sha256": "f" * 64}


class AggregateLIDMarkAttacksTests(unittest.TestCase):
    def test_cross_seed_summary_finds_weakest_attack(self) -> None:
        result = MODULE.summarize([report("b", "b", 1.0, 0.4), report("a", "a", 0.8, 0.2)])
        self.assertEqual(result["run_count"], 2)
        self.assertEqual(result["total_result_rows"], 300)
        self.assertEqual(result["weakest_attack_by_mean_success"], "crop")
        self.assertAlmostEqual(result["attacks"]["crop"]["success_rate"]["mean"], 0.3)

    def test_duplicate_checkpoint_fails_closed(self) -> None:
        first = report("a", "a", 1.0, 0.5)
        second = report("b", "a", 1.0, 0.5)
        with self.assertRaisesRegex(ValueError, "distinct"):
            MODULE.summarize([first, second])


if __name__ == "__main__":
    unittest.main()
