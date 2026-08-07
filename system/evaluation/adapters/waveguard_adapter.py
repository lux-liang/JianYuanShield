from __future__ import annotations

import numpy as np
from PIL import Image

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from system.evaluation.runtime import WEIGHT_ROOT

CKPT = (
    WEIGHT_ROOT
    / 'MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth'
)
CHECKPOINT_SHA256 = (
    'cd093467a834cde47a0abed1d90a3ed62120092a2affcbcb1ed2f7d72b346377'
)
MSG_LEN = 30
IMG_SIZE = 256


class WaveGuardModelAdapter(ModelAdapter):
    name = 'WaveGuard'
    message_length = MSG_LEN
    checkpoint = str(CKPT)
    expected_checkpoint_sha256 = CHECKPOINT_SHA256
    checkpoint_selection = 'fixed_content_addressed_epoch16'
    primary_decoder = 'tracer'
    secondary_decoder = 'detector'

    def __init__(self) -> None:
        from system.backend.model_adapters import WaveGuardAdapter as _WA
        self._adapter = _WA.get()

    @property
    def available(self) -> bool:
        return CKPT.exists()

    @property
    def blocker(self) -> str | None:
        return None if self.available else 'checkpoint_missing'

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        import torch
        self.validate_image(image)
        bits = self.validate_message(message)
        a = self._adapter

        import cv2
        arr = np.array(Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC))
        yuv_t = a._rgb_to_yuv_tensor(arr)
        msg_vals = (bits.astype(np.float32) * 2 - 1) * a.cfg.message_range
        msg_t = torch.tensor(msg_vals, dtype=torch.float32, device=a.device).unsqueeze(0)

        with torch.no_grad():
            y, u, v = yuv_t[:,[0]], yuv_t[:,[1]], yuv_t[:,[2]]
            lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
            sel = torch.index_select(hp[1], 2, a.indices_enc)[:,:,:,:,:,0].squeeze(1)
            emb = a.encoder(sel, msg_t).unsqueeze(1)
            hp[1][:,:,a.indices_enc,:,:,0] = emb
            u_emb = a.DTCWT.dtcwt_images_U(lp, hp)
            wm_yuv = torch.cat([y, u_emb, v], dim=1).clamp(-1, 1)

        encoded_u8 = a._yuv_tensor_to_rgb(wm_yuv)
        if encoded_u8.shape[:2] != image.shape[:2]:
            encoded_u8 = np.array(Image.fromarray(encoded_u8).resize(
                (image.shape[1], image.shape[0]), Image.BICUBIC))
        return EmbeddingResult(
            image=encoded_u8,
            message=bits,
            metadata={'model': 'WaveGuard', 'img_size': IMG_SIZE, 'msg_len': MSG_LEN},
        )

    def decode(self, image: np.ndarray) -> DecodeResult:
        import torch
        self.validate_image(image)
        a = self._adapter

        arr = np.array(Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC))
        yuv_t = a._rgb_to_yuv_tensor(arr)

        with torch.no_grad():
            u_atk = yuv_t[:,[1]]
            lp2, hp2 = a.DTCWT.images_U_dtcwt_with_low(u_atk)
            sel_t = torch.index_select(hp2[1], 2, a.indices_dec_t)[:,:,:,:,:,0].squeeze(1)
            sel_d = torch.index_select(hp2[1], 2, a.indices_dec_d)[:,:,:,:,:,0].squeeze(1)
            decoded_t = a.decoder_t(sel_t)
            decoded_d = a.decoder_d(sel_d)

        bits_t = (decoded_t.detach().cpu()[0].numpy() > 0).astype(np.uint8)
        bits_d = (decoded_d.detach().cpu()[0].numpy() > 0).astype(np.uint8)
        return DecodeResult(
            bits=bits_t,
            metadata={
                'decoder': self.primary_decoder,
                'primary_decoder': self.primary_decoder,
                'secondary_decoder': self.secondary_decoder,
                'secondary_bits': bits_d.tolist(),
            },
        )
