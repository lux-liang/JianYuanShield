#!/usr/bin/env bash
# Waits for CelebAMask-HQ.zip to finish uploading, extracts, resizes, then launches LIDMark training

set -euo pipefail

ZIP=/home/luxliang/JianYuanShield/data/CelebAMask-HQ.zip
DEST=/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/image/celeba-hq_128
WM_ROOT=/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/watermark_152/celeba-hq/128
LIDMARK_DIR=/data1/luxliang/work/vpsg_competition_candidates/LIDMark
EXTRACT_TMP=/tmp/celeba_hq_extract

echo "[1/5] Waiting for zip upload to complete..."
prev_size=0
stable_count=0
while true; do
    cur_size=$(stat -c%s "$ZIP" 2>/dev/null || echo 0)
    if [ "$cur_size" = "$prev_size" ] && [ "$cur_size" -gt 100000000 ]; then
        stable_count=$((stable_count+1))
        if [ $stable_count -ge 3 ]; then
            # Try actual unzip test
            if unzip -t "$ZIP" > /dev/null 2>&1; then
                echo "Upload complete: ${cur_size} bytes"
                break
            fi
        fi
    else
        stable_count=0
    fi
    prev_size=$cur_size
    echo "  $(date '+%H:%M:%S') size=${cur_size} stable=${stable_count}/3"
    sleep 15
done

echo "[2/5] Extracting zip to $EXTRACT_TMP ..."
rm -rf "$EXTRACT_TMP"
mkdir -p "$EXTRACT_TMP"
unzip -q "$ZIP" -d "$EXTRACT_TMP"

# Find image directory (CelebA-HQ-img or similar)
IMG_SRC=$(find "$EXTRACT_TMP" -type d -name 'CelebA-HQ-img' | head -1)
if [ -z "$IMG_SRC" ]; then
    # fallback: find directory with .jpg files
    IMG_SRC=$(find "$EXTRACT_TMP" -name '*.jpg' -printf '%h\n' | sort -u | head -1)
fi
echo "  Image source: $IMG_SRC"
echo "  Sample files: $(ls "$IMG_SRC" | head -5)"

echo "[3/5] Resizing and organizing images to $DEST ..."
mkdir -p "$DEST/train" "$DEST/val" "$DEST/test"

python3 - << 'PYEOF'
import os, sys
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

img_src = sys.argv[1] if len(sys.argv) > 1 else None

import subprocess
result = subprocess.run(['bash', '-c', 'echo "$IMG_SRC"'], capture_output=True, text=True)
img_src = result.stdout.strip() or '/tmp/celeba_hq_extract'

# Try to find source images
src_dir = None
for d in Path('/tmp/celeba_hq_extract').rglob('*.jpg'):
    src_dir = d.parent
    break

if src_dir is None:
    print('ERROR: No jpg files found in extract directory')
    sys.exit(1)

print(f'Source: {src_dir}, files: {len(list(src_dir.glob("*.jpg")))}')

wm_root = Path('/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/watermark_152/celeba-hq/128')
dest_root = Path('/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/image/celeba-hq_128')

TARGET_SIZE = (128, 128)

def process_split(split):
    wm_dir = wm_root / split
    out_dir = dest_root / split
    out_dir.mkdir(parents=True, exist_ok=True)
    
    indices = [p.stem for p in wm_dir.glob('*.npy')]
    ok = 0
    missing = []
    
    for idx in indices:
        src = src_dir / f'{idx}.jpg'
        dst = out_dir / f'{idx}.jpg'
        if dst.exists():
            ok += 1
            continue
        if not src.exists():
            missing.append(idx)
            continue
        img = Image.open(src).convert('RGB')
        img = img.resize(TARGET_SIZE, Image.BICUBIC)
        img.save(dst, 'JPEG', quality=95)
        ok += 1
    
    print(f'  {split}: ok={ok}/{len(indices)}, missing={len(missing)}')
    if missing[:5]:
        print(f'    first missing: {missing[:5]}')

for split in ['train', 'val', 'test']:
    process_split(split)
print('Image preparation complete.')
PYEOF

echo "[4/5] Re-running LIDMark training readiness check..."
cd /home/luxliang/JianYuanShield
PYTHONPATH=/home/luxliang/JianYuanShield python3 system/scripts/audit_lidmark_training.py 2>/dev/null || true

echo "[5/5] Launching LIDMark training on GPU 2,3 (seed 20260603)..."
cd "$LIDMARK_DIR"
# Update config with correct paths
python3 - << 'PYEOF'
import yaml
cfg_path = 'configurations/train_distortions.yaml'
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)
cfg['img_size'] = 128
cfg['img_path'] = '/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/image/celeba-hq_128'
cfg['wm_path'] = '/data1/luxliang/work/vpsg_competition_candidates/datasets/lidmark_official/watermark_152/celeba-hq'
cfg['gpu_ids'] = '2, 3'
cfg['seed'] = 20260603
cfg['epochs'] = 100
cfg['validation'] = {'enable': True, 'save_count': 16}
cfg['resume'] = {'enable': False, 'epoch': 0}
with open(cfg_path, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
print('Config updated:', cfg_path)
PYEOF

nohup python3 main.py train_distortions > /data1/luxliang/work/vpsg_competition_candidates/runs/lidmark/train_seed20260603.log 2>&1 &
echo "LIDMark training started. PID=$! Log: runs/lidmark/train_seed20260603.log"
