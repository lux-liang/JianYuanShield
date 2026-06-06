from __future__ import annotations

import unittest

import numpy as np

from system.evaluation.adapters import DecodeResult, EmbeddingResult, ModelAdapter, evaluate_double_embedding


class DummyAdapter(ModelAdapter):
    message_length = 4
    checkpoint = "dummy"

    def __init__(self, name: str, channel: int):
        self.name = name
        self.channel = channel

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        bits = self.validate_message(message)
        output = image.copy()
        output[0, :bits.size, self.channel] = bits
        return EmbeddingResult(output, bits, {"channel": self.channel})

    def decode(self, image: np.ndarray) -> DecodeResult:
        bits = image[0, :self.message_length, self.channel].astype(np.uint8)
        return DecodeResult(bits, {"channel": self.channel})


class MultiEmbeddingTests(unittest.TestCase):
    def test_cross_adapter_double_embedding_tracks_both_messages(self) -> None:
        image = np.full((16, 16, 3), 128, dtype=np.uint8)
        source = DummyAdapter("source", 0)
        attacker = DummyAdapter("attacker", 1)
        result = evaluate_double_embedding(
            image,
            source,
            attacker,
            np.array([0, 1, 1, 0], dtype=np.uint8),
            np.array([1, 0, 1, 0], dtype=np.uint8),
        )
        self.assertEqual(result.first_message_metrics["accuracy"], 1.0)
        self.assertEqual(result.second_message_metrics["accuracy"], 1.0)
        self.assertEqual(result.source_model, "source")
        self.assertEqual(result.attacker_model, "attacker")

    def test_adapter_rejects_invalid_message_length(self) -> None:
        adapter = DummyAdapter("source", 0)
        with self.assertRaises(ValueError):
            adapter.validate_message(np.array([1, 0]))


if __name__ == "__main__":
    unittest.main()
