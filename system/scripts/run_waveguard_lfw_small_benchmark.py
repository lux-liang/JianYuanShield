from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
CODE = ROOT / "MEA/codes/WaveGuard"
DEFAULT_CKPT = ROOT / "weights/mea/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
DEFAULT_IMAGES = ROOT / "datasets/lfw_full_upload/unknown"
REPORT_DIR = ROOT / "system/reports/waveguard_lfw_small_benchmark"
ASSET_DIR = ROOT / "system/assets/waveguard_lfw_small_benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WaveGuard real-checkpoint small LFW benchmark.")
    parser.add_argument("--num-images", type=int, default=100)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CKPT)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--attacks", nargs="+", default=["clean", "jpeg", "resize", "noise"])
    parser.add_argument("--artifact-limit", type=int, default=24)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    return parser.parse_args()


def list_images(root: Path, limit: int) -> list[Path]:
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return images[:limit]


def expand_attacks(attacks: list[str]) -> list[str]:
    out: list[str] = []
    for attack in attacks:
        if attack == "jpeg":
            out.extend(["jpeg50", "jpeg70", "jpeg90"])
        else:
            out.append(attack)
    return out


def yuv_tensor_from_image(path: Path, device: torch.device, size: int) -> torch.Tensor:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"failed to read image: {path}")
    bgr = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV).astype(np.float32)
    return torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(device)


def tensor_yuv_to_rgb_uint8(tensor: torch.Tensor) -> np.ndarray:
    yuv = ((tensor.detach().cpu()[0].permute(1, 2, 0).numpy() + 1.0) * 127.5)
    yuv = np.clip(yuv, 0, 255).astype(np.uint8)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB)


def rgb_uint8_to_yuv_tensor(rgb: np.ndarray, device: torch.device) -> torch.Tensor:
    yuv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32)
    return torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(device)


def apply_attack(watermarked_yuv: torch.Tensor, attack: str, device: torch.device) -> torch.Tensor:
    if attack == "clean":
        return watermarked_yuv
    rgb = tensor_yuv_to_rgb_uint8(watermarked_yuv)
    if attack.startswith("jpeg"):
        quality = int(attack.replace("jpeg", "") or 70)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError(f"jpeg encode failed: {attack}")
        rgb = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    elif attack == "resize":
        small = cv2.resize(rgb, (rgb.shape[1] // 2, rgb.shape[0] // 2), interpolation=cv2.INTER_AREA)
        rgb = cv2.resize(small, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
    elif attack == "noise":
        rng = np.random.default_rng(2026)
        rgb = np.clip(rgb.astype(np.float32) + rng.normal(0, 3.0, rgb.shape), 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"unknown attack: {attack}")
    return rgb_uint8_to_yuv_tensor(rgb, device)


def bit_error(message: torch.Tensor, decoded: torch.Tensor) -> float:
    return float((message.detach().cpu().gt(0) != decoded.detach().cpu().gt(0)).float().mean().item())


def write_progress(total: int, processed: int, attacks: list[str], status: str = "running") -> None:
    (REPORT_DIR / "progress.json").write_text(json.dumps({
        "processed_images": processed,
        "total_images": total,
        "attacks": attacks,
        "updated_at": int(time.time()),
        "status": status,
    }, indent=2), encoding="utf-8")


def summarize(results_path: Path, status: str, args: argparse.Namespace) -> dict:
    rows = list(csv.DictReader(results_path.open("r", encoding="utf-8"))) if results_path.exists() else []
    attacks = {}
    for attack in sorted({row["attack_type"] for row in rows}):
        subset = [row for row in rows if row["attack_type"] == attack]
        def mean(key: str) -> float | None:
            vals = [float(row[key]) for row in subset if row.get(key) not in ("", None)]
            return round(sum(vals) / len(vals), 6) if vals else None
        attacks[attack] = {
            "status": status if len(subset) == args.num_images else "partial",
            "count": len(subset),
            "mean_bit_error_tracer": mean("bit_error_tracer"),
            "mean_bit_accuracy_tracer": mean("bit_accuracy_tracer"),
            "mean_bit_error_detector": mean("bit_error_detector"),
            "mean_bit_accuracy_detector": mean("bit_accuracy_detector"),
            "mean_bit_error": mean("bit_error_detector"),
            "mean_bit_accuracy": mean("bit_accuracy_detector"),
            "mean_psnr": mean("psnr"),
            "mean_ssim": mean("ssim"),
            "success_rate": mean("success"),
        }
    summary = {
        "method": "WaveGuard",
        "mode": "real_checkpoint_full_benchmark" if args.num_images >= 1000 else "real_checkpoint_small_benchmark",
        "status": status,
        "checkpoint": str(args.checkpoint),
        "data_type": "real_lfw_images",
        "requested_images": args.num_images,
        "evaluated_rows": len(rows),
        "attacks": attacks,
        "success_definition": "detector bit_accuracy >= 0.9",
        "warning": "" if args.num_images >= 1000 else "Small LFW benchmark, not full 13,233-image benchmark.",
    }
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def make_grid(samples: list[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> None:
    if not samples:
        return
    tile = 160
    canvas = Image.new("RGB", (3 * tile, min(6, len(samples)) * tile), "white")
    draw = ImageDraw.Draw(canvas)
    labels = ["original", "watermarked", "attacked"]
    for r, sample in enumerate(samples[:6]):
        for c, arr in enumerate(sample):
            canvas.paste(Image.fromarray(arr).resize((tile, tile), Image.BICUBIC), (c * tile, r * tile))
            draw.text((c * tile + 6, r * tile + 6), labels[c], fill=(255, 255, 255))
    canvas.save(ASSET_DIR / "grid.png")


def main() -> None:
    global REPORT_DIR, ASSET_DIR
    args = parse_args()
    REPORT_DIR = args.report_dir
    ASSET_DIR = args.asset_dir
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    attacks = expand_attacks(args.attacks)
    sys.path.insert(0, str(CODE))
    old_cwd = Path.cwd()
    os.chdir(CODE)
    try:
        from config import training_config as cfg
        from network.encoder import Encoder
        from network.decoder import Decoder
        from utils import DTCWT_highpass
    finally:
        os.chdir(old_cwd)

    device = torch.device(args.device if torch.cuda.is_available() and args.device.startswith("cuda") else "cpu")
    cfg.device = str(device)
    indices_encoder = torch.tensor([0, 2]).to(device)
    indices_decoder_t = torch.tensor([0, 2, 3, 5]).to(device)
    indices_decoder_d = torch.tensor([0, 2]).to(device)

    encoder = Encoder().to(device).eval()
    decoder_t = Decoder(type="tracer").to(device).eval()
    decoder_d = Decoder(type="detector").to(device).eval()
    state = torch.load(args.checkpoint, map_location=device)
    for prefix, model in [("encoder.", encoder), ("decoder_t.", decoder_t), ("decoder_d.", decoder_d)]:
        model.load_state_dict({k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}, strict=False)

    images = list_images(args.image_root, args.num_images)
    args.num_images = len(images)
    results_path = REPORT_DIR / "results.csv"
    bad_path = REPORT_DIR / "bad_cases.csv"
    fields = ["image_id", "source_path", "attack_type", "bit_error_tracer", "bit_accuracy_tracer", "bit_error_detector", "bit_accuracy_detector", "psnr", "ssim", "success", "error"]
    if not results_path.exists():
        with results_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()
    if not bad_path.exists():
        with bad_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writeheader()
    existing = set()
    with results_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            existing.add((row["image_id"], row["attack_type"]))

    samples: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for idx, path in enumerate(images, start=1):
        image_id = path.stem
        try:
            image = yuv_tensor_from_image(path, device, cfg.image_size)
            message = torch.tensor(np.random.choice([-cfg.message_range, cfg.message_range], (1, cfg.message_length)), dtype=torch.float32, device=device)
            with torch.no_grad():
                y, u, v = image[:, [0]], image[:, [1]], image[:, [2]]
                low_pass, high_pass = DTCWT_highpass.images_U_dtcwt_with_low(u)
                selected = torch.index_select(high_pass[1], 2, indices_encoder)
                selected = selected[:, :, :, :, :, 0].squeeze(1)
                high_pass[1][:, :, indices_encoder, :, :, 0] = encoder(selected, message).unsqueeze(1)
                u_embedded = DTCWT_highpass.dtcwt_images_U(low_pass, high_pass)
                watermarked = torch.cat([y, u_embedded, v], dim=1).clamp(-1, 1)
            original_rgb = tensor_yuv_to_rgb_uint8(image)
            watermarked_rgb = tensor_yuv_to_rgb_uint8(watermarked)
            psnr = float(peak_signal_noise_ratio(original_rgb, watermarked_rgb, data_range=255))
            ssim = float(structural_similarity(original_rgb, watermarked_rgb, channel_axis=2, data_range=255))
            for attack in attacks:
                if (image_id, attack) in existing:
                    continue
                try:
                    attacked = apply_attack(watermarked, attack, device)
                    attacked_rgb = tensor_yuv_to_rgb_uint8(attacked)
                    with torch.no_grad():
                        high_pass_extract = DTCWT_highpass.images_U_dtcwt_without_low(attacked[:, [1]])
                        selected_t = torch.index_select(high_pass_extract[1], 2, indices_decoder_t)
                        selected_t = selected_t[:, :, :, :, :, 0].squeeze(1)
                        selected_d = torch.index_select(high_pass_extract[1], 2, indices_decoder_d)
                        selected_d = selected_d[:, :, :, :, :, 0].squeeze(1)
                        decoded_t = decoder_t(selected_t)
                        decoded_d = decoder_d(selected_d)
                    ber_t = bit_error(message, decoded_t)
                    ber_d = bit_error(message, decoded_d)
                    row = {
                        "image_id": image_id,
                        "source_path": str(path),
                        "attack_type": attack,
                        "bit_error_tracer": f"{ber_t:.6f}",
                        "bit_accuracy_tracer": f"{1.0 - ber_t:.6f}",
                        "bit_error_detector": f"{ber_d:.6f}",
                        "bit_accuracy_detector": f"{1.0 - ber_d:.6f}",
                        "psnr": f"{psnr:.6f}",
                        "ssim": f"{ssim:.6f}",
                        "success": int((1.0 - ber_d) >= 0.9),
                        "error": "",
                    }
                    with results_path.open("a", encoding="utf-8", newline="") as handle:
                        csv.DictWriter(handle, fieldnames=fields).writerow(row)
                    if len(samples) < args.artifact_limit and attack in {"clean", "jpeg70", "resize"}:
                        samples.append((original_rgb, watermarked_rgb, attacked_rgb))
                except Exception as exc:
                    with bad_path.open("a", encoding="utf-8", newline="") as handle:
                        csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writerow({"image_id": image_id, "source_path": str(path), "attack_type": attack, "error": repr(exc)})
        except Exception as exc:
            with bad_path.open("a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writerow({"image_id": image_id, "source_path": str(path), "attack_type": "all", "error": repr(exc)})
        if idx % 20 == 0:
            write_progress(args.num_images, idx, attacks)
            summarize(results_path, "partial", args)

    write_progress(args.num_images, args.num_images, attacks, "complete")
    summary = summarize(results_path, "complete", args)
    make_grid(samples)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
