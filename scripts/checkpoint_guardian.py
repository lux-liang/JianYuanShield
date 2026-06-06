#!/usr/bin/env python3
"""Track which seed owns which checkpoint epoch by monitoring training logs.
Copies new checkpoints to seed-specific dirs immediately after writing."""
from __future__ import annotations
import shutil, time
from pathlib import Path

RUNS  = Path('/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark')
CKPT  = Path('/data1/luxliang/work/vpsg_competition_candidates/LIDMark/weights/128_152/checkpoints_distortions')
SEEDS = {20260603: RUNS/'seed_checkpoints/s1', 
         20260604: RUNS/'seed_checkpoints/s2',
         20260605: RUNS/'seed_checkpoints/s3'}

for d in SEEDS.values():
    d.mkdir(parents=True, exist_ok=True)

def latest_epoch_in_log(seed: int) -> int:
    log = RUNS / f'train_seed{seed}.log'
    epochs = []
    for line in log.read_text(errors='ignore').splitlines():
        if f'Epoch ' in line and '/100' in line:
            try:
                e = int(line.split('Epoch ')[1].split('/')[0])
                epochs.append(e)
            except:
                pass
    return max(epochs) if epochs else 0

seen: dict[int, set[int]] = {s: set() for s in SEEDS}

print('Checkpoint guardian started')
while True:
    for seed, dst_dir in SEEDS.items():
        epoch = latest_epoch_in_log(seed)
        if epoch > 0 and epoch not in seen[seed]:
            src = CKPT / f'checkpoint_epoch_{epoch}.pth'
            dst = dst_dir / f'checkpoint_epoch_{epoch}.pth'
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
                print(f'[s{list(SEEDS).index(seed)+1}] Saved epoch {epoch} → {dst}')
            seen[seed].add(epoch)
    
    # Check if all seeds done
    if all(latest_epoch_in_log(s) >= 100 for s in SEEDS):
        print('All seeds completed training!')
        break
    time.sleep(30)
