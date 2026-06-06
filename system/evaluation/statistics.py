from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ConfidenceInterval:
    mean: float
    low: float
    high: float
    confidence: float
    samples: int


def bootstrap_ci(
    values: Iterable[float],
    *,
    confidence: float = 0.95,
    resamples: int = 5000,
    seed: int = 20260603,
) -> ConfidenceInterval:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size == 0:
        raise ValueError("values must not be empty")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    rng = np.random.default_rng(seed)
    samples = rng.choice(array, size=(resamples, array.size), replace=True).mean(axis=1)
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(samples, [alpha, 1.0 - alpha])
    return ConfidenceInterval(
        mean=float(array.mean()),
        low=float(low),
        high=float(high),
        confidence=confidence,
        samples=int(array.size),
    )


def paired_bootstrap_difference(
    first: Iterable[float],
    second: Iterable[float],
    *,
    confidence: float = 0.95,
    resamples: int = 5000,
    seed: int = 20260603,
) -> ConfidenceInterval:
    a = np.asarray(list(first), dtype=np.float64)
    b = np.asarray(list(second), dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("paired samples must have equal non-zero shape")
    return bootstrap_ci(a - b, confidence=confidence, resamples=resamples, seed=seed)


def paired_effect_size(first: Iterable[float], second: Iterable[float]) -> float:
    a = np.asarray(list(first), dtype=np.float64)
    b = np.asarray(list(second), dtype=np.float64)
    if a.shape != b.shape or a.size < 2:
        raise ValueError("paired samples must have equal shape and at least two values")
    differences = a - b
    deviation = differences.std(ddof=1)
    if deviation == 0:
        if differences.mean() == 0:
            return 0.0
        return float("inf") if differences.mean() > 0 else float("-inf")
    return float(differences.mean() / deviation)


def paired_sign_flip_test(
    first: Iterable[float],
    second: Iterable[float],
    *,
    permutations: int = 20000,
    seed: int = 20260603,
) -> float:
    a = np.asarray(list(first), dtype=np.float64)
    b = np.asarray(list(second), dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("paired samples must have equal non-zero shape")
    differences = a - b
    observed = abs(float(differences.mean()))
    if observed == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    exceed = 0
    batch_size = 1000
    completed = 0
    while completed < permutations:
        count = min(batch_size, permutations - completed)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(count, differences.size))
        permuted = np.abs((signs * differences).mean(axis=1))
        exceed += int(np.count_nonzero(permuted >= observed))
        completed += count
    return float((exceed + 1) / (permutations + 1))


def holm_adjust(p_values: Iterable[float]) -> list[float]:
    values = np.asarray(list(p_values), dtype=np.float64)
    if values.size == 0:
        return []
    order = np.argsort(values)
    adjusted_sorted = np.empty(values.size, dtype=np.float64)
    running = 0.0
    for rank, index in enumerate(order):
        adjusted = min(1.0, float(values[index]) * (values.size - rank))
        running = max(running, adjusted)
        adjusted_sorted[rank] = running
    result = np.empty(values.size, dtype=np.float64)
    for rank, index in enumerate(order):
        result[index] = adjusted_sorted[rank]
    return result.tolist()


def normal_approximation_p_value(z_score: float) -> float:
    return float(2.0 * (1.0 - 0.5 * (1.0 + erf(abs(z_score) / sqrt(2.0)))))
