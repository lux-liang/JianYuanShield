from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from .config import ASSETS, DATASETS, REPORTS
from .schemas import DemoRunRequest
from .utils import artifact_url
from .evidence import sha256_file
from .model_adapters import LIDMarkAdapter


def sample_path(sample_id: str) -> Path:
    return DATASETS / f"{sample_id}.png"


def ensure_sample(sample_id: str = "sample_face_001") -> Path:
    path = sample_path(sample_id)
    if path.exists():
        return path

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
    img.save(path)
    return path


def samples_payload() -> list[dict[str, str]]:
    path = ensure_sample()
    return [{"id": path.stem, "name": "Demo face sample", "url": f"/api/samples/{path.stem}/image"}]


def load_rgb(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def save_rgb(array: np.ndarray, path: Path) -> Path:
    Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).save(path)
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
    """Map demo attack string to LIDMarkAdapter attack key."""
    attack = attack.lower()
    if 'jpeg' in attack:
        return 'jpeg'
    if 'resize' in attack:
        return 'resize'
    if 'noise' in attack:
        return 'noise'
    return 'clean'


def apply_attack(image: np.ndarray, attack: str) -> np.ndarray:
    attacked = image.copy()
    if "multi_embedding" in attack:
        rng = np.random.default_rng(2026)
        attacked = np.clip(attacked.astype(np.int16) + rng.integers(-6, 7, attacked.shape), 0, 255).astype(np.uint8)
    if "jpeg" in attack:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]
        ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(attacked, cv2.COLOR_RGB2BGR), encode_param)
        if ok:
            attacked = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if "blur" in attack:
        attacked = cv2.GaussianBlur(attacked, (5, 5), 0)
    if "resize" in attack:
        h, w = attacked.shape[:2]
        attacked = cv2.resize(attacked, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        attacked = cv2.resize(attacked, (w, h), interpolation=cv2.INTER_LINEAR)
    return attacked


def make_heatmap(reference: np.ndarray, attacked: np.ndarray) -> np.ndarray:
    diff = np.mean(np.abs(reference.astype(np.float32) - attacked.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    heat = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
    return cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)


def metrics(reference: np.ndarray, candidate: np.ndarray, residual: np.ndarray) -> dict[str, Any]:
    psnr = peak_signal_noise_ratio(reference, candidate, data_range=255)
    ssim = structural_similarity(reference, candidate, channel_axis=2, data_range=255)
    energy = float(np.mean(residual) / 255.0)
    ber = min(1.0, max(0.0, energy * 0.42))
    source_id_acc = max(0.0, 1.0 - ber * 1.8)
    return {
        "psnr": round(float(psnr), 4),
        "ssim": round(float(ssim), 4),
        "ber": round(float(ber), 4),
        "bit_accuracy": round(float(1.0 - ber), 4),
        "source_id_acc": round(float(source_id_acc), 4),
        "landmark_error": round(float(ber * 12.0), 4),
        "attack_success": bool(ber > 0.18 or source_id_acc < 0.75),
    }


def demo_run_payload(request: DemoRunRequest) -> dict[str, Any]:
    original_path = ensure_sample(request.sample_id)
    original = load_rgb(original_path)
    # Try real LIDMarkAdapter; fall back to deterministic simulation
    _adapter = LIDMarkAdapter.get()
    _lm_attack = _map_attack_for_lidmark(request.attack or '')
    if _adapter is not None:
        _out = _adapter.run(original, attack=_lm_attack)
        _orig_128   = _out['images']['original']  # 128x128 input used by LIDMark
        watermarked = _out['images']['watermarked']
        attacked    = _out['images']['attacked']
        heatmap     = _out['images']['heatmap']
        residual    = np.clip(
            np.abs(watermarked.astype(np.int16) - _orig_128.astype(np.int16)) * 32,
            0, 255).astype(np.uint8)
        attack_residual = _out['images']['diff']
        original    = _orig_128  # use 128x128 consistently for artifact saving
        _real_metrics = {
            'psnr':         _out['psnr'],
            'ssim':         _out['ssim'],
            'ber':          round(_out['id_ber'], 4),
            'bit_accuracy': _out['bit_accuracy'],
            'source_id_acc': _out['bit_accuracy'],
            'landmark_error': round(_out['landmark_aed'], 4) if _out.get('landmark_aed') else None,
            'attack_success': not _out['success'],
        }
        _demo_mode = 'real_lidmark'
    else:
        watermarked, residual = simulate_lidmark_embed(original)
        attacked = apply_attack(watermarked, request.attack or '')
        heatmap  = make_heatmap(watermarked, attacked)
        attack_residual = np.clip(
            np.abs(attacked.astype(np.int16) - watermarked.astype(np.int16)) * 12,
            0, 255).astype(np.uint8)
        _real_metrics = None
        _demo_mode = 'demo_simulation'

    task_id = uuid.uuid4().hex[:12]
    out_dir = ASSETS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
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
        "project": request.project,
        "sample_id": request.sample_id,
        "attack": request.attack,
        "security_conclusion": "attack_degraded_traceability" if request.attack else "protected",
        "metrics": _real_metrics if _real_metrics is not None else metrics(watermarked, attacked, attack_residual),
        "artifacts": {key: artifact_url(value) for key, value in paths.items()},
        "evidence": {
            "input_sha256": sha256_file(original_path),
            "artifact_sha256": {key: sha256_file(value) for key, value in paths.items()},
            "engine": "deterministic_competition_demo",
        },
        "notes": [
            "This interactive task is a deterministic system demonstration, not a formal model benchmark.",
            "Formal conclusions are sourced from the completed real-checkpoint benchmark reports.",
        ],
    }
    (REPORTS / f"{task_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def report_payload(task_id: str) -> dict[str, Any] | None:
    path = REPORTS / f"{task_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def real_evals_payload() -> list[dict[str, Any]]:
    reports = []
    for path in sorted((REPORTS / "real_hidden").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            reports.append({
                "task_id": item.get("task_id"),
                "project": item.get("project"),
                "mode": item.get("mode"),
                "checkpoint": item.get("checkpoint"),
                "metrics": item.get("metrics", {}),
                "artifacts": item.get("artifacts", {}),
                "report_path": str(path),
            })
        except Exception:
            continue
    return reports
