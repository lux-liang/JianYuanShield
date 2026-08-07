from __future__ import annotations

import hashlib
import unittest
from types import SimpleNamespace

import numpy as np

from system.evaluation import synchronization


def fixture_image() -> np.ndarray:
    rows, columns = np.indices((23, 27))
    return np.stack(
        (
            (rows * 11 + columns * 3) % 256,
            (rows * 5 + columns * 17) % 256,
            (rows * 19 + columns * 7) % 256,
        ),
        axis=2,
    ).astype(np.uint8)


def digest(image: np.ndarray) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


class SynchronizationTests(unittest.TestCase):
    def test_default_candidates_are_deterministic_shape_preserving_and_hashed(self) -> None:
        image = fixture_image()
        original = image.copy()
        outputs = []
        for candidate in synchronization.DEFAULT_CANDIDATES:
            first = synchronization.apply_synchronization_candidate(image, candidate)
            second = synchronization.apply_synchronization_candidate(image, candidate)
            np.testing.assert_array_equal(first, second)
            self.assertEqual(first.shape, image.shape)
            self.assertEqual(first.dtype, np.uint8)
            outputs.append(digest(first))
        np.testing.assert_array_equal(image, original)
        self.assertEqual(len(set(outputs)), len(synchronization.DEFAULT_CANDIDATES))
        self.assertEqual(
            [candidate.id for candidate in synchronization.DEFAULT_CANDIDATES],
            [
                "identity",
                "inverse_rotate_for_plus_5",
                "inverse_rotate_for_minus_5",
                "inverse_crop_center_0.8_approx",
            ],
        )
        self.assertRegex(
            synchronization.candidate_contract_sha256(),
            r"^[0-9a-f]{64}$",
        )
        contract = synchronization.candidate_contract()
        self.assertEqual(
            contract["candidates"][1]["parameters"]["correction_degrees"],
            -5.0,
        )
        self.assertEqual(
            contract["candidates"][2]["parameters"]["correction_degrees"],
            5.0,
        )
        self.assertEqual(
            contract["candidates"][3]["parameters"]["retained_ratio"],
            0.8,
        )

    def test_registered_message_selects_best_candidate_with_all_scores_retained(self) -> None:
        image = fixture_image()
        registered = np.array([1, 0, 1, 1, 0, 0, 1, 0], dtype=np.uint8)
        target_id = "inverse_rotate_for_plus_5"
        candidate_ids = {
            digest(
                synchronization.apply_synchronization_candidate(image, candidate)
            ): candidate.id
            for candidate in synchronization.DEFAULT_CANDIDATES
        }

        def decode_bits(candidate_image: np.ndarray) -> np.ndarray:
            if candidate_ids[digest(candidate_image)] == target_id:
                return registered.copy()
            return 1 - registered

        result = synchronization.search_registered_message_alignment(
            image,
            registered_message=registered,
            decode_bits=decode_bits,
        )
        self.assertEqual(result.selected_candidate_id, target_id)
        self.assertEqual(result.selected_decoded_bits, tuple(registered.tolist()))
        self.assertEqual(result.selected_bit_errors, 0)
        self.assertEqual(result.selected_bit_accuracy, 1.0)
        self.assertEqual(result.search_space_size, 4)
        self.assertEqual(len(result.candidate_scores), 4)
        self.assertEqual(
            [score.candidate_id for score in result.candidate_scores],
            [candidate.id for candidate in synchronization.DEFAULT_CANDIDATES],
        )

    def test_ties_prefer_first_declared_candidate(self) -> None:
        image = fixture_image()
        registered = np.array([0, 1, 1, 0], dtype=np.uint8)
        result = synchronization.search_registered_message_alignment(
            image,
            registered_message=registered,
            decode_bits=lambda _candidate: registered.copy(),
        )
        self.assertEqual(result.selected_candidate_id, "identity")
        self.assertEqual(result.tie_breaker, "first_in_declared_candidate_order")
        self.assertTrue(
            all(score.bit_accuracy == 1.0 for score in result.candidate_scores)
        )

    def test_kad_and_sepmark_style_adapters_can_use_the_pure_callable_interface(self) -> None:
        image = fixture_image()
        registered = np.array([1, 0, 0, 1], dtype=np.uint8)

        class KADStyleAdapter:
            def decode(self, _candidate: np.ndarray) -> SimpleNamespace:
                return SimpleNamespace(bits=registered.copy())

        class SepMarkStyleAdapter:
            def decode(self, _candidate: np.ndarray) -> dict[str, np.ndarray]:
                return {
                    "decoder_C": registered.copy(),
                    "decoder_RF": 1 - registered,
                }

        kad_result = synchronization.search_registered_message_alignment(
            image,
            registered_message=registered,
            decode_bits=KADStyleAdapter().decode,
        )
        sepmark_adapter = SepMarkStyleAdapter()
        sepmark_result = synchronization.search_registered_message_alignment(
            image,
            registered_message=registered,
            decode_bits=lambda candidate: sepmark_adapter.decode(candidate)[
                "decoder_C"
            ],
        )
        self.assertEqual(kad_result.selected_bit_accuracy, 1.0)
        self.assertEqual(sepmark_result.selected_bit_accuracy, 1.0)
        self.assertEqual(kad_result.selected_candidate_id, "identity")
        self.assertEqual(sepmark_result.selected_candidate_id, "identity")

    def test_result_forbids_claim_and_requires_exact_search_far_recalibration(self) -> None:
        image = fixture_image()
        registered = np.array([0, 1, 0, 1], dtype=np.uint8)
        result = synchronization.search_registered_message_alignment(
            image,
            registered_message=registered,
            decode_bits=lambda _candidate: registered.copy(),
        )
        self.assertTrue(result.multiple_hypothesis_search)
        self.assertTrue(result.selection_uses_registered_message)
        self.assertEqual(
            result.registered_message_source_requirement,
            "pre_existing_registration_record_only",
        )
        self.assertFalse(result.benchmark_ground_truth_selection_permitted)
        self.assertTrue(result.far_calibration_required)
        self.assertIn(
            "expands_the_null_score_distribution",
            result.far_calibration_reason,
        )
        self.assertFalse(result.formal_claim_eligible)
        self.assertEqual(
            result.required_far_negative_controls,
            (
                "unwatermarked",
                "wrong_message",
                "cross_record_watermarked",
            ),
        )
        self.assertEqual(
            result.selection_rule,
            "maximum_registered_message_bit_accuracy",
        )
        self.assertRegex(result.candidate_contract_sha256, r"^[0-9a-f]{64}$")

    def test_candidate_decoder_failure_is_not_silently_skipped(self) -> None:
        image = fixture_image()
        registered = np.array([0, 1, 0, 1], dtype=np.uint8)
        target = synchronization.apply_synchronization_candidate(
            image,
            synchronization.DEFAULT_CANDIDATES[1],
        )
        target_digest = digest(target)

        def decode_bits(candidate: np.ndarray) -> np.ndarray:
            if digest(candidate) == target_digest:
                raise RuntimeError("intentional decoder failure")
            return registered.copy()

        with self.assertRaisesRegex(
            RuntimeError,
            "inverse_rotate_for_plus_5",
        ):
            synchronization.search_registered_message_alignment(
                image,
                registered_message=registered,
                decode_bits=decode_bits,
            )

    def test_binary_length_and_candidate_contracts_are_strict(self) -> None:
        image = fixture_image()
        with self.assertRaisesRegex(ValueError, "binary"):
            synchronization.search_registered_message_alignment(
                image,
                registered_message=[0, 2, 1],
                decode_bits=lambda _candidate: [0, 1, 1],
            )
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            synchronization.search_registered_message_alignment(
                image,
                registered_message=[0, 1, 1],
                decode_bits=lambda _candidate: [0, 1],
            )
        duplicate = (
            synchronization.SynchronizationCandidate("same", "identity"),
            synchronization.SynchronizationCandidate("same", "identity"),
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            synchronization.search_registered_message_alignment(
                image,
                registered_message=[0, 1],
                decode_bits=lambda _candidate: [0, 1],
                candidates=duplicate,
            )

    def test_registered_message_bit_accuracy_accepts_adapter_decode_results(self) -> None:
        decoded = SimpleNamespace(bits=np.array([1, 0, 1, 1], dtype=np.uint8))
        accuracy = synchronization.registered_message_bit_accuracy(
            decoded,
            [1, 0, 0, 1],
        )
        self.assertEqual(accuracy, 0.75)


if __name__ == "__main__":
    unittest.main()
