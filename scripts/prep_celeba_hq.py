#!/usr/bin/env python3
"""Prepare CelebA-HQ images for LIDMark (jpg/index) and KAD-Net (png/00000 format)."""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image


LIDMARK_WM = Path('/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/watermark_152/celeba-hq/128')
LIDMARK_IMG = Path('/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/image/celeba-hq_128')
KADNET_DIR = Path('/data1/luxliang/work/vpsg_competition_candidates/KAD-Net')
KADNET_DATASET = Path('/data1/luxliang/work/vpsg_competition_candidates/datasets/celeba_hq_kadnet')


def find_image_source(extract_dir: Path) -> tuple[Path, Path | None]:
    """Returns (img_dir, attr_anno_path)."""
    img_dir = None
    for cand in ['CelebA-HQ-img', 'images', 'img']:
        d = extract_dir / cand
        if d.is_dir() and any(d.glob('*.jpg')):
            img_dir = d
            break
    if img_dir is None:
        for p in extract_dir.rglob('*.jpg'):
            img_dir = p.parent
            break
    if img_dir is None:
        raise FileNotFoundError(f'No .jpg images found under {extract_dir}')
    
    # Look for attribute annotation
    anno = None
    for cand_name in ['CelebAMask-HQ-attribute-anno.txt', 'list_attr_celeba.txt']:
        for p in extract_dir.rglob(cand_name):
            anno = p
            break
    return img_dir, anno


def prepare_lidmark(src_dir: Path, size: int = 128) -> None:
    """LIDMark: {idx}.jpg in train/val/test matching watermark npy stems."""
    print(f'\n--- Preparing LIDMark images (size={size}) ---')
    for split in ['train', 'val', 'test']:
        wm_dir = LIDMARK_WM / split
        out_dir = LIDMARK_IMG / split
        out_dir.mkdir(parents=True, exist_ok=True)
        indices = [p.stem for p in wm_dir.glob('*.npy')]
        ok = skipped = missing = 0
        for idx in indices:
            dst = out_dir / f'{idx}.jpg'
            if dst.exists():
                skipped += 1
                continue
            src = src_dir / f'{idx}.jpg'
            if not src.exists():
                missing += 1
                continue
            img = Image.open(src).convert('RGB')
            img = img.resize((size, size), Image.BICUBIC)
            img.save(dst, 'JPEG', quality=95)
            ok += 1
        print(f'  {split}: resized={ok} skipped={skipped} missing={missing}')


def prepare_kadnet(src_dir: Path, anno_path: Path | None, size: int = 128) -> None:
    """KAD-Net: {00000}.png in train_{size}/ and val_{size}/."""
    print(f'\n--- Preparing KAD-Net images (size={size}) ---')
    # Train: 0-24178 (indices matching LIDMark train), Val: 24179-27171
    train_out = KADNET_DATASET / f'train_{size}'
    val_out = KADNET_DATASET / f'val_{size}'
    train_out.mkdir(parents=True, exist_ok=True)
    val_out.mkdir(parents=True, exist_ok=True)

    all_imgs = sorted(src_dir.glob('*.jpg'), key=lambda p: int(p.stem))
    print(f'  Total source images: {len(all_imgs)}')
    
    train_count = val_count = missing = 0
    for src in all_imgs:
        idx = int(src.stem)
        padded = str(idx).zfill(5)
        if idx < 24179:
            dst = train_out / f'{padded}.png'
        elif idx < 27172:
            dst = val_out / f'{padded}.png'
        else:
            continue  # test images not needed for KAD-Net training

        if dst.exists():
            continue
        img = Image.open(src).convert('RGB')
        img = img.resize((size, size), Image.BICUBIC)
        img.save(dst, 'PNG')
        if idx < 24179:
            train_count += 1
        else:
            val_count += 1

    print(f'  train_{size}: {train_count} new images')
    print(f'  val_{size}: {val_count} new images')

    # Copy attribute annotation file
    anno_dst = KADNET_DIR / 'network/noise_layers/stargan/CelebAMask-HQ-attribute-anno.txt'
    if anno_path and anno_path.exists() and not anno_dst.exists():
        anno_dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy(anno_path, anno_dst)
        print(f'  Copied attribute annotation to {anno_dst}')
    elif not anno_path:
        print(f'  WARNING: No attribute annotation file found in zip.')
        print(f'  KAD-Net needs: {anno_dst}')


def main() -> None:
    extract_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/celeba_hq_extract')
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 128

    print(f'Finding images in {extract_dir} ...')
    src_dir, anno_path = find_image_source(extract_dir)
    total = sum(1 for _ in src_dir.glob('*.jpg'))
    print(f'Source: {src_dir} ({total} jpg files)')
    print(f'Attribute anno: {anno_path}')

    prepare_lidmark(src_dir, size)
    prepare_kadnet(src_dir, anno_path, size)

    print('\nDone. Next steps:')
    print('  python3 scripts/launch_lidmark_training.py "2, 3" 20260603')
    print('  python3 scripts/launch_kadnet_training.py "4" 42')


if __name__ == '__main__':
    main()
