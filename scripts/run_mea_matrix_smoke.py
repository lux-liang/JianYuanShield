#!/usr/bin/env python3
"""Run MEA 5x5 double-embedding matrix smoke (16 images per cell)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from system.evaluation.adapters import get_available_adapters, evaluate_double_embedding
from system.evaluation.runtime import PROJECT_ROOT
import numpy as np
from PIL import Image

SMOKE_N   = 16
REPORT    = PROJECT_ROOT / 'system/reports/multi_embedding_matrix'
IMG_ROOT  = PROJECT_ROOT / 'datasets/lfw_full_upload/unknown'


def load_images(n: int) -> list[np.ndarray]:
    paths = sorted(IMG_ROOT.glob('*.jpg'))[:n]
    imgs  = []
    for p in paths:
        arr = np.array(Image.open(p).convert('RGB'))
        imgs.append(arr)
    return imgs


def random_bits(n: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, n, dtype=np.uint8)


def run_cell(src_name: str, src_cls, atk_name: str, atk_cls,
             images: list[np.ndarray]) -> dict:
    try:
        src = src_cls()
        atk = atk_cls()
        results = []
        for i, img in enumerate(images):
            m1 = random_bits(src.message_length, seed=i)
            m2 = random_bits(atk.message_length, seed=i + 1000)
            try:
                r = evaluate_double_embedding(img, src, atk, m1, m2)
                results.append({
                    'first_acc':  r.first_message_metrics.get('accuracy', 0),
                    'second_acc': r.second_message_metrics.get('accuracy', 0),
                    'psnr1':      r.first_embedding_quality.get('psnr', 0),
                    'psnr2':      r.second_embedding_quality_vs_original.get('psnr', 0),
                })
            except Exception as e:
                results.append({'error': str(e)})
        ok = [r for r in results if 'error' not in r]
        return {
            'source':          src_name,
            'attacker':        atk_name,
            'status':          'complete' if ok else 'failed',
            'n_ok':            len(ok),
            'mean_first_acc':  round(np.mean([r['first_acc']  for r in ok]), 4) if ok else None,
            'mean_second_acc': round(np.mean([r['second_acc'] for r in ok]), 4) if ok else None,
            'mean_psnr1':      round(np.mean([r['psnr1']      for r in ok]), 2) if ok else None,
            'mean_psnr2':      round(np.mean([r['psnr2']      for r in ok]), 2) if ok else None,
        }
    except Exception as e:
        return {'source': src_name, 'attacker': atk_name, 'status': 'error', 'error': str(e)}


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    available = get_available_adapters()
    print(f'Available adapters: {list(available.keys())}')
    images = load_images(SMOKE_N)
    print(f'Loaded {len(images)} images')

    cells = []
    for src_name, src_cls in available.items():
        for atk_name, atk_cls in available.items():
            print(f'Running {src_name} -> {atk_name} ...', end=' ', flush=True)
            t0 = time.time()
            cell = run_cell(src_name, src_cls, atk_name, atk_cls, images)
            cell['elapsed_s'] = round(time.time() - t0, 1)
            cells.append(cell)
            print(f"first_acc={cell.get('mean_first_acc','?')} second_acc={cell.get('mean_second_acc','?')} [{cell['elapsed_s']}s]")

    report = {
        'schema_version': 'mea-matrix-smoke.v1',
        'generated_at':   int(time.time()),
        'smoke_n':        SMOKE_N,
        'adapters':       list(available.keys()),
        'cells':          cells,
        'status':         'complete',
    }
    out = REPORT / 'smoke_results.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'\nSaved to {out}')
    for c in cells:
        mark = '✅' if c.get('status') == 'complete' else '❌'
        print(f"  {mark} {c['source']:12} -> {c.get('attacker','?'):12} | first={c.get('mean_first_acc','?')} second={c.get('mean_second_acc','?')}")


if __name__ == '__main__':
    main()
