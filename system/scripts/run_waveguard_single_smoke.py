from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
CODE = ROOT / "MEA/codes/WaveGuard"
CKPT = ROOT / "weights/mea/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
IMAGE = ROOT / "datasets/lfw_full_upload/unknown/lfw_00000.jpg"
REPORT = ROOT / "system/reports/waveguard_lfw_benchmark/single_smoke.json"
ASSET = ROOT / "system/assets/waveguard_single_smoke"


def yuv_tensor_from_image(path: Path, device: torch.device, size: int = 256) -> torch.Tensor:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"failed to read image: {path}")
    bgr = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV).astype(np.float32)
    tensor = torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(device)
    return tensor


def tensor_yuv_to_rgb_uint8(tensor: torch.Tensor) -> np.ndarray:
    yuv = ((tensor.detach().cpu()[0].permute(1, 2, 0).numpy() + 1.0) * 127.5)
    yuv = np.clip(yuv, 0, 255).astype(np.uint8)
    rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB)
    return rgb


def rgb_uint8_to_yuv_tensor(rgb: np.ndarray, device: torch.device) -> torch.Tensor:
    yuv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32)
    return torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(device)


def apply_attack(watermarked_yuv: torch.Tensor, attack: str, device: torch.device) -> torch.Tensor:
    if attack == "clean":
        return watermarked_yuv
    rgb = tensor_yuv_to_rgb_uint8(watermarked_yuv)
    if attack == "jpeg70":
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        rgb = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    elif attack == "resize":
        small = cv2.resize(rgb, (128, 128), interpolation=cv2.INTER_AREA)
        rgb = cv2.resize(small, (256, 256), interpolation=cv2.INTER_LINEAR)
    elif attack == "noise":
        rng = np.random.default_rng(2026)
        rgb = np.clip(rgb.astype(np.float32) + rng.normal(0, 3.0, rgb.shape), 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"unknown attack: {attack}")
    return rgb_uint8_to_yuv_tensor(rgb, device)


def bit_error(message: torch.Tensor, decoded: torch.Tensor) -> float:
    return float((message.detach().cpu().gt(0) != decoded.detach().cpu().gt(0)).float().mean().item())


def main() -> None:
    ASSET.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(CODE))
    old_cwd = Path.cwd()
    try:
        import os
        os.chdir(CODE)
        from config import training_config as cfg
        from network.encoder import Encoder
        from network.decoder import Decoder
        from utils import DTCWT_highpass
    finally:
        os.chdir(old_cwd)

    device = torch.device(cfg.device if torch.cuda.is_available() else "cpu")
    indices_encoder = torch.tensor([0, 2]).to(device)
    indices_decoder_t = torch.tensor([0, 2, 3, 5]).to(device)
    indices_decoder_d = torch.tensor([0, 2]).to(device)

    encoder = Encoder().to(device).eval()
    decoder_t = Decoder(type="tracer").to(device).eval()
    decoder_d = Decoder(type="detector").to(device).eval()
    state = torch.load(CKPT, map_location=device)
    load_summary = {}
    for prefix, model in [("encoder.", encoder), ("decoder_t.", decoder_t), ("decoder_d.", decoder_d)]:
        sub = {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}
        info = model.load_state_dict(sub, strict=False)
        load_summary[prefix.rstrip(".")] = {
            "subkeys": len(sub),
            "missing": list(info.missing_keys),
            "unexpected": list(info.unexpected_keys),
        }

    image = yuv_tensor_from_image(IMAGE, device, cfg.image_size)
    message = torch.tensor(np.random.choice([-cfg.message_range, cfg.message_range], (1, cfg.message_length)), dtype=torch.float32, device=device)
    with torch.no_grad():
        y, u, v = image[:, [0]], image[:, [1]], image[:, [2]]
        low_pass, high_pass = DTCWT_highpass.images_U_dtcwt_with_low(u)
        selected = torch.index_select(high_pass[1], 2, indices_encoder)
        selected = selected[:, :, :, :, :, 0].squeeze(1)
        embedded_selected = encoder(selected, message).unsqueeze(1)
        high_pass[1][:, :, indices_encoder, :, :, 0] = embedded_selected
        u_embedded = DTCWT_highpass.dtcwt_images_U(low_pass, high_pass)
        watermarked = torch.cat([y, u_embedded, v], dim=1).clamp(-1, 1)

    original_rgb = tensor_yuv_to_rgb_uint8(image)
    watermarked_rgb = tensor_yuv_to_rgb_uint8(watermarked)
    Image.fromarray(original_rgb).save(ASSET / "original.png")
    Image.fromarray(watermarked_rgb).save(ASSET / "watermarked.png")

    rows = {}
    for attack in ["clean", "jpeg70", "resize", "noise"]:
        attacked = apply_attack(watermarked, attack, device)
        attacked_rgb = tensor_yuv_to_rgb_uint8(attacked)
        Image.fromarray(attacked_rgb).save(ASSET / f"{attack}.png")
        with torch.no_grad():
            attacked_u = attacked[:, [1]]
            high_pass_extract = DTCWT_highpass.images_U_dtcwt_without_low(attacked_u)
            selected_t = torch.index_select(high_pass_extract[1], 2, indices_decoder_t)
            selected_t = selected_t[:, :, :, :, :, 0].squeeze(1)
            selected_d = torch.index_select(high_pass_extract[1], 2, indices_decoder_d)
            selected_d = selected_d[:, :, :, :, :, 0].squeeze(1)
            decoded_t = decoder_t(selected_t)
            decoded_d = decoder_d(selected_d)
        ber_t = bit_error(message, decoded_t)
        ber_d = bit_error(message, decoded_d)
        rows[attack] = {
            "bit_error_tracer": round(ber_t, 6),
            "bit_accuracy_tracer": round(1.0 - ber_t, 6),
            "bit_error_detector": round(ber_d, 6),
            "bit_accuracy_detector": round(1.0 - ber_d, 6),
            "psnr": round(float(peak_signal_noise_ratio(original_rgb, watermarked_rgb, data_range=255)), 6),
            "ssim": round(float(structural_similarity(original_rgb, watermarked_rgb, channel_axis=2, data_range=255)), 6),
        }

    report = {
        "method": "WaveGuard",
        "mode": "real_checkpoint_single_image_smoke",
        "status": "single_smoke_ok",
        "checkpoint": str(CKPT),
        "image": str(IMAGE),
        "message_length": int(cfg.message_length),
        "image_size": int(cfg.image_size),
        "load_summary": load_summary,
        "attacks": rows,
        "artifacts": {
            "original": str(ASSET / "original.png"),
            "watermarked": str(ASSET / "watermarked.png"),
            "asset_dir": str(ASSET),
        },
        "warning": "Single-image smoke only; not a full LFW benchmark.",
        "updated_at": int(time.time()),
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path = ROOT / "system/reports/waveguard_lfw_benchmark/summary.json"
    existing = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    existing["single_image_smoke"] = report
    existing["status"] = "single_smoke_ok"
    summary_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
