#!/usr/bin/env bash
# 鉴源盾 大规模实验 campaign —— 5 条 GPU lane 并行, 每 lane 内顺序跑, 避免超额占卡.
# 在 box 上以 nohup 后台运行: nohup bash scripts/run_campaign.sh > runs/logs/campaign/_nohup.log 2>&1 &
set -u
cd ~/JianYuanShield
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate pytorch_env
export PYTHONPATH=.
LOG=runs/logs/campaign
mkdir -p "$LOG"
DS=/data1/luxliang/datasets/deepfake_images_extracted
LFW=/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown
AE=system/reports/face_autoencoder/checkpoints/best.pt

run(){ # gpu name cmd...
  local gpu=$1 name=$2; shift 2
  echo "[$(date +%H:%M:%S)] START $name cuda:$gpu :: $*" >> "$LOG/_campaign.log"
  "$@" --device "cuda:$gpu" > "$LOG/$name.log" 2>&1
  local rc=$?
  echo "[$(date +%H:%M:%S)] DONE  $name rc=$rc" >> "$LOG/_campaign.log"
}

WM=system/scripts/run_watermark_dataset_benchmark.py
TL=system/scripts/run_tamper_localization_splice.py
RG=system/scripts/run_regeneration_attack.py

echo "[$(date +%H:%M:%S)] CAMPAIGN START" >> "$LOG/_campaign.log"

# ── GPU3: 自训练AE(40ep) → 再生成攻击闭环×5 模型 ─────────────────────────────
( run 3 ae_train python system/scripts/train_face_autoencoder.py --epochs 40 --batch-size 64 --out system/reports/face_autoencoder
  for m in kadnet waveguard hidden sepmark lidmark; do
    run 3 regen_$m python $RG --model $m --ae-checkpoint "$AE" --image-root $DS/Real --num-images 1000
  done
) &

# ── GPU4: 被动检测器(20ep)+OOD泛化 → 篡改定位(waveguard,sepmark) ────────────
( run 4 detector python system/scripts/train_passive_detector.py --epochs 20 --batch-size 128 --num-workers 4 --data-root $DS --out system/reports/passive_detector --ood-real-root $LFW
  run 4 tamper_waveguard python $TL --model waveguard --num-images 200 --grid 8 --save-heatmaps 6
  run 4 tamper_sepmark   python $TL --model sepmark   --num-images 200 --grid 8 --save-heatmaps 6
) &

# ── GPU5: Track A 真实脸 kadnet,hidden → AIGC假脸 kadnet,hidden ──────────────
( for m in kadnet hidden; do run 5 trackA_real_$m python $WM --model $m --image-root $DS/Real --report-subdir ${m}_deepfakeset_real --num-images 5000; done
  for m in kadnet hidden; do run 5 trackA_fake_$m python $WM --model $m --image-root $DS/Fake --report-subdir ${m}_deepfakeset_fake --num-images 2000; done
) &

# ── GPU6: Track A 真实脸 waveguard,sepmark → AIGC假脸 waveguard,sepmark ──────
( for m in waveguard sepmark; do run 6 trackA_real_$m python $WM --model $m --image-root $DS/Real --report-subdir ${m}_deepfakeset_real --num-images 5000; done
  for m in waveguard sepmark; do run 6 trackA_fake_$m python $WM --model $m --image-root $DS/Fake --report-subdir ${m}_deepfakeset_fake --num-images 2000; done
) &

# ── GPU7: Track A lidmark(真/假) → 篡改定位(kadnet,hidden,lidmark) ───────────
( run 7 trackA_real_lidmark python $WM --model lidmark --image-root $DS/Real --report-subdir lidmark_deepfakeset_real --num-images 5000
  run 7 trackA_fake_lidmark python $WM --model lidmark --image-root $DS/Fake --report-subdir lidmark_deepfakeset_fake --num-images 2000
  for m in kadnet hidden lidmark; do run 7 tamper_$m python $TL --model $m --num-images 200 --grid 8 --save-heatmaps 6; done
) &

wait
echo "[$(date +%H:%M:%S)] CAMPAIGN ALL DONE" >> "$LOG/_campaign.log"
