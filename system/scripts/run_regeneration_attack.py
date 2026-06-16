from __future__ import annotations

"""AI re-generation attack closed-loop (Track B1, evaluation side).

Honestly measures whether a watermark survives a *self-trained autoencoder
regeneration* attack -- the standard "generative regeneration" threat in modern
watermark-removal literature. The pipeline is fully self-contained and
reproducible: no external face-swap weights are required.

For each real face host image:
  1. msg  = random `adapter.message_length` bits
  2. wm   = adapter.encode(host, msg).image          (host-resolution, e.g. 256)
  3. bits0 = adapter.decode(wm).bits     -> acc_clean (control; proves no leakage)
  4. regen:  resize wm -> ae_img_size -> AE.forward -> resize back to host size
  5. bits1 = adapter.decode(regen).bits  -> acc_regen (THE measured robustness)
  6. AE distortion: image_quality(wm_resized_to_ae, recon) psnr/ssim

acc_regen is decoded on the *actually regenerated* image. There is no leakage:
the clean control and the regen measurement use independent decode() calls on
independent image arrays.

manipulation_type  = "self_trained_autoencoder_regeneration"
evidence_level     = "self_trained_generative_regeneration"

The autoencoder structure is defined in this file (FaceAutoencoder) and is
re-instantiated from the hyperparameters stored inside the checkpoint
(`hyperparams` key). The companion training script `train_face_autoencoder.py`
MUST define a byte-for-byte identical FaceAutoencoder and persist its
constructor kwargs under checkpoint["hyperparams"] so the state_dict loads
strictly.
"""

import argparse
import csv
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


# --------------------------------------------------------------------------- #
# Autoencoder definition (must match train_face_autoencoder.py byte-for-byte). #
# Re-instantiated from checkpoint["hyperparams"]; weights=None (from scratch). #
# --------------------------------------------------------------------------- #
def _build_autoencoder():
    """Return the FaceAutoEncoder class — byte-for-byte identical to the one in
    train_face_autoencoder.py (enc1..enc4 ConvBlock / dec1..dec4 UpBlock /
    out_conv). The checkpoint produced by the trainer stores its weights under
    these exact module names, so a strict load only succeeds with this arch.

    Lazy torch import so the module can be argparse'd before CUDA init.
    """
    import torch.nn as nn

    class ConvBlock(nn.Module):
        """Conv2d + BN + LeakyReLU (matches trainer)."""

        def __init__(self, in_ch, out_ch, kernel=3, stride=1, padding=1):
            super().__init__()
            self.block = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel, stride=stride, padding=padding, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.LeakyReLU(0.1, inplace=True),
            )

        def forward(self, x):
            return self.block(x)

    class UpBlock(nn.Module):
        """ConvTranspose2d (stride-2) + BN + ReLU (matches trainer)."""

        def __init__(self, in_ch, out_ch):
            super().__init__()
            self.block = nn.Sequential(
                nn.ConvTranspose2d(in_ch, out_ch, kernel_size=4, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.block(x)

    class FaceAutoEncoder(nn.Module):
        """有损人脸卷积 AE — 与 train_face_autoencoder.py 完全一致。

        仅一个超参 latent_ch (8x8 瓶颈通道数). 输入/输出 (B,3,128,128) float[0,1].
        """

        def __init__(self, latent_ch: int = 128):
            super().__init__()
            self.latent_ch = int(latent_ch)
            self.enc1 = ConvBlock(3,        64,  stride=2)   # 128→64
            self.enc2 = ConvBlock(64,       128, stride=2)   # 64→32
            self.enc3 = ConvBlock(128,      256, stride=2)   # 32→16
            self.enc4 = ConvBlock(256, latent_ch, stride=2)  # 16→8
            self.dec1 = UpBlock(latent_ch, 256)              # 8→16
            self.dec2 = UpBlock(256, 128)                    # 16→32
            self.dec3 = UpBlock(128, 64)                     # 32→64
            self.dec4 = UpBlock(64,  32)                     # 64→128
            self.out_conv = nn.Sequential(
                nn.Conv2d(32, 3, kernel_size=3, stride=1, padding=1),
                nn.Sigmoid(),
            )

        def encode(self, x):
            return self.enc4(self.enc3(self.enc2(self.enc1(x))))

        def decode(self, z):
            return self.out_conv(self.dec4(self.dec3(self.dec2(self.dec1(z)))))

        def forward(self, x):
            return self.decode(self.encode(x))

    return FaceAutoEncoder


# --------------------------------------------------------------------------- #
# Model name -> (module, class) mapping. Parameterless constructors.          #
# --------------------------------------------------------------------------- #
ADAPTER_REGISTRY = {
    "kadnet": ("system.evaluation.adapters.kadnet_adapter", "KADNetAdapter"),
    "waveguard": ("system.evaluation.adapters.waveguard_adapter", "WaveGuardModelAdapter"),
    "hidden": ("system.evaluation.adapters.hidden_adapter", "HiDDeNAdapter"),
    "sepmark": ("system.evaluation.adapters.sepmark_adapter", "SepMarkModelAdapter"),
    "lidmark": ("system.evaluation.adapters.lidmark_adapter", "LIDMarkAdapter"),
}

DEFAULT_IMAGE_ROOT = Path("/data1/luxliang/datasets/deepfake_images_extracted/Real")
DEFAULT_OUT = PROJECT_DIR / "system" / "reports" / "regeneration_attack"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI re-generation attack closed-loop")
    p.add_argument("--model", required=True, choices=sorted(ADAPTER_REGISTRY.keys()))
    p.add_argument("--ae-checkpoint", type=Path, required=True,
                   help="train_face_autoencoder.py product (best.pt)")
    p.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    p.add_argument("--num-images", type=int, default=1000)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--ae-img-size", type=int, default=128,
                   help="AE spatial resolution (trainer fixed arch = 128)")
    p.add_argument("--ae-latent-ch", type=int, default=128,
                   help="AE bottleneck channels (trainer default 128; auto-inferred from ckpt if possible)")
    p.add_argument("--flush-every", type=int, default=100,
                   help="periodic CSV/summary flush cadence")
    return p.parse_args()


def list_images(root: Path, limit: int) -> list[Path]:
    imgs = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return imgs[:limit] if limit > 0 else imgs


def read_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add(row["image_id"])
    return done


CSV_FIELDS = ["image_id", "source_path", "acc_clean", "acc_regen",
              "success_clean", "success_regen", "ae_psnr", "ae_ssim", "error"]


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def load_success_threshold() -> tuple[float, str]:
    """Read success_threshold from the evaluation protocol; 0.9 fallback."""
    try:
        from system.evaluation.protocol import load_protocol
        proto = load_protocol()
        thr = float(proto["success_threshold"])
        return thr, "protocol"
    except Exception:
        return 0.9, "fallback_default_protocol_unreadable"


def load_adapter(model: str):
    import importlib
    module_name, class_name = ADAPTER_REGISTRY[model]
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()


def load_ae(ckpt_path: Path, latent_ch: int, device):
    """Re-instantiate the trainer's FaceAutoEncoder and load weights strictly.

    The trainer (train_face_autoencoder.py) saves {"epoch","model":state_dict,
    "optimizer":...}; latent_ch is NOT stored in the checkpoint (it lives in the
    sibling metrics.json), so it is passed in via --ae-latent-ch (default 128,
    the trainer default). Returns (model, hyperparams_dict, state_source_str).
    """
    import torch
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"AE checkpoint not found: {ckpt_path}")

    ckpt = torch.load(str(ckpt_path), map_location="cpu")

    state = None
    if isinstance(ckpt, dict):
        for key in ("model", "model_state_dict", "state_dict", "ae_state_dict", "weights"):
            if key in ckpt and isinstance(ckpt[key], dict):
                state = ckpt[key]
                break
        if state is None and ckpt and all(isinstance(v, torch.Tensor) for v in ckpt.values()):
            state = ckpt  # checkpoint is itself a raw state_dict
    else:
        state = ckpt  # raw state_dict object

    if state is None:
        raise RuntimeError(f"could not locate a state_dict inside {ckpt_path}")

    # If latent_ch wasn't given explicitly, try to infer it from enc4 conv weight
    # shape (out_channels = latent_ch); fall back to the provided value.
    inferred = state.get("enc4.block.0.weight")
    if inferred is not None:
        latent_ch = int(inferred.shape[0])

    FaceAutoEncoder = _build_autoencoder()
    model = FaceAutoEncoder(latent_ch=latent_ch)
    # strict load: any structural mismatch with the training script will raise.
    model.load_state_dict(state, strict=True)
    model.eval().to(device)

    resolved_hp = {
        "arch": "FaceAutoEncoder_stride2_conv",
        "latent_ch": latent_ch,
        "img_size": 128,
    }
    return model, resolved_hp, "trainer_class_match"


def regenerate(ae, wm_uint8_rgb: np.ndarray, ae_img_size: int, device) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Resize wm -> ae_img_size, run AE, resize back to host size.

    Returns (regen_host_uint8, wm_small_uint8, recon_small_uint8):
      - regen_host:  AE reconstruction resized back to the host resolution
                     (the actual attacked image that gets decoded).
      - wm_small:    the AE input (watermarked image at AE resolution).
      - recon_small: the AE's direct output at AE resolution (used to score
                     reconstruction distortion against wm_small).
    """
    import torch
    h, w = wm_uint8_rgb.shape[:2]
    wm_small = np.array(
        Image.fromarray(wm_uint8_rgb).resize((ae_img_size, ae_img_size), Image.BICUBIC)
    )
    x = torch.from_numpy(wm_small.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0).to(device)
    with torch.no_grad():
        y = ae(x)
    recon_small = (y.clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy() * 255.0)
    recon_small = np.clip(np.rint(recon_small), 0, 255).astype(np.uint8)
    regen_host = np.array(
        Image.fromarray(recon_small).resize((w, h), Image.BICUBIC)
    )
    return regen_host, wm_small, recon_small


def summarize(csv_path: Path, threshold: float) -> dict:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]

    def col(name: str) -> np.ndarray:
        return np.array([float(r[name]) for r in rows], dtype=np.float64)

    n = len(rows)
    if n == 0:
        return {"n": 0, "status": "no_valid_rows"}

    acc_clean = col("acc_clean")
    acc_regen = col("acc_regen")
    ae_psnr = col("ae_psnr")
    ae_ssim = col("ae_ssim")
    return {
        "n": n,
        "mean_acc_clean": round(float(acc_clean.mean()), 6),
        "success_rate_clean@0.9": round(float((acc_clean >= threshold).mean()), 6),
        "mean_acc_regen": round(float(acc_regen.mean()), 6),
        "success_rate_regen@0.9": round(float((acc_regen >= threshold).mean()), 6),
        "ae_recon_psnr": round(float(ae_psnr.mean()), 6),
        "ae_recon_ssim": round(float(ae_ssim.mean()), 6),
        "success_threshold": threshold,
    }


def main() -> None:
    args = parse_args()
    # Adapters pick their GPU from this env var; must be set before importing them.
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    import torch
    from system.evaluation.metrics import bit_metrics, image_quality
    from system.evaluation.run_metadata import build_run_metadata

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")

    threshold, threshold_source = load_success_threshold()

    adapter = load_adapter(args.model)
    if not adapter.available:
        sys.exit(f"adapter unavailable: {getattr(adapter, 'blocker', 'unknown')}")
    msg_len = int(adapter.message_length)
    adapter_ckpt = getattr(adapter, "checkpoint", None)
    print(f"adapter={args.model} message_length={msg_len} checkpoint={adapter_ckpt}")

    ae, ae_hp, ae_hp_source = load_ae(args.ae_checkpoint, args.ae_latent_ch, device)
    ae_img_size = int(ae_hp["img_size"])
    print(f"AE loaded: hyperparams={ae_hp} source={ae_hp_source} img_size={ae_img_size}")

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "per_image.csv"
    summary_path = out_dir / "summary.json"
    progress_path = out_dir / "progress.json"

    images = list_images(args.image_root, args.num_images)
    if not images:
        sys.exit(f"no images found under {args.image_root}")
    done = read_done(csv_path)

    rng = np.random.default_rng(args.seed)
    pending: list[dict] = []
    processed = 0
    t0 = time.time()

    for img_path in images:
        image_id = img_path.stem
        if image_id in done:
            continue

        # Per-image message: deterministic given (seed, image order).
        msg = rng.integers(0, 2, size=msg_len).astype(np.uint8)

        try:
            host = np.array(Image.open(img_path).convert("RGB"))
            wm = adapter.encode(host, msg).image
            if wm.dtype != np.uint8:
                wm = np.clip(np.rint(wm), 0, 255).astype(np.uint8)

            # Control: decode the clean watermarked image (no manipulation).
            bits0 = np.asarray(adapter.decode(wm).bits, dtype=np.uint8).reshape(-1)
            m_clean = bit_metrics(msg, bits0, success_threshold=threshold)

            # Attack: regenerate, then decode the *actually regenerated* image.
            regen, wm_small, recon_small = regenerate(ae, wm, ae_img_size, device)
            bits1 = np.asarray(adapter.decode(regen).bits, dtype=np.uint8).reshape(-1)
            m_regen = bit_metrics(msg, bits1, success_threshold=threshold)

            # AE distortion at AE resolution: AE input (wm_small) vs AE output (recon_small).
            q = image_quality(wm_small, recon_small)

            pending.append({
                "image_id": image_id,
                "source_path": str(img_path),
                "acc_clean": f"{m_clean['accuracy']:.6f}",
                "acc_regen": f"{m_regen['accuracy']:.6f}",
                "success_clean": "1" if m_clean["success"] else "0",
                "success_regen": "1" if m_regen["success"] else "0",
                "ae_psnr": f"{q['psnr']:.6f}",
                "ae_ssim": f"{q['ssim']:.6f}",
                "error": "",
            })
        except Exception as exc:  # noqa: BLE001
            pending.append({
                "image_id": image_id,
                "source_path": str(img_path),
                "acc_clean": "", "acc_regen": "",
                "success_clean": "0", "success_regen": "0",
                "ae_psnr": "", "ae_ssim": "",
                "error": repr(exc),
            })

        processed += 1
        if pending and processed % max(1, args.flush_every) == 0:
            append_rows(csv_path, pending)
            pending = []
            elapsed = time.time() - t0
            partial = summarize(csv_path, threshold)
            progress_path.write_text(json.dumps({
                "processed": processed,
                "total": len(images),
                "elapsed_s": round(elapsed),
                "updated_at": int(time.time()),
                "partial_summary": partial,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[{processed}/{len(images)}] "
                  f"acc_clean={partial.get('mean_acc_clean')} "
                  f"acc_regen={partial.get('mean_acc_regen')}")

    if pending:
        append_rows(csv_path, pending)

    agg = summarize(csv_path, threshold)
    summary = {
        "model": args.model,
        "adapter_name": getattr(adapter, "name", args.model),
        "message_length": msg_len,
        **agg,
        "ae_checkpoint": str(args.ae_checkpoint),
        "ae_hyperparams": ae_hp,
        "ae_hyperparams_source": ae_hp_source,
        "ae_img_size": ae_img_size,
        "manipulation_type": "self_trained_autoencoder_regeneration",
        "evidence_level": "self_trained_generative_regeneration",
        "image_root": str(args.image_root),
        "requested_images": args.num_images,
        "success_threshold": threshold,
        "success_threshold_source": threshold_source,
        "seed": args.seed,
        "device": str(device),
        "adapter_checkpoint": str(adapter_ckpt) if adapter_ckpt else None,
        "generated_at": int(time.time()),
        "notes": (
            "acc_regen is decoded on the AE-regenerated image (real measured "
            "robustness, no leakage). acc_clean is the control on the unmanipulated "
            "watermarked image. ae_recon_psnr/ssim compare the AE input vs its "
            "reconstruction at AE resolution."
        ),
    }
    try:
        summary["run_metadata"] = build_run_metadata(
            model=args.model,
            checkpoint=args.ae_checkpoint if args.ae_checkpoint.is_file() else None,
            seed=args.seed,
            command=sys.argv,
        )
    except Exception as exc:  # noqa: BLE001
        summary["run_metadata_error"] = repr(exc)

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    progress_path.write_text(json.dumps({
        "processed": processed,
        "total": len(images),
        "status": "complete",
        "updated_at": int(time.time()),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in {"run_metadata"}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
