from __future__ import annotations

"""
train_face_autoencoder.py — 训练人脸卷积自编码器 (Track B1 训练侧)

在 CelebA-HQ 128px 上从零训练一个有损卷积 AE.
瓶颈足够窄, 使 val PSNR 落在 28-34 dB 区间,
既保留人脸结构又引入可感失真 —— 作为 AI 再生成操纵的基础.

用法:
  PYTHONPATH=. python system/scripts/train_face_autoencoder.py \
      --data-root /home/luxliang/JianYuanShield/datasets/celeba_hq_kadnet \
      --epochs 40 --batch-size 64 --lr 2e-4 --device cuda:0 \
      --img-size 128 --latent-ch 128 \
      --out system/reports/face_autoencoder --seed 20260616

冒烟测试:
  PYTHONPATH=. python system/scripts/train_face_autoencoder.py \
      --epochs 1 --batch-size 8 --device cuda:5 \
      --out system/reports/_smoke_ae --limit 64
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image

# ── 项目路径 ──────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T
from skimage.metrics import peak_signal_noise_ratio

# ── 默认路径 ──────────────────────────────────────────────────────────────────
DEFAULT_DATA_ROOT = Path("/home/luxliang/JianYuanShield/datasets/celeba_hq_kadnet")
DEFAULT_OUT = Path("system/reports/face_autoencoder")


# ═══════════════════════════════════════════════════════════════════════════════
# Dataset
# ═══════════════════════════════════════════════════════════════════════════════

class ImageFolderFlat(Dataset):
    """递归扫描目录下所有 jpg/png 文件, 返回 [0,1] float tensor."""

    EXTS = {".jpg", ".jpeg", ".png"}

    def __init__(self, root: Path, img_size: int, limit: int = 0) -> None:
        paths: List[Path] = sorted(
            p for p in root.rglob("*") if p.suffix.lower() in self.EXTS
        )
        if limit > 0:
            paths = paths[:limit]
        if not paths:
            raise FileNotFoundError(f"No images found under {root}")
        self.paths = paths
        self.transform = T.Compose([
            T.Resize((img_size, img_size), interpolation=T.InterpolationMode.BICUBIC),
            T.ToTensor(),          # [0,1] float32, CxHxW
        ])

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> torch.Tensor:
        img = Image.open(self.paths[idx]).convert("RGB")
        return self.transform(img)


# ═══════════════════════════════════════════════════════════════════════════════
# Model: stride-2 Encoder + ConvTranspose Decoder
# ═══════════════════════════════════════════════════════════════════════════════
# 128 → 64 → 32 → 16 → 8  (4 stride-2 conv) 瓶颈 8×8×latent_ch
# 8 → 16 → 32 → 64 → 128  (4 ConvTranspose2d)

class ConvBlock(nn.Module):
    """Conv2d + BN + LeakyReLU."""

    def __init__(
        self,
        in_ch: int,
        out_ch: int,
        kernel: int = 3,
        stride: int = 1,
        padding: int = 1,
    ) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, kernel, stride=stride, padding=padding, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.LeakyReLU(0.1, inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class UpBlock(nn.Module):
    """ConvTranspose2d (stride-2 upsample) + BN + ReLU."""

    def __init__(self, in_ch: int, out_ch: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.ConvTranspose2d(in_ch, out_ch, kernel_size=4, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class FaceAutoEncoder(nn.Module):
    """
    有损人脸卷积自编码器.
    Encoder: 3 → 64 → 128 → 256 → latent_ch  (全 stride-2)
    Bottleneck: 8×8×latent_ch
    Decoder: latent_ch → 256 → 128 → 64 → 3  (全 stride-2 转置卷积)
    输出 sigmoid → [0,1].
    """

    def __init__(self, latent_ch: int = 128) -> None:
        super().__init__()
        # Encoder: 128→64→32→16→8
        self.enc1 = ConvBlock(3,        64,  stride=2)   # 128→64
        self.enc2 = ConvBlock(64,       128, stride=2)   # 64→32
        self.enc3 = ConvBlock(128,      256, stride=2)   # 32→16
        self.enc4 = ConvBlock(256, latent_ch, stride=2)  # 16→8

        # Decoder: 8→16→32→64→128
        self.dec1 = UpBlock(latent_ch, 256)   # 8→16
        self.dec2 = UpBlock(256, 128)          # 16→32
        self.dec3 = UpBlock(128, 64)           # 32→64
        self.dec4 = UpBlock(64,  32)           # 64→128

        # 输出头
        self.out_conv = nn.Sequential(
            nn.Conv2d(32, 3, kernel_size=3, stride=1, padding=1),
            nn.Sigmoid(),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        x = self.enc1(x)
        x = self.enc2(x)
        x = self.enc3(x)
        x = self.enc4(x)
        return x

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        x = self.dec1(z)
        x = self.dec2(x)
        x = self.dec3(x)
        x = self.dec4(x)
        return self.out_conv(x)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decode(self.encode(x))


# ═══════════════════════════════════════════════════════════════════════════════
# Loss
# ═══════════════════════════════════════════════════════════════════════════════

class ReconLoss(nn.Module):
    """L1 + 0.5 * MSE."""

    def __init__(self) -> None:
        super().__init__()
        self.l1 = nn.L1Loss()
        self.mse = nn.MSELoss()

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return self.l1(pred, target) + 0.5 * self.mse(pred, target)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def psnr_batch(pred: torch.Tensor, target: torch.Tensor) -> float:
    """
    计算一个 batch 的平均 PSNR (data_range=1.0, [0,1] float).
    用 skimage 与其它脚本保持一致.
    """
    pred_np = pred.detach().cpu().permute(0, 2, 3, 1).numpy()   # BxHxWxC
    tgt_np  = target.detach().cpu().permute(0, 2, 3, 1).numpy()
    vals = []
    for p, t in zip(pred_np, tgt_np):
        vals.append(peak_signal_noise_ratio(t, p, data_range=1.0))
    return float(np.mean(vals))


def tensor_to_uint8(t: torch.Tensor) -> np.ndarray:
    """CxHxW float[0,1] → HxWxC uint8."""
    return (t.clamp(0, 1).cpu().permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)


def load_checkpoint(path: Path, model: FaceAutoEncoder, optimizer: optim.Optimizer) -> int:
    """从 checkpoint 恢复, 返回下一个 epoch 编号(0-based). 找不到返回 0."""
    ckpt_path = path / "last.pt"
    if not ckpt_path.exists():
        return 0
    state = torch.load(ckpt_path, map_location="cpu")
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    resume_epoch = state["epoch"] + 1
    print(f"[resume] Loaded {ckpt_path} → resuming from epoch {resume_epoch}")
    return resume_epoch


def save_checkpoint(
    path: Path,
    model: FaceAutoEncoder,
    optimizer: optim.Optimizer,
    epoch: int,
    is_best: bool,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    state = {
        "epoch": epoch,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
    }
    torch.save(state, path / "last.pt")
    if is_best:
        torch.save(state, path / "best.pt")


# ═══════════════════════════════════════════════════════════════════════════════
# Argument parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train face convolutional autoencoder for AI-regeneration attack (Track B1)"
    )
    p.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT,
                   help="CelebA-HQ data root; expects train_128/ and val_128/ subdirs")
    p.add_argument("--epochs",     type=int,   default=40)
    p.add_argument("--batch-size", type=int,   default=64)
    p.add_argument("--lr",         type=float, default=2e-4)
    p.add_argument("--device",     type=str,   default="cuda:0")
    p.add_argument("--img-size",   type=int,   default=128)
    p.add_argument("--latent-ch",  type=int,   default=128,
                   help="Bottleneck channels at 8x8 spatial resolution")
    p.add_argument("--out",        type=Path,  default=DEFAULT_OUT,
                   help="Output directory for checkpoints and metrics")
    p.add_argument("--seed",       type=int,   default=20260616)
    p.add_argument("--limit",      type=int,   default=0,
                   help="Limit total images per split (0=no limit); for smoke tests")
    p.add_argument("--num-workers", type=int,  default=4)
    p.add_argument("--log-interval", type=int, default=50,
                   help="Print training loss every N batches")
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = parse_args()

    # ── 输出目录 ────────────────────────────────────────────────────────────
    out_dir: Path = args.out if args.out.is_absolute() else PROJECT_DIR / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # ── 随机种子 ────────────────────────────────────────────────────────────
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    # ── 设备 ────────────────────────────────────────────────────────────────
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"[init] device={device}  latent_ch={args.latent_ch}  img_size={args.img_size}")

    # ── 数据 ────────────────────────────────────────────────────────────────
    train_root = args.data_root / "train_128"
    val_root   = args.data_root / "val_128"

    if not train_root.exists():
        print(f"[error] train_128 not found: {train_root}", file=sys.stderr)
        sys.exit(1)
    if not val_root.exists():
        print(f"[error] val_128 not found: {val_root}", file=sys.stderr)
        sys.exit(1)

    train_ds = ImageFolderFlat(train_root, args.img_size, limit=args.limit)
    val_ds   = ImageFolderFlat(val_root,   args.img_size, limit=args.limit)
    print(f"[data] train={len(train_ds)}  val={len(val_ds)}")

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=True,
    )

    # ── 模型 ────────────────────────────────────────────────────────────────
    model = FaceAutoEncoder(latent_ch=args.latent_ch).to(device)
    param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[model] params={param_count/1e6:.2f}M  bottleneck=8x8x{args.latent_ch}")

    criterion = ReconLoss()
    optimizer = optim.Adam(model.parameters(), lr=args.lr, betas=(0.9, 0.999))
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=1e-6)

    # ── Resume ──────────────────────────────────────────────────────────────
    start_epoch = load_checkpoint(ckpt_dir, model, optimizer)

    # ── 历史记录 (追加模式, 支持 resume) ────────────────────────────────────
    metrics_path = out_dir / "metrics.json"
    if metrics_path.exists() and start_epoch > 0:
        history: List[dict] = json.loads(metrics_path.read_text(encoding="utf-8")).get("epochs", [])
        # 只保留已完成的 epoch
        history = [e for e in history if e["epoch"] < start_epoch]
    else:
        history = []

    best_psnr: float = max((e["val_psnr_db"] for e in history), default=0.0)
    # Recover best_epoch from history so resume reports the correct epoch number.
    best_epoch: int = next(
        (e["epoch"] for e in history if round(e["val_psnr_db"], 4) == round(best_psnr, 4)),
        0,
    )

    run_start = time.time()
    print(f"[train] start_epoch={start_epoch}  total_epochs={args.epochs}  best_psnr_so_far={best_psnr:.2f}")

    # ── 训练循环 ────────────────────────────────────────────────────────────
    for epoch in range(start_epoch, args.epochs):
        epoch_t0 = time.time()
        model.train()

        train_loss_sum = 0.0
        train_steps = 0
        for batch_idx, imgs in enumerate(train_loader):
            imgs = imgs.to(device, non_blocking=True)
            recon = model(imgs)
            loss = criterion(recon, imgs)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss_sum += loss.item()
            train_steps += 1

            if (batch_idx + 1) % args.log_interval == 0:
                print(
                    f"  [epoch {epoch+1}/{args.epochs}]"
                    f"  step {batch_idx+1}/{len(train_loader)}"
                    f"  loss={loss.item():.5f}"
                )

        mean_train_loss = train_loss_sum / max(train_steps, 1)

        # ── 验证 ────────────────────────────────────────────────────────
        model.eval()
        val_psnr_vals: List[float] = []
        val_l1_sum = 0.0
        val_steps = 0
        with torch.no_grad():
            for imgs in val_loader:
                imgs = imgs.to(device, non_blocking=True)
                recon = model(imgs)
                l1 = F.l1_loss(recon, imgs).item()
                val_l1_sum += l1
                val_steps += 1
                val_psnr_vals.append(psnr_batch(recon, imgs))

        mean_val_l1   = val_l1_sum / max(val_steps, 1)
        mean_val_psnr = float(np.mean(val_psnr_vals)) if val_psnr_vals else 0.0

        # ── 调度 ────────────────────────────────────────────────────────
        scheduler.step()
        current_lr = scheduler.get_last_lr()[0]

        is_best = mean_val_psnr > best_psnr
        if is_best:
            best_psnr  = mean_val_psnr
            best_epoch = epoch + 1

        epoch_elapsed = time.time() - epoch_t0
        print(
            f"[epoch {epoch+1}/{args.epochs}]"
            f"  train_l1={mean_train_loss:.5f}"
            f"  val_l1={mean_val_l1:.5f}"
            f"  val_psnr={mean_val_psnr:.2f}dB"
            f"  lr={current_lr:.2e}"
            f"  best={best_psnr:.2f}dB(ep{best_epoch})"
            f"  time={epoch_elapsed:.1f}s"
            + ("  [BEST]" if is_best else "")
        )

        # ── 存档 ────────────────────────────────────────────────────────
        save_checkpoint(ckpt_dir, model, optimizer, epoch, is_best)

        epoch_record: dict = {
            "epoch":           epoch + 1,
            "train_l1_loss":   round(mean_train_loss, 6),
            "val_l1_loss":     round(mean_val_l1, 6),
            "val_psnr_db":     round(mean_val_psnr, 4),
            "lr":              float(current_lr),
            "is_best":         is_best,
            "elapsed_s":       round(epoch_elapsed, 2),
            "timestamp":       int(time.time()),
        }
        history.append(epoch_record)

        # ── 周期落盘 metrics.json ────────────────────────────────────
        metrics_snapshot: dict = {
            "generated_at":      int(time.time()),
            "script":            "train_face_autoencoder.py",
            "project":           "鉴源盾",
            "manipulation_type": "self_trained_autoencoder_regeneration",
            "evidence_level":    "self_trained_autoencoder_regeneration",
            "model_arch":        "FaceAutoEncoder_stride2_conv",
            "latent_ch":         args.latent_ch,
            "bottleneck_shape":  f"8x8x{args.latent_ch}",
            "img_size":          args.img_size,
            "seed":              args.seed,
            "device":            str(device),
            "data_root":         str(args.data_root),
            "train_images":      len(train_ds),
            "val_images":        len(val_ds),
            "total_params_M":    round(param_count / 1e6, 3),
            "epochs_planned":    args.epochs,
            "epochs_completed":  epoch + 1,
            "best_val_psnr_db":  round(best_psnr, 4),
            "best_epoch":        best_epoch,
            "checkpoint_last":   str(ckpt_dir / "last.pt"),
            "checkpoint_best":   str(ckpt_dir / "best.pt"),
            "loss_formula":      "L1 + 0.5*MSE",
            "psnr_target_range": "28-34 dB (lossy but face-preserving)",
            "elapsed_total_s":   round(time.time() - run_start, 1),
            "epochs":            history,
        }
        metrics_path.write_text(
            json.dumps(metrics_snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── 训练结束 ─────────────────────────────────────────────────────────────
    total_elapsed = time.time() - run_start
    print(f"\n[done] best val_psnr={best_psnr:.2f}dB at epoch {best_epoch}")
    print(f"[done] checkpoints → {ckpt_dir}")
    print(f"[done] total_time={total_elapsed/60:.1f}min")

    # ── 最终 metrics.json (保证包含全量 epochs) ──────────────────────────────
    final_metrics: dict = {
        "generated_at":      int(time.time()),
        "script":            "train_face_autoencoder.py",
        "project":           "鉴源盾",
        "manipulation_type": "self_trained_autoencoder_regeneration",
        "evidence_level":    "self_trained_autoencoder_regeneration",
        "training_status":   "complete" if (args.epochs - start_epoch) > 0 else "no_epochs_run",
        "model_arch":        "FaceAutoEncoder_stride2_conv",
        "latent_ch":         args.latent_ch,
        "bottleneck_shape":  f"8x8x{args.latent_ch}",
        "img_size":          args.img_size,
        "seed":              args.seed,
        "device":            str(device),
        "data_root":         str(args.data_root),
        "train_images":      len(train_ds),
        "val_images":        len(val_ds),
        "total_params_M":    round(param_count / 1e6, 3),
        "epochs_planned":    args.epochs,
        "epochs_completed":  args.epochs,
        "best_val_psnr_db":  round(best_psnr, 4),
        "best_epoch":        best_epoch,
        "checkpoint_last":   str(ckpt_dir / "last.pt"),
        "checkpoint_best":   str(ckpt_dir / "best.pt"),
        "loss_formula":      "L1 + 0.5*MSE",
        "psnr_target_range": "28-34 dB (lossy but face-preserving)",
        "elapsed_total_s":   round(total_elapsed, 1),
        "epochs":            history,
        "note":              (
            "PSNR measured on [0,1] float images using skimage.peak_signal_noise_ratio "
            "(data_range=1.0). All numbers are real measurements — no values hardcoded."
        ),
    }
    metrics_path.write_text(
        json.dumps(final_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[done] metrics → {metrics_path}")


if __name__ == "__main__":
    main()
