from __future__ import annotations

import json
import hashlib
import io
import math
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from .config import ASSETS, DATASETS, REPORTS
from .schemas import DemoRunRequest
from .utils import (
    artifact_url,
    atomic_write_bytes,
    atomic_write_json,
    create_ephemeral_artifact_directory,
)
from system.evaluation.attacks import apply_attack as apply_protocol_attack
from .evidence import sha256_file
from .model_adapters import get_adapter
from .security import resolve_path_within, validate_identifier
from .settings import settings
from system.evaluation.runtime import logical_path


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _safe_checkpoint_reference(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value)
    if "://" in raw:
        remote_name = Path(urlsplit(raw).path).name
        return remote_name or "remote-checkpoint"
    try:
        return logical_path(raw)
    except (OSError, RuntimeError, ValueError):
        return Path(raw).name or None


def sample_path(sample_id: str) -> Path:
    validate_identifier(sample_id, field="sample_id")
    path = resolve_path_within(DATASETS, f"{sample_id}.png")
    if path is None:
        raise RuntimeError("sample path is outside the configured dataset root")
    return path


def ensure_sample(sample_id: str = "sample_face_001") -> Path:
    path = sample_path(sample_id)
    if path.is_symlink():
        raise RuntimeError("sample path cannot be a symbolic link")
    if path.is_file():
        return path
    if path.exists():
        raise RuntimeError("sample path is not a regular file")

    size = 512
    img = Image.new("RGB", (size, size), (238, 241, 244))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size, size), fill=(235, 238, 242))
    draw.ellipse((132, 78, 380, 410), fill=(232, 190, 162), outline=(54, 68, 82), width=4)
    draw.ellipse((190, 190, 230, 228), fill=(28, 35, 45))
    draw.ellipse((292, 190, 332, 228), fill=(28, 35, 45))
    draw.arc((214, 222, 318, 330), 20, 160, fill=(121, 62, 64), width=5)
    draw.polygon([(160, 92), (260, 30), (370, 96), (382, 170), (128, 174)], fill=(45, 45, 54))
    draw.rectangle((0, 438, size, size), fill=(38, 78, 102))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    atomic_write_bytes(path, buffer.getvalue())
    return path


def samples_payload() -> list[dict[str, str]]:
    path = ensure_sample()
    return [{"id": path.stem, "name": "Demo face sample", "url": f"/api/samples/{path.stem}/image"}]


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def save_rgb(array: np.ndarray, path: Path) -> Path:
    buffer = io.BytesIO()
    Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).save(buffer, format="PNG")
    atomic_write_bytes(path, buffer.getvalue())
    return path


def simulate_lidmark_embed(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic fallback — only used when LIDMarkAdapter is unavailable."""
    rng = np.random.default_rng(152)
    pattern = rng.integers(-2, 3, size=image.shape, dtype=np.int16)
    grid = np.zeros_like(image, dtype=np.int16)
    grid[::16, :, 1] = 3
    grid[:, ::16, 2] = -3
    watermarked = np.clip(image.astype(np.int16) + pattern + grid, 0, 255).astype(np.uint8)
    residual = np.clip(np.abs(watermarked.astype(np.int16) - image.astype(np.int16)) * 32, 0, 255).astype(np.uint8)
    return watermarked, residual


def _map_attack_for_lidmark(attack: str) -> str:
    """Translate the legacy demo form into protocol attack identifiers."""
    attack = (attack or '').lower()
    if not attack:
        return 'clean'
    if 'deepfake' in attack:
        return 'deepfake_proxy_v1'
    if 'jpeg' in attack:
        if '90' in attack:
            return 'jpeg90'
        if '70' in attack:
            return 'jpeg70'
        return 'jpeg50'
    if 'resize' in attack:
        return 'resize_0.5x'
    if 'noise' in attack:
        return 'gaussian_noise_sigma_3'
    if 'blur' in attack:
        return 'gaussian_blur_5'
    return attack


def apply_attack(image: np.ndarray, attack: str) -> np.ndarray:
    """Apply the versioned attack library, including the legacy demo compound."""
    attacked = image.copy().astype(np.uint8)
    if "multi_embedding" in attack:
        rng = np.random.default_rng(2026)
        attacked = np.clip(attacked.astype(np.int16) + rng.integers(-6, 7, attacked.shape), 0, 255).astype(np.uint8)
        operations = ["jpeg50", "gaussian_blur_5"]
    else:
        canonical = {
            "jpeg_50": "jpeg50",
            "jpeg_70": "jpeg70",
            "jpeg_90": "jpeg90",
            "resize": "resize_0.5x",
            "noise": "gaussian_noise_sigma_3",
            "blur": "gaussian_blur_5",
        }.get(attack or "clean", attack or "clean")
        operations = [canonical]
    for operation in operations:
        image_id = hashlib.sha256(attacked.tobytes()).hexdigest()
        attacked, _metadata = apply_protocol_attack(
            attacked,
            operation,
            image_id=image_id,
        )
    return attacked


def make_heatmap(reference: np.ndarray, attacked: np.ndarray) -> np.ndarray:
    diff = np.mean(np.abs(reference.astype(np.float32) - attacked.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    heat = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
    return cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)


def metrics(reference: np.ndarray, candidate: np.ndarray, residual: np.ndarray) -> dict[str, Any]:
    psnr = (
        math.inf
        if np.array_equal(reference, candidate)
        else peak_signal_noise_ratio(reference, candidate, data_range=255)
    )
    ssim = structural_similarity(reference, candidate, channel_axis=2, data_range=255)
    energy = float(np.mean(residual) / 255.0)
    ber = min(1.0, max(0.0, energy * 0.42))
    source_id_acc = max(0.0, 1.0 - ber * 1.8)
    return {
        "psnr": round(float(psnr), 4) if math.isfinite(float(psnr)) else None,
        "ssim": round(float(ssim), 4),
        "ber": round(float(ber), 4),
        "bit_accuracy": round(float(1.0 - ber), 4),
        "source_id_acc": round(float(source_id_acc), 4),
        "landmark_error": round(float(ber * 12.0), 4),
        "attack_success": bool(ber > 0.18 or source_id_acc < 0.75),
    }


def _primary_decode_metrics(project: str, output: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return the protocol-defined primary decoder accuracy and BER.

    Adapter dictionaries intentionally retain every decoder output.  The demo
    response, however, also exposes generic ``bit_accuracy``/``ber`` fields, so
    their source must follow the frozen evaluation protocol instead of whichever
    dictionary key happens to be encountered first.
    """
    normalized = project.strip().lower()
    candidates = {
        "sepmark": (("bit_accuracy_c", "ber_c"),),
        "waveguard": (("bit_accuracy_tracer", "ber_tracer"),),
        "lidmark": (("bit_accuracy", "id_ber"),),
        "kad-net": (("bit_accuracy", "ber"), ("bit_accuracy", "bit_error")),
    }.get(normalized, (("bit_accuracy", "ber"),))

    for accuracy_key, ber_key in candidates:
        raw_accuracy = output.get(accuracy_key)
        raw_ber = output.get(ber_key)
        accuracy = float(raw_accuracy) if raw_accuracy is not None else None
        ber = float(raw_ber) if raw_ber is not None else None
        if accuracy is not None or ber is not None:
            if accuracy is None:
                accuracy = 1.0 - ber
            if ber is None:
                ber = 1.0 - accuracy
            return accuracy, ber
    return None, None


def demo_run_payload(request: DemoRunRequest) -> dict[str, Any]:
    validate_identifier(request.sample_id, field="sample_id")
    original_path = ensure_sample(request.sample_id)
    original = load_rgb(original_path)
    # Run the model selected by the caller; fall back to a visibly labelled simulation.
    _adapter = get_adapter(request.project)
    if _adapter is None and not settings.enable_demo:
        raise RuntimeError(
            f"model adapter unavailable: {request.project}; demo fallback is disabled"
        )
    _lm_attack = _map_attack_for_lidmark(request.attack or '')
    if _adapter is not None:
        _out = _adapter.run(original, attack=_lm_attack)
        _orig_128   = _out['images']['original']
        watermarked = _out['images']['watermarked']
        attacked    = _out['images']['attacked']
        heatmap     = _out['images']['heatmap']
        residual    = np.clip(
            np.abs(watermarked.astype(np.int16) - _orig_128.astype(np.int16)) * 32,
            0, 255).astype(np.uint8)
        attack_residual = _out['images']['diff']
        original    = _orig_128
        bit_accuracy, ber = _primary_decode_metrics(request.project, _out)
        _real_metrics = {
            'psnr': (
                round(float(_out['psnr']), 4)
                if _out.get('psnr') is not None
                and math.isfinite(float(_out['psnr']))
                else None
            ),
            'ssim': (
                round(float(_out['ssim']), 4)
                if _out.get('ssim') is not None
                and math.isfinite(float(_out['ssim']))
                else None
            ),
            'ber': round(ber, 4) if ber is not None else None,
            'bit_accuracy': round(bit_accuracy, 4) if bit_accuracy is not None else None,
            'source_id_acc': (
                round(bit_accuracy, 4)
                if request.project.lower() == 'lidmark' and bit_accuracy is not None
                else None
            ),
            'landmark_error': (
                round(float(_out['landmark_aed']), 4)
                if _out.get('landmark_aed') is not None else None
            ),
            'attack_success': not bool(_out.get('success', False)),
        }
        _demo_mode = 'real_checkpoint'
    else:
        watermarked, residual = simulate_lidmark_embed(original)
        attacked = apply_attack(watermarked, request.attack or '')
        heatmap  = make_heatmap(watermarked, attacked)
        attack_residual = np.clip(
            np.abs(attacked.astype(np.int16) - watermarked.astype(np.int16)) * 12,
            0, 255).astype(np.uint8)
        _real_metrics = None
        _demo_mode = 'demo_simulation'

    task_id, out_dir = create_ephemeral_artifact_directory(ASSETS)
    report_path = REPORTS / f"{task_id}.json"
    try:
        paths = {
            "original": save_rgb(original, out_dir / "original.png"),
            "watermarked": save_rgb(watermarked, out_dir / "watermarked.png"),
            "attacked": save_rgb(attacked, out_dir / "attacked.png"),
            "heatmap": save_rgb(heatmap, out_dir / "heatmap.png"),
            "residual": save_rgb(residual, out_dir / "residual.png"),
            "attack_residual": save_rgb(attack_residual, out_dir / "attack_residual.png"),
        }

        result = {
            "schema_version": "forensic-task.v1",
            "task_id": task_id,
            "created_at": int(time.time()),
            "mode": _demo_mode,
            "claim_valid": False,
            "execution_valid": _adapter is not None,
            "result_provenance": (
                "checkpoint_single_sample_evaluation"
                if _adapter is not None else "deterministic_ui_simulation"
            ),
            "project": request.project,
            "sample_id": request.sample_id,
            "attack": request.attack,
            "security_conclusion": (
                "attack_degraded_traceability" if request.attack else "protected"
            ) if _adapter is not None else "demonstration_only",
            "metrics": (
                _real_metrics
                if _real_metrics is not None
                else metrics(watermarked, attacked, attack_residual)
            ),
            "artifacts": {key: artifact_url(value) for key, value in paths.items()},
            "evidence": {
                "input_sha256": sha256_file(original_path),
                "artifact_sha256": {key: sha256_file(value) for key, value in paths.items()},
                "engine": (
                    request.project
                    if _adapter is not None
                    else "deterministic_competition_demo"
                ),
            },
            "notes": [
                (
                    "This task used a real checkpoint but remains a single-sample demonstration."
                    if _adapter is not None
                    else "No compatible checkpoint was available; this is a deterministic UI simulation."
                ),
                "Formal conclusions remain blocked until the machine-readable claims gate verifies the required evidence.",
            ],
        }
        atomic_write_json(report_path, result)
        return result
    except Exception:
        shutil.rmtree(out_dir, ignore_errors=True)
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def report_payload(task_id: str) -> dict[str, Any] | None:
    validate_identifier(task_id, field="task_id")
    path = REPORTS / f"{task_id}.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("task_id") != task_id:
        return None
    return payload


def real_evals_payload() -> list[dict[str, Any]]:
    directory = resolve_path_within(REPORTS, "real_hidden")
    if directory is None or not directory.is_dir():
        return []
    candidates = []
    for path in directory.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            modified_at = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((modified_at, path))
    reports = []
    for _modified_at, path in sorted(candidates, reverse=True):
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            item = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
            if not isinstance(item, dict):
                continue
            reports.append({
                "task_id": item.get("task_id"),
                "project": item.get("project"),
                "mode": item.get("mode"),
                "checkpoint": _safe_checkpoint_reference(item.get("checkpoint")),
                "metrics": item.get("metrics", {}),
                "artifacts": item.get("artifacts", {}),
                "report_path": f"system/reports/real_hidden/{path.name}",
            })
        except Exception:
            continue
    return reports
