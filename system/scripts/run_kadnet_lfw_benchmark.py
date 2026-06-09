from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import build_run_metadata  # noqa: E402
from system.evaluation.runtime import DATA_ROOT, PROJECT_ROOT  # noqa: E402

ROOT = PROJECT_ROOT
DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw_full_upload/unknown"
REPORT_DIR = ROOT / "system/reports/kadnet_lfw_benchmark"
ASSET_DIR = ROOT / "system/assets/kadnet_lfw_benchmark"
MSG_LEN = 30
IMG_SIZE = 128


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--num-images", type=int, default=13233)
    p.add_argument("--attacks", nargs="+", default=["clean", "jpeg50", "jpeg70", "jpeg90", "resize", "noise", "crop_center_0.8", "rotate_5"])
    p.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=20260609)
    p.add_argument("--artifact-limit", type=int, default=100)
    return p.parse_args()


def list_images(root: Path, limit: int) -> list[Path]:
    imgs = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return imgs[:limit] if limit > 0 else imgs


def apply_attack(arr: np.ndarray, attack: str, rng: np.random.Generator) -> np.ndarray:
    if attack == "clean":
        return arr
    if attack.startswith("jpeg"):
        q = int(attack[4:] or "70")
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
        if not ok:
            raise RuntimeError(f"jpeg encode failed q={q}")
        return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if attack == "resize":
        h, w = arr.shape[:2]
        small = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if attack == "noise":
        return np.clip(arr.astype(np.float32) + rng.normal(0, 3.0, arr.shape), 0, 255).astype(np.uint8)
    if attack.startswith("crop_center_"):
        scale = float(attack[len("crop_center_"):])
        h, w = arr.shape[:2]
        ch, cw = int(h * scale), int(w * scale)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        cropped = arr[y0:y0+ch, x0:x0+cw]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)
    if attack.startswith("rotate_"):
        angle = float(attack[len("rotate_"):])
        h, w = arr.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        return cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    raise ValueError(f"unknown attack: {attack}")


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
    fields = ["image_id", "source_path", "attack_type", "bit_error", "bit_accuracy",
              "psnr", "ssim", "success", "error"]
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def compute_metrics(ref: np.ndarray, cand: np.ndarray) -> tuple[float, float]:
    psnr = peak_signal_noise_ratio(ref, cand, data_range=255)
    ssim = structural_similarity(ref, cand, channel_axis=2, data_range=255)
    return float(psnr), float(ssim)


def summarize(csv_path: Path, attacks: list[str], ckpt: str, n: int) -> dict:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]
    summary: dict = {
        "project": "鉴源盾", "method": "KAD-Net", "mode": "real_checkpoint",
        "checkpoint": ckpt, "data_type": "real_lfw_images",
        "requested_images": n, "evaluated_rows": len(rows),
        "attacks": {}, "success_definition": "bit_accuracy >= 0.9",
    }
    for attack in attacks:
        subset = [r for r in rows if r["attack_type"] == attack]
        if not subset:
            summary["attacks"][attack] = {"status": "pending", "count": 0}
            continue
        vals = {k: np.array([float(r[k]) for r in subset]) for k in ["bit_error", "bit_accuracy", "psnr", "ssim"]}
        success = np.array([r["success"] == "1" for r in subset], dtype=float)
        summary["attacks"][attack] = {
            "status": "complete", "count": len(subset),
            "mean_bit_error": round(float(vals["bit_error"].mean()), 6),
            "mean_bit_accuracy": round(float(vals["bit_accuracy"].mean()), 6),
            "mean_psnr": round(float(vals["psnr"].mean()), 6),
            "mean_ssim": round(float(vals["ssim"].mean()), 6),
            "success_rate": round(float(success.mean()), 6),
        }
    return summary


def main() -> None:
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    from system.evaluation.adapters.kadnet_adapter import KADNetAdapter
    adapter = KADNetAdapter()
    if not adapter.available:
        print(f"KAD-Net not available: {adapter.blocker}", file=sys.stderr)
        sys.exit(1)

    ckpt_str = adapter.checkpoint or "unknown"
    print(f"KAD-Net checkpoint: {ckpt_str}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_DIR / "results.csv"
    progress_path = REPORT_DIR / "progress.json"

    images = list_images(args.image_root, args.num_images)
    done = read_done(csv_path)
    rng = np.random.default_rng(args.seed)

    pending: list[dict] = []
    processed = 0
    t0 = time.time()

    for idx, img_path in enumerate(images):
        image_id = img_path.stem
        img_orig = np.array(Image.open(img_path).convert("RGB"))
        msg = rng.integers(0, 2, size=(MSG_LEN,)).astype(np.uint8)

        try:
            enc_result = adapter.encode(img_orig, msg)
            enc_arr = enc_result.image
        except Exception as exc:
            for attack in args.attacks:
                if (image_id, attack) not in done:
                    pending.append({"image_id": image_id, "source_path": str(img_path),
                                    "attack_type": attack, "bit_error": "", "bit_accuracy": "",
                                    "psnr": "", "ssim": "", "success": "0", "error": repr(exc)})
            processed += 1
            continue

        for attack in args.attacks:
            if (image_id, attack) in done:
                continue
            try:
                attacked = apply_attack(enc_arr, attack, rng)
                dec_result = adapter.decode(attacked)
                ber = float(np.mean(dec_result.bits != msg))
                acc = 1.0 - ber
                ref_for_quality = np.array(Image.fromarray(img_orig).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC))
                enc_resized = np.array(Image.fromarray(enc_arr).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC))
                psnr, ssim = compute_metrics(ref_for_quality, enc_resized)
                pending.append({
                    "image_id": image_id, "source_path": str(img_path),
                    "attack_type": attack,
                    "bit_error": f"{ber:.6f}", "bit_accuracy": f"{acc:.6f}",
                    "psnr": f"{psnr:.6f}", "ssim": f"{ssim:.6f}",
                    "success": "1" if acc >= 0.9 else "0", "error": "",
                })
            except Exception as exc:
                pending.append({"image_id": image_id, "source_path": str(img_path),
                                "attack_type": attack, "bit_error": "", "bit_accuracy": "",
                                "psnr": "", "ssim": "", "success": "0", "error": repr(exc)})

        processed += 1
        if pending and processed % 200 == 0:
            append_rows(csv_path, pending)
            pending = []
            elapsed = time.time() - t0
            eta = elapsed / processed * (len(images) - processed)
            summary = summarize(csv_path, args.attacks, ckpt_str, len(images))
            (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
            progress_path.write_text(json.dumps({
                "processed": processed, "total": len(images),
                "elapsed_s": round(elapsed), "eta_s": round(eta),
                "updated_at": int(time.time()),
            }, indent=2))
            clean_acc = summary["attacks"].get("clean", {}).get("mean_bit_accuracy", "?")
            print(f"[{processed}/{len(images)}] clean_acc={clean_acc} eta={round(eta/60)}min")

    if pending:
        append_rows(csv_path, pending)

    summary = summarize(csv_path, args.attacks, ckpt_str, len(images))
    summary["run_metadata"] = build_run_metadata(
        model="KAD-Net", checkpoint=Path(ckpt_str) if ckpt_str != "unknown" else None,
        seed=args.seed, command=sys.argv,
    )
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    progress_path.write_text(json.dumps({"processed": len(images), "total": len(images),
                                          "status": "complete", "updated_at": int(time.time())}, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "run_metadata"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
