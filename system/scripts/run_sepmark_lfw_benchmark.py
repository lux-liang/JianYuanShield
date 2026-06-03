from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity
from torchvision import transforms


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
SEPMARK_CODE = ROOT / "MEA/codes/SepMark"
DEFAULT_EC = ROOT / "weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth"
DEFAULT_IMAGE_ROOT = ROOT / "datasets/lfw_full_upload/unknown"
REPORT_DIR = ROOT / "system/reports/sepmark_lfw_benchmark"
ASSET_DIR = ROOT / "system/assets/sepmark_lfw_benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SepMark real-checkpoint benchmark on LFW images.")
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_EC)
    parser.add_argument("--num-images", type=int, default=100)
    parser.add_argument("--attacks", nargs="+", default=["clean", "jpeg", "resize", "noise"])
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--message-length", type=int, default=128)
    parser.add_argument("--message-range", type=float, default=0.1)
    parser.add_argument("--artifact-limit", type=int, default=48)
    parser.add_argument("--seed", type=int, default=2026)
    return parser.parse_args()


def list_images(root: Path, limit: int) -> list[Path]:
    images = sorted([p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}])
    return images[:limit] if limit > 0 else images


def to_uint8(tensor: torch.Tensor) -> np.ndarray:
    array = ((tensor.detach().cpu().clamp(-1, 1).permute(1, 2, 0).numpy() + 1.0) * 127.5)
    return np.clip(array + 0.5, 0, 255).astype(np.uint8)


def to_tensor(array: np.ndarray, device: torch.device) -> torch.Tensor:
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ])
    return transform(Image.fromarray(array.astype(np.uint8))).unsqueeze(0).to(device)


def load_image(path: Path, size: int, device: torch.device) -> torch.Tensor:
    image = Image.open(path).convert("RGB").resize((size, size), Image.BICUBIC)
    return to_tensor(np.array(image), device)


def attack_image(encoded: torch.Tensor, attack: str, device: torch.device) -> torch.Tensor:
    if attack == "clean":
        return encoded
    arr = to_uint8(encoded[0])
    if attack.startswith("jpeg"):
        quality = int(attack.replace("jpeg", "") or 70)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError(f"jpeg encode failed for {attack}")
        arr = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    elif attack == "resize":
        h, w = arr.shape[:2]
        small = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        arr = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    elif attack == "noise":
        rng = np.random.default_rng(2026)
        arr = np.clip(arr.astype(np.float32) + rng.normal(0, 3.0, arr.shape), 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"unknown attack: {attack}")
    return to_tensor(arr, device)


def bit_error(message: torch.Tensor, decoded: torch.Tensor) -> float:
    gt = message.detach().cpu().gt(0)
    pred = decoded.detach().cpu().gt(0)
    return float((gt != pred).float().mean().item())


def psnr_ssim(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    return (
        float(peak_signal_noise_ratio(reference, candidate, data_range=255)),
        float(structural_similarity(reference, candidate, channel_axis=2, data_range=255)),
    )


def heatmap(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    diff = np.mean(np.abs(reference.astype(np.float32) - candidate.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.applyColorMap(diff, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)


def write_progress(total: int, processed: int, attacks: list[str], status: str = "running") -> None:
    payload = {
        "processed_images": processed,
        "total_images": total,
        "attacks": attacks,
        "updated_at": int(time.time()),
        "status": status,
    }
    (REPORT_DIR / "progress.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def summarize(results_path: Path, args: argparse.Namespace, status: str) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    if results_path.exists():
        with results_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    attacks: dict[str, Any] = {}
    for attack in sorted({row["attack_type"] for row in rows}):
        subset = [row for row in rows if row["attack_type"] == attack]
        def mean(key: str) -> float:
            vals = [float(row[key]) for row in subset if row.get(key) not in ("", None)]
            return round(sum(vals) / len(vals), 6) if vals else math.nan

        attacks[attack] = {
            "status": status if len(subset) == args.num_images else "partial",
            "count": len(subset),
            "mean_bit_error": mean("bit_error_c"),
            "mean_bit_accuracy": mean("bit_accuracy_c"),
            "mean_bit_error_rf": mean("bit_error_rf"),
            "mean_bit_accuracy_rf": mean("bit_accuracy_rf"),
            "mean_psnr": mean("psnr"),
            "mean_ssim": mean("ssim"),
            "success_rate": mean("success"),
        }
    summary = {
        "method": "SepMark",
        "mode": "real_checkpoint",
        "checkpoint": str(args.checkpoint),
        "data_type": "real_lfw_images",
        "requested_images": args.num_images,
        "evaluated_rows": len(rows),
        "message_length": args.message_length,
        "image_size": args.image_size,
        "attacks": attacks,
        "success_definition": "decoder_C bit_accuracy >= 0.9",
    }
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def make_grid(samples: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]) -> None:
    if not samples:
        return
    tile = 160
    rows = min(6, len(samples))
    cols = 4
    canvas = Image.new("RGB", (cols * tile, rows * tile), "white")
    labels = ["original", "encoded", "attacked", "diff"]
    draw = ImageDraw.Draw(canvas)
    for r, sample in enumerate(samples[:rows]):
        for c, arr in enumerate(sample):
            img = Image.fromarray(arr).resize((tile, tile), Image.BICUBIC)
            canvas.paste(img, (c * tile, r * tile))
            draw.text((c * tile + 6, r * tile + 6), labels[c], fill=(255, 255, 255))
    canvas.save(ASSET_DIR / "grid.png")


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    attacks: list[str] = []
    for attack in args.attacks:
        if attack == "jpeg":
            attacks.extend(["jpeg50", "jpeg70", "jpeg90"])
        else:
            attacks.append(attack)

    sys.path.insert(0, str(SEPMARK_CODE))
    from network.Encoder_U import DW_Encoder
    from network.Decoder_U import DW_Decoder

    device = torch.device(args.device if torch.cuda.is_available() and args.device.startswith("cuda") else "cpu")
    encoder = DW_Encoder(args.message_length, attention="se").to(device)
    decoder_c = DW_Decoder(args.message_length, attention="se").to(device)
    decoder_rf = DW_Decoder(args.message_length, attention="se").to(device)
    state = torch.load(args.checkpoint, map_location=device)
    def strip_prefix(prefix: str) -> dict[str, torch.Tensor]:
        return {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}

    load_info = {
        "encoder": encoder.load_state_dict(strip_prefix("encoder."), strict=False),
        "decoder_C": decoder_c.load_state_dict(strip_prefix("decoder_C."), strict=False),
        "decoder_RF": decoder_rf.load_state_dict(strip_prefix("decoder_RF."), strict=False),
    }
    load_warnings = {
        name: {
            "missing": list(info.missing_keys),
            "unexpected": list(info.unexpected_keys),
        }
        for name, info in load_info.items()
        if info.missing_keys or info.unexpected_keys
    }
    if load_warnings:
        (REPORT_DIR / "load_warnings.json").write_text(json.dumps({
            "warnings": load_warnings,
        }, indent=2), encoding="utf-8")
    encoder.eval()
    decoder_c.eval()
    decoder_rf.eval()

    images = list_images(args.image_root, args.num_images)
    if not images:
        raise RuntimeError(f"no images found under {args.image_root}")
    args.num_images = len(images)
    results_path = REPORT_DIR / "results.csv"
    bad_path = REPORT_DIR / "bad_cases.csv"
    existing: set[tuple[str, str]] = set()
    if results_path.exists():
        with results_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                existing.add((row["image_id"], row["attack_type"]))
    fieldnames = [
        "image_id", "source_path", "attack_type", "bit_error_c", "bit_accuracy_c",
        "bit_error_rf", "bit_accuracy_rf", "psnr", "ssim", "success", "error",
    ]
    if not results_path.exists():
        with results_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fieldnames).writeheader()
    if not bad_path.exists():
        with bad_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writeheader()

    samples: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    processed_images = 0
    for idx, path in enumerate(images):
        image_id = path.stem
        try:
            image = load_image(path, args.image_size, device)
            message_values = np.random.choice([-args.message_range, args.message_range], (1, args.message_length))
            message = torch.tensor(message_values, dtype=torch.float32, device=device)
            with torch.no_grad():
                encoded = encoder(image, message).clamp(-1, 1)
            original_u8 = to_uint8(image[0])
            encoded_u8 = to_uint8(encoded[0])
            for attack in attacks:
                if (image_id, attack) in existing:
                    continue
                try:
                    attacked = attack_image(encoded, attack, device)
                    with torch.no_grad():
                        decoded_c = decoder_c(attacked)
                        decoded_rf = decoder_rf(attacked)
                    ber_c = bit_error(message, decoded_c)
                    ber_rf = bit_error(message, decoded_rf)
                    attacked_u8 = to_uint8(attacked[0])
                    psnr, ssim = psnr_ssim(original_u8, encoded_u8)
                    row = {
                        "image_id": image_id,
                        "source_path": str(path),
                        "attack_type": attack,
                        "bit_error_c": f"{ber_c:.6f}",
                        "bit_accuracy_c": f"{1.0 - ber_c:.6f}",
                        "bit_error_rf": f"{ber_rf:.6f}",
                        "bit_accuracy_rf": f"{1.0 - ber_rf:.6f}",
                        "psnr": f"{psnr:.6f}",
                        "ssim": f"{ssim:.6f}",
                        "success": int((1.0 - ber_c) >= 0.9),
                        "error": "",
                    }
                    with results_path.open("a", encoding="utf-8", newline="") as handle:
                        csv.DictWriter(handle, fieldnames=fieldnames).writerow(row)
                    if len(samples) < args.artifact_limit and attack in {"clean", "jpeg70", "resize", "noise"}:
                        samples.append((original_u8, encoded_u8, attacked_u8, heatmap(encoded_u8, attacked_u8)))
                except Exception as exc:
                    with bad_path.open("a", encoding="utf-8", newline="") as handle:
                        csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writerow({
                            "image_id": image_id,
                            "source_path": str(path),
                            "attack_type": attack,
                            "error": repr(exc),
                        })
        except Exception as exc:
            with bad_path.open("a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=["image_id", "source_path", "attack_type", "error"]).writerow({
                    "image_id": image_id,
                    "source_path": str(path),
                    "attack_type": "all",
                    "error": repr(exc),
                })
        processed_images = idx + 1
        if processed_images % 100 == 0:
            write_progress(args.num_images, processed_images, attacks)
            summarize(results_path, args, "partial")

    write_progress(args.num_images, processed_images, attacks, status="complete")
    summary = summarize(results_path, args, "complete")
    make_grid(samples)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
