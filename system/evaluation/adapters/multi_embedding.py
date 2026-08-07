from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from system.evaluation.metrics import bit_metrics, image_quality

from .base import ModelAdapter


@dataclass(frozen=True)
class MultiEmbeddingResult:
    source_model: str
    attacker_model: str
    first_decoded_message: np.ndarray
    second_decoded_message: np.ndarray
    first_message_metrics: dict
    second_message_metrics: dict
    first_embedding_quality: dict
    second_embedding_quality_vs_original: dict
    second_embedding_quality_vs_first: dict
    metadata: dict


def evaluate_double_embedding(
    image: np.ndarray,
    source: ModelAdapter,
    attacker: ModelAdapter,
    first_message: np.ndarray,
    second_message: np.ndarray,
    *,
    threshold: float = 0.9,
) -> MultiEmbeddingResult:
    if not source.available:
        raise RuntimeError(f"source adapter unavailable: {source.name}: {source.blocker}")
    if not attacker.available:
        raise RuntimeError(f"attacker adapter unavailable: {attacker.name}: {attacker.blocker}")
    source.validate_image(image)
    original = image.copy()
    first_bits = source.validate_message(first_message)
    second_bits = attacker.validate_message(second_message)

    source_input = image.copy()
    first = source.encode(source_input, first_bits)
    if not np.array_equal(source_input, original):
        raise ValueError(f"{source.name}: encode mutated its input image")
    source.validate_image(first.image)
    if first.image.shape != original.shape:
        raise ValueError(f"{source.name}: encode changed image shape")
    first_registered = source.validate_message(first.message)
    if not np.array_equal(first_registered, first_bits):
        raise ValueError(f"{source.name}: encode returned a different message")

    attacker_input = first.image.copy()
    second = attacker.encode(attacker_input, second_bits)
    if not np.array_equal(attacker_input, first.image):
        raise ValueError(f"{attacker.name}: encode mutated its input image")
    attacker.validate_image(second.image)
    if second.image.shape != original.shape:
        raise ValueError(f"{attacker.name}: encode changed image shape")
    second_registered = attacker.validate_message(second.message)
    if not np.array_equal(second_registered, second_bits):
        raise ValueError(f"{attacker.name}: encode returned a different message")

    recovered_first = source.decode(second.image)
    recovered_second = attacker.decode(second.image)
    recovered_first_bits = source.validate_message(recovered_first.bits)
    recovered_second_bits = attacker.validate_message(recovered_second.bits)

    for adapter, decoded in (
        (source, recovered_first),
        (attacker, recovered_second),
    ):
        expected_decoder = getattr(adapter, "primary_decoder", None)
        actual_decoder = decoded.metadata.get(
            "primary_decoder", decoded.metadata.get("decoder")
        )
        if expected_decoder and actual_decoder != expected_decoder:
            raise ValueError(
                f"{adapter.name}: primary decoder drift: "
                f"expected {expected_decoder}, got {actual_decoder}"
            )

    return MultiEmbeddingResult(
        source_model=source.name,
        attacker_model=attacker.name,
        first_decoded_message=recovered_first_bits.copy(),
        second_decoded_message=recovered_second_bits.copy(),
        first_message_metrics=bit_metrics(
            first_bits, recovered_first_bits, success_threshold=threshold
        ),
        second_message_metrics=bit_metrics(
            second_bits, recovered_second_bits, success_threshold=threshold
        ),
        first_embedding_quality=image_quality(image, first.image),
        second_embedding_quality_vs_original=image_quality(image, second.image),
        second_embedding_quality_vs_first=image_quality(first.image, second.image),
        metadata={
            "source_checkpoint": source.checkpoint,
            "attacker_checkpoint": attacker.checkpoint,
            "source_encode": first.metadata,
            "attacker_encode": second.metadata,
            "source_decode": recovered_first.metadata,
            "attacker_decode": recovered_second.metadata,
        },
    )
