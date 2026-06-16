from __future__ import annotations

"""Track B2 — Face-region splice tamper + watermark-based tamper localization.

A watermarked real face (host) is spliced with a different person's face
(donor) inside an elliptical face region. This is a *real image-level splice
forgery* (manipulation_type=face_region_splice, evidence_level=
real_image_splice_forgery), NOT a hue/blur proxy and NOT a real deepfake swap.

Localization uses occlusion-sensitivity over a grid: for each grid cell we build
a probe = watermarked-host with only that cell's pixels replaced by the spliced
image (cells inside the face mask therefore carry the donor's pixels; cells
outside the mask are identical to the host and act as controls). The cell score
is 1 - decode(probe).bit_accuracy, so a tampered cell perturbs the watermark and
raises the score. Ground truth marks a cell tampered when >=50% of its pixels
fall inside the face mask.

Honesty notes:
  * Every bit-accuracy number is measured by adapter.decode on the actually
    manipulated pixels — no leakage, no shortcut.
  * AUC is a pure-numpy rank-based implementation (no sklearn dependency).
  * success_threshold is read from configs/evaluation_protocol.v1.json
    (falls back to 0.9 with a printed note if unreadable).
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.metrics import bit_metrics  # noqa: E402
from system.evaluation.run_metadata import build_run_metadata  # noqa: E402
from system.evaluation.runtime import ASSET_ROOT, PROJECT_ROOT  # noqa: E402

IMG_SIZE = 256  # canonical H x W for this benchmark

# CLI model name -> (adapter module, class name, registry name)
MODEL_MAP = {
    "kadnet": ("system.evaluation.adapters.kadnet_adapter", "KADNetAdapter", "KAD-Net"),
    "waveguard": ("system.evaluation.adapters.waveguard_adapter", "WaveGuardModelAdapter", "WaveGuard"),
    "hidden": ("system.evaluation.adapters.hidden_adapter", "HiDDeNAdapter", "HiDDeN"),
    "sepmark": ("system.evaluation.adapters.sepmark_adapter", "SepMarkModelAdapter", "SepMark"),
    "lidmark": ("system.evaluation.adapters.lidmark_adapter", "LIDMarkAdapter", "LIDMark"),
}

DEFAULT_HOST_ROOT = Path("/data1/luxliang/datasets/deepfake_images_extracted/Real")
DEFAULT_DONOR_ROOT = Path("/data1/luxliang/datasets/deepfake_images_extracted/Real")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Face-region splice tamper localization via watermark.")
    p.add_argument("--model", required=True, choices=sorted(MODEL_MAP.keys()))
    p.add_argument("--host-root", type=Path, default=DEFAULT_HOST_ROOT)
    p.add_argument("--donor-root", type=Path, default=DEFAULT_DONOR_ROOT)
    p.add_argument("--num-images", type=int, default=200)
    p.add_argument("--grid", type=int, default=8)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "system/reports/tamper_localization")
    p.add_argument("--save-heatmaps", type=int, default=8)
    p.add_argument("--feather", type=int, default=0,
                   help="optional alpha feather radius (px) on the splice mask edge; 0 = hard splice")
    return p.parse_args()


def load_success_threshold() -> tuple[float, str]:
    """Read success_threshold from the evaluation protocol; fall back to 0.9."""
    cfg = PROJECT_ROOT / "configs" / "evaluation_protocol.v1.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        thr = data.get("success_threshold")
        if isinstance(thr, (int, float)) and 0.0 <= thr <= 1.0:
            return float(thr), str(cfg)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[warn] could not read success_threshold from {cfg}: {exc!r}; falling back to 0.9", file=sys.stderr)
        return 0.9, "fallback_default_0.9"
    print(f"[warn] success_threshold missing/invalid in {cfg}; falling back to 0.9", file=sys.stderr)
    return 0.9, "fallback_default_0.9"


def list_images(root: Path, limit: int) -> list[Path]:
    imgs = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return imgs[:limit] if limit > 0 else imgs


def load_rgb(path: Path, size: int = IMG_SIZE) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if img.size != (size, size):
        img = img.resize((size, size), Image.BICUBIC)
    return np.array(img, dtype=np.uint8)


def face_ellipse_mask(h: int, w: int) -> np.ndarray:
    """Elliptical face mask: center (w//2, 0.45*h), semi-axes scaled by min(h,w)."""
    cx, cy = w // 2, int(0.45 * h)
    ax = int(0.27 * min(h, w))
    ay = int(0.32 * min(h, w))
    yy, xx = np.ogrid[:h, :w]
    norm = ((xx - cx) / float(ax)) ** 2 + ((yy - cy) / float(ay)) ** 2
    return norm <= 1.0


def build_spliced(wm_host: np.ndarray, donor: np.ndarray, mask: np.ndarray, feather: int) -> np.ndarray:
    """Splice donor pixels into wm_host inside mask. Hard splice unless feather>0."""
    if feather <= 0:
        out = wm_host.copy()
        out[mask] = donor[mask]
        return out
    # Feathered alpha blend on the mask edge.
    import cv2
    alpha = mask.astype(np.float32)
    k = feather * 2 + 1
    alpha = cv2.GaussianBlur(alpha, (k, k), 0)
    alpha = np.clip(alpha, 0.0, 1.0)[..., None]
    blended = wm_host.astype(np.float32) * (1.0 - alpha) + donor.astype(np.float32) * alpha
    return np.clip(blended + 0.5, 0, 255).astype(np.uint8)


def cell_bounds(idx: int, n: int, total: int) -> tuple[int, int]:
    """Even split of `total` px into `n` cells; returns [start, end) for cell idx."""
    start = (idx * total) // n
    end = ((idx + 1) * total) // n
    return start, end


def numpy_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Rank-based ROC-AUC (Mann-Whitney U). Pure numpy, no sklearn.

    Returns NaN if labels are all-positive or all-negative (AUC undefined).
    """
    scores = np.asarray(scores, dtype=np.float64).reshape(-1)
    labels = np.asarray(labels).reshape(-1).astype(bool)
    n_pos = int(labels.sum())
    n_neg = int((~labels).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    sorted_scores = scores[order]
    # Average ranks for ties (ranks are 1-based).
    i = 0
    rank_buf = np.arange(1, scores.size + 1, dtype=np.float64)
    while i < scores.size:
        j = i
        while j + 1 < scores.size and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        avg = rank_buf[i:j + 1].mean()
        ranks[order[i:j + 1]] = avg
        i = j + 1
    sum_pos_ranks = ranks[labels].sum()
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def iou_at_threshold(scores: np.ndarray, true: np.ndarray, thr: float) -> float:
    pred = scores >= thr
    truth = true.astype(bool)
    inter = int(np.logical_and(pred, truth).sum())
    union = int(np.logical_or(pred, truth).sum())
    if union == 0:
        return float("nan")
    return inter / float(union)


def save_heatmap_panel(out_dir: Path, image_id: str, wm_host: np.ndarray, spliced: np.ndarray,
                       score: np.ndarray, true: np.ndarray) -> None:
    """Save a horizontal panel: wm_host | spliced | score heatmap | true mask."""
    h, w = wm_host.shape[:2]

    def upscale(grid_arr: np.ndarray) -> np.ndarray:
        g = Image.fromarray(grid_arr)
        return np.array(g.resize((w, h), Image.NEAREST))

    smin, smax = float(score.min()), float(score.max())
    if smax - smin < 1e-12:
        score_norm = np.zeros_like(score, dtype=np.float32)
    else:
        score_norm = (score - smin) / (smax - smin)
    score_u8 = (score_norm * 255.0 + 0.5).astype(np.uint8)
    score_rgb = upscale(np.stack([score_u8, np.zeros_like(score_u8), 255 - score_u8], axis=-1))

    true_u8 = (true.astype(np.uint8) * 255)
    true_rgb = upscale(np.stack([true_u8, true_u8, true_u8], axis=-1))

    panel = np.concatenate([wm_host, spliced, score_rgb, true_rgb], axis=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(panel).save(out_dir / f"{image_id}_splice_localization.png")


def read_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add(row["image_id"])
    return done


def append_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def summarize(csv_path: Path, args: argparse.Namespace, registry_name: str, ckpt: str,
              threshold: float, threshold_source: str, msg_len: int) -> dict:
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]

    def col(name: str) -> np.ndarray:
        vals = [float(r[name]) for r in rows if r[name] not in ("", "nan")]
        return np.array(vals, dtype=np.float64) if vals else np.array([], dtype=np.float64)

    acc = col("acc_global")
    auc = col("localization_auc")
    iou_med = col("iou_median")
    iou_05 = col("iou_0.5")

    def m(arr: np.ndarray) -> float | None:
        return round(float(arr.mean()), 6) if arr.size else None

    return {
        "project": "鉴源盾",
        "track": "B2_tamper_localization",
        "model": registry_name,
        "checkpoint": ckpt,
        "n": len(rows),
        "requested_images": args.num_images,
        "grid": args.grid,
        "message_length": msg_len,
        "feather_px": args.feather,
        "mean_acc_global": m(acc),
        "mean_localization_auc": m(auc),
        "mean_iou_med": m(iou_med),
        "mean_iou_0.5": m(iou_05),
        "manipulation_type": "face_region_splice",
        "evidence_level": "real_image_splice_forgery",
        "localization_method": "watermark_occlusion_sensitivity_grid",
        "auc_implementation": "numpy_rank_based_mann_whitney",
        "success_threshold": threshold,
        "success_threshold_source": threshold_source,
        "seed": args.seed,
        "device": args.device,
        "generated_at": int(time.time()),
    }


def main() -> None:
    args = parse_args()
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    if args.grid < 1:
        sys.exit("--grid must be >= 1")

    threshold, threshold_source = load_success_threshold()

    import importlib
    module_path, class_name, registry_name = MODEL_MAP[args.model]
    adapter_cls = getattr(importlib.import_module(module_path), class_name)
    adapter = adapter_cls()
    if not adapter.available:
        sys.exit(f"adapter {registry_name} unavailable: {adapter.blocker}")

    msg_len = int(adapter.message_length)
    ckpt_str = adapter.checkpoint or "unknown"
    print(f"{registry_name} checkpoint: {ckpt_str} | message_length={msg_len} | grid={args.grid}")

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = ASSET_ROOT / "tamper_localization"
    csv_path = out_dir / f"{args.model}_results.csv"
    progress_path = out_dir / f"{args.model}_progress.json"

    csv_fields = ["image_id", "host_path", "donor_path", "acc_global",
                  "localization_auc", "iou_median", "iou_0.5", "n_true_cells", "error"]

    host_imgs = list_images(args.host_root, args.num_images)
    if not host_imgs:
        sys.exit(f"no host images found under {args.host_root}")
    donor_pool = list_images(args.donor_root, 0)
    if not donor_pool:
        sys.exit(f"no donor images found under {args.donor_root}")

    done = read_done(csv_path)
    rng = np.random.default_rng(args.seed)

    pending: list[dict] = []
    processed = 0
    saved_heatmaps = 0
    t0 = time.time()

    for host_path in host_imgs:
        image_id = host_path.stem
        if image_id in done:
            processed += 1
            continue

        # Per-image deterministic RNG (stable across processes, unlike builtin hash)
        # so resume reproduces identical messages/donor selection.
        id_hash = int.from_bytes(hashlib.sha256(image_id.encode("utf-8")).digest()[:8], "big")
        img_seed = (args.seed + id_hash) % (2 ** 32)
        img_rng = np.random.default_rng(img_seed)

        try:
            host = load_rgb(host_path, IMG_SIZE)

            # Pick a donor that is not the host.
            donor_path = host_path
            for _ in range(16):
                cand = donor_pool[int(img_rng.integers(0, len(donor_pool)))]
                if cand.resolve() != host_path.resolve():
                    donor_path = cand
                    break
            if donor_path.resolve() == host_path.resolve():
                raise RuntimeError("could not select a donor distinct from host")
            donor = load_rgb(donor_path, IMG_SIZE)

            msg = img_rng.integers(0, 2, size=msg_len).astype(np.uint8)
            wm_host = adapter.encode(host, msg).image
            if wm_host.shape[:2] != (IMG_SIZE, IMG_SIZE):
                wm_host = np.array(
                    Image.fromarray(wm_host).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC),
                    dtype=np.uint8,
                )

            h, w = wm_host.shape[:2]
            mask = face_ellipse_mask(h, w)
            spliced = build_spliced(wm_host, donor, mask, args.feather)

            # Global decode on the actually-manipulated spliced image (no leakage).
            acc_global = bit_metrics(msg, adapter.decode(spliced).bits, success_threshold=threshold)["accuracy"]

            g = args.grid
            score = np.zeros((g, g), dtype=np.float64)
            true = np.zeros((g, g), dtype=bool)
            for i in range(g):
                y0, y1 = cell_bounds(i, g, h)
                for j in range(g):
                    x0, x1 = cell_bounds(j, g, w)
                    cell_mask = mask[y0:y1, x0:x1]
                    frac_in = float(cell_mask.mean()) if cell_mask.size else 0.0
                    true[i, j] = frac_in >= 0.5

                    # Probe = wm_host with this cell's pixels replaced by spliced pixels.
                    # Inside-mask cells thus carry donor pixels; outside-mask cells stay
                    # identical to wm_host (controls). Decode measures watermark damage.
                    probe = wm_host.copy()
                    probe[y0:y1, x0:x1] = spliced[y0:y1, x0:x1]
                    cell_acc = bit_metrics(msg, adapter.decode(probe).bits,
                                           success_threshold=threshold)["accuracy"]
                    score[i, j] = 1.0 - cell_acc

            auc = numpy_auc(score.reshape(-1), true.reshape(-1))
            med_thr = float(np.median(score))
            iou_med = iou_at_threshold(score, true, med_thr)
            iou_05 = iou_at_threshold(score, true, 0.5)

            if saved_heatmaps < args.save_heatmaps:
                save_heatmap_panel(asset_dir, image_id, wm_host, spliced, score, true)
                saved_heatmaps += 1

            pending.append({
                "image_id": image_id,
                "host_path": str(host_path),
                "donor_path": str(donor_path),
                "acc_global": f"{acc_global:.6f}",
                "localization_auc": f"{auc:.6f}" if np.isfinite(auc) else "nan",
                "iou_median": f"{iou_med:.6f}" if np.isfinite(iou_med) else "nan",
                "iou_0.5": f"{iou_05:.6f}" if np.isfinite(iou_05) else "nan",
                "n_true_cells": str(int(true.sum())),
                "error": "",
            })
        except Exception as exc:  # noqa: BLE001 - record and continue
            pending.append({
                "image_id": image_id, "host_path": str(host_path), "donor_path": "",
                "acc_global": "", "localization_auc": "", "iou_median": "", "iou_0.5": "",
                "n_true_cells": "", "error": repr(exc),
            })

        processed += 1
        if pending and processed % 50 == 0:
            append_rows(csv_path, pending, csv_fields)
            pending = []
            elapsed = time.time() - t0
            summary = summarize(csv_path, args, registry_name, ckpt_str, threshold, threshold_source, msg_len)
            (out_dir / f"{args.model}_summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            progress_path.write_text(json.dumps({
                "processed": processed, "total": len(host_imgs),
                "elapsed_s": round(elapsed), "updated_at": int(time.time()),
            }, indent=2), encoding="utf-8")
            print(f"[{processed}/{len(host_imgs)}] "
                  f"mean_auc={summary['mean_localization_auc']} "
                  f"mean_acc_global={summary['mean_acc_global']}")

    if pending:
        append_rows(csv_path, pending, csv_fields)

    summary = summarize(csv_path, args, registry_name, ckpt_str, threshold, threshold_source, msg_len)
    summary["run_metadata"] = build_run_metadata(
        model=registry_name,
        checkpoint=Path(ckpt_str) if ckpt_str != "unknown" else None,
        seed=args.seed, command=sys.argv,
    )
    (out_dir / f"{args.model}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    progress_path.write_text(json.dumps({
        "processed": len(host_imgs), "total": len(host_imgs),
        "status": "complete", "updated_at": int(time.time()),
    }, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "run_metadata"},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
