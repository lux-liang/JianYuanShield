from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from system.evaluation.runtime import MODEL_SOURCE_ROOT

_HIDDEN_CODE = MODEL_SOURCE_ROOT / "MEA/codes/HiDDeN"
_HIDDEN_RUN = MODEL_SOURCE_ROOT / "MEA/codes/HiDDeN/runs/hidden_celeba_noise 2026.06.07--23-58-20"
_OPTIONS_FILE = _HIDDEN_RUN / "options-and-config.pickle"
_CHECKPOINT_FILE = _HIDDEN_RUN / "checkpoints" / "hidden_celeba_noise--epoch-300.pyt"

# Fallback to old run if new checkpoint not available
_OLD_RUN = Path(__file__).resolve().parents[3] / "weights/mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43"
_OLD_CKPT = _OLD_RUN / "checkpoints" / "train-test-1--epoch-200.pyt"

_ACTIVE_RUN = _HIDDEN_RUN if _OPTIONS_FILE.exists() else _OLD_RUN
_ACTIVE_OPTIONS = _ACTIVE_RUN / "options-and-config.pickle"
_ACTIVE_CKPT = _CHECKPOINT_FILE if _CHECKPOINT_FILE.exists() else (_OLD_CKPT if _OLD_CKPT.exists() else None)


class HiDDeNAdapter(ModelAdapter):
    name = "HiDDeN"
    message_length = 30  # overridden at load time from config
    checkpoint = str(_ACTIVE_CKPT) if _ACTIVE_CKPT else None

    def __init__(self) -> None:
        self._net = None
        self._config = None
        self._device = None

    @property
    def available(self) -> bool:
        return _ACTIVE_OPTIONS.exists() and _ACTIVE_CKPT is not None and _ACTIVE_CKPT.exists()

    @property
    def blocker(self) -> str | None:
        if not _ACTIVE_OPTIONS.exists():
            return "options_missing"
        if _ACTIVE_CKPT is None or not _ACTIVE_CKPT.exists():
            return "checkpoint_missing"
        return None

    def _ensure_loaded(self, device_str: str = "cuda:0") -> None:
        if self._net is not None:
            return
        import torch
        if str(_HIDDEN_CODE) not in sys.path:
            sys.path.insert(0, str(_HIDDEN_CODE))
        import utils  # type: ignore
        from model.hidden import Hidden  # type: ignore
        from noise_layers.noiser import Noiser  # type: ignore

        device = torch.device(device_str if torch.cuda.is_available() else "cpu")
        train_options, hidden_config, noise_config = utils.load_options(str(_ACTIVE_OPTIONS))
        noiser = Noiser(noise_config, device)
        checkpoint = torch.load(str(_ACTIVE_CKPT), map_location=device)
        net = Hidden(hidden_config, device, noiser, None)
        utils.model_from_checkpoint(net, checkpoint)
        net.encoder_decoder.eval()
        net.discriminator.eval()

        self._net = net
        self._config = hidden_config
        self._device = device
        # Update message_length from actual config
        self.message_length = hidden_config.message_length

    def _to_tensor(self, arr: np.ndarray):
        import torch
        import torchvision.transforms.functional as TF
        t = TF.to_tensor(arr).to(self._device)
        return (t * 2 - 1).unsqueeze(0)

    def _to_uint8(self, tensor) -> np.ndarray:
        arr = tensor.detach().cpu().clamp(-1, 1)
        arr = ((arr + 1) / 2)[0].permute(1, 2, 0).numpy()
        return np.clip(arr * 255, 0, 255).astype(np.uint8)

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        import torch
        self._ensure_loaded()
        self.validate_image(image)
        bits = self.validate_message(message)

        H, W = self._config.H, self._config.W
        resized = np.array(Image.fromarray(image).resize((W, H), Image.BICUBIC))
        img_t = self._to_tensor(resized)

        msg_t = torch.tensor(bits.astype(np.float32), dtype=torch.float32, device=self._device).unsqueeze(0)
        with torch.no_grad():
            encoded_t = self._net.encoder_decoder.encoder(img_t, msg_t)

        encoded_arr = self._to_uint8(encoded_t)
        # Resize back to original size
        if encoded_arr.shape[:2] != image.shape[:2]:
            encoded_arr = np.array(Image.fromarray(encoded_arr).resize(
                (image.shape[1], image.shape[0]), Image.BICUBIC))
        return EmbeddingResult(
            image=encoded_arr,
            message=bits,
            metadata={"model": "HiDDeN", "img_size": H, "msg_len": self.message_length,
                      "checkpoint": str(_ACTIVE_CKPT)},
        )

    def decode(self, image: np.ndarray) -> DecodeResult:
        import torch
        self._ensure_loaded()
        self.validate_image(image)

        H, W = self._config.H, self._config.W
        resized = np.array(Image.fromarray(image).resize((W, H), Image.BICUBIC))
        img_t = self._to_tensor(resized)

        with torch.no_grad():
            decoded_t = self._net.encoder_decoder.decoder(img_t)

        bits = decoded_t.detach().cpu()[0].numpy().round().clip(0, 1).astype(np.uint8)
        return DecodeResult(
            bits=bits,
            metadata={"model": "HiDDeN"},
        )
