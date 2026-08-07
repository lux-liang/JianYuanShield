#!/usr/bin/env python3
"""Validate paths, update a KAD-Net training config, and launch training."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.runtime import DATA_ROOT, MODEL_SOURCE_ROOT, WEIGHT_ROOT  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpu_id", nargs="?", default="4")
    parser.add_argument("--model-dir", type=Path, default=MODEL_SOURCE_ROOT / "KAD-Net")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dataset-root", type=Path, default=DATA_ROOT / "celeba_hq_kadnet")
    parser.add_argument("--run-dir", type=Path, default=MODEL_SOURCE_ROOT / "runs" / "kadnet")
    parser.add_argument("--result-root", type=Path, default=WEIGHT_ROOT / "kadnet" / "results")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--branch-type", default="ST")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print paths without editing or launching.")
    return parser.parse_args()


def patch_config(
    config_path: Path,
    *,
    dataset_root: Path,
    epochs: int,
    batch_size: int,
    branch_type: str,
) -> None:
    import yaml

    with config_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    cfg["dataset_path"] = str(dataset_root)
    cfg["image_size"] = 128
    cfg["epoch_number"] = epochs
    cfg["batch_size"] = batch_size
    cfg["branch_type"] = branch_type
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"KAD-Net config patched: {config_path}")


def check_data_ready(model_dir: Path, dataset_root: Path) -> bool:
    ready = True
    for split in ("train_128", "val_128"):
        directory = dataset_root / split
        if not directory.is_dir() or not any(directory.glob("*.png")):
            print(f"ERROR: dataset split is not ready: {directory}", file=sys.stderr)
            ready = False
    annotation = model_dir / "network" / "noise_layers" / "stargan" / "CelebAMask-HQ-attribute-anno.txt"
    if not annotation.is_file():
        print(f"ERROR: required attribute annotation is missing: {annotation}", file=sys.stderr)
        ready = False
    return ready


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir.expanduser().resolve()
    config_path = (args.config or model_dir / "cfg" / "train_KAD_Net.yaml").expanduser().resolve()
    dataset_root = args.dataset_root.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    result_root = args.result_root.expanduser().resolve()

    if args.epochs <= 0 or args.batch_size <= 0:
        raise SystemExit("--epochs and --batch-size must be positive")
    if not model_dir.is_dir():
        raise SystemExit(f"KAD-Net source directory not found: {model_dir}")
    if not config_path.is_file():
        raise SystemExit(f"KAD-Net config not found: {config_path}")
    if not check_data_ready(model_dir, dataset_root):
        raise SystemExit("Dataset is incomplete; run prep_celeba_hq.py first.")

    command = [sys.executable, "train.py"]
    log_file = run_dir / f"train_{args.branch_type}.log"
    if args.dry_run:
        print(
            f"Validated KAD-Net launch: cwd={model_dir}, log={log_file}, "
            f"result_root={result_root}, command={' '.join(command)}"
        )
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)
    patch_config(
        config_path,
        dataset_root=dataset_root,
        epochs=args.epochs,
        batch_size=args.batch_size,
        branch_type=args.branch_type,
    )
    env = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": args.gpu_id,
        "KADNET_CFG": str(config_path),
        "KADNET_RESULTS": str(result_root),
    }
    print(f"Launching KAD-Net (branch={args.branch_type}, gpu={args.gpu_id}): {' '.join(command)}")
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
    print(f"KAD-Net training started. PID={process.pid}")
    print(f"Monitor: tail -f {log_file}")


if __name__ == "__main__":
    main()
