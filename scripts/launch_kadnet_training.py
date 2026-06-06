#!/usr/bin/env python3
"""Fix KAD-Net hardcoded paths and launch training."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml


KADNET_DIR = Path('/data1/luxliang/work/vpsg_competition_candidates/KAD-Net')
LOG_DIR = Path('/data1/luxliang/work/vpsg_competition_candidates/runs/kadnet')
CFG_PATH = KADNET_DIR / 'cfg/train_KAD_Net.yaml'
DATASET_PATH = '/data1/luxliang/work/vpsg_competition_candidates/datasets/celeba_hq_kadnet'


def patch_config() -> None:
    with open(CFG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg['dataset_path'] = DATASET_PATH
    cfg['image_size'] = 128
    cfg['epoch_number'] = 100
    cfg['batch_size'] = 16
    cfg['branch_type'] = 'ST'  # Start with ST (robust/sensitive tracer)
    with open(CFG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    print(f'KAD-Net config patched. dataset_path={DATASET_PATH}')


def check_data_ready() -> bool:
    for split in ['train_128', 'val_128']:
        d = Path(DATASET_PATH) / split
        if not d.is_dir() or not any(d.glob('*.png')):
            print(f'ERROR: {d} not ready. Run prep_celeba_hq.py first.')
            return False
    anno = KADNET_DIR / 'network/noise_layers/stargan/CelebAMask-HQ-attribute-anno.txt'
    if not anno.exists():
        print(f'WARNING: Attribute anno missing: {anno}')
    return True


def main() -> None:
    gpu_id = sys.argv[1] if len(sys.argv) > 1 else '4'
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / 'train_ST.log'

    if not check_data_ready():
        sys.exit(1)

    patch_config()

    env = os.environ.copy()
    env['CUDA_VISIBLE_DEVICES'] = gpu_id
    env['KADNET_CFG'] = str(CFG_PATH)
    env['KADNET_RESULTS'] = str(LOG_DIR / 'results')

    cmd = [sys.executable, 'train.py']
    print(f'Launching KAD-Net (branch=ST, gpu={gpu_id}): {" ".join(cmd)}')
    print(f'Log: {log_file}')

    with open(log_file, 'w') as log:
        proc = subprocess.Popen(
            cmd, cwd=str(KADNET_DIR),
            stdout=log, stderr=subprocess.STDOUT,
            env=env, start_new_session=True
        )
    print(f'KAD-Net training started. PID={proc.pid}')
    print(f'Monitor: tail -f {log_file}')


if __name__ == '__main__':
    main()
