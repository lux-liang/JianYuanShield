#!/usr/bin/env python3
"""Monitor LIDMark training completion and auto-run LFW benchmark for each seed."""
from __future__ import annotations

import json, os, subprocess, sys, time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DATA1   = Path('/data1/luxliang/work/vpsg_competition_candidates')
LIDMARK = DATA1 / 'LIDMark'
RUNS    = DATA1 / 'runs/lidmark'
REPORTS = DATA1 / 'system/reports'

SEEDS = [20260603, 20260604, 20260605]
TOTAL_EPOCHS = 100
POLL_SEC = 60


def best_checkpoint(seed: int) -> Path | None:
    """Return path to best checkpoint from seed-specific guardian directory."""
    idx = SEEDS.index(seed) + 1
    seed_dir = RUNS / f'seed_checkpoints/s{idx}'
    if not seed_dir.exists():
        return None
    ckpts = sorted(seed_dir.glob('checkpoint_epoch_*.pth'),
                   key=lambda p: int(p.stem.split('_')[-1]))
    return ckpts[-1] if ckpts else None


def is_training_done(seed: int) -> bool:
    log = RUNS / f'train_seed{seed}.log'
    if not log.exists():
        return False
    content = log.read_text(errors='ignore')
    return f'Epoch {TOTAL_EPOCHS}/{TOTAL_EPOCHS}' in content


def run_lfw_benchmark(seed: int, ckpt: Path) -> None:
    """Run LIDMark LFW eval with the best checkpoint via env override."""
    report_dir = RUNS / f'lidmark_lfw_eval_seed{seed}'
    report_dir.mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        'PYTHONPATH': str(PROJECT),
        'JYS_LIDMARK_CHECKPOINT': str(ckpt),
        'JYS_LIDMARK_REPORT_DIR': str(report_dir),
    }
    cmd = [sys.executable, str(PROJECT / 'system/scripts/run_lidmark_lfw_eval.py')]
    log_path = RUNS / f'benchmark_seed{seed}.log'
    print(f'[{seed}] Starting LFW benchmark → {report_dir}')
    with open(log_path, 'w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    print(f'[{seed}] Benchmark PID={proc.pid}, log={log_path}')
    (report_dir / 'status.json').write_text(json.dumps({
        'seed': seed, 'checkpoint': str(ckpt), 'pid': proc.pid,
        'started_at': int(time.time()), 'status': 'running'
    }, indent=2))


def run_multi_seed_stats() -> None:
    """Run statistical analysis across all seed benchmarks."""
    cmd = [sys.executable, str(PROJECT / 'system/scripts/run_statistical_analysis.py')]
    log = RUNS / 'multi_seed_stats.log'
    print('Running multi-seed statistical analysis...')
    with open(log, 'w') as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                       env={**os.environ, 'PYTHONPATH': str(PROJECT)})
    print(f'Stats done → {log}')


def main() -> None:
    print(f'Auto-benchmark monitor started. Watching {len(SEEDS)} seeds...')
    benchmarked: set[int] = set()
    all_done_time: float | None = None

    while True:
        for seed in SEEDS:
            if seed in benchmarked:
                continue
            if is_training_done(seed):
                ckpt = best_checkpoint(seed)
                if ckpt:
                    print(f'[{seed}] Training DONE. Best ckpt: {ckpt}')
                    run_lfw_benchmark(seed, ckpt)
                    benchmarked.add(seed)
                else:
                    print(f'[{seed}] Training done but no checkpoint found yet...')

        if len(benchmarked) == len(SEEDS) and all_done_time is None:
            all_done_time = time.time()
            print('All seeds benchmarked! Waiting 5min for benchmark procs...')

        if all_done_time and time.time() - all_done_time > 300:
            run_multi_seed_stats()
            print('All done. Exiting monitor.')
            break

        remaining = [s for s in SEEDS if s not in benchmarked]
        if remaining:
            # Show progress for remaining seeds
            for seed in remaining:
                log = RUNS / f'train_seed{seed}.log'
                if log.exists():
                    last = [l for l in log.read_text(errors='ignore').splitlines()
                            if 'Epoch' in l and '/100' in l]
                    ep = last[-1].split('Epoch ')[1].split('/')[0] if last else '?'
                    print(f'  seed {seed}: epoch {ep}/100 ...')
        time.sleep(POLL_SEC)


if __name__ == '__main__':
    main()
