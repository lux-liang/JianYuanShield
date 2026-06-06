from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from system.evaluation.metrics import bit_metrics, image_quality

from .base import ModelAdapter


@dataclass(frozen=True)
class MultiEmbeddingResult:
    source_model: str
    attacker_model: str
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
    first_bits = source.validate_message(first_message)
    second_bits = attacker.validate_message(second_message)

    first = source.encode(image, first_bits)
    source.validate_image(first.image)
    second = attacker.encode(first.image, second_bits)
    attacker.validate_image(second.image)
    recovered_first = source.decode(second.image)
    recovered_second = attacker.decode(second.image)

    return MultiEmbeddingResult(
        source_model=source.name,
        attacker_model=attacker.name,
        first_message_metrics=bit_metrics(first_bits, recovered_first.bits, success_threshold=threshold),
        second_message_metrics=bit_metrics(second_bits, recovered_second.bits, success_threshold=threshold),
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
