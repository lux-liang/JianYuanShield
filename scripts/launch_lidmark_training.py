#!/usr/bin/env python3
"""Validate paths, update a LIDMark training config, and launch training."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.runtime import DATA_ROOT, MODEL_SOURCE_ROOT  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpu_ids", nargs="?", default="2, 3")
    parser.add_argument("seed", nargs="?", type=int, default=20260603)
    parser.add_argument("--model-dir", type=Path, default=MODEL_SOURCE_ROOT / "LIDMark")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-dir", type=Path, default=MODEL_SOURCE_ROOT / "runs" / "lidmark")
    parser.add_argument(
        "--image-root",
        type=Path,
        default=DATA_ROOT / "lidmark_official" / "image" / "celeba-hq_128",
    )
    parser.add_argument(
        "--watermark-root",
        type=Path,
        default=DATA_ROOT / "lidmark_official" / "watermark_152" / "celeba-hq",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print paths without editing or launching.")
    return parser.parse_args()


def patch_config(
    config_path: Path,
    *,
    image_root: Path,
    watermark_root: Path,
    gpu_ids: str,
    seed: int,
    epochs: int,
    batch_size: int,
) -> None:
    import yaml

    with config_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    cfg["img_size"] = 128
    cfg["img_path"] = str(image_root)
    cfg["wm_path"] = str(watermark_root)
    cfg["gpu_ids"] = gpu_ids
    cfg["seed"] = seed
    cfg["epochs"] = epochs
    cfg["batch_size"] = batch_size
    cfg["validation"] = {"enable": True, "save_count": 16}
    cfg["resume"] = {"enable": False, "epoch": 0}
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"Config patched: {config_path}")


def check_data_ready(image_root: Path, watermark_root: Path) -> bool:
    ready = True
    for split in ("train", "val", "test"):
        image_dir = image_root / split
        watermark_dir = watermark_root / "128" / split
        if not image_dir.is_dir() or not any(image_dir.glob("*.jpg")):
            print(f"ERROR: image split is not ready: {image_dir}", file=sys.stderr)
            ready = False
        if not watermark_dir.is_dir() or not any(watermark_dir.glob("*.npy")):
            print(f"ERROR: watermark split is not ready: {watermark_dir}", file=sys.stderr)
            ready = False
    return ready


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir.expanduser().resolve()
    config_path = (args.config or model_dir / "configurations" / "train_distortions.yaml").expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    image_root = args.image_root.expanduser().resolve()
    watermark_root = args.watermark_root.expanduser().resolve()

    if args.epochs <= 0 or args.batch_size <= 0:
        raise SystemExit("--epochs and --batch-size must be positive")
    if not model_dir.is_dir():
        raise SystemExit(f"LIDMark source directory not found: {model_dir}")
    if not config_path.is_file():
        raise SystemExit(f"LIDMark config not found: {config_path}")
    if not check_data_ready(image_root, watermark_root):
        raise SystemExit("Dataset is incomplete; run prep_celeba_hq.py first.")

    command = [sys.executable, "main.py", "train_distortions", "--res", "128"]
    log_file = run_dir / f"train_seed{args.seed}.log"
    if args.dry_run:
        print(f"Validated LIDMark launch: cwd={model_dir}, log={log_file}, command={' '.join(command)}")
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    patch_config(
        config_path,
        image_root=image_root,
        watermark_root=watermark_root,
        gpu_ids=args.gpu_ids,
        seed=args.seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    env = {**os.environ, "JYS_LIDMARK_CONFIG": str(config_path)}
    print(f"Launching: {' '.join(command)}")
    print(f"Log: {log_file}")
    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=model_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    print(f"LIDMark training started. PID={process.pid}")
    print(f"Monitor: tail -f {log_file}")


if __name__ == "__main__":
    main()
