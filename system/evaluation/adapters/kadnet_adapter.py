"""KAD-Net (ST branch) MEA adapter.

Message: 30-bit watermark (ST_KAD_Net_128_30_... configuration).
Checkpoint: the official released ST/128 epoch-100 checkpoint.
"""
from __future__ import annotations

import sys
import types
import numpy as np
from pathlib import Path
from PIL import Image

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from system.evaluation.runtime import MODEL_SOURCE_ROOT, WEIGHT_ROOT

KADNET_CODE = MODEL_SOURCE_ROOT / "KAD-Net"
KADNET_CHECKPOINT = WEIGHT_ROOT / "KAD-Net/ST/128/models/EC_100.pth"
KADNET_CHECKPOINT_SHA256 = (
    "3b298493ae3510e73fc85a5fcae2f470d8e6892e9e058aa9cca3a0d8d35f5079"
)
IMG_SIZE = 128
MSG_LEN = 30


def _selected_run_and_checkpoint() -> tuple[Path, Path] | tuple[None, None]:
    """Return the official epoch-100 checkpoint; never auto-select a newer file."""

    if not KADNET_CHECKPOINT.is_file():
        return None, None
    return KADNET_CHECKPOINT.parent.parent, KADNET_CHECKPOINT


class KADNetAdapter(ModelAdapter):
    name = "KAD-Net"
    message_length = MSG_LEN
    checkpoint = str(KADNET_CHECKPOINT)
    expected_checkpoint_sha256 = KADNET_CHECKPOINT_SHA256
    checkpoint_selection = "official_released_epoch100"
    primary_decoder = "ST_Decoder_C"

    @property
    def available(self) -> bool:
        _, ckpt = _selected_run_and_checkpoint()
        return ckpt is not None

    @property
    def blocker(self) -> str | None:
        return None if self.available else "kadnet_checkpoint_missing"

    def _load_models(self):
        if hasattr(self, "_encoder"):
            return
        import torch

        _run_dir, ckpt_path = _selected_run_and_checkpoint()
        if ckpt_path is None:
            raise RuntimeError("No KAD-Net checkpoint found")

        # Add KAD-Net code to path (isolate from other 'network' packages)
        kn_str = str(KADNET_CODE)
        if kn_str not in sys.path:
            sys.path.insert(0, kn_str)

        # Clear any stale 'network' cache entries before importing
        for mod in list(sys.modules.keys()):
            if mod in ("network", "config") or mod.startswith("network."):
                del sys.modules[mod]

        # The official inference core imports Random_Noise even though encode
        # and decode never call it. Its transitive optional deepfake packages
        # are not part of the released checkpoint, so expose only the inert
        # class required to import the checkpoint-backed core.
        import torch.nn as nn
        import network

        random_noise_stub = types.ModuleType("network.Random_Noise")

        class RandomNoise(nn.Module):
            def __init__(self, *_args, **_kwargs) -> None:
                super().__init__()

            def forward(self, values):
                return values[0], values[0], values[0]

        random_noise_stub.Random_Noise = RandomNoise
        sys.modules["network.Random_Noise"] = random_noise_stub
        from network.ST_EncoderDecoder import ST_Encoder, ST_Decoder

        import os as _os
        _dev_str = _os.environ.get("JYS_INFER_DEVICE", "cuda:0")
        self._device = torch.device(_dev_str if torch.cuda.is_available() else "cpu")

        state = torch.load(str(ckpt_path), map_location=self._device, weights_only=True)
        enc_state = {k[len("encoder."):]: v for k, v in state.items() if k.startswith("encoder.")}
        dec_state = {k[len("decoder_C."):]: v for k, v in state.items() if k.startswith("decoder_C.")}

        # Auto-detect attention type from checkpoint keys (more robust than parsing run name)
        has_enc_se = any(".se." in k for k in enc_state)
        has_dec_se = any(".se." in k for k in dec_state)
        attn_enc = "se" if has_enc_se else None
        attn_dec = "se" if has_dec_se else None

        encoder = ST_Encoder(MSG_LEN, attention=attn_enc).to(self._device)
        decoder = ST_Decoder(MSG_LEN, attention=attn_dec).to(self._device)

        encoder.load_state_dict(enc_state, strict=True)
        decoder.load_state_dict(dec_state, strict=True)
        encoder.eval(); decoder.eval()

        self._encoder = encoder
        self._decoder = decoder
        self._ckpt_path = str(ckpt_path)

    def _preprocess(self, image: np.ndarray) -> "torch.Tensor":
        """Normalize to [-1,1] matching training Normalize([0.5]*3,[0.5]*3)."""
        import torch
        from torchvision import transforms
        t = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
        ])
        img_resized = Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)
        return t(img_resized).unsqueeze(0).to(self._device)

    def _denormalize(self, tensor: "torch.Tensor") -> np.ndarray:
        """Convert [-1,1] tensor to uint8 [0,255] numpy array."""
        arr = (tensor.detach().cpu().clamp(-1, 1).permute(1, 2, 0).numpy() + 1.0) * 127.5
        return np.clip(arr + 0.5, 0, 255).astype(np.uint8)

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        import torch
        self.validate_image(image)
        bits = self.validate_message(message)
        self._load_models()

        t = self._preprocess(image)
        # KAD-Net training uses msg_range=0.1: {-0.1, 0.1} not {0, 1}
        msg_vals = (bits.astype(np.float32) * 0.2 - 0.1)  # {0,1} → {-0.1, 0.1}
        msg_t = torch.from_numpy(msg_vals).unsqueeze(0).to(self._device)

        with torch.no_grad():
            encoded_t = self._encoder(t, msg_t).clamp(-1, 1)

        enc_np = self._denormalize(encoded_t[0])
        if enc_np.shape[:2] != image.shape[:2]:
            enc_np = np.array(Image.fromarray(enc_np).resize((image.shape[1], image.shape[0]), Image.BICUBIC))

        return EmbeddingResult(
            image=enc_np,
            message=bits,
            metadata={"model": "KAD-Net", "checkpoint": self._ckpt_path,
                      "img_size": IMG_SIZE, "msg_len": MSG_LEN},
        )

    def decode(self, image: np.ndarray) -> DecodeResult:
        import torch
        self.validate_image(image)
        self._load_models()

        t = self._preprocess(image)
        with torch.no_grad():
            decoded = self._decoder(t)
        # Decoder outputs values near {-0.1, 0.1}; use gt(0) to binarize
        bits = decoded.cpu().gt(0).numpy()[0].astype(np.uint8)

        return DecodeResult(
            bits=bits,
            metadata={
                "decoder": self.primary_decoder,
                "primary_decoder": self.primary_decoder,
            },
        )
