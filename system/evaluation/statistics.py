from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from statistics import NormalDist
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ConfidenceInterval:
    mean: float
    low: float
    high: float
    confidence: float
    samples: int


@dataclass(frozen=True)
class SeedLevelSummary:
    """跨 seed（between-seed）不确定性汇总。

    与 ``bootstrap_ci`` 严格区分：这里的样本是「每个 seed 的图像级均值」，
    n 即独立训练 seed 的个数（本项目仅 3），故区间反映的是模型重训之间的
    方差，而非图像采样噪声。n 很小时区间仅供参考，不应当作严格统计结论。
    """

    mean: float
    std: float
    low: float
    high: float
    confidence: float
    n_seeds: int


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


def _student_t_critical(confidence: float, dof: int) -> float:
    """双侧 Student-t 临界值。

    n 很小（dof≤2）时无 scipy 可用，这里对常见的 95% 置信度给出查表值，
    其余置信度退化为正态近似（并由调用方在文档中坦诚标注 n 小、仅供参考）。
    """
    if dof <= 0:
        return float("nan")
    # 仅对最常用的 95% 双侧置信度内置 t 表（dof=1..6），覆盖 n=3 主用例。
    if abs(confidence - 0.95) < 1e-9:
        table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447}
        if dof in table:
            return table[dof]
    # 退化：正态近似（dof 较大或非标准置信度时）。
    return float(NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0))


def seed_level_summary(
    seed_means: Iterable[float],
    *,
    confidence: float = 0.95,
) -> SeedLevelSummary:
    """由「每个 seed 的图像级均值」估计 between-seed 不确定性。

    输入必须是每个独立训练 seed 的单一标量（如该 seed 在某攻击下的图像级
    平均 bit_accuracy），而不是把所有图拍平的逐图值——后者会把图像采样噪声
    误当作 between-seed 方差（pseudoreplication）。当 n_seeds<2 时无法估方差，
    区间退化为点估计；n 小时区间仅供参考。
    """
    array = np.asarray(list(seed_means), dtype=np.float64)
    if array.size == 0:
        raise ValueError("seed_means must not be empty")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    mean = float(array.mean())
    if array.size < 2:
        return SeedLevelSummary(
            mean=mean,
            std=0.0,
            low=mean,
            high=mean,
            confidence=confidence,
            n_seeds=int(array.size),
        )
    std = float(array.std(ddof=1))
    standard_error = std / sqrt(array.size)
    critical = _student_t_critical(confidence, array.size - 1)
    margin = critical * standard_error
    return SeedLevelSummary(
        mean=mean,
        std=std,
        low=mean - margin,
        high=mean + margin,
        confidence=confidence,
        n_seeds=int(array.size),
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
