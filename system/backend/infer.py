from __future__ import annotations

import base64
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from .config import ASSETS, REPORTS
from .evidence import sha256_file
from .logging_config import logger
from .model_adapters import get_adapter
from .demo import (
    simulate_lidmark_embed, apply_attack, make_heatmap,
    metrics as sim_metrics, load_rgb, save_rgb,
)

# ── 上传安全校验常量 ────────────────────────────────────────────────────────────
# 单张图片字节上限（5 MB）；批量端点张数上限；像素与解码格式白名单
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_BATCH_FILES = 64
MAX_IMAGE_PIXELS = 6000 * 6000  # 防解压炸弹（decompression bomb）
ALLOWED_PIL_FORMATS = {'PNG', 'JPEG'}  # 仅允许 png/jpeg


def validate_upload_bytes(data: bytes, filename: str | None = None) -> np.ndarray:
    """校验单个上传图片：体积上限、可解码、格式白名单(png/jpeg)、像素上限。

    校验失败抛 HTTPException（413/400，中文文案），由全局异常处理器序列化为 error_payload。
    成功返回 RGB ndarray。
    """
    if data is None or len(data) == 0:
        raise HTTPException(status_code=400, detail='上传内容为空，请提交有效的图片文件')
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f'图片体积超过上限（{MAX_UPLOAD_BYTES // (1024 * 1024)} MB），请压缩后重试',
        )
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or '').upper()
            width, height = probe.size
            if fmt not in ALLOWED_PIL_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail='仅支持 PNG / JPEG 格式的图片上传',
                )
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=413,
                    detail='图片分辨率过大，请使用更小尺寸的图片',
                )
            probe.load()
            return np.array(probe.convert('RGB'))
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        # Pillow 解码失败兜底：不回显底层异常，返回通用中文文案
        raise HTTPException(status_code=400, detail='图片解码失败，请确认文件为有效的 PNG / JPEG')


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
    # 安全：先做上传校验（体积/格式/像素/可解码），失败抛 HTTPException
    original_rgb = validate_upload_bytes(image_bytes)

    task_id = uuid.uuid4().hex[:12]
    out_dir = ASSETS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

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
    # 安全：批量张数上限
    if not images_bytes:
        raise HTTPException(status_code=400, detail='未收到任何图片，请至少上传一张待检图片')
    if len(images_bytes) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f'单次批量检测最多 {MAX_BATCH_FILES} 张图片，请分批提交',
        )

    adapter = get_adapter(model)
    # 合规结论必须有真实模型支撑：无模型时不再用图像熵“伪装检测”，
    # 而是返回 503 明确告知调用方结论无效（避免无模型时界面照常出报告）。
    if adapter is None:
        logger.warning('compliance batch requested but adapter unavailable model=%s', model)
        raise HTTPException(
            status_code=503,
            detail='合规检测模型当前不可用（adapter_unavailable），无法给出有效的合规结论，请稍后重试或联系管理员',
        )

    results = []
    for filename, data in images_bytes:
        try:
            # 安全：逐张校验体积/格式/像素/可解码
            rgb = validate_upload_bytes(data, filename)
            r = adapter.run(rgb, 'clean')
            acc = r.get('bit_accuracy_c') or r.get('bit_accuracy_detector') or 0
            success = r.get('success', False)

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
        except HTTPException as exc:
            # 单张校验失败（体积/格式等）：记录该张，不中断整批
            results.append({
                'filename': filename,
                'status': 'error',
                'label': str(exc.detail),
                'bit_accuracy': None,
                'error': 'invalid_upload',
            })
        except Exception:
            # 安全：记录完整堆栈到日志，对外只返回通用中文文案，不回显原始异常
            logger.exception('compliance batch item failed filename=%s model=%s', filename, model)
            results.append({
                'filename': filename,
                'status': 'error',
                'label': '处理失败：图片无法完成合规检测',
                'bit_accuracy': None,
                'error': 'processing_failed',
            })

    compliant = sum(1 for r in results if r['status'] == 'watermark_verified')
    degraded  = sum(1 for r in results if r['status'] == 'watermark_degraded')
    no_wm     = sum(1 for r in results if r['status'] == 'no_watermark')

    return {
        'schema_version': 'compliance-batch.v1',
        'generated_at': int(time.time()),
        'model': model,
        'mode': 'real_checkpoint',
        'total': len(results),
        'compliant': compliant,
        'degraded': degraded,
        'no_watermark': no_wm,
        'compliance_rate': round(compliant / len(results), 4) if results else 0,
        'regulation': '《人工智能生成合成内容标识办法》',
        'results': results,
    }
