from __future__ import annotations

import unittest

from system.evaluation.statistics import (
    bootstrap_ci,
    holm_adjust,
    paired_bootstrap_difference,
    paired_effect_size,
    paired_sign_flip_test,
)


class StatisticsTests(unittest.TestCase):
    def test_bootstrap_interval_contains_constant_mean(self) -> None:
        interval = bootstrap_ci([0.75] * 20, resamples=100)
        self.assertEqual(interval.mean, 0.75)
        self.assertEqual(interval.low, 0.75)
        self.assertEqual(interval.high, 0.75)

    def test_paired_difference_and_effect_direction(self) -> None:
        first = [0.9, 0.8, 0.85, 0.88]
        second = [0.5, 0.55, 0.52, 0.50]
        interval = paired_bootstrap_difference(first, second, resamples=200)
        self.assertGreater(interval.low, 0)
        self.assertGreater(paired_effect_size(first, second), 0)
        self.assertLess(paired_sign_flip_test(first, second, permutations=2000), 0.2)

    def test_holm_adjust_is_order_preserving_and_bounded(self) -> None:
        adjusted = holm_adjust([0.01, 0.04, 0.03])
        self.assertTrue(all(0 <= value <= 1 for value in adjusted))
        self.assertLessEqual(adjusted[0], adjusted[1])
        self.assertLessEqual(adjusted[0], adjusted[2])

    def test_mismatched_pairs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_difference([1, 2], [1])


if __name__ == "__main__":
    unittest.main()
