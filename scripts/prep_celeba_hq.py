#!/usr/bin/env python3
"""Prepare CelebA-HQ images for LIDMark and KAD-Net."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.runtime import DATA_ROOT, MODEL_SOURCE_ROOT  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "extract_dir",
        nargs="?",
        type=Path,
        default=DATA_ROOT / ".staging" / "celeba_hq_extract",
    )
    parser.add_argument("size", nargs="?", type=int, default=128)
    parser.add_argument(
        "--lidmark-watermark-root",
        type=Path,
        default=DATA_ROOT / "lidmark_official" / "watermark_152" / "celeba-hq" / "128",
    )
    parser.add_argument(
        "--lidmark-image-root",
        type=Path,
        default=DATA_ROOT / "lidmark_official" / "image" / "celeba-hq_128",
    )
    parser.add_argument("--kadnet-model-dir", type=Path, default=MODEL_SOURCE_ROOT / "KAD-Net")
    parser.add_argument("--kadnet-dataset-root", type=Path, default=DATA_ROOT / "celeba_hq_kadnet")
    return parser.parse_args()


def find_image_source(extract_dir: Path) -> tuple[Path, Path | None]:
    """Return the source image directory and optional attribute annotation."""
    image_dir: Path | None = None
    for candidate in ("CelebA-HQ-img", "images", "img"):
        directory = extract_dir / candidate
        if directory.is_dir() and any(directory.glob("*.jpg")):
            image_dir = directory
            break
    if image_dir is None:
        first_image = next(extract_dir.rglob("*.jpg"), None)
        image_dir = first_image.parent if first_image else None
    if image_dir is None:
        raise FileNotFoundError(f"No .jpg images found under {extract_dir}")

    annotation = None
    for candidate in ("CelebAMask-HQ-attribute-anno.txt", "list_attr_celeba.txt"):
        annotation = next(extract_dir.rglob(candidate), None)
        if annotation:
            break
    return image_dir, annotation


def prepare_lidmark(
    source_dir: Path,
    watermark_root: Path,
    image_root: Path,
    size: int,
) -> None:
    """Write ``{index}.jpg`` files matching the watermark split manifests."""
    from PIL import Image

    print(f"\n--- Preparing LIDMark images (size={size}) ---")
    for split in ("train", "val", "test"):
        watermark_dir = watermark_root / split
        output_dir = image_root / split
        output_dir.mkdir(parents=True, exist_ok=True)
        indices = [path.stem for path in watermark_dir.glob("*.npy")]
        created = skipped = missing = 0
        for index in indices:
            destination = output_dir / f"{index}.jpg"
            if destination.exists():
                skipped += 1
                continue
            source = source_dir / f"{index}.jpg"
            if not source.is_file():
                missing += 1
                continue
            with Image.open(source) as image:
                image.convert("RGB").resize((size, size), Image.Resampling.BICUBIC).save(
                    destination,
                    "JPEG",
                    quality=95,
                )
            created += 1
        print(f"  {split}: resized={created} skipped={skipped} missing={missing}")


def prepare_kadnet(
    source_dir: Path,
    annotation_path: Path | None,
    model_dir: Path,
    dataset_root: Path,
    size: int,
) -> None:
    """Write zero-padded PNG files into KAD-Net train and validation splits."""
    from PIL import Image

    print(f"\n--- Preparing KAD-Net images (size={size}) ---")
    train_output = dataset_root / f"train_{size}"
    validation_output = dataset_root / f"val_{size}"
    train_output.mkdir(parents=True, exist_ok=True)
    validation_output.mkdir(parents=True, exist_ok=True)

    source_images = sorted(source_dir.glob("*.jpg"), key=lambda path: int(path.stem))
    print(f"  Total source images: {len(source_images)}")
    train_count = validation_count = 0
    for source in source_images:
        index = int(source.stem)
        if index < 24179:
            destination = train_output / f"{index:05d}.png"
        elif index < 27172:
            destination = validation_output / f"{index:05d}.png"
        else:
            continue
        if destination.exists():
            continue
        with Image.open(source) as image:
            image.convert("RGB").resize((size, size), Image.Resampling.BICUBIC).save(destination, "PNG")
        if index < 24179:
            train_count += 1
        else:
            validation_count += 1

    print(f"  train_{size}: {train_count} new images")
    print(f"  val_{size}: {validation_count} new images")
    annotation_destination = (
        model_dir / "network" / "noise_layers" / "stargan" / "CelebAMask-HQ-attribute-anno.txt"
    )
    if annotation_path and annotation_path.is_file() and not annotation_destination.exists():
        annotation_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(annotation_path, annotation_destination)
        print(f"  Copied attribute annotation to {annotation_destination}")
    elif not annotation_path:
        print(f"  WARNING: no attribute annotation found; KAD-Net expects {annotation_destination}")


def main() -> None:
    args = parse_args()
    if args.size <= 0:
        raise SystemExit("size must be positive")
    extract_dir = args.extract_dir.expanduser().resolve()
    print(f"Finding images in {extract_dir} ...")
    source_dir, annotation_path = find_image_source(extract_dir)
    print(f"Source: {source_dir} ({sum(1 for _ in source_dir.glob('*.jpg'))} jpg files)")
    print(f"Attribute annotation: {annotation_path}")

    prepare_lidmark(
        source_dir,
        args.lidmark_watermark_root.expanduser().resolve(),
        args.lidmark_image_root.expanduser().resolve(),
        args.size,
    )
    prepare_kadnet(
        source_dir,
        annotation_path,
        args.kadnet_model_dir.expanduser().resolve(),
        args.kadnet_dataset_root.expanduser().resolve(),
        args.size,
    )
    print("\nDone. Training launchers remain separate and must be invoked explicitly.")


if __name__ == "__main__":
    main()
