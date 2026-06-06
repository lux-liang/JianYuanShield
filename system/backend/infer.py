from __future__ import annotations

import base64
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import ASSETS, REPORTS
from .evidence import sha256_file
from .model_adapters import get_adapter
from .demo import (
    simulate_lidmark_embed, apply_attack, make_heatmap,
    metrics as sim_metrics, load_rgb, save_rgb,
)


def _pil_to_rgb(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert('RGB'))


def _rgb_to_b64(arr: np.ndarray, fmt: str = 'PNG') -> str:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def _save_and_url(arr: np.ndarray, path: Path) -> str:
    Image.fromarray(arr.astype(np.uint8)).save(path)
    rel = path.relative_to(ASSETS.parent)
    return f'/artifacts/{rel}'


def run_single_infer(
    image_bytes: bytes,
    model: str = 'SepMark',
    attack: str = 'clean',
    return_b64: bool = True,
) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:12]
    out_dir = ASSETS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    original_rgb = _pil_to_rgb(image_bytes)
    # Resize to reasonable size for display
    h, w = original_rgb.shape[:2]
    if max(h, w) > 1024:
        scale = 1024 / max(h, w)
        original_rgb = np.array(Image.fromarray(original_rgb).resize(
            (int(w * scale), int(h * scale)), Image.BICUBIC))

    adapter = get_adapter(model)
    mode = 'real_checkpoint' if adapter else 'demo_simulation'

    if adapter:
        result = adapter.run(original_rgb, attack)
        imgs = result.pop('images')
        original_u8   = imgs['original']
        watermarked_u8 = imgs['watermarked']
        attacked_u8   = imgs['attacked']
        heatmap_u8    = imgs['heatmap']
        diff_u8       = imgs['diff']
        metrics_out = {k: v for k, v in result.items()
                       if k not in ('model', 'checkpoint', 'attack')}
    else:
        # simulation fallback
        watermarked_u8, residual = simulate_lidmark_embed(original_rgb)
        attacked_u8 = apply_attack(watermarked_u8, attack)
        heatmap_u8  = make_heatmap(watermarked_u8, attacked_u8)
        atk_res = np.clip(
            np.abs(attacked_u8.astype(np.int16) - watermarked_u8.astype(np.int16)) * 12,
            0, 255).astype(np.uint8)
        original_u8 = original_rgb
        diff_u8 = atk_res
        metrics_out = sim_metrics(watermarked_u8, attacked_u8, atk_res)

    paths = {
        'original':    save_rgb(original_u8,    out_dir / 'original.png'),
        'watermarked': save_rgb(watermarked_u8, out_dir / 'watermarked.png'),
        'attacked':    save_rgb(attacked_u8,    out_dir / 'attacked.png'),
        'heatmap':     save_rgb(heatmap_u8,     out_dir / 'heatmap.png'),
        'diff':        save_rgb(diff_u8,         out_dir / 'diff.png'),
    }

    artifacts: dict[str, Any] = {
        k: f'/artifacts/{task_id}/{p.name}' for k, p in paths.items()
    }
    if return_b64:
        artifacts_b64 = {k: _rgb_to_b64(v) for k, v in {
            'original': original_u8, 'watermarked': watermarked_u8,
            'attacked': attacked_u8, 'heatmap': heatmap_u8, 'diff': diff_u8,
        }.items()}
    else:
        artifacts_b64 = {}

    payload = {
        'schema_version': 'infer-single.v1',
        'task_id': task_id,
        'created_at': int(time.time()),
        'mode': mode,
        'model': model,
        'attack': attack,
        'metrics': metrics_out,
        'artifacts': artifacts,
        'artifacts_b64': artifacts_b64,
        'evidence': {
            'sha256': {k: sha256_file(v) for k, v in paths.items()},
        },
        'compliance': {
            'watermark_detected': metrics_out.get('success', metrics_out.get('bit_accuracy_c', 0) >= 0.9),
            'regulation': '《人工智能生成合成内容标识办法》第五条（隐式标识）',
            'verdict': 'compliant' if metrics_out.get('success', False) else 'degraded',
        },
    }
    (REPORTS / f'{task_id}.json').write_text(
        json.dumps(payload, indent=2, default=str), encoding='utf-8')
    return payload


def run_compliance_batch(
    images_bytes: list[tuple[str, bytes]],
    model: str = 'SepMark',
) -> dict[str, Any]:
    """Check a batch of images for watermark compliance."""
    adapter = get_adapter(model)
    results = []
    for filename, data in images_bytes:
        try:
            rgb = _pil_to_rgb(data)
            if adapter:
                r = adapter.run(rgb, 'clean')
                acc = r.get('bit_accuracy_c') or r.get('bit_accuracy_detector') or 0
                success = r.get('success', False)
            else:
                # Heuristic simulation: check for embedded watermark signature
                # Without real model, classify based on image statistics
                gray = np.mean(rgb, axis=2)
                entropy = float(-np.sum(
                    np.histogram(gray.flatten(), bins=256, density=True)[0]
                    * np.log2(np.histogram(gray.flatten(), bins=256, density=True)[0] + 1e-9)
                ))
                acc = 0.0
                success = False

            if success:
                status = 'watermark_verified'
                label = '✅ 合规水印已验证'
            elif acc > 0.7:
                status = 'watermark_degraded'
                label = '⚠️ 水印降级（攻击后残留）'
            else:
                status = 'no_watermark'
                label = '❌ 未检测到合规隐式水印'

            results.append({
                'filename': filename,
                'status': status,
                'label': label,
                'bit_accuracy': round(float(acc), 4) if acc else None,
                'error': None,
            })
        except Exception as exc:
            results.append({
                'filename': filename,
                'status': 'error',
                'label': f'处理失败：{exc}',
                'bit_accuracy': None,
                'error': str(exc),
            })

    compliant = sum(1 for r in results if r['status'] == 'watermark_verified')
    degraded  = sum(1 for r in results if r['status'] == 'watermark_degraded')
    no_wm     = sum(1 for r in results if r['status'] == 'no_watermark')

    return {
        'schema_version': 'compliance-batch.v1',
        'generated_at': int(time.time()),
        'model': model,
        'mode': 'real_checkpoint' if adapter else 'demo_simulation',
        'total': len(results),
        'compliant': compliant,
        'degraded': degraded,
        'no_watermark': no_wm,
        'compliance_rate': round(compliant / len(results), 4) if results else 0,
        'regulation': '《人工智能生成合成内容标识办法》',
        'results': results,
    }
