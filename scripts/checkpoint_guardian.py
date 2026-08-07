#!/usr/bin/env python3
"""Copy LIDMark checkpoints into seed-specific directories as training advances."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.runtime import MODEL_SOURCE_ROOT, WEIGHT_ROOT  # noqa: E402


DEFAULT_RUNS = MODEL_SOURCE_ROOT / "runs" / "lidmark"
DEFAULT_CHECKPOINTS = (
    MODEL_SOURCE_ROOT / "LIDMark" / "weights" / "128_152" / "checkpoints_distortions"
)
DEFAULT_SEED_CHECKPOINT_ROOT = WEIGHT_ROOT / "lidmark" / "seed_checkpoints"
DEFAULT_SEEDS = (20260603, 20260604, 20260605)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINTS)
    parser.add_argument("--seed-checkpoint-root", type=Path, default=DEFAULT_SEED_CHECKPOINT_ROOT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--total-epochs", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    return parser.parse_args()


def latest_epoch_in_log(runs_dir: Path, seed: int, total_epochs: int) -> int:
    log = runs_dir / f"train_seed{seed}.log"
    if not log.is_file():
        return 0
    epochs: list[int] = []
    marker = f"/{total_epochs}"
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "Epoch " not in line or marker not in line:
            continue
        try:
            epochs.append(int(line.split("Epoch ", 1)[1].split("/", 1)[0]))
        except (IndexError, ValueError):
            continue
    return max(epochs, default=0)


def main() -> None:
    args = parse_args()
    if args.total_epochs <= 0:
        raise SystemExit("--total-epochs must be positive")
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")

    runs_dir = args.runs_dir.expanduser().resolve()
    checkpoint_dir = args.checkpoint_dir.expanduser().resolve()
    seed_checkpoint_root = args.seed_checkpoint_root.expanduser().resolve()
    seed_dirs = {
        seed: seed_checkpoint_root / f"s{index}"
        for index, seed in enumerate(args.seeds, start=1)
    }
    for directory in seed_dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    seen: dict[int, set[int]] = {seed: set() for seed in seed_dirs}
    print(f"Checkpoint guardian started; source={checkpoint_dir}")
    while True:
        for index, (seed, destination_dir) in enumerate(seed_dirs.items(), start=1):
            epoch = latest_epoch_in_log(runs_dir, seed, args.total_epochs)
            if epoch <= 0 or epoch in seen[seed]:
                continue
            source = checkpoint_dir / f"checkpoint_epoch_{epoch}.pth"
            destination = destination_dir / source.name
            if destination.exists():
                seen[seed].add(epoch)
                continue
            if source.is_file():
                shutil.copy2(source, destination)
                print(f"[s{index}] Saved epoch {epoch} -> {destination}")
                seen[seed].add(epoch)

        if all(
            latest_epoch_in_log(runs_dir, seed, args.total_epochs) >= args.total_epochs
            for seed in seed_dirs
        ):
            print("All seeds completed training.")
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
