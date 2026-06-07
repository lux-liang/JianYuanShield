"""LIDMark MEA adapter — wraps LIDMarkEncoder + FHD for the attack matrix.

Message: 16-bit identity watermark (the id_head portion of 152-D watermark).
The 136-D landmark coordinates are set to zeros during MEA encode (not available without face detector).
"""
from __future__ import annotations

import sys
import numpy as np
from pathlib import Path
from PIL import Image

from .base import DecodeResult, EmbeddingResult, ModelAdapter
from system.evaluation.runtime import PROJECT_ROOT

LIDMARK_CODE = Path("/data1/luxliang/work/vpsg_competition_candidates/LIDMark")
S1_CKPT_DIR = Path("/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark/seed_checkpoints/s1")
IMG_SIZE = 128
MSG_LEN = 16          # id bits only (last 16 of 152-D watermark)
LANDMARK_LEN = 136    # first 136 dims: continuous facial landmarks (set to 0 for MEA)
WM_LEN = MSG_LEN + LANDMARK_LEN  # 152


def _latest_ckpt(seed_dir: Path) -> Path | None:
    ckpts = sorted(seed_dir.glob("checkpoint_epoch_*.pth"),
                   key=lambda p: int(p.stem.split("_")[-1]))
    return ckpts[-1] if ckpts else None


class LIDMarkAdapter(ModelAdapter):
    name = "LIDMark"
    message_length = MSG_LEN

    @property
    def checkpoint(self) -> str | None:
        p = _latest_ckpt(S1_CKPT_DIR)
        return str(p) if p else None

    @property
    def available(self) -> bool:
        return _latest_ckpt(S1_CKPT_DIR) is not None

    @property
    def blocker(self) -> str | None:
        return None if self.available else "lidmark_checkpoint_missing"

    def _load_models(self):
        if hasattr(self, "_encoder"):
            return
        import torch
        if str(LIDMARK_CODE) not in sys.path:
            sys.path.insert(0, str(LIDMARK_CODE))

        from model.lidmark import LIDMarkEncoder, FHD

        ckpt_path = _latest_ckpt(S1_CKPT_DIR)
        ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
        cfg_list = ckpt.get("configs", [])
        cfg = dict(cfg_list) if isinstance(cfg_list, list) else cfg_list

        en_c = int(cfg.get("encoder_channels", 64))
        en_b = int(cfg.get("encoder_blocks", 3))
        de_c = int(cfg.get("decoder_channels", 64))
        de_b = int(cfg.get("decoder_blocks", 1))

        import os as _os
        _dev_str = _os.environ.get("JYS_INFER_DEVICE", "cuda:2")
        self._device = torch.device(_dev_str if torch.cuda.is_available() else "cpu")

        enc = LIDMarkEncoder(IMG_SIZE, en_c, en_b, WM_LEN).to(self._device)
        dec = FHD(IMG_SIZE, de_c, de_b, WM_LEN).to(self._device)

        state = ckpt["model_state_dict"]
        enc_state = {k[len("encoder."):]: v for k, v in state.items() if k.startswith("encoder.")}
        dec_state = {k[len("decoder."):]: v for k, v in state.items() if k.startswith("decoder.")}
        enc.load_state_dict(enc_state, strict=True)
        dec.load_state_dict(dec_state, strict=True)
        enc.eval(); dec.eval()

        self._encoder = enc
        self._decoder = dec
        self._ckpt_path = str(ckpt_path)

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        import torch
        self.validate_image(image)
        bits = self.validate_message(message)
        self._load_models()

        img_pil = Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)
        arr = np.array(img_pil).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self._device)
        # Normalize to [-1, 1]
        t = t * 2 - 1

        # Build 152-D watermark: [0...0 (136 landmarks), id_bits (16)]
        id_float = (bits.astype(np.float32) * 2 - 1)  # 0/1 → -1/+1
        wm_np = np.zeros(WM_LEN, dtype=np.float32)
        wm_np[LANDMARK_LEN:] = id_float
        wm_t = torch.from_numpy(wm_np).unsqueeze(0).to(self._device)

        with torch.no_grad():
            encoded_t = self._encoder(t, wm_t)
            encoded_t = encoded_t.clamp(-1, 1)

        # Back to uint8
        enc_np = ((encoded_t[0].cpu().numpy().transpose(1, 2, 0) + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
        if enc_np.shape[:2] != image.shape[:2]:
            enc_np = np.array(Image.fromarray(enc_np).resize((image.shape[1], image.shape[0]), Image.BICUBIC))

        return EmbeddingResult(
            image=enc_np,
            message=bits,
            metadata={"model": "LIDMark", "checkpoint": self._ckpt_path,
                      "img_size": IMG_SIZE, "msg_len": MSG_LEN},
        )

    def decode(self, image: np.ndarray) -> DecodeResult:
        import torch
        self.validate_image(image)
        self._load_models()

        arr = np.array(Image.fromarray(image).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self._device)
        t = t * 2 - 1

        with torch.no_grad():
            _, id_logits = self._decoder(t)
        # id_logits: (1, 16) raw linear outputs → sigmoid → threshold
        probs = torch.sigmoid(id_logits).cpu().numpy()[0]
        bits = (probs >= 0.5).astype(np.uint8)

        return DecodeResult(
            bits=bits,
            metadata={"decoder": "FHD_id_head", "id_probs": probs.tolist()},
        )
