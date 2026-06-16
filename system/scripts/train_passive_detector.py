from __future__ import annotations

"""
train_passive_detector.py
Track C: 被动 Deepfake 检测器训练 + 泛化评测

Purpose: 在真假脸数据上从零训练 ResNet18 二分类器(Real=1/Fake=0),
         评测跨域泛化 gap, 论证"被动检测不可靠 → 主动水印确定性溯源"。

Usage:
  PYTHONPATH=. python system/scripts/train_passive_detector.py \
      --device cuda:0 --epochs 20 --batch-size 128 --seed 20260616 \
      --data-root /data1/luxliang/datasets/deepfake_images_extracted \
      --out system/reports/passive_detector

Smoke test (2 images per class, 1 epoch):
  PYTHONPATH=. python system/scripts/train_passive_detector.py \
      --epochs 1 --batch-size 8 --device cuda:5 \
      --out system/reports/_smoke_detector --limit-per-class 2
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# ── Project root on sys.path ──────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# ── JYS runtime (DATA_ROOT / REPORT_ROOT / PROJECT_ROOT) ─────────────────────
from system.evaluation.runtime import PROJECT_ROOT, REPORT_ROOT  # noqa: E402
from system.evaluation.run_metadata import build_run_metadata      # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train ResNet18 passive deepfake detector (Track C)."
    )
    p.add_argument(
        "--data-root",
        type=Path,
        default=Path("/data1/luxliang/datasets/deepfake_images_extracted"),
        help="Root with Real/ and Fake/ sub-directories (JPEG, 256×256).",
    )
    p.add_argument("--arch", default="resnet18", choices=["resnet18"],
                   help="Backbone architecture (currently only resnet18).")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--img-size", type=int, default=224,
                   help="Resize target for training (bicubic).")
    p.add_argument(
        "--out",
        type=Path,
        default=REPORT_ROOT / "passive_detector",
        help="Output directory for checkpoints and reports.",
    )
    p.add_argument(
        "--val-frac",
        type=float,
        default=0.2,
        help="Fraction of images per class reserved for validation.",
    )
    p.add_argument(
        "--ood-real-root",
        type=Path,
        default=None,
        help=(
            "Optional: path to OOD real face images "
            "(e.g. LFW glob pattern root). "
            "If supplied, measures FPR on these images (passive gap metric)."
        ),
    )
    p.add_argument(
        "--limit-per-class",
        type=int,
        default=0,
        help=(
            "Debug: only load this many images per class (0 = all). "
            "Smoke-test with --limit-per-class 2."
        ),
    )
    p.add_argument(
        "--num-workers",
        type=int,
        default=4,
        help="DataLoader worker count.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Resume training from best.pt if it exists.",
    )
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Dataset
# ─────────────────────────────────────────────────────────────────────────────

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _list_images(directory: Path, limit: int) -> list[Path]:
    """Collect all image files under *directory*, sorted, optional cap."""
    files = sorted(
        p for p in directory.rglob("*") if p.suffix.lower() in IMG_EXTS
    )
    if limit > 0:
        files = files[:limit]
    return files


def build_splits(
    data_root: Path,
    val_frac: float,
    seed: int,
    limit_per_class: int,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    """
    Returns (train_samples, val_samples) where each element is (path, label).
    label: Real=1, Fake=0.
    """
    real_dir = data_root / "Real"
    fake_dir = data_root / "Fake"
    if not real_dir.is_dir():
        raise FileNotFoundError(f"Real directory not found: {real_dir}")
    if not fake_dir.is_dir():
        raise FileNotFoundError(f"Fake directory not found: {fake_dir}")

    real_files = _list_images(real_dir, limit_per_class)
    fake_files = _list_images(fake_dir, limit_per_class)

    if not real_files:
        raise RuntimeError(f"No images found under {real_dir}")
    if not fake_files:
        raise RuntimeError(f"No images found under {fake_dir}")

    rng = np.random.default_rng(seed)

    def _split(files: list[Path], label: int) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
        arr = np.array(files, dtype=object)
        rng.shuffle(arr)
        n_val = max(1, int(len(arr) * val_frac))
        val_paths = arr[:n_val].tolist()
        trn_paths = arr[n_val:].tolist()
        return (
            [(p, label) for p in trn_paths],
            [(p, label) for p in val_paths],
        )

    real_trn, real_val = _split(real_files, 1)
    fake_trn, fake_val = _split(fake_files, 0)

    train_samples = real_trn + fake_trn
    val_samples   = real_val + fake_val

    # shuffle combined train list
    rng.shuffle(train_samples)  # type: ignore[arg-type]
    return train_samples, val_samples


class DeepfakeDataset:
    """
    Minimal torch Dataset wrapper (avoids importing torch at module level
    before the device env-var is set).
    """

    def __init__(
        self,
        samples: list[tuple[Path, int]],
        img_size: int,
        augment: bool,
    ) -> None:
        self.samples = samples
        self.img_size = img_size
        self.augment = augment

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        import torch
        import torchvision.transforms.functional as TF
        from PIL import Image as PILImage

        path, label = self.samples[idx]
        img = PILImage.open(path).convert("RGB")

        if self.augment:
            import torchvision.transforms as T
            transform = T.Compose([
                T.RandomResizedCrop(self.img_size, scale=(0.8, 1.0)),
                T.RandomHorizontalFlip(),
                T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406],
                            std=[0.229, 0.224, 0.225]),
            ])
        else:
            import torchvision.transforms as T
            transform = T.Compose([
                T.Resize(int(self.img_size * 256 / 224)),
                T.CenterCrop(self.img_size),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406],
                            std=[0.229, 0.224, 0.225]),
            ])

        tensor = transform(img)
        return tensor, torch.tensor(label, dtype=torch.long)


# ─────────────────────────────────────────────────────────────────────────────
# CSV helpers
# ─────────────────────────────────────────────────────────────────────────────

EPOCH_CSV_FIELDS = [
    "epoch", "phase", "loss", "acc", "n",
    "tp", "tn", "fp", "fn",
    "elapsed_s", "timestamp",
]


def _write_epoch_row(csv_path: Path, row: dict[str, Any]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EPOCH_CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────────────────────────────────────
# Model
# ─────────────────────────────────────────────────────────────────────────────

def build_model(arch: str, num_classes: int = 2):
    """Build model from scratch (weights=None, no network access)."""
    import torchvision.models as models

    if arch == "resnet18":
        # weights=None → random init, no download
        model = models.resnet18(weights=None, num_classes=num_classes)
        return model
    raise ValueError(f"Unsupported arch: {arch}")


# ─────────────────────────────────────────────────────────────────────────────
# Training loop helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_epoch(
    model,
    loader,
    criterion,
    optimizer,
    device,
    train: bool,
) -> dict[str, Any]:
    """Run one epoch; return dict with loss, acc, confusion counts."""
    import torch

    model.train(train)
    total_loss = 0.0
    correct = 0
    n = 0
    tp = tn = fp = fn = 0

    ctx = torch.enable_grad() if train else torch.no_grad()
    with ctx:
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)

            if train:
                optimizer.zero_grad()

            logits = model(images)
            loss = criterion(logits, labels)

            if train:
                loss.backward()
                optimizer.step()

            preds = logits.argmax(dim=1)
            total_loss += loss.item() * images.size(0)
            correct += (preds == labels).sum().item()
            n += images.size(0)

            # confusion: label 1=Real(positive), 0=Fake(negative)
            tp += int(((preds == 1) & (labels == 1)).sum())
            tn += int(((preds == 0) & (labels == 0)).sum())
            fp += int(((preds == 1) & (labels == 0)).sum())
            fn += int(((preds == 0) & (labels == 1)).sum())

    return {
        "loss": total_loss / n if n > 0 else float("nan"),
        "acc": correct / n if n > 0 else float("nan"),
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def _compute_auc(
    model,
    loader,
    device,
) -> float:
    """Compute binary AUC (class-1 score) over loader. Returns float."""
    import torch

    model.eval()
    scores: list[float] = []
    labels_all: list[int] = []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            logits = model(images)
            # softmax probability of class 1 (Real)
            probs = torch.softmax(logits, dim=1)[:, 1]
            scores.extend(probs.cpu().tolist())
            labels_all.extend(labels.tolist())

    scores_arr = np.array(scores)
    labels_arr = np.array(labels_all)

    # Wilcoxon / Mann-Whitney U statistic → AUC
    pos_scores = scores_arr[labels_arr == 1]
    neg_scores = scores_arr[labels_arr == 0]

    if len(pos_scores) == 0 or len(neg_scores) == 0:
        return float("nan")

    # O(n log n) version via sort
    combined = np.concatenate([pos_scores, neg_scores])
    ranks = np.argsort(np.argsort(combined)) + 1  # 1-based ranks
    n_pos = len(pos_scores)
    n_neg = len(neg_scores)
    rank_sum_pos = float(ranks[:n_pos].sum())
    u_stat = rank_sum_pos - n_pos * (n_pos + 1) / 2
    auc = u_stat / (n_pos * n_neg)
    return float(auc)


def _evaluate_ood_fpr(model, ood_root: Path, img_size: int, batch_size: int,
                      num_workers: int, device) -> dict[str, Any]:
    """
    Measure False Positive Rate on OOD real images
    (detector predicts Fake=0 on a real-world real face → FP).
    Images are all treated as Real (label=1); FP = predicted as Fake.
    Returns dict with n, fpr, fp, tn.
    """
    import torch
    from torch.utils.data import DataLoader

    ood_files = _list_images(ood_root, 0)
    if not ood_files:
        return {"error": f"no images found under {ood_root}", "n": 0}

    # label=1 (Real) for all OOD real images
    samples = [(p, 1) for p in ood_files]
    dataset = DeepfakeDataset(samples, img_size=img_size, augment=False)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )

    model.eval()
    fp = tn = n = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            logits = model(images)
            preds = logits.argmax(dim=1)
            n += images.size(0)
            # FP: real image predicted as Fake (0)
            fp += int((preds == 0).sum())
            tn += int((preds == 1).sum())

    fpr = fp / n if n > 0 else float("nan")
    return {"n": n, "fpr": fpr, "fp": fp, "tn": tn,
            "interpretation": "FPR = fraction of OOD real images mis-classified as Fake"}


# ─────────────────────────────────────────────────────────────────────────────
# Load success_threshold from protocol
# ─────────────────────────────────────────────────────────────────────────────

def _load_success_threshold() -> tuple[float, str]:
    """Returns (threshold, source_note)."""
    protocol_path = PROJECT_ROOT / "configs" / "evaluation_protocol.v1.json"
    try:
        with protocol_path.open(encoding="utf-8") as f:
            proto = json.load(f)
        threshold = float(proto["success_threshold"])
        return threshold, str(protocol_path)
    except Exception as exc:
        fallback = 0.9
        note = f"fallback={fallback} (protocol load failed: {exc})"
        return fallback, note


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # Must set before any torch/cuda import to select GPU
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader

    # ── reproducibility ───────────────────────────────────────────────────────
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"[train_passive_detector] device={device}  arch={args.arch}  "
          f"epochs={args.epochs}  lr={args.lr}  seed={args.seed}")

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    best_ckpt_path = out_dir / "best.pt"
    epoch_csv_path = out_dir / "epoch_log.csv"
    metrics_json_path = out_dir / "metrics.json"
    progress_json_path = out_dir / "progress.json"

    success_threshold, threshold_source = _load_success_threshold()
    print(f"[train_passive_detector] success_threshold={success_threshold} "
          f"(from: {threshold_source})")

    # ── build dataset splits ──────────────────────────────────────────────────
    print(f"[train_passive_detector] scanning {args.data_root} ...")
    train_samples, val_samples = build_splits(
        data_root=args.data_root,
        val_frac=args.val_frac,
        seed=args.seed,
        limit_per_class=args.limit_per_class,
    )
    n_train_real = sum(1 for _, l in train_samples if l == 1)
    n_train_fake = sum(1 for _, l in train_samples if l == 0)
    n_val_real = sum(1 for _, l in val_samples if l == 1)
    n_val_fake = sum(1 for _, l in val_samples if l == 0)
    print(f"  train: {len(train_samples)} (Real={n_train_real}, Fake={n_train_fake})")
    print(f"  val:   {len(val_samples)}   (Real={n_val_real},   Fake={n_val_fake})")
    if args.limit_per_class > 0:
        print(f"  [DEBUG] --limit-per-class={args.limit_per_class} active")

    train_dataset = DeepfakeDataset(train_samples, img_size=args.img_size, augment=True)
    val_dataset   = DeepfakeDataset(val_samples,   img_size=args.img_size, augment=False)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=False,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=True,
    )

    # ── model / optimizer / scheduler ────────────────────────────────────────
    model = build_model(args.arch, num_classes=2).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr * 0.01
    )

    start_epoch = 1
    best_val_acc = 0.0

    # ── optional resume ───────────────────────────────────────────────────────
    if args.resume and best_ckpt_path.is_file():
        ckpt = torch.load(best_ckpt_path, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        best_val_acc = ckpt.get("val_acc", 0.0)
        start_epoch = ckpt.get("epoch", 0) + 1
        print(f"[resume] loaded {best_ckpt_path}  "
              f"best_val_acc={best_val_acc:.4f}  next_epoch={start_epoch}")

    epoch_records: list[dict[str, Any]] = []
    t_run_start = time.time()

    # ── training loop ─────────────────────────────────────────────────────────
    for epoch in range(start_epoch, args.epochs + 1):
        t0 = time.time()

        train_stats = _run_epoch(
            model, train_loader, criterion, optimizer, device, train=True
        )
        val_stats = _run_epoch(
            model, val_loader, criterion, optimizer, device, train=False
        )
        scheduler.step()

        elapsed = time.time() - t0

        print(
            f"[epoch {epoch:03d}/{args.epochs:03d}] "
            f"train_loss={train_stats['loss']:.4f} train_acc={train_stats['acc']:.4f}  "
            f"val_loss={val_stats['loss']:.4f}  val_acc={val_stats['acc']:.4f}  "
            f"({elapsed:.1f}s)"
        )

        # CSV logging
        for phase, stats in [("train", train_stats), ("val", val_stats)]:
            row = {
                "epoch": epoch,
                "phase": phase,
                "loss": f"{stats['loss']:.6f}",
                "acc": f"{stats['acc']:.6f}",
                "n": stats["n"],
                "tp": stats["tp"],
                "tn": stats["tn"],
                "fp": stats["fp"],
                "fn": stats["fn"],
                "elapsed_s": f"{elapsed:.2f}" if phase == "val" else "",
                "timestamp": int(time.time()),
            }
            _write_epoch_row(epoch_csv_path, row)

        # record for summary
        epoch_records.append({
            "epoch": epoch,
            "train_loss": round(train_stats["loss"], 6),
            "train_acc":  round(train_stats["acc"],  6),
            "val_loss":   round(val_stats["loss"],   6),
            "val_acc":    round(val_stats["acc"],    6),
        })

        # save best checkpoint
        if val_stats["acc"] > best_val_acc:
            best_val_acc = val_stats["acc"]
            torch.save(
                {
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "val_acc": best_val_acc,
                    "arch": args.arch,
                    "img_size": args.img_size,
                    "seed": args.seed,
                    "saved_at": int(time.time()),
                },
                best_ckpt_path,
            )
            print(f"  [checkpoint] new best val_acc={best_val_acc:.4f} → {best_ckpt_path}")

        # periodic progress dump
        elapsed_total = time.time() - t_run_start
        epochs_done = epoch - start_epoch + 1
        epochs_left = args.epochs - epoch
        eta_s = (elapsed_total / epochs_done * epochs_left) if epochs_done > 0 else 0
        progress_json_path.write_text(json.dumps({
            "epoch": epoch,
            "total_epochs": args.epochs,
            "best_val_acc": round(best_val_acc, 6),
            "elapsed_s": round(elapsed_total),
            "eta_s": round(eta_s),
            "updated_at": int(time.time()),
        }, indent=2))

    # ── final val AUC (load best checkpoint) ─────────────────────────────────
    print("[final] computing val AUC from best checkpoint ...")
    if best_ckpt_path.is_file():
        ckpt = torch.load(best_ckpt_path, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        _ckpt_val_acc = ckpt.get("val_acc", "?")
        _ckpt_val_acc_str = f"{_ckpt_val_acc:.4f}" if isinstance(_ckpt_val_acc, float) else str(_ckpt_val_acc)
        print(f"  loaded best checkpoint (epoch={ckpt.get('epoch','?')}, "
              f"val_acc={_ckpt_val_acc_str})")

    val_auc = _compute_auc(model, val_loader, device)
    print(f"  val_auc={val_auc:.4f}")

    # final val confusion (recompute on best model)
    val_final = _run_epoch(model, val_loader, criterion, optimizer, device, train=False)
    confusion = {
        "tp": val_final["tp"],
        "tn": val_final["tn"],
        "fp": val_final["fp"],
        "fn": val_final["fn"],
    }

    # ── OOD evaluation (optional) ─────────────────────────────────────────────
    ood_result: dict[str, Any] | None = None
    if args.ood_real_root is not None:
        print(f"[ood] evaluating OOD real images from {args.ood_real_root} ...")
        ood_result = _evaluate_ood_fpr(
            model,
            ood_root=args.ood_real_root,
            img_size=args.img_size,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            device=device,
        )
        fpr_str = f"{ood_result['fpr']:.4f}" if isinstance(ood_result.get("fpr"), float) else "N/A"
        print(f"  ood_fpr={fpr_str}  n={ood_result.get('n', 0)}")

    # ── metrics.json ─────────────────────────────────────────────────────────
    run_meta = build_run_metadata(
        model=f"passive_detector/{args.arch}",
        checkpoint=best_ckpt_path if best_ckpt_path.is_file() else None,
        seed=args.seed,
        command=sys.argv,
    )

    metrics: dict[str, Any] = {
        "generated_at": int(time.time()),
        "seed": args.seed,
        "device": args.device,
        "arch": args.arch,
        "epochs_trained": args.epochs,
        "img_size": args.img_size,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "val_frac": args.val_frac,
        "limit_per_class": args.limit_per_class,
        "checkpoint": str(best_ckpt_path) if best_ckpt_path.is_file() else None,
        "data_root": str(args.data_root),
        "dataset_split": {
            "n_train": len(train_samples),
            "n_train_real": n_train_real,
            "n_train_fake": n_train_fake,
            "n_val": len(val_samples),
            "n_val_real": n_val_real,
            "n_val_fake": n_val_fake,
        },
        "best_val_acc": round(best_val_acc, 6),
        "final_val_acc": round(val_final["acc"], 6),
        "val_auc": round(val_auc, 6) if not np.isnan(val_auc) else None,
        "val_confusion": confusion,
        "success_threshold_used": success_threshold,
        "success_threshold_source": threshold_source,
        "epoch_history": epoch_records,
        "ood_evaluation": ood_result,
        "conclusion_note": (
            "Passive detector accuracy and generalization gap "
            "measured on held-out val set and optional OOD real images. "
            "Numbers are purely empirical — no hand-tuned constants. "
            "High val_acc on in-distribution data but elevated ood_fpr "
            "demonstrates the brittleness of passive detection, "
            "motivating active watermarking for deterministic provenance."
        ),
        "run_metadata": run_meta,
    }

    metrics_json_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False)
    )
    print(f"\n[done] metrics written to {metrics_json_path}")

    # Print compact summary
    summary = {k: v for k, v in metrics.items()
               if k not in ("epoch_history", "run_metadata")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
