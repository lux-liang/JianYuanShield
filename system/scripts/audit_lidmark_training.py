from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import (  # noqa: E402
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    PROJECT_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def names(path: Path, suffixes: set[str]) -> set[str]:
    if not path.is_dir():
        return set()
    return {item.stem for item in path.iterdir() if item.is_file() and item.suffix.lower() in suffixes}


def main() -> int:
    source = MODEL_SOURCE_ROOT / "LIDMark"
    image_root = DATA_ROOT / "lidmark_official" / "image" / "celeba-hq_128"
    watermark_root = DATA_ROOT / "lidmark_official" / "watermark_152" / "celeba-hq" / "128"
    splits = {}
    total_pairs = 0
    for split in ("train", "val", "test"):
        image_names = names(image_root / split, IMAGE_SUFFIXES)
        watermark_names = names(watermark_root / split, {".npy"})
        paired = image_names & watermark_names
        total_pairs += len(paired)
        splits[split] = {
            "images": len(image_names),
            "watermarks": len(watermark_names),
            "paired": len(paired),
            "missing_images": len(watermark_names - image_names),
            "missing_watermarks": len(image_names - watermark_names),
        }

    smoke_checkpoints = sorted((WEIGHT_ROOT / "lidmark" / "smoke_128").rglob("*.pth"))
    deepfake_assets = {
        name: (source / "model" / name).is_dir()
        for name in ("SimSwap", "UniFace", "CSCS", "StarGAN", "InfoSwap")
    }
    blockers = []
    if total_pairs == 0:
        blockers.append("official_celeba_hq_images_missing")
    if any(item["paired"] != item["watermarks"] for item in splits.values()):
        blockers.append("image_watermark_pairs_incomplete")
    if not all(deepfake_assets.values()):
        blockers.append("deepfake_finetune_assets_incomplete")

    payload = {
        "schema_version": "lidmark-training-audit.v1",
        "status": "blocked" if blockers else "ready_for_single_batch_gate",
        "source": str(source),
        "source_exists": source.is_dir(),
        "image_root": str(image_root),
        "watermark_root": str(watermark_root),
        "splits": splits,
        "total_pairs": total_pairs,
        "smoke_checkpoint_count": len(smoke_checkpoints),
        "smoke_checkpoints": [str(path) for path in smoke_checkpoints],
        "deepfake_assets": deepfake_assets,
        "blockers": blockers,
        "training_config": str(PROJECT_ROOT / "configs" / "lidmark_training.v1.json"),
        "required_next_actions": [
            "Add the licensed CelebA-HQ images with filenames matching the official watermark files.",
            "Record dataset provenance/license and verify identity-disjoint train/val/test splits.",
            "Run a one-batch forward/backward and checkpoint-resume gate on an unused GPU.",
            "Enable validation and select the best checkpoint on validation ID BER then landmark AED.",
            "Only start Deepfake fine-tuning after third-party model licenses and checkpoints are recorded.",
        ],
    }
    output = REPORT_ROOT / "lidmark_training"
    output.mkdir(parents=True, exist_ok=True)
    (output / "readiness.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
