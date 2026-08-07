from __future__ import annotations

from system.evaluation.runtime import ASSET_ROOT, DATA_ROOT, PROJECT_ROOT, REPORT_ROOT, WEIGHT_ROOT


ROOT = PROJECT_ROOT
DATASETS = DATA_ROOT / "samples"
REPORTS = REPORT_ROOT
ASSETS = ASSET_ROOT
MANIFEST = WEIGHT_ROOT / "WEIGHT_MANIFEST.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WEIGHT_SUFFIXES = {".pth", ".pyt", ".pt", ".ckpt", ".onnx"}


def ensure_runtime_dirs() -> None:
    for directory in (DATASETS, REPORTS, ASSETS):
        directory.mkdir(parents=True, exist_ok=True)
