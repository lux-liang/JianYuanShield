#!/usr/bin/env bash
# Waits for CelebAMask-HQ.zip to finish uploading, extracts, resizes, then launches LIDMark training

set -euo pipefail

SCRIPT_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${JYS_PROJECT_ROOT:-$SCRIPT_PROJECT_ROOT}"
MODEL_SOURCE_ROOT="${JYS_MODEL_SOURCE_ROOT:-$PROJECT_ROOT}"
DATA_ROOT="${JYS_DATA_ROOT:-$PROJECT_ROOT/datasets}"
WEIGHT_ROOT="${JYS_WEIGHT_ROOT:-$PROJECT_ROOT/weights}"
REPORT_ROOT="${JYS_REPORT_ROOT:-$PROJECT_ROOT/system/reports}"
export JYS_PROJECT_ROOT="$PROJECT_ROOT"
export JYS_MODEL_SOURCE_ROOT="$MODEL_SOURCE_ROOT"
export JYS_DATA_ROOT="$DATA_ROOT"
export JYS_WEIGHT_ROOT="$WEIGHT_ROOT"
export JYS_REPORT_ROOT="$REPORT_ROOT"

ZIP="$DATA_ROOT/CelebAMask-HQ.zip"
DEST="$DATA_ROOT/lidmark_official/image/celeba-hq_128"
WM_BASE="$DATA_ROOT/lidmark_official/watermark_152/celeba-hq"
WM_ROOT="$WM_BASE/128"
LIDMARK_DIR="$MODEL_SOURCE_ROOT/LIDMark"
RUN_DIR="$MODEL_SOURCE_ROOT/runs/lidmark"
EXTRACT_TMP="$DATA_ROOT/.staging/celeba_hq_extract"

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
if [[ -z "$EXTRACT_TMP" || "$EXTRACT_TMP" == "/" || "$EXTRACT_TMP" == "$DATA_ROOT" ]]; then
    echo "Refusing unsafe extraction target: $EXTRACT_TMP" >&2
    exit 2
fi
rm -rf -- "$EXTRACT_TMP"
mkdir -p "$EXTRACT_TMP"
unzip -q "$ZIP" -d "$EXTRACT_TMP"

# Find image directory (CelebA-HQ-img or similar)
IMG_SRC=$(find "$EXTRACT_TMP" -type d -name 'CelebA-HQ-img' -print -quit)
if [ -z "$IMG_SRC" ]; then
    # fallback: find directory with .jpg files
    IMG_SRC=$(find "$EXTRACT_TMP" -name '*.jpg' -printf '%h\n' -quit)
fi
if [[ -z "$IMG_SRC" || ! -d "$IMG_SRC" ]]; then
    echo "No CelebA-HQ image directory found under $EXTRACT_TMP" >&2
    exit 2
fi
echo "  Image source: $IMG_SRC"
sample_files=$(find "$IMG_SRC" -maxdepth 1 -type f -printf '%f\n' | sort | sed -n '1,5p')
echo "  Sample files: $sample_files"

echo "[3/5] Resizing and organizing images to $DEST ..."
mkdir -p "$DEST/train" "$DEST/val" "$DEST/test"

python3 - "$IMG_SRC" "$WM_ROOT" "$DEST" << 'PYEOF'
import sys
from pathlib import Path
from PIL import Image

src_dir = Path(sys.argv[1])
wm_root = Path(sys.argv[2])
dest_root = Path(sys.argv[3])

print(f'Source: {src_dir}, files: {len(list(src_dir.glob("*.jpg")))}')

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
        with Image.open(src) as image:
            image.convert('RGB').resize(TARGET_SIZE, Image.Resampling.BICUBIC).save(
                dst, 'JPEG', quality=95
            )
        ok += 1
    
    print(f'  {split}: ok={ok}/{len(indices)}, missing={len(missing)}')
    if missing[:5]:
        print(f'    first missing: {missing[:5]}')

for split in ['train', 'val', 'test']:
    process_split(split)
print('Image preparation complete.')
PYEOF

echo "[4/5] Re-running LIDMark training readiness check..."
cd "$PROJECT_ROOT"
PYTHONPATH="$PROJECT_ROOT" python3 system/scripts/audit_lidmark_training.py 2>/dev/null || true

echo "[5/5] Launching LIDMark training on GPU 2,3 (seed 20260603)..."
PYTHONPATH="$PROJECT_ROOT" python3 "$PROJECT_ROOT/scripts/launch_lidmark_training.py" \
    "2, 3" 20260603 \
    --model-dir "$LIDMARK_DIR" \
    --run-dir "$RUN_DIR" \
    --image-root "$DEST" \
    --watermark-root "$WM_BASE"
