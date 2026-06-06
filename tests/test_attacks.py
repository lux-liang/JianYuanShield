from __future__ import annotations

import unittest

import numpy as np

from system.evaluation.attacks import ATTACKS, apply_attack, attack_spec, derived_seed


class AttackTests(unittest.TestCase):
    def setUp(self) -> None:
        x = np.linspace(0, 255, 64, dtype=np.uint8)
        self.image = np.stack(np.meshgrid(x, x), axis=2)
        self.image = np.concatenate([self.image, self.image[..., :1]], axis=2)

    def test_every_registered_attack_preserves_shape_dtype_and_range(self) -> None:
        for attack_id in ATTACKS:
            with self.subTest(attack=attack_id):
                output, metadata = apply_attack(self.image, attack_id, image_id="sample")
                self.assertEqual(output.shape, self.image.shape)
                self.assertEqual(output.dtype, np.uint8)
                self.assertGreaterEqual(int(output.min()), 0)
                self.assertLessEqual(int(output.max()), 255)
                self.assertEqual(metadata["attack_id"], attack_id)
                self.assertEqual(len(metadata["config_hash"]), 64)

    def test_noise_is_deterministic_per_image_and_varies_between_images(self) -> None:
        first, _ = apply_attack(self.image, "gaussian_noise_sigma_3", image_id="a")
        repeat, _ = apply_attack(self.image, "gaussian_noise_sigma_3", image_id="a")
        second, _ = apply_attack(self.image, "gaussian_noise_sigma_3", image_id="b")
        self.assertTrue(np.array_equal(first, repeat))
        self.assertFalse(np.array_equal(first, second))

    def test_unknown_attack_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            attack_spec("not-real")

    def test_seed_derivation_is_stable(self) -> None:
        self.assertEqual(derived_seed(7, "a", "clean"), derived_seed(7, "a", "clean"))
        self.assertNotEqual(derived_seed(7, "a", "clean"), derived_seed(7, "b", "clean"))


if __name__ == "__main__":
    unittest.main()
