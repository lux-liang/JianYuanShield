from __future__ import annotations

import unittest

from system.backend.simswap_evidence import (
    SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
    _conditioned_registered_positive_metrics,
)
from system.scripts import run_simswap_lfw_robustness as runner


class SimSwapConditionedMigrationTests(unittest.TestCase):
    @staticmethod
    def _formal_count_fixture():
        pairs = [
            {"pair_id": f"pair-{index:03d}", "split": "holdout"}
            for index in range(192)
        ]
        rows = {}
        for index, pair in enumerate(pairs):
            pair_id = pair["pair_id"]
            rows[(pair_id, "KAD-Net")] = {
                "registered_positive_score": "0.1" if index == 0 else "0.9",
                "arcface_clean_identity_migrated": "1" if index < 161 else "0",
                "arcface_watermarked_identity_migrated": (
                    "1" if index < 154 else "0"
                ),
            }
            sepmark_failure = index in {*range(9), 159}
            rows[(pair_id, "SepMark")] = {
                "registered_positive_score": "0.1" if sepmark_failure else "0.9",
                "arcface_clean_identity_migrated": "1" if index < 161 else "0",
                "arcface_watermarked_identity_migrated": (
                    "1" if index < 159 else "0"
                ),
            }
        summary = {
            "model_results": {
                model: {"calibration": {"threshold": 0.5}}
                for model in ("KAD-Net", "SepMark")
            }
        }
        return pairs, rows, summary

    def test_recomputes_exact_conditioned_counts_from_holdout_rows(self) -> None:
        pairs, rows, summary = self._formal_count_fixture()
        result = _conditioned_registered_positive_metrics(
            pairs=pairs,
            result_rows=rows,
            recomputed_summary=summary,
            runner=runner,
            models=("KAD-Net", "SepMark"),
        )
        self.assertEqual(
            result["KAD-Net"],
            {
                "clean_swap_migrated": {
                    "successes": 160,
                    "total": 161,
                    "estimate": 0.99378882,
                    "wilson_95_low": 0.96566044,
                    "wilson_95_high": 0.99890273,
                },
                "clean_and_watermarked_swap_migrated": {
                    "successes": 153,
                    "total": 154,
                    "estimate": 0.99350649,
                    "wilson_95_low": 0.96413879,
                    "wilson_95_high": 0.99885282,
                },
            },
        )
        self.assertEqual(
            result["SepMark"],
            {
                "clean_swap_migrated": {
                    "successes": 151,
                    "total": 161,
                    "estimate": 0.9378882,
                    "wilson_95_low": 0.88945175,
                    "wilson_95_high": 0.96591559,
                },
                "clean_and_watermarked_swap_migrated": {
                    "successes": 150,
                    "total": 159,
                    "estimate": 0.94339623,
                    "wilson_95_low": 0.89593484,
                    "wilson_95_high": 0.96993802,
                },
            },
        )

        rows[("pair-000", "KAD-Net")]["registered_positive_score"] = "0.9"
        recomputed = _conditioned_registered_positive_metrics(
            pairs=pairs,
            result_rows=rows,
            recomputed_summary=summary,
            runner=runner,
            models=("KAD-Net", "SepMark"),
        )
        self.assertEqual(
            recomputed["KAD-Net"]["clean_swap_migrated"]["successes"],
            161,
        )
        self.assertEqual(
            recomputed["KAD-Net"][
                "clean_and_watermarked_swap_migrated"
            ]["successes"],
            154,
        )

    def test_identity_evidence_scope_is_explicitly_pipeline_internal(self) -> None:
        self.assertEqual(
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE["scope"],
            "pipeline_internal_identity_migration_evidence",
        )
        self.assertTrue(
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE[
                "same_arcface_checkpoint_used_for_generation_and_measurement"
            ]
        )
        self.assertFalse(
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE[
                "independent_identity_verifier"
            ]
        )


if __name__ == "__main__":
    unittest.main()
