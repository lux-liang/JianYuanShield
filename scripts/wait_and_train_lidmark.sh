#!/usr/bin/env bash
# Poll CelebAMask-HQ.zip completion, extract, resize, launch LIDMark + KAD-Net training.
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
EXTRACT="$DATA_ROOT/.staging/celeba_hq_extract"
RUN_ROOT="$MODEL_SOURCE_ROOT/runs"

echo "=== [1/4] Waiting for CelebAMask-HQ.zip to finish uploading ==="
prev=0; stable=0
while true; do
    cur=$(stat -c%s "$ZIP" 2>/dev/null || echo 0)
    if [ "$cur" -eq "$prev" ] && [ "$cur" -gt 200000000 ]; then
        stable=$((stable+1))
        echo "  $(date '+%H:%M:%S') size=$((cur/1048576))MB stable=${stable}/4"
        if [ $stable -ge 4 ] && unzip -t "$ZIP" >/dev/null 2>&1; then
            echo "  Zip integrity OK at $((cur/1048576))MB"; break
        fi
    else
        stable=0
        echo "  $(date '+%H:%M:%S') size=$((cur/1048576))MB growing..."
    fi
    prev=$cur
    sleep 20
done

echo "=== [2/4] Extracting zip ==="
if [[ -z "$EXTRACT" || "$EXTRACT" == "/" || "$EXTRACT" == "$DATA_ROOT" ]]; then
    echo "Refusing unsafe extraction target: $EXTRACT" >&2
    exit 2
fi
rm -rf -- "$EXTRACT"
mkdir -p "$EXTRACT"
unzip -q "$ZIP" -d "$EXTRACT"
echo "  Extracted to $EXTRACT"

echo "=== [3/4] Preparing LIDMark (jpg/index) and KAD-Net (png/00000) datasets ==="
PYTHONPATH="$PROJECT_ROOT" python3 "$PROJECT_ROOT/scripts/prep_celeba_hq.py" "$EXTRACT" 128

echo "=== [4/4] Launching training ==="
mkdir -p "$RUN_ROOT/lidmark" "$RUN_ROOT/kadnet"

# LIDMark on GPU 2,3
PYTHONPATH="$PROJECT_ROOT" python3 "$PROJECT_ROOT/scripts/launch_lidmark_training.py" "2, 3" 20260603
echo "  LIDMark: GPU 2,3 | log: runs/lidmark/train_seed20260603.log"

# KAD-Net on GPU 4
PYTHONPATH="$PROJECT_ROOT" python3 "$PROJECT_ROOT/scripts/launch_kadnet_training.py" "4"
echo "  KAD-Net: GPU 4   | log: runs/kadnet/train_ST.log"

echo ""
echo "=== ALL TRAINING LAUNCHED ==="
echo "Monitor LIDMark: tail -f $RUN_ROOT/lidmark/train_seed20260603.log"
echo "Monitor KAD-Net: tail -f $RUN_ROOT/kadnet/train_ST.log"
