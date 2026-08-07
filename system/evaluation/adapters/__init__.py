from __future__ import annotations

from pathlib import Path

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from .multi_embedding import MultiEmbeddingResult, evaluate_double_embedding


MEA_MODEL_ORDER = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")


def get_mea_adapter_classes() -> dict[str, type[ModelAdapter]]:
    """Return the frozen four-model MEA registry, including missing models."""

    from .kadnet_adapter import KADNetAdapter
    from .lidmark_adapter import LIDMarkAdapter
    from .sepmark_adapter import SepMarkModelAdapter
    from .waveguard_adapter import WaveGuardModelAdapter

    return {
        "LIDMark": LIDMarkAdapter,
        "KAD-Net": KADNetAdapter,
        "SepMark": SepMarkModelAdapter,
        "WaveGuard": WaveGuardModelAdapter,
    }


def _checkpoint_exists(adapter_class: type[ModelAdapter]) -> bool:
    checkpoint = getattr(adapter_class, "checkpoint", None)
    return bool(checkpoint and Path(str(checkpoint)).expanduser().is_file())


def get_available_adapters() -> dict[str, type[ModelAdapter]]:
    """Return checkpoint-backed adapters without loading model weights.

    The four MEA entries are pinned to the same selected checkpoints as the
    formal benchmark runners. HiDDeN remains available to legacy callers but
    is not part of the frozen 4x4 matrix.
    """

    adapters = {
        name: adapter_class
        for name, adapter_class in get_mea_adapter_classes().items()
        if _checkpoint_exists(adapter_class)
    }

    try:
        from .hidden_adapter import _ACTIVE_CKPT, _ACTIVE_OPTIONS, HiDDeNAdapter

        if (
            _ACTIVE_OPTIONS.is_file()
            and _ACTIVE_CKPT is not None
            and _ACTIVE_CKPT.is_file()
        ):
            adapters["HiDDeN"] = HiDDeNAdapter
    except (ImportError, OSError):
        pass

    return adapters


__all__ = [
    "DecodeResult",
    "EmbeddingResult",
    "MEA_MODEL_ORDER",
    "ModelAdapter",
    "MultiEmbeddingResult",
    "evaluate_double_embedding",
    "get_available_adapters",
    "get_mea_adapter_classes",
]
