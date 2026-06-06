from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EmbeddingResult:
    image: np.ndarray
    message: np.ndarray
    metadata: dict


@dataclass(frozen=True)
class DecodeResult:
    bits: np.ndarray
    metadata: dict


class ModelAdapter(ABC):
    name: str
    message_length: int
    checkpoint: str | None

    @property
    def available(self) -> bool:
        return True

    @property
    def blocker(self) -> str | None:
        return None

    @abstractmethod
    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        """Embed one binary message into an RGB uint8 image."""

    @abstractmethod
    def decode(self, image: np.ndarray) -> DecodeResult:
        """Decode a binary message from an RGB uint8 image."""

    def validate_image(self, image: np.ndarray) -> None:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError(f"{self.name}: expected HxWx3 uint8 RGB image, got {image.shape}/{image.dtype}")

    def validate_message(self, message: np.ndarray) -> np.ndarray:
        bits = np.asarray(message, dtype=np.uint8).reshape(-1)
        if bits.size != self.message_length:
            raise ValueError(f"{self.name}: expected {self.message_length} bits, got {bits.size}")
        if not np.isin(bits, [0, 1]).all():
            raise ValueError(f"{self.name}: message must contain only 0/1")
        return bits
