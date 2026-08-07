from __future__ import annotations

import os
import sys
import threading
import types
import hashlib
import hmac
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

try:
    import torch
    from torchvision import transforms
except (ImportError, OSError):
    torch = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]

from system.evaluation.runtime import MODEL_SOURCE_ROOT, WEIGHT_ROOT
from system.evaluation.attacks import apply_attack

SEPMARK_CODE  = MODEL_SOURCE_ROOT / "MEA/codes/SepMark"
WAVEGUARD_CODE = MODEL_SOURCE_ROOT / "MEA/codes/WaveGuard"
SEPMARK_CKPT = (
    WEIGHT_ROOT
    / "MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth"
)
WAVEGUARD_CKPT = (
    WEIGHT_ROOT
    / "MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
)
LIDMARK_CKPT = WEIGHT_ROOT / "lidmark/lfw-id-s20260603-128/checkpoint_epoch_20.pth"
KADNET_CKPT = WEIGHT_ROOT / "KAD-Net/ST/128/models/EC_100.pth"

SEPMARK_CKPT_SHA256 = "433992186176483bd92341fd033cf3c2fa2682f159aea7fe4542c4a6b88b5e55"
WAVEGUARD_CKPT_SHA256 = "cd093467a834cde47a0abed1d90a3ed62120092a2affcbcb1ed2f7d72b346377"
LIDMARK_CKPT_SHA256 = "762369c8e4e881c8d72fde08ebaf7fea3fd7a26354aa344aed288cb780ad3436"
KADNET_CKPT_SHA256 = "3b298493ae3510e73fc85a5fcae2f470d8e6892e9e058aa9cca3a0d8d35f5079"

_lock = threading.Lock()


def _torch_runtime_available() -> bool:
    """Allow evidence-only web nodes to start without the GPU inference stack."""

    return torch is not None and transforms is not None


@lru_cache(maxsize=16)
def _checkpoint_digest(
    path_text: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    """Hash one stable file identity and cache only status probes."""

    del device, inode, size, mtime_ns, ctime_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_available(path: Path, expected_sha256: str) -> bool:
    try:
        stat = path.stat()
        actual = _checkpoint_digest(
            str(path.resolve()),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
    except OSError:
        return False
    return hmac.compare_digest(actual, expected_sha256)


def _load_pinned_checkpoint(
    path: Path,
    expected_sha256: str,
    *,
    map_location: torch.device,
) -> Any:
    """Verify and deserialize the exact same open checkpoint handle."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        actual = digest.hexdigest()
        if not hmac.compare_digest(actual, expected_sha256):
            raise RuntimeError(f"checkpoint SHA-256 mismatch: {path.name}")
        handle.seek(0)
        return torch.load(handle, map_location=map_location, weights_only=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_tensor_rgb(array: np.ndarray, device: torch.device) -> torch.Tensor:
    t = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.5]*3, [0.5]*3),
    ])
    return t(Image.fromarray(array.astype(np.uint8))).unsqueeze(0).to(device)


def _to_uint8_rgb(tensor: torch.Tensor) -> np.ndarray:
    arr = (tensor.detach().cpu().clamp(-1, 1).permute(1, 2, 0).numpy() + 1.0) * 127.5
    return np.clip(arr + 0.5, 0, 255).astype(np.uint8)


def _apply_attack_rgb(arr: np.ndarray, attack: str) -> np.ndarray:
    """Apply the shared, protocol-versioned attack implementation."""
    canonical = {
        "resize": "resize_0.5x",
        "noise": "gaussian_noise_sigma_3",
        "blur": "gaussian_blur_5",
    }.get(attack, attack)
    image_id = hashlib.sha256(arr.tobytes()).hexdigest()
    attacked, _metadata = apply_attack(arr, canonical, image_id=image_id)
    return attacked


def _bit_error(msg: torch.Tensor, decoded: torch.Tensor) -> float:
    return float((msg.cpu().gt(0) != decoded.cpu().gt(0)).float().mean().item())


def _random_message(length: int, device: torch.device, rng_range: float = 0.1) -> torch.Tensor:
    vals = np.random.choice([-rng_range, rng_range], (1, length))
    return torch.tensor(vals, dtype=torch.float32, device=device)


def _heatmap(ref: np.ndarray, cand: np.ndarray) -> np.ndarray:
    diff = np.mean(np.abs(ref.astype(np.float32) - cand.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.applyColorMap(diff, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)


# ── SepMark adapter ──────────────────────────────────────────────────────────

class SepMarkAdapter:
    _instance: "SepMarkAdapter | None" = None
    MSG_LEN = 128
    IMG_SIZE = 256

    def __init__(self) -> None:
        import os as _os
        _device_str = _os.environ.get("JYS_INFER_DEVICE", "cuda:0")
        self.device = torch.device(_device_str if torch.cuda.is_available() else "cpu")
        import importlib.util as _ilu, types as _types
        # Register SepMark network as sm_network package to isolate from WaveGuard network
        _sm_code = SEPMARK_CODE / "network"
        _sm_pkg = _types.ModuleType("sm_network")
        _sm_pkg.__path__ = [str(_sm_code)]
        _sm_pkg.__package__ = "sm_network"
        sys.modules["sm_network"] = _sm_pkg
        def _sm_sub(name):
            sp = _ilu.spec_from_file_location(f"sm_network.{name}", _sm_code / f"{name}.py")
            m = _ilu.module_from_spec(sp); m.__package__ = "sm_network"
            sys.modules[f"sm_network.{name}"] = m; sp.loader.exec_module(m); return m
        # Pre-load sub-modules that __init__.py needs via relative imports
        _sm_sub("ResBlock"); _sm_sub("ConvBlock")
        # Now exec the package __init__.py
        _init_sp = _ilu.spec_from_file_location("sm_network", _sm_code / "__init__.py",
            submodule_search_locations=[str(_sm_code)])
        _init_sp.loader.exec_module(_sm_pkg)
        # Load Encoder_U and Decoder_U under sm_network namespace
        _sm_eu = _sm_sub("Encoder_U")
        _sm_du = _sm_sub("Decoder_U")
        DW_Encoder = _sm_eu.DW_Encoder
        DW_Decoder = _sm_du.DW_Decoder

        enc = DW_Encoder(self.MSG_LEN, attention="se").to(self.device)
        dec_c = DW_Decoder(self.MSG_LEN, attention="se").to(self.device)
        dec_rf = DW_Decoder(self.MSG_LEN, attention="se").to(self.device)
        state = _load_pinned_checkpoint(
            SEPMARK_CKPT,
            SEPMARK_CKPT_SHA256,
            map_location=self.device,
        )

        def strip(prefix: str) -> dict:
            return {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}

        enc.load_state_dict(strip("encoder."), strict=True)
        dec_c.load_state_dict(strip("decoder_C."), strict=True)
        dec_rf.load_state_dict(strip("decoder_RF."), strict=True)
        self.encoder = enc.eval()
        self.decoder_c = dec_c.eval()
        self.decoder_rf = dec_rf.eval()

    @classmethod
    def get(cls) -> "SepMarkAdapter":
        with _lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def available(cls) -> bool:
        return _torch_runtime_available() and _checkpoint_available(
            SEPMARK_CKPT, SEPMARK_CKPT_SHA256
        )

    def run(self, image_rgb: np.ndarray, attack: str = "clean") -> dict[str, Any]:
        img = Image.fromarray(image_rgb).convert("RGB").resize(
            (self.IMG_SIZE, self.IMG_SIZE), Image.BICUBIC)
        arr = np.array(img)
        tensor = _to_tensor_rgb(arr, self.device)
        msg = _random_message(self.MSG_LEN, self.device)

        with torch.no_grad():
            encoded_t = self.encoder(tensor, msg).clamp(-1, 1)

        original_u8 = arr
        encoded_u8 = _to_uint8_rgb(encoded_t[0])
        attacked_arr = _apply_attack_rgb(encoded_u8.copy(), attack)
        attacked_t = _to_tensor_rgb(attacked_arr, self.device)

        with torch.no_grad():
            dec_c_out = self.decoder_c(attacked_t)
            dec_rf_out = self.decoder_rf(attacked_t)

        ber_c = _bit_error(msg, dec_c_out)
        ber_rf = _bit_error(msg, dec_rf_out)
        from skimage.metrics import peak_signal_noise_ratio, structural_similarity
        psnr = float(peak_signal_noise_ratio(original_u8, encoded_u8, data_range=255))
        ssim = float(structural_similarity(original_u8, encoded_u8, channel_axis=2, data_range=255))

        return {
            "model": "SepMark",
            "checkpoint": "real",
            "attack": attack,
            "ber_c": round(ber_c, 4),
            "bit_accuracy_c": round(1 - ber_c, 4),
            "ber_rf": round(ber_rf, 4),
            "bit_accuracy_rf": round(1 - ber_rf, 4),
            "primary_decoder": "decoder_C",
            "secondary_decoder": "decoder_RF",
            "psnr": round(psnr, 4),
            "ssim": round(ssim, 4),
            "success": bool((1 - ber_c) >= 0.9),
            "images": {
                "original": original_u8,
                "watermarked": encoded_u8,
                "attacked": attacked_arr,
                "heatmap": _heatmap(original_u8, encoded_u8),
                "diff": _heatmap(encoded_u8, attacked_arr),
            },
        }


# ── WaveGuard adapter ─────────────────────────────────────────────────────────

class WaveGuardAdapter:
    _instance: "WaveGuardAdapter | None" = None
    MSG_LEN = 30
    IMG_SIZE = 256

    def __init__(self) -> None:
        _device_str = os.environ.get("JYS_INFER_DEVICE", "cuda:0")
        self.device = torch.device(_device_str if torch.cuda.is_available() else "cpu")
        old_cwd = Path.cwd()
        try:
            os.chdir(WAVEGUARD_CODE)
            sys.path.insert(0, str(WAVEGUARD_CODE))
            # Clear stale network/config/utils from KAD-Net before loading WaveGuard modules
            for _m in list(sys.modules.keys()):
                if _m in ("network", "config", "utils") or _m.startswith(("network.", "utils.")):
                    del sys.modules[_m]
            from config import training_config as cfg
            from network.encoder import Encoder
            from network.decoder import Decoder
            from utils import DTCWT_highpass
        finally:
            os.chdir(old_cwd)
        # Override config device to match adapter device (config yaml hardcodes cuda:0)
        cfg.device = str(self.device)

        self.cfg = cfg
        self.DTCWT = DTCWT_highpass
        self.indices_enc = torch.tensor([0, 2]).to(self.device)
        self.indices_dec_t = torch.tensor([0, 2, 3, 5]).to(self.device)
        self.indices_dec_d = torch.tensor([0, 2]).to(self.device)

        enc = Encoder().to(self.device).eval()
        dec_t = Decoder(type="tracer").to(self.device).eval()
        dec_d = Decoder(type="detector").to(self.device).eval()
        state = _load_pinned_checkpoint(
            WAVEGUARD_CKPT,
            WAVEGUARD_CKPT_SHA256,
            map_location=self.device,
        )

        def strip(prefix: str) -> dict:
            return {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}

        enc.load_state_dict(strip("encoder."), strict=True)
        dec_t.load_state_dict(strip("decoder_t."), strict=True)
        dec_d.load_state_dict(strip("decoder_d."), strict=True)
        self.encoder = enc
        self.decoder_t = dec_t
        self.decoder_d = dec_d

    @classmethod
    def get(cls) -> "WaveGuardAdapter":
        with _lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def available(cls) -> bool:
        return _torch_runtime_available() and _checkpoint_available(
            WAVEGUARD_CKPT, WAVEGUARD_CKPT_SHA256
        )

    def _rgb_to_yuv_tensor(self, rgb: np.ndarray) -> torch.Tensor:
        yuv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32)
        return torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(self.device)

    def _yuv_tensor_to_rgb(self, tensor: torch.Tensor) -> np.ndarray:
        yuv = ((tensor.detach().cpu()[0].permute(1, 2, 0).numpy() + 1.0) * 127.5)
        yuv = np.clip(yuv, 0, 255).astype(np.uint8)
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB)

    def run(self, image_rgb: np.ndarray, attack: str = "clean") -> dict[str, Any]:
        img = Image.fromarray(image_rgb).convert("RGB").resize(
            (self.IMG_SIZE, self.IMG_SIZE), Image.BICUBIC)
        arr = np.array(img)
        yuv_t = self._rgb_to_yuv_tensor(arr)
        msg = _random_message(self.cfg.message_length, self.device, self.cfg.message_range)

        with torch.no_grad():
            y, u, v = yuv_t[:, [0]], yuv_t[:, [1]], yuv_t[:, [2]]
            low_pass, high_pass = self.DTCWT.images_U_dtcwt_with_low(u)
            selected = torch.index_select(high_pass[1], 2, self.indices_enc)
            selected = selected[:, :, :, :, :, 0].squeeze(1)
            embedded = self.encoder(selected, msg).unsqueeze(1)
            high_pass[1][:, :, self.indices_enc, :, :, 0] = embedded
            u_emb = self.DTCWT.dtcwt_images_U(low_pass, high_pass)
            watermarked_yuv = torch.cat([y, u_emb, v], dim=1).clamp(-1, 1)

        original_u8 = arr
        watermarked_u8 = self._yuv_tensor_to_rgb(watermarked_yuv)
        attacked_arr = _apply_attack_rgb(watermarked_u8.copy(), attack)
        attacked_yuv = self._rgb_to_yuv_tensor(attacked_arr)

        with torch.no_grad():
            u_atk = attacked_yuv[:, [1]]
            lp2, hp2 = self.DTCWT.images_U_dtcwt_with_low(u_atk)
            sel_t = torch.index_select(hp2[1], 2, self.indices_dec_t)[:, :, :, :, :, 0].squeeze(1)
            sel_d = torch.index_select(hp2[1], 2, self.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
            dec_t_out = self.decoder_t(sel_t)
            dec_d_out = self.decoder_d(sel_d)

        ber_t = _bit_error(msg, dec_t_out)
        ber_d = _bit_error(msg, dec_d_out)
        from skimage.metrics import peak_signal_noise_ratio, structural_similarity
        psnr = float(peak_signal_noise_ratio(original_u8, watermarked_u8, data_range=255))
        ssim = float(structural_similarity(original_u8, watermarked_u8, channel_axis=2, data_range=255))

        return {
            "model": "WaveGuard",
            "checkpoint": "real",
            "attack": attack,
            "ber_tracer": round(ber_t, 4),
            "bit_accuracy_tracer": round(1 - ber_t, 4),
            "ber_detector": round(ber_d, 4),
            "bit_accuracy_detector": round(1 - ber_d, 4),
            "psnr": round(psnr, 4),
            "ssim": round(ssim, 4),
            "success": bool((1 - ber_t) >= 0.9),
            "images": {
                "original": original_u8,
                "watermarked": watermarked_u8,
                "attacked": attacked_arr,
                "heatmap": _heatmap(original_u8, watermarked_u8),
                "diff": _heatmap(watermarked_u8, attacked_arr),
            },
        }




# -- LIDMark adapter ----------------------------------------------------------

class LIDMarkAdapter:
    _instance: "LIDMarkAdapter | None" = None
    IMG_SIZE = 128

    def __init__(self, ckpt_path: Path) -> None:
        import os as _os, sys as _sys
        self._ckpt_path = ckpt_path
        device_str = _os.environ.get("JYS_INFER_DEVICE", "cuda:0")
        self.device = torch.device(device_str if torch.cuda.is_available() else "cpu")
        lidmark_code = MODEL_SOURCE_ROOT / "LIDMark"
        if str(lidmark_code) not in _sys.path:
            _sys.path.insert(0, str(lidmark_code))
        # Clear KAD-Net utils package collision before importing LIDMark utils
        for _m in list(_sys.modules.keys()):
            if _m == "utils" or _m.startswith("utils."):
                del _sys.modules[_m]
        from model.lidmark import LIDMark
        from utils import Config, update_config_resolution
        cfg = Config()
        cfg.load_config_file(str(lidmark_code / "configurations/train_distortions.yaml"))
        update_config_resolution(cfg, self.IMG_SIZE)
        cfg.manipulation_layers = ["Identity()"]
        self.model = LIDMark(
            cfg.img_size, cfg.encoder_channels, cfg.encoder_blocks,
            cfg.decoder_channels, cfg.decoder_blocks, cfg.watermark_length,
            self.device, ["Identity()"],
        ).to(self.device)
        state = _load_pinned_checkpoint(
            ckpt_path,
            LIDMARK_CKPT_SHA256,
            map_location=self.device,
        )
        self.model.load_state_dict(state["model_state_dict"], strict=True)
        self.model.eval()
        self.wm_length = cfg.watermark_length  # 152

    @classmethod
    def _find_ckpt(cls) -> "Path | None":
        if not _torch_runtime_available():
            return None
        if _checkpoint_available(LIDMARK_CKPT, LIDMARK_CKPT_SHA256):
            return LIDMARK_CKPT
        return None

    @classmethod
    def get(cls) -> "LIDMarkAdapter | None":
        with _lock:
            if cls._instance is None:
                ckpt = cls._find_ckpt()
                if ckpt:
                    try:
                        cls._instance = cls(ckpt)
                    except Exception as exc:
                        import logging as _log
                        _log.getLogger(__name__).warning("LIDMarkAdapter init failed: %s", exc)
            return cls._instance

    @classmethod
    def available(cls) -> bool:
        return cls._find_ckpt() is not None

    def run(self, image_rgb: np.ndarray, attack: str = "clean") -> dict[str, Any]:
        img = Image.fromarray(image_rgb).convert("RGB").resize(
            (self.IMG_SIZE, self.IMG_SIZE), Image.BICUBIC)
        arr = np.array(img)
        t = (torch.from_numpy(arr.astype(np.float32) / 127.5 - 1.0)
               .permute(2, 0, 1).unsqueeze(0).to(self.device))
        # LIDMark: detect real face landmarks (68×2=136 dims), random 16-bit ID
        wm_np = np.zeros(self.wm_length, dtype=np.float32)
        try:
            if not hasattr(self, "_fa"):
                import face_alignment as _fa
                self._fa = _fa.FaceAlignment(_fa.LandmarksType.TWO_D, device=str(self.device))
            lms = self._fa.get_landmarks_from_image(arr)  # list of (68, 2) arrays
            if lms is not None and len(lms) > 0:
                # Normalize to [0,1] by dividing by IMG_SIZE (matches training)
                lm_norm = lms[0].flatten()[:136] / self.IMG_SIZE
                wm_np[:136] = lm_norm.astype(np.float32)
        except Exception:
            pass  # fallback: zeros for landmark dims
        # ID bits must be {-1.0, 1.0} — training .npy stores {-1,1}, not {0,1}
        rng = np.random.default_rng(42)
        wm_np[136:] = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=self.wm_length - 136)
        wm_t = torch.from_numpy(wm_np).unsqueeze(0).to(self.device)
        with torch.no_grad():
            encoded = self.model.encoder(t, wm_t).clamp(-1, 1)
        original_u8 = arr
        encoded_u8 = np.clip(
            (encoded[0].cpu().permute(1, 2, 0).numpy() + 1.0) * 127.5, 0, 255
        ).astype(np.uint8)
        attacked_arr = _apply_attack_rgb(encoded_u8.copy(), attack)
        attacked_t = (torch.from_numpy(attacked_arr.astype(np.float32) / 127.5 - 1.0)
                       .permute(2, 0, 1).unsqueeze(0).to(self.device))
        with torch.no_grad():
            pred_landmark, pred_id_logits = self.model.decoder(attacked_t)
        id_bits_gt = torch.from_numpy(wm_np[136:]).to(self.device) > 0
        id_bits_pred = pred_id_logits[0] > 0
        id_ber = float((id_bits_gt != id_bits_pred).float().mean().item())
        lm_raw = torch.sqrt(torch.sum(
            (pred_landmark.view(-1, 68, 2) - wm_t[:, :136].view(-1, 68, 2)) ** 2, dim=2))
        lm_raw = lm_raw[torch.isfinite(lm_raw)]
        landmark_aed = float(lm_raw.mean().item()) if lm_raw.numel() > 0 else None
        from skimage.metrics import peak_signal_noise_ratio, structural_similarity
        psnr = float(peak_signal_noise_ratio(original_u8, encoded_u8, data_range=255))
        ssim = float(structural_similarity(original_u8, encoded_u8, channel_axis=2, data_range=255))
        return {
            "model": "LIDMark",
            "checkpoint": "real",
            "attack": attack,
            "id_ber": round(id_ber, 4),
            "bit_accuracy": round(1 - id_ber, 4),
            "landmark_aed": round(landmark_aed, 4) if landmark_aed is not None else None,
            "psnr": round(psnr, 4),
            "ssim": round(ssim, 4),
            "success": bool((1 - id_ber) >= 0.9),
            "images": {
                "original": original_u8,
                "watermarked": encoded_u8,
                "attacked": attacked_arr,
                "heatmap": _heatmap(original_u8, encoded_u8),
                "diff": _heatmap(encoded_u8, attacked_arr),
            },
        }



# -- KAD-Net adapter ----------------------------------------------------------

class KADNetAdapter:
    _instance: "KADNetAdapter | None" = None
    MSG_LEN = 30
    IMG_SIZE = 128
    _CODE = MODEL_SOURCE_ROOT / "KAD-Net"

    def __init__(self, ckpt_path: Path, attn_enc: "str | None", attn_dec: "str | None") -> None:
        import os as _os, sys as _sys
        device_str = _os.environ.get("JYS_INFER_DEVICE", "cuda:0")
        self.device = torch.device(device_str if torch.cuda.is_available() else "cpu")
        # Clear stale network modules (KAD-Net conflicts with SepMark/WaveGuard 'network' pkg)
        for _mod in list(_sys.modules.keys()):
            if _mod in ("network", "config") or _mod.startswith("network."):
                del _sys.modules[_mod]
        kn_str = str(self._CODE)
        if kn_str not in _sys.path:
            _sys.path.insert(0, kn_str)
        # The official encoder imports Random_Noise, but checkpoint inference
        # never invokes it. Avoid pulling unpinned deepfake toolchains into the
        # production API process merely to construct the released ST model.
        import torch.nn as nn
        import network

        random_noise_stub = types.ModuleType("network.Random_Noise")

        class RandomNoise(nn.Module):
            def __init__(self, *_args, **_kwargs) -> None:
                super().__init__()

            def forward(self, values):
                return values[0], values[0], values[0]

        random_noise_stub.Random_Noise = RandomNoise
        _sys.modules["network.Random_Noise"] = random_noise_stub
        from network.ST_EncoderDecoder import ST_Encoder, ST_Decoder
        encoder = ST_Encoder(self.MSG_LEN, attention=attn_enc).to(self.device)
        decoder = ST_Decoder(self.MSG_LEN, attention=attn_dec).to(self.device)
        state = _load_pinned_checkpoint(
            ckpt_path,
            KADNET_CKPT_SHA256,
            map_location=self.device,
        )
        enc_s = {k[len("encoder."):]: v for k, v in state.items() if k.startswith("encoder.")}
        dec_s = {k[len("decoder_C."):]: v for k, v in state.items() if k.startswith("decoder_C.")}
        encoder.load_state_dict(enc_s, strict=True)
        decoder.load_state_dict(dec_s, strict=True)
        encoder.eval(); decoder.eval()
        self.encoder = encoder
        self.decoder = decoder
        self.ckpt_path = ckpt_path

    @classmethod
    def _find_ckpt(cls) -> "tuple[Path, str | None, str | None] | tuple[None, None, None]":
        if not _torch_runtime_available():
            return None, None, None
        if _checkpoint_available(KADNET_CKPT, KADNET_CKPT_SHA256):
            return KADNET_CKPT, "se", "se"
        return None, None, None

    @classmethod
    def get(cls) -> "KADNetAdapter | None":
        with _lock:
            if cls._instance is None:
                ckpt, ae, ad = cls._find_ckpt()
                if ckpt:
                    try:
                        cls._instance = cls(ckpt, ae, ad)
                    except Exception as exc:
                        import logging as _log
                        _log.getLogger(__name__).warning("KADNetAdapter init failed: %s", exc)
            return cls._instance

    @classmethod
    def available(cls) -> bool:
        ckpt, _, _ = cls._find_ckpt()
        return ckpt is not None

    def run(self, image_rgb: np.ndarray, attack: str = "clean") -> dict[str, Any]:
        img = Image.fromarray(image_rgb).convert("RGB").resize(
            (self.IMG_SIZE, self.IMG_SIZE), Image.BICUBIC)
        arr = np.array(img)
        # Input: [-1,1] to match training Normalize([0.5]*3,[0.5]*3); messages: {-0.1,0.1}
        t = _to_tensor_rgb(arr, self.device)
        msg_np = np.random.choice([-0.1, 0.1], self.MSG_LEN).astype(np.float32)
        msg_t = torch.from_numpy(msg_np).unsqueeze(0).to(self.device)
        with torch.no_grad():
            encoded_t = self.encoder(t, msg_t).clamp(-1, 1)
        original_u8 = arr
        encoded_u8 = _to_uint8_rgb(encoded_t[0])
        attacked_arr = _apply_attack_rgb(encoded_u8.copy(), attack)
        attacked_t = _to_tensor_rgb(attacked_arr, self.device)
        with torch.no_grad():
            decoded = self.decoder(attacked_t)
        bits_pred = decoded[0].cpu().gt(0).numpy()
        bits_gt = msg_np > 0
        ber = float(np.mean(bits_pred != bits_gt))
        from skimage.metrics import peak_signal_noise_ratio, structural_similarity
        psnr = float(peak_signal_noise_ratio(original_u8, encoded_u8, data_range=255))
        ssim = float(structural_similarity(original_u8, encoded_u8, channel_axis=2, data_range=255))
        return {
            "model": "KAD-Net",
            "checkpoint": "real",
            "attack": attack,
            "id_ber": round(ber, 4),
            "bit_accuracy": round(1 - ber, 4),
            "landmark_aed": None,
            "psnr": round(psnr, 4),
            "ssim": round(ssim, 4),
            "success": bool((1 - ber) >= 0.9),
            "images": {
                "original": original_u8,
                "watermarked": encoded_u8,
                "attacked": attacked_arr,
                "heatmap": _heatmap(original_u8, encoded_u8),
                "diff": _heatmap(encoded_u8, attacked_arr),
            },
        }

def get_adapter(model: str) -> "SepMarkAdapter | WaveGuardAdapter | LIDMarkAdapter | KADNetAdapter | None":
    if model.lower() in ("sepmark", "mea/sepmark"):
        return SepMarkAdapter.get() if SepMarkAdapter.available() else None
    if model.lower() == "waveguard":
        return WaveGuardAdapter.get() if WaveGuardAdapter.available() else None
    if model.lower() == "lidmark":
        return LIDMarkAdapter.get() if LIDMarkAdapter.available() else None
    if model.lower() in ("kad-net", "kadnet", "kad_net"):
        return KADNetAdapter.get() if KADNetAdapter.available() else None
    return None
