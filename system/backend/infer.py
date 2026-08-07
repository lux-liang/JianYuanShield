from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .config import ASSETS, REPORTS
from .evidence import sha256_file
from .model_adapters import get_adapter
from .demo import (
    simulate_lidmark_embed, apply_attack, make_heatmap,
    metrics as sim_metrics, save_rgb,
)
from .security import MIN_IMAGE_DIMENSION
from .settings import settings
from .utils import (
    atomic_write_json,
    create_ephemeral_artifact_directory,
    is_ephemeral_artifact_directory,
)


class InferenceCapabilityError(RuntimeError):
    """Raised when a real model is required but no compatible adapter is ready."""


_EPHEMERAL_TASK_ID = re.compile(r"^[0-9a-f]{12}$")
_LEGACY_TASK_SCHEMAS = frozenset({"infer-single.v1", "forensic-task.v1"})


def _legacy_report_identifies_task(task_id: str) -> bool:
    """Recognize generated directories created before marker files were added."""

    report_path = REPORTS / f"{task_id}.json"
    if report_path.is_symlink() or not report_path.is_file():
        return False
    try:
        if report_path.stat().st_size > 2 * 1024 * 1024:
            return False
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("task_id") == task_id
        and payload.get("schema_version") in _LEGACY_TASK_SCHEMAS
    )


def _is_generated_task_directory(path: Path) -> bool:
    return is_ephemeral_artifact_directory(path) or _legacy_report_identifies_task(path.name)


def is_inference_task_expired(task_id: str, *, now: float | None = None) -> bool:
    """Return whether a positively identified generated task is past its TTL."""

    if not _EPHEMERAL_TASK_ID.fullmatch(task_id):
        return False
    cutoff = (time.time() if now is None else now) - settings.artifact_ttl_seconds
    path = ASSETS / task_id
    if not path.is_symlink() and path.is_dir() and _is_generated_task_directory(path):
        try:
            return path.stat().st_mtime < cutoff
        except OSError:
            return True

    report_path = REPORTS / f"{task_id}.json"
    if _legacy_report_identifies_task(task_id):
        try:
            return report_path.stat().st_mtime < cutoff
        except OSError:
            return True
    return False


def expire_inference_task(task_id: str, *, now: float | None = None) -> bool:
    """Delete one expired, positively identified generated task and its report."""

    if not is_inference_task_expired(task_id, now=now):
        return False
    path = ASSETS / task_id
    removed = False
    if not path.is_symlink() and path.is_dir() and _is_generated_task_directory(path):
        try:
            shutil.rmtree(path)
        except OSError:
            return False
        removed = True
    try:
        report_path = REPORTS / f"{task_id}.json"
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
            removed = True
    except OSError:
        # The derived images are already gone; a later janitor pass may remove
        # the non-sensitive report once its filesystem becomes writable.
        pass
    return removed


def cleanup_expired_inference_artifacts(*, now: float | None = None, limit: int = 100) -> int:
    """Remove only positively identified expired task directories and reports."""
    removed = 0
    if limit <= 0:
        return 0
    if ASSETS.is_dir():
        try:
            for path in ASSETS.iterdir():
                if removed >= limit:
                    break
                if path.is_symlink() or not path.is_dir() or not _EPHEMERAL_TASK_ID.fullmatch(path.name):
                    continue
                if expire_inference_task(path.name, now=now):
                    removed += 1
        except OSError:
            pass

    cutoff = (time.time() if now is None else now) - settings.artifact_ttl_seconds
    if removed < limit and REPORTS.is_dir():
        try:
            for report_path in REPORTS.glob("*.json"):
                if removed >= limit:
                    break
                task_id = report_path.stem
                if (
                    report_path.is_symlink()
                    or not _EPHEMERAL_TASK_ID.fullmatch(task_id)
                    or (ASSETS / task_id).exists()
                    or not _legacy_report_identifies_task(task_id)
                ):
                    continue
                try:
                    if report_path.stat().st_mtime >= cutoff:
                        continue
                    report_path.unlink()
                except OSError:
                    continue
                removed += 1
        except OSError:
            pass
    return removed


def _json_safe_metrics(value: Any) -> Any:
    """Convert numeric adapter outputs to strict, portable JSON values."""

    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe_metrics(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_metrics(item) for item in value]
    return value


def _pil_to_rgb(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            raise ValueError("decoded image is smaller than the configured minimum")
        if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
            raise ValueError("decoded image exceeds configured pixel limit")
        return np.array(ImageOps.exif_transpose(image).convert("RGB"))


def _rgb_to_b64(arr: np.ndarray, fmt: str = 'PNG') -> str:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def run_single_infer(
    image_bytes: bytes,
    model: str = 'SepMark',
    attack: str = 'clean',
    return_b64: bool = True,
) -> dict[str, Any]:
    cleanup_expired_inference_artifacts()
    original_rgb = _pil_to_rgb(image_bytes)
    # Resize to reasonable size for display
    h, w = original_rgb.shape[:2]
    if max(h, w) > 1024:
        scale = 1024 / max(h, w)
        original_rgb = np.array(Image.fromarray(original_rgb).resize(
            (
                max(MIN_IMAGE_DIMENSION, int(round(w * scale))),
                max(MIN_IMAGE_DIMENSION, int(round(h * scale))),
            ),
            Image.BICUBIC,
        ))

    adapter = get_adapter(model)
    if adapter is None and not settings.enable_demo:
        raise InferenceCapabilityError(
            f"model adapter unavailable: {model}; demo fallback is disabled"
        )
    mode = 'real_checkpoint' if adapter else 'demo_simulation'

    if adapter:
        result = adapter.run(original_rgb, attack)
        imgs = result.pop('images')
        original_u8   = imgs['original']
        watermarked_u8 = imgs['watermarked']
        attacked_u8   = imgs['attacked']
        heatmap_u8    = imgs['heatmap']
        diff_u8       = imgs['diff']
        metrics_out = _json_safe_metrics({
            k: v
            for k, v in result.items()
            if k not in ('model', 'checkpoint', 'attack')
        })
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
        metrics_out = _json_safe_metrics(
            sim_metrics(watermarked_u8, attacked_u8, atk_res)
        )

    task_id, out_dir = create_ephemeral_artifact_directory(ASSETS)
    report_path = REPORTS / f'{task_id}.json'
    try:
        paths = {
            'watermarked': save_rgb(watermarked_u8, out_dir / 'watermarked.png'),
            'attacked':    save_rgb(attacked_u8,    out_dir / 'attacked.png'),
            'heatmap':     save_rgb(heatmap_u8,     out_dir / 'heatmap.png'),
            'diff':        save_rgb(diff_u8,         out_dir / 'diff.png'),
        }

        artifacts: dict[str, Any] = {
            k: f'/api/artifacts/{task_id}/{p.name}' for k, p in paths.items()
        }
        if return_b64:
            artifacts_b64 = {k: _rgb_to_b64(v) for k, v in {
                'original': original_u8, 'watermarked': watermarked_u8,
                'attacked': attacked_u8, 'heatmap': heatmap_u8, 'diff': diff_u8,
            }.items()}
        else:
            artifacts_b64 = {}

        is_checkpoint_execution = adapter is not None
        payload = {
            'schema_version': 'infer-single.v1',
            'task_id': task_id,
            'created_at': int(time.time()),
            'mode': mode,
            # This legacy endpoint evaluates a newly embedded message in one request.
            # It is not a cross-request provenance or blind compliance conclusion.
            'claim_valid': False,
            'execution_valid': is_checkpoint_execution,
            'result_provenance': (
                'checkpoint_single_sample_evaluation'
                if is_checkpoint_execution else 'deterministic_ui_simulation'
            ),
            'model': model,
            'attack': attack,
            'metrics': metrics_out,
            'artifacts': artifacts,
            'artifacts_b64': artifacts_b64,
            'evidence': {
                'input_sha256': hashlib.sha256(image_bytes).hexdigest(),
                'sha256': {k: sha256_file(v) for k, v in paths.items()},
            },
            'privacy': {
                'original_persisted': False,
                'base64_response_requested': bool(return_b64),
                'base64_persisted': False,
                'derived_artifact_ttl_seconds': settings.artifact_ttl_seconds,
            },
            'compliance': {
                'assessment_status': 'not_assessed',
                'watermark_detected': None,
                'regulation': '《人工智能生成合成内容标识办法》第五条（隐式标识）',
                'verdict': 'not_assessed',
                'reason': 'embed-attack-decode evaluation is not blind watermark detection',
            },
            'warnings': (
                [
                    'A compatible checkpoint executed, but this is a single-sample embed-attack-decode evaluation.',
                    'Use the provenance protect/verify lifecycle and evidence-gated benchmark artifacts for claims.',
                ]
                if is_checkpoint_execution else [
                    'No compatible checkpoint was available; images and metrics are a deterministic UI demonstration only.',
                    'Simulation output must not be used for compliance, provenance, or research claims.',
                ]
            ),
        }
        persisted_payload = dict(payload)
        persisted_payload['artifacts_b64'] = {}
        atomic_write_json(report_path, persisted_payload)
        return payload
    except Exception:
        shutil.rmtree(out_dir, ignore_errors=True)
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def run_compliance_batch(
    images_bytes: list[tuple[str, bytes]],
    model: str = 'SepMark',
) -> dict[str, Any]:
    """Describe compliance capability without manufacturing a detection result.

    Existing adapters expose ``run`` (embed a fresh random message and decode it).
    Calling that operation on an uploaded image cannot establish whether the upload
    already carried a compliant watermark. Until a model exposes a blind ``detect``
    contract, this endpoint returns an explicit, machine-readable unavailable state.
    """

    results = [
        {
            'filename': filename,
            'status': 'assessment_unavailable',
            'label': '未执行：当前模型未提供盲检接口',
            'bit_accuracy': None,
            'error': None,
        }
        for filename, _ in images_bytes
    ]
    return {
        'schema_version': 'compliance-batch.v2',
        'generated_at': int(time.time()),
        'model': model,
        'mode': 'capability_unavailable',
        'claim_valid': False,
        'capability': 'blind_watermark_detection',
        'capability_available': False,
        'reason': 'configured adapters only support embed-then-decode evaluation',
        'total': len(results),
        'assessed': 0,
        'compliant': None,
        'degraded': None,
        'no_watermark': None,
        'compliance_rate': None,
        'regulation': '《人工智能生成合成内容标识办法》',
        'warning': 'No compliance verdict was produced. Do not interpret this response as watermark absence.',
        'results': results,
    }
