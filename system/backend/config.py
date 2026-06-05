from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets" / "samples"
REPORTS = ROOT / "system" / "reports"
ASSETS = ROOT / "system" / "assets"
MANIFEST = ROOT / "weights" / "WEIGHT_MANIFEST.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WEIGHT_SUFFIXES = {".pth", ".pyt", ".pt", ".ckpt", ".onnx"}


def ensure_runtime_dirs() -> None:
    for directory in (DATASETS, REPORTS, ASSETS):
        directory.mkdir(parents=True, exist_ok=True)
