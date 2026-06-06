from __future__ import annotations

import math
import unittest

import numpy as np

from system.evaluation.metrics import bit_metrics, image_quality, paired_quality


class MetricTests(unittest.TestCase):
    def test_bit_metrics(self) -> None:
        payload = bit_metrics([1, -1, 1, -1], [1, -1, -1, -1], success_threshold=0.7)
        self.assertEqual(payload["ber"], 0.25)
        self.assertEqual(payload["accuracy"], 0.75)
        self.assertTrue(payload["success"])

    def test_bit_shape_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bit_metrics([1, -1], [1])

    def test_identical_images_have_perfect_quality(self) -> None:
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        quality = image_quality(image, image)
        self.assertTrue(math.isinf(quality["psnr"]))
        self.assertEqual(quality["ssim"], 1.0)

    def test_paired_quality_has_explicit_references(self) -> None:
        original = np.zeros((16, 16, 3), dtype=np.uint8)
        watermarked = original.copy()
        attacked = np.ones_like(original)
        payload = paired_quality(original, watermarked, attacked)
        self.assertIn("watermarked_vs_original", payload)
        self.assertIn("attacked_vs_original", payload)


if __name__ == "__main__":
    unittest.main()
