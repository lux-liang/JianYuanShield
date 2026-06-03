from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
HIDDEN_CODE = ROOT / "MEA/codes/HiDDeN"
sys.path.insert(0, str(HIDDEN_CODE))

import utils  # noqa: E402
from model.hidden import Hidden  # noqa: E402
from noise_layers.noiser import Noiser  # noqa: E402


DEFAULT_OPTIONS = ROOT / "weights/mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/options-and-config.pickle"
DEFAULT_CHECKPOINT = ROOT / "weights/mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/checkpoints/train-test-1--epoch-200.pyt"
DEFAULT_IMAGE_ROOT = ROOT / "datasets/lfw_full_upload/unknown"
REPORT_DIR = ROOT / "system/reports/hidden_lfw_full_benchmark"
ASSET_DIR = ROOT / "system/assets/real_hidden_benchmark"


def expand_attacks(attacks: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for attack in attacks:
        if attack == "jpeg":
            expanded.extend(["jpeg50", "jpeg70", "jpeg90"])
        else:
            expanded.append(attack)
    return expanded


def read_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    done = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["image_id"], row["attack_type"]))
    return done


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fields = [
        "image_id", "source_path", "attack_type", "bit_error", "bit_accuracy",
        "psnr", "ssim", "success", "artifact_original", "artifact_encoded",
        "artifact_attacked", "artifact_heatmap", "error"
    ]
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def append_bad(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["image_id", "source_path", "attack_type", "error"])
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def write_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_image(path: Path, height: int, width: int, device: torch.device) -> torch.Tensor:
    image = Image.open(path).convert("RGB")
    arr = np.array(image)
    if arr.shape[0] < height or arr.shape[1] < width:
        image = image.resize((max(width, image.width), max(height, image.height)))
        arr = np.array(image)
    y = max((arr.shape[0] - height) // 2, 0)
    x = max((arr.shape[1] - width) // 2, 0)
    arr = arr[y:y + height, x:x + width]
    tensor = TF.to_tensor(arr).to(device)
    return (tensor * 2 - 1).unsqueeze(0)


def tensor_to_uint8(tensor: torch.Tensor) -> np.ndarray:
    arr = tensor.detach().cpu().clamp(-1, 1)
    arr = ((arr + 1) / 2)[0].permute(1, 2, 0).numpy()
    return np.clip(arr * 255, 0, 255).astype(np.uint8)


def uint8_to_tensor(arr: np.ndarray, device: torch.device) -> torch.Tensor:
    tensor = TF.to_tensor(arr).to(device)
    return (tensor * 2 - 1).unsqueeze(0)


def apply_attack(encoded: torch.Tensor, attack: str, device: torch.device) -> torch.Tensor:
    if attack == "clean":
        return encoded
    arr = tensor_to_uint8(encoded)
    if attack.startswith("jpeg"):
        quality = int(attack.replace("jpeg", ""))
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("cv2.imencode failed")
        arr = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    elif attack == "resize":
        h, w = arr.shape[:2]
        arr = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
    elif attack == "noise":
        rng = np.random.default_rng(20260603)
        noise = rng.normal(0, 3.0, size=arr.shape)
        arr = np.clip(arr.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"unknown attack: {attack}")
    return uint8_to_tensor(arr, device)


def save_artifacts(image_id: str, attack: str, original: torch.Tensor, encoded: torch.Tensor, attacked: torch.Tensor) -> dict[str, str]:
    out = ASSET_DIR / image_id / attack
    out.mkdir(parents=True, exist_ok=True)
    original_arr = tensor_to_uint8(original)
    encoded_arr = tensor_to_uint8(encoded)
    attacked_arr = tensor_to_uint8(attacked)
    diff = np.mean(np.abs(encoded_arr.astype(np.float32) - attacked_arr.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    heat = cv2.cvtColor(cv2.applyColorMap(diff, cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
    paths = {
        "original": out / "original.png",
        "encoded": out / "encoded.png",
        "attacked": out / "attacked.png",
        "heatmap": out / "heatmap.png",
    }
    Image.fromarray(original_arr).save(paths["original"])
    Image.fromarray(encoded_arr).save(paths["encoded"])
    Image.fromarray(attacked_arr).save(paths["attacked"])
    Image.fromarray(heat).save(paths["heatmap"])
    return {k: f"/artifacts/real_hidden_benchmark/{image_id}/{attack}/{v.name}" for k, v in paths.items()}


def metric_pair(reference: torch.Tensor, candidate: torch.Tensor) -> tuple[float, float]:
    ref = tensor_to_uint8(reference)
    cand = tensor_to_uint8(candidate)
    psnr = peak_signal_noise_ratio(ref, cand, data_range=255)
    ssim = structural_similarity(ref, cand, channel_axis=2, data_range=255)
    return float(psnr), float(ssim)


def summarize(csv_path: Path, attacks: list[str], checkpoint: Path, num_images: int) -> dict:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f) if not row.get("error")]
    summary = {
        "project": "鉴源盾",
        "method": "MEA/HiDDeN",
        "mode": "real_checkpoint",
        "checkpoint": str(checkpoint),
        "data_type": "real_lfw_images",
        "requested_images": num_images,
        "evaluated_rows": len(rows),
        "attacks": {},
        "success_definition": "bit_accuracy >= 0.9",
    }
    for attack in attacks:
        subset = [r for r in rows if r["attack_type"] == attack]
        if not subset:
            summary["attacks"][attack] = {"status": "pending", "count": 0}
            continue
        vals = {k: np.array([float(r[k]) for r in subset], dtype=np.float64) for k in ["bit_error", "bit_accuracy", "psnr", "ssim"]}
        successes = np.array([r["success"] == "1" for r in subset], dtype=np.float64)
        summary["attacks"][attack] = {
            "status": "complete",
            "count": len(subset),
            "mean_bit_error": round(float(vals["bit_error"].mean()), 6),
            "mean_bit_accuracy": round(float(vals["bit_accuracy"].mean()), 6),
            "mean_psnr": round(float(vals["psnr"].mean()), 6),
            "mean_ssim": round(float(vals["ssim"].mean()), 6),
            "success_rate": round(float(successes.mean()), 6),
        }
    return summary


def make_grid(rows_csv: Path, output: Path, max_items: int = 8) -> None:
    entries = []
    with rows_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["attack_type"] == "clean" and row["artifact_encoded"]:
                entries.append(row)
            if len(entries) >= max_items:
                break
    if not entries:
        return
    tiles = []
    for row in entries:
        enc_path = ROOT / "system/assets" / row["artifact_encoded"].replace("/artifacts/", "")
        heat_path = ROOT / "system/assets" / row["artifact_heatmap"].replace("/artifacts/", "")
        if enc_path.exists() and heat_path.exists():
            tiles.extend([Image.open(enc_path).convert("RGB"), Image.open(heat_path).convert("RGB")])
    if not tiles:
        return
    w, h = tiles[0].size
    grid = Image.new("RGB", (w * 4, h * math.ceil(len(tiles) / 4)), "white")
    for i, tile in enumerate(tiles):
        grid.paste(tile, ((i % 4) * w, (i // 4) * h))
    output.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_images", type=int, default=100)
    parser.add_argument("--attacks", nargs="+", default=["clean", "jpeg", "resize", "noise"])
    parser.add_argument("--image-root", default=str(DEFAULT_IMAGE_ROOT))
    parser.add_argument("--options-file", default=str(DEFAULT_OPTIONS))
    parser.add_argument("--checkpoint-file", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--artifact-limit", type=int, default=100)
    args = parser.parse_args()

    device = torch.device(args.device if torch.cuda.is_available() and args.device != "cpu" else "cpu")
    attacks = expand_attacks(args.attacks)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_DIR / "results.csv"
    bad_path = REPORT_DIR / "bad_cases.csv"
    progress_path = REPORT_DIR / "progress.json"

    train_options, hidden_config, noise_config = utils.load_options(args.options_file)
    noiser = Noiser(noise_config, device)
    checkpoint = torch.load(args.checkpoint_file, map_location=device)
    hidden_net = Hidden(hidden_config, device, noiser, None)
    utils.model_from_checkpoint(hidden_net, checkpoint)
    hidden_net.encoder_decoder.eval()
    hidden_net.discriminator.eval()

    images = sorted(Path(args.image_root).glob("*.jpg"))[: args.num_images]
    done = read_done(csv_path)
    rng = np.random.default_rng(20260603)

    config_summary = {
        "image_size": [hidden_config.H, hidden_config.W],
        "message_length": hidden_config.message_length,
        "checkpoint_path": str(args.checkpoint_file),
        "options_file": str(args.options_file),
        "encoder_blocks": hidden_config.encoder_blocks,
        "encoder_channels": hidden_config.encoder_channels,
        "decoder_blocks": hidden_config.decoder_blocks,
        "decoder_channels": hidden_config.decoder_channels,
        "device": str(device),
    }
    (ROOT / "system/reports/real_hidden/hidden_config_summary.json").write_text(
        json.dumps(config_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    pending_rows: list[dict] = []
    processed = 0
    for idx, path in enumerate(images):
        image_id = path.stem
        for attack in attacks:
            if (image_id, attack) in done:
                continue
            try:
                image_tensor = load_image(path, hidden_config.H, hidden_config.W, device)
                message_np = rng.integers(0, 2, size=(1, hidden_config.message_length)).astype("float32")
                message = torch.from_numpy(message_np).to(device)
                with torch.no_grad():
                    encoded = hidden_net.encoder_decoder.encoder(image_tensor, message)
                    attacked = apply_attack(encoded, attack, device)
                    decoded = hidden_net.encoder_decoder.decoder(attacked)
                decoded_np = decoded.detach().cpu().numpy().round().clip(0, 1)
                bit_error = float(np.mean(np.abs(decoded_np - message_np)))
                bit_accuracy = 1.0 - bit_error
                psnr, ssim = metric_pair(image_tensor, attacked)
                artifacts = {"original": "", "encoded": "", "attacked": "", "heatmap": ""}
                if idx < args.artifact_limit and attack in {"clean", "jpeg50", "resize", "noise"}:
                    artifacts = save_artifacts(image_id, attack, image_tensor, encoded, attacked)
                pending_rows.append({
                    "image_id": image_id,
                    "source_path": str(path),
                    "attack_type": attack,
                    "bit_error": f"{bit_error:.6f}",
                    "bit_accuracy": f"{bit_accuracy:.6f}",
                    "psnr": f"{psnr:.6f}",
                    "ssim": f"{ssim:.6f}",
                    "success": "1" if bit_accuracy >= 0.9 else "0",
                    "artifact_original": artifacts["original"],
                    "artifact_encoded": artifacts["encoded"],
                    "artifact_attacked": artifacts["attacked"],
                    "artifact_heatmap": artifacts["heatmap"],
                    "error": "",
                })
            except Exception as exc:
                append_bad(bad_path, {"image_id": image_id, "source_path": str(path), "attack_type": attack, "error": repr(exc)})
        processed += 1
        if pending_rows and (processed % 100 == 0):
            append_rows(csv_path, pending_rows)
            pending_rows = []
            summary = summarize(csv_path, attacks, Path(args.checkpoint_file), len(images))
            (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            write_progress(progress_path, {"processed_images": processed, "total_images": len(images), "attacks": attacks, "updated_at": int(time.time())})
    if pending_rows:
        append_rows(csv_path, pending_rows)
    summary = summarize(csv_path, attacks, Path(args.checkpoint_file), len(images))
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    make_grid(csv_path, ASSET_DIR / "grid.png")
    write_progress(progress_path, {"processed_images": len(images), "total_images": len(images), "attacks": attacks, "updated_at": int(time.time()), "status": "complete"})
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

