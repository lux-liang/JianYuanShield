#!/usr/bin/env python3
"""Update LIDMark config paths and launch training on specified GPUs."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml


LIDMARK_DIR = Path('/data1/luxliang/work/vpsg_competition_candidates/LIDMark')
LOG_DIR = Path('/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark')
CFG_PATH = LIDMARK_DIR / 'configurations/train_distortions.yaml'

IMG_ROOT = '/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/image/celeba-hq_128'
WM_ROOT = '/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/watermark_152/celeba-hq'


def patch_config(gpu_ids: str = '2, 3', seed: int = 20260603) -> None:
    with open(CFG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg['img_size'] = 128
    cfg['img_path'] = IMG_ROOT
    cfg['wm_path'] = WM_ROOT
    cfg['gpu_ids'] = gpu_ids
    cfg['seed'] = seed
    cfg['epochs'] = 100
    cfg['batch_size'] = 32
    cfg['validation'] = {'enable': True, 'save_count': 16}
    cfg['resume'] = {'enable': False, 'epoch': 0}
    with open(CFG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print(f'Config patched: img_size=128, gpu_ids={gpu_ids}, seed={seed}')


def check_data_ready() -> bool:
    for split in ['train', 'val', 'test']:
        d = Path(IMG_ROOT) / split
        if not d.is_dir() or not any(d.glob('*.jpg')):
            print(f'ERROR: {d} not ready')
            return False
    return True


def main() -> None:
    gpu_ids = sys.argv[1] if len(sys.argv) > 1 else '2, 3'
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260603

    if not check_data_ready():
        sys.exit('Run prep_celeba_hq.py first.')

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f'train_seed{seed}.log'

    patch_config(gpu_ids=gpu_ids, seed=seed)

    cmd = [sys.executable, 'main.py', 'train_distortions', '--res', str(128)]
    print(f'Launching: {" ".join(cmd)}')
    print(f'Log: {log_file}')

    with open(log_file, 'w') as log:
        proc = subprocess.Popen(
            cmd, cwd=str(LIDMARK_DIR),
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True
        )
    print(f'LIDMark training started. PID={proc.pid}')
    print(f'Monitor: tail -f {log_file}')


if __name__ == '__main__':
    main()
