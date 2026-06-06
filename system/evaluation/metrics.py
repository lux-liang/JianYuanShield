from __future__ import annotations

from typing import Any

import numpy as np
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


def _bits(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.size == 0:
        raise ValueError("bit arrays must not be empty")
    if array.dtype == np.bool_:
        return array
    return array > 0


def bit_metrics(original: Any, decoded: Any, success_threshold: float = 0.9) -> dict[str, Any]:
    truth = _bits(original)
    prediction = _bits(decoded)
    if truth.shape != prediction.shape:
        raise ValueError(f"bit shape mismatch: {truth.shape} != {prediction.shape}")
    ber = float(np.mean(truth != prediction))
    accuracy = 1.0 - ber
    return {
        "ber": ber,
        "accuracy": accuracy,
        "success": accuracy >= success_threshold,
        "success_threshold": success_threshold,
        "num_bits": int(truth.size),
        "semantics": "bit decision is value > 0; accuracy = 1 - ber",
    }


def _image(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim not in {2, 3}:
        raise ValueError("images must be HxW or HxWxC arrays")
    if array.size == 0:
        raise ValueError("images must not be empty")
    return array.astype(np.float64)


def image_quality(reference: Any, candidate: Any, data_range: float = 255.0) -> dict[str, float]:
    ref = _image(reference)
    cand = _image(candidate)
    if ref.shape != cand.shape:
        raise ValueError(f"image shape mismatch: {ref.shape} != {cand.shape}")
    channel_axis = 2 if ref.ndim == 3 else None
    return {
        "psnr": float(peak_signal_noise_ratio(ref, cand, data_range=data_range)),
        "ssim": float(structural_similarity(ref, cand, data_range=data_range, channel_axis=channel_axis)),
    }


def paired_quality(original: Any, watermarked: Any, attacked: Any, data_range: float = 255.0) -> dict[str, Any]:
    return {
        "watermarked_vs_original": image_quality(original, watermarked, data_range=data_range),
        "attacked_vs_original": image_quality(original, attacked, data_range=data_range),
        "metric_semantics": {
            "watermarked_vs_original": "embedding invisibility",
            "attacked_vs_original": "end-to-end propagation quality",
        },
    }
