#!/usr/bin/env bash
# Poll CelebAMask-HQ.zip completion, extract, resize, launch LIDMark + KAD-Net training
set -euo pipefail

ZIP=/home/luxliang/JianYuanShield/data/CelebAMask-HQ.zip
EXTRACT=/tmp/celeba_hq_extract
JYS=/home/luxliang/JianYuanShield

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
rm -rf "$EXTRACT"
mkdir -p "$EXTRACT"
unzip -q "$ZIP" -d "$EXTRACT"
echo "  Extracted to $EXTRACT"

echo "=== [3/4] Preparing LIDMark (jpg/index) and KAD-Net (png/00000) datasets ==="
PYTHONPATH="$JYS" python3 "$JYS/scripts/prep_celeba_hq.py" "$EXTRACT" 128

echo "=== [4/4] Launching training ==="
mkdir -p /data1/luxliang/work/vpsg_competition_candidates/runs/lidmark
mkdir -p /data1/luxliang/work/vpsg_competition_candidates/runs/kadnet

# LIDMark on GPU 2,3
PYTHONPATH="$JYS" python3 "$JYS/scripts/launch_lidmark_training.py" "2, 3" 20260603
echo "  LIDMark: GPU 2,3 | log: runs/lidmark/train_seed20260603.log"

# KAD-Net on GPU 4
PYTHONPATH="$JYS" python3 "$JYS/scripts/launch_kadnet_training.py" "4"
echo "  KAD-Net: GPU 4   | log: runs/kadnet/train_ST.log"

echo ""
echo "=== ALL TRAINING LAUNCHED ==="
echo "Monitor LIDMark: tail -f /data1/luxliang/work/vpsg_competition_candidates/runs/lidmark/train_seed20260603.log"
echo "Monitor KAD-Net: tail -f /data1/luxliang/work/vpsg_competition_candidates/runs/kadnet/train_ST.log"
