from __future__ import annotations
import hashlib
import os

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import build_run_metadata  # noqa: E402
from system.evaluation.runtime import MODEL_SOURCE_ROOT, PROJECT_ROOT  # noqa: E402


BASE_SEED = 20260603


def _derived_seed(base_seed: int, image_id: str, attack_id: str) -> int:
    """与 system/evaluation/attacks.py:derived_seed 完全对齐：每图独立 seed。"""
    payload = f"{base_seed}:{image_id}:{attack_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2 ** 32)


ROOT = PROJECT_ROOT
LIDMARK_CODE = MODEL_SOURCE_ROOT / "LIDMark"
sys.path.insert(0, str(LIDMARK_CODE))

from model.lidmark import LIDMark  # noqa: E402
from utils import Config, make_loader, update_config_resolution  # noqa: E402


REPORT_DIR = ROOT / "runs/lidmark_lfw_eval_full"
ASSET_DIR = ROOT / "system/assets/lidmark_lfw_eval_full"
CHECKPOINT = Path(os.environ.get('JYS_LIDMARK_CHECKPOINT',
    str(ROOT / 'weights/lidmark/smoke_128/checkpoints_distortions/checkpoint_epoch_2.pth')))
if 'JYS_LIDMARK_REPORT_DIR' in os.environ:
    REPORT_DIR = Path(os.environ['JYS_LIDMARK_REPORT_DIR'])
    ASSET_DIR  = REPORT_DIR / 'assets' 


def tensor_to_uint8(tensor: torch.Tensor) -> np.ndarray:
    arr = tensor.detach().cpu().clamp(-1, 1)
    arr = ((arr + 1) / 2)[0].permute(1, 2, 0).numpy()
    return np.clip(arr * 255, 0, 255).astype(np.uint8)


def uint8_to_tensor(arr: np.ndarray, device: torch.device) -> torch.Tensor:
    import torchvision.transforms.functional as TF
    return (TF.to_tensor(arr).to(device) * 2 - 1).unsqueeze(0)


def apply_attack(encoded: torch.Tensor, attack: str, device: torch.device,
                 image_id: str = "") -> torch.Tensor:
    if attack == "clean":
        return encoded
    arr = tensor_to_uint8(encoded)
    if attack == "jpeg":
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        arr = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    elif attack == "resize":
        h, w = arr.shape[:2]
        arr = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
    elif attack == "noise":
        # P2-7：每图独立 seed，由 (BASE_SEED, image_id, "noise") 派生，与 attacks.py:derived_seed 对齐
        seed = _derived_seed(BASE_SEED, image_id, "noise")
        rng = np.random.default_rng(seed)
        arr = np.clip(arr.astype(np.float32) + rng.normal(0, 3.0, arr.shape), 0, 255).astype(np.uint8)
    else:
        raise ValueError(attack)
    return uint8_to_tensor(arr, device)


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fields = ["index", "attack_type", "landmark_aed", "id_ber", "psnr", "ssim", "success", "error"]
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def summarize(csv_path: Path, attacks: list[str], total: int) -> dict:
    rows = []
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if not r.get("error")]
    _ckpt_str = str(CHECKPOINT)
    _mode = "smoke_checkpoint" if "smoke" in _ckpt_str.lower() else "trained_checkpoint"
    out = {
        "method": "LIDMark",
        "mode": _mode,
        "checkpoint": _ckpt_str,
        "data_type": "lfw_eval_split",
        "requested_images": total,
        "attacks": {},
    }
    if _mode == "smoke_checkpoint":
        out["warning"] = "Smoke checkpoint - not official full LIDMark model."
    for attack in attacks:
        subset = [r for r in rows if r["attack_type"] == attack]
        if not subset:
            out["attacks"][attack] = {"status": "pending", "count": 0}
            continue
        out["attacks"][attack] = {
            "status": "complete",
            "count": len(subset),
            "mean_landmark_aed": round(float(np.nanmean([float(r["landmark_aed"]) if r["landmark_aed"] and r["landmark_aed"].lower() not in ("inf","-inf","nan") else float("nan") for r in subset])), 6),
            "inf_landmark_count": sum(1 for r in subset if r.get("landmark_aed","").lower() in ("inf","-inf")),
            "mean_id_ber": round(float(np.mean([float(r["id_ber"]) for r in subset])), 6),
            "mean_psnr": round(float(np.mean([float(r["psnr"]) for r in subset])), 6),
            "mean_ssim": round(float(np.mean([float(r["ssim"]) for r in subset])), 6),
            "success_rate": round(float(np.mean([r["success"] == "1" for r in subset])), 6),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_images", type=int, default=512)
    parser.add_argument("--attacks", nargs="+", default=["clean", "jpeg", "resize", "noise"])
    parser.add_argument("--res", type=int, default=128)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    device = torch.device(args.device if torch.cuda.is_available() and args.device != "cpu" else "cpu")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_DIR / "results.csv"
    progress_path = REPORT_DIR / "progress.json"

    cfg = Config()
    cfg.load_config_file(str(LIDMARK_CODE / "configurations/train_distortions.yaml"))
    update_config_resolution(cfg, args.res)
    cfg.img_path = str(ROOT / "datasets/lidmark_lfw_eval/image" / f"lfw_{args.res}")
    cfg.wm_path = str(ROOT / "datasets/lidmark_lfw_eval/watermark_152/lfw")
    cfg.batch_size = 1
    cfg.seed = 42
    cfg.manipulation_layers = ["Identity()"]

    model = LIDMark(cfg.img_size, cfg.encoder_channels, cfg.encoder_blocks, cfg.decoder_channels, cfg.decoder_blocks, cfg.watermark_length, device, ["Identity()"]).to(device)
    checkpoint = torch.load(CHECKPOINT, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"], strict=False)
    model.eval()
    loader = make_loader(cfg, model_mode="test", shuffle=False)
    attacks = args.attacks
    rows: list[dict] = []
    processed = 0
    with torch.no_grad():
        for idx, (img, wm) in enumerate(loader):
            if idx >= args.num_images:
                break
            img = img.to(device)
            wm = wm.to(device)
            encoded = model.encoder(img, wm)
            gt_landmark = wm[:, :136]
            gt_id = wm[:, 136:] > 0
            for attack in attacks:
                try:
                    attacked = apply_attack(encoded, attack, device, image_id=str(idx))
                    pred_landmark, pred_id_logits = model.decoder(attacked)
                    _lm_raw = torch.sqrt(torch.sum((pred_landmark.view(-1, 68, 2) - gt_landmark.view(-1, 68, 2)) ** 2, dim=2))
                    _lm_raw = _lm_raw[torch.isfinite(_lm_raw)]
                    landmark_aed = float(_lm_raw.mean().item()) if _lm_raw.numel() > 0 else float("inf")
                    pred_id = pred_id_logits > 0
                    id_ber = float(torch.mean((pred_id != gt_id).float()).item())
                    ref = tensor_to_uint8(img)
                    cand = tensor_to_uint8(attacked)
                    psnr = float(peak_signal_noise_ratio(ref, cand, data_range=255))
                    ssim = float(structural_similarity(ref, cand, channel_axis=2, data_range=255))
                    rows.append({
                        "index": idx,
                        "attack_type": attack,
                        "landmark_aed": f"{landmark_aed:.6f}",
                        "id_ber": f"{id_ber:.6f}",
                        "psnr": f"{psnr:.6f}",
                        "ssim": f"{ssim:.6f}",
                        "success": "1" if id_ber <= 0.1 else "0",
                        "error": "",
                    })
                except Exception as exc:
                    rows.append({"index": idx, "attack_type": attack, "landmark_aed": "", "id_ber": "", "psnr": "", "ssim": "", "success": "0", "error": repr(exc)})
            processed += 1
            if rows and processed % 100 == 0:
                append_rows(csv_path, rows)
                rows = []
                (REPORT_DIR / "summary.json").write_text(json.dumps(summarize(csv_path, attacks, min(args.num_images, len(loader))), indent=2), encoding="utf-8")
                progress_path.write_text(json.dumps({"processed_images": processed, "updated_at": int(time.time())}, indent=2), encoding="utf-8")
    if rows:
        append_rows(csv_path, rows)
    summary = summarize(csv_path, attacks, min(args.num_images, len(loader)))
    summary["run_metadata"] = build_run_metadata(
        model="LIDMark",
        checkpoint=CHECKPOINT,
        seed=cfg.seed,
        command=sys.argv,
    )
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    progress_path.write_text(json.dumps({"processed_images": processed, "updated_at": int(time.time()), "status": "complete"}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
