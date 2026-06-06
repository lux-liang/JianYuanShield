from __future__ import annotations

import numpy as np
from PIL import Image

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from system.evaluation.runtime import MODEL_SOURCE_ROOT, PROJECT_ROOT

CKPT = PROJECT_ROOT / 'weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth'
MSG_LEN = 128
IMG_SIZE = 256


class SepMarkModelAdapter(ModelAdapter):
    name = 'SepMark'
    message_length = MSG_LEN
    checkpoint = str(CKPT)

    def __init__(self) -> None:
        from system.backend.model_adapters import SepMarkAdapter as _SA
        self._adapter = _SA.get()

    @property
    def available(self) -> bool:
        return CKPT.exists()

    @property
    def blocker(self) -> str | None:
        return None if self.available else 'checkpoint_missing'

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        import torch
        from system.backend.model_adapters import _to_tensor_rgb, _to_uint8_rgb, SEPMARK_CKPT
        self.validate_image(image)
        bits = self.validate_message(message)
        adapter = self._adapter

        img_pil = Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)
        arr = np.array(img_pil)
        tensor = _to_tensor_rgb(arr, adapter.device)
        # Convert 0/1 bits to -0.1/+0.1 message range
        msg_vals = (bits.astype(np.float32) * 2 - 1) * 0.1
        msg_t = torch.tensor(msg_vals, dtype=torch.float32, device=adapter.device).unsqueeze(0)
        with torch.no_grad():
            encoded_t = adapter.encoder(tensor, msg_t).clamp(-1, 1)
        encoded_u8 = _to_uint8_rgb(encoded_t[0])
        # Resize back to original size if needed
        if encoded_u8.shape[:2] != image.shape[:2]:
            encoded_u8 = np.array(Image.fromarray(encoded_u8).resize(
                (image.shape[1], image.shape[0]), Image.BICUBIC))
        return EmbeddingResult(
            image=encoded_u8,
            message=bits,
            metadata={'model': 'SepMark', 'img_size': IMG_SIZE, 'msg_len': MSG_LEN},
        )

    def decode(self, image: np.ndarray) -> DecodeResult:
        import torch
        from system.backend.model_adapters import _to_tensor_rgb
        self.validate_image(image)
        adapter = self._adapter

        arr = np.array(Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC))
        tensor = _to_tensor_rgb(arr, adapter.device)
        with torch.no_grad():
            decoded_c = adapter.decoder_c(tensor)
            decoded_rf = adapter.decoder_rf(tensor)
        bits_c = (decoded_c.detach().cpu()[0].numpy() > 0).astype(np.uint8)
        bits_rf = (decoded_rf.detach().cpu()[0].numpy() > 0).astype(np.uint8)
        # Use decoder_RF as primary (more robust)
        return DecodeResult(
            bits=bits_rf,
            metadata={'decoder': 'decoder_RF', 'decoder_c_bits': bits_c.tolist()},
        )
