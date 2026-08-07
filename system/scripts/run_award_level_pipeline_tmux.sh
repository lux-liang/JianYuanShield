#!/usr/bin/env bash
set -euo pipefail

ROOT="${JYS_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUNTIME_ROOT="${JYS_RUNTIME_ROOT:-$ROOT/runtime}"
MODEL_SOURCE_ROOT="${JYS_MODEL_SOURCE_ROOT:-$RUNTIME_ROOT/model-sources}"
DATA_ROOT="${JYS_DATA_ROOT:-$RUNTIME_ROOT/data}"
WEIGHT_ROOT="${JYS_WEIGHT_ROOT:-$RUNTIME_ROOT/weights}"
REPORT_ROOT="${JYS_REPORT_ROOT:-$RUNTIME_ROOT/reports}"
ASSET_ROOT="${JYS_ASSET_ROOT:-$RUNTIME_ROOT/assets}"
PY="${JYS_BENCHMARK_PYTHON:-python3}"
GPU_LANE_2="${JYS_GPU_LANE_2:-2}"
GPU_LANE_7="${JYS_GPU_LANE_7:-7}"
FORMAL_N="${JYS_FORMAL_SAMPLE_COUNT:-13233}"
SEED="${JYS_BENCHMARK_SEED:-20260603}"
MIN_FREE_GPU_MIB="${JYS_MIN_FREE_GPU_MIB:-30000}"
RUN_ID="${JYS_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
SESSION="${JYS_TMUX_SESSION:-jys_formal_${RUN_ID}}"
SCRIPT_PATH="$ROOT/system/scripts/run_award_level_pipeline_tmux.sh"

export JYS_PROJECT_ROOT="$ROOT"
export JYS_RUNTIME_ROOT="$RUNTIME_ROOT"
export JYS_MODEL_SOURCE_ROOT="$MODEL_SOURCE_ROOT"
export JYS_DATA_ROOT="$DATA_ROOT"
export JYS_WEIGHT_ROOT="$WEIGHT_ROOT"
export JYS_REPORT_ROOT="$REPORT_ROOT"
export JYS_ASSET_ROOT="$ASSET_ROOT"
export JYS_BENCHMARK_PYTHON="$PY"

KAD_IMAGE_ROOT="$DATA_ROOT/lfw/processed/image/lfw_128"
SEP_IMAGE_ROOT="$DATA_ROOT/lfw/processed/image/lfw_256"
KAD_CHECKPOINT="$WEIGHT_ROOT/KAD-Net/ST/128/models/EC_100.pth"
SEP_CHECKPOINT="$WEIGHT_ROOT/MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth"
KAD_REPORT="$REPORT_ROOT/kadnet-lfw-protocol-v1-full-${RUN_ID}"
SEP_REPORT="$REPORT_ROOT/sepmark-lfw-protocol-v1-full-${RUN_ID}"
KAD_ASSETS="$ASSET_ROOT/kadnet-lfw-protocol-v1-full-${RUN_ID}"
SEP_ASSETS="$ASSET_ROOT/sepmark-lfw-protocol-v1-full-${RUN_ID}"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

require_file() {
  [[ -f "$1" ]] || die "required file missing: $1"
}

require_dir() {
  [[ -d "$1" ]] || die "required directory missing: $1"
}

write_worker_exit() {
  local code="$1"
  local report="$2"
  printf '%s\n' "$code" > "$report/worker.exit"
}

run_gpu2_worker() {
  local report="$SEP_REPORT"
  local code=0
  mkdir -p "$report" "$SEP_ASSETS"
  cd "$ROOT"
  CUDA_VISIBLE_DEVICES="$GPU_LANE_2" "$PY" system/scripts/run_sepmark_lfw_benchmark.py \
    --num-images "$FORMAL_N" \
    --image-root "$SEP_IMAGE_ROOT" \
    --checkpoint "$SEP_CHECKPOINT" \
    --report-dir "$report" \
    --asset-dir "$SEP_ASSETS" \
    --device cuda:0 \
    --seed "$SEED" \
    --flush-every 128 \
    2>&1 | tee "$report/stdout.log" || code=$?
  if [[ "$code" -eq 0 ]]; then
    CUDA_VISIBLE_DEVICES="$GPU_LANE_2" "$PY" scripts/capture_experiment_context.py \
      --output "$report/context" \
      --source "$MODEL_SOURCE_ROOT/MEA" \
      --checkpoint "$SEP_CHECKPOINT" \
      --dataset-manifest "$report/dataset_manifest.json" \
      --summary "$report/summary.json" \
      --benchmark-command "$PY" system/scripts/run_sepmark_lfw_benchmark.py \
      --num-images "$FORMAL_N" --seed "$SEED" || code=$?
  fi
  write_worker_exit "$code" "$report"
  return "$code"
}

run_gpu7_worker() {
  local report="$KAD_REPORT"
  local code=0
  mkdir -p "$report" "$KAD_ASSETS"
  cd "$ROOT"
  CUDA_VISIBLE_DEVICES="$GPU_LANE_7" "$PY" system/scripts/run_kadnet_lfw_benchmark.py \
    --num-images "$FORMAL_N" \
    --image-root "$KAD_IMAGE_ROOT" \
    --checkpoint "$KAD_CHECKPOINT" \
    --report-dir "$report" \
    --asset-dir "$KAD_ASSETS" \
    --device cuda:0 \
    --seed "$SEED" \
    --flush-every 128 \
    2>&1 | tee "$report/stdout.log" || code=$?
  if [[ "$code" -eq 0 ]]; then
    CUDA_VISIBLE_DEVICES="$GPU_LANE_7" "$PY" scripts/capture_experiment_context.py \
      --output "$report/context" \
      --source "$MODEL_SOURCE_ROOT/KAD-Net" \
      --checkpoint "$KAD_CHECKPOINT" \
      --dataset-manifest "$report/dataset_manifest.json" \
      --summary "$report/summary.json" \
      --benchmark-command "$PY" system/scripts/run_kadnet_lfw_benchmark.py \
      --num-images "$FORMAL_N" --seed "$SEED" || code=$?
  fi
  write_worker_exit "$code" "$report"
  return "$code"
}

if [[ "${1:-}" == "__worker_gpu2" ]]; then
  run_gpu2_worker
  exit $?
fi
if [[ "${1:-}" == "__worker_gpu7" ]]; then
  run_gpu7_worker
  exit $?
fi

[[ "$GPU_LANE_2" =~ ^[0-9]+$ ]] || die "JYS_GPU_LANE_2 must be one physical GPU index"
[[ "$GPU_LANE_7" =~ ^[0-9]+$ ]] || die "JYS_GPU_LANE_7 must be one physical GPU index"
[[ "$GPU_LANE_2" != "$GPU_LANE_7" ]] || die "GPU lanes must be distinct"
[[ "$FORMAL_N" =~ ^[1-9][0-9]*$ ]] || die "JYS_FORMAL_SAMPLE_COUNT must be positive"
[[ "$SEED" =~ ^[0-9]+$ ]] || die "JYS_BENCHMARK_SEED must be non-negative"
[[ "$MIN_FREE_GPU_MIB" =~ ^[0-9]+$ ]] || die "JYS_MIN_FREE_GPU_MIB must be non-negative"
[[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || die "JYS_RUN_ID contains unsafe characters"
[[ "$SESSION" =~ ^[A-Za-z0-9._-]+$ ]] || die "JYS_TMUX_SESSION contains unsafe characters"

command -v tmux >/dev/null || die "tmux is required"
command -v nvidia-smi >/dev/null || die "nvidia-smi is required"
if [[ "$PY" == */* ]]; then
  [[ -x "$PY" ]] || die "benchmark Python is not executable: $PY"
else
  command -v "$PY" >/dev/null || die "benchmark Python not found: $PY"
fi

require_dir "$KAD_IMAGE_ROOT"
require_dir "$SEP_IMAGE_ROOT"
require_dir "$MODEL_SOURCE_ROOT/KAD-Net/.git"
require_dir "$MODEL_SOURCE_ROOT/MEA/.git"
require_file "$KAD_CHECKPOINT"
require_file "$SEP_CHECKPOINT"
[[ ! -e "$KAD_REPORT" && ! -e "$SEP_REPORT" ]] || die "run ID already has report output"
[[ ! -e "$KAD_ASSETS" && ! -e "$SEP_ASSETS" ]] || die "run ID already has asset output"
tmux has-session -t "$SESSION" 2>/dev/null && die "tmux session already exists: $SESSION"

for gpu in "$GPU_LANE_2" "$GPU_LANE_7"; do
  free_mib="$(nvidia-smi --id="$gpu" --query-gpu=memory.free --format=csv,noheader,nounits | tr -d '[:space:]')"
  [[ "$free_mib" =~ ^[0-9]+$ ]] || die "cannot query free memory for GPU $gpu"
  (( free_mib >= MIN_FREE_GPU_MIB )) || die "GPU $gpu has only ${free_mib} MiB free"
done

gpu2_command=(env
  JYS_PROJECT_ROOT="$ROOT" JYS_RUNTIME_ROOT="$RUNTIME_ROOT"
  JYS_MODEL_SOURCE_ROOT="$MODEL_SOURCE_ROOT" JYS_DATA_ROOT="$DATA_ROOT"
  JYS_WEIGHT_ROOT="$WEIGHT_ROOT" JYS_REPORT_ROOT="$REPORT_ROOT"
  JYS_ASSET_ROOT="$ASSET_ROOT" JYS_BENCHMARK_PYTHON="$PY"
  JYS_GPU_LANE_2="$GPU_LANE_2" JYS_GPU_LANE_7="$GPU_LANE_7"
  JYS_FORMAL_SAMPLE_COUNT="$FORMAL_N" JYS_BENCHMARK_SEED="$SEED"
  JYS_RUN_ID="$RUN_ID" "$SCRIPT_PATH" __worker_gpu2)
gpu7_command=(env
  JYS_PROJECT_ROOT="$ROOT" JYS_RUNTIME_ROOT="$RUNTIME_ROOT"
  JYS_MODEL_SOURCE_ROOT="$MODEL_SOURCE_ROOT" JYS_DATA_ROOT="$DATA_ROOT"
  JYS_WEIGHT_ROOT="$WEIGHT_ROOT" JYS_REPORT_ROOT="$REPORT_ROOT"
  JYS_ASSET_ROOT="$ASSET_ROOT" JYS_BENCHMARK_PYTHON="$PY"
  JYS_GPU_LANE_2="$GPU_LANE_2" JYS_GPU_LANE_7="$GPU_LANE_7"
  JYS_FORMAL_SAMPLE_COUNT="$FORMAL_N" JYS_BENCHMARK_SEED="$SEED"
  JYS_RUN_ID="$RUN_ID" "$SCRIPT_PATH" __worker_gpu7)
printf -v gpu2_shell '%q ' "${gpu2_command[@]}"
printf -v gpu7_shell '%q ' "${gpu7_command[@]}"

if [[ "${JYS_PIPELINE_DRY_RUN:-false}" == "true" ]]; then
  printf 'session=%s\nGPU %s: %s\nGPU %s: %s\n' \
    "$SESSION" "$GPU_LANE_2" "$gpu2_shell" "$GPU_LANE_7" "$gpu7_shell"
  exit 0
fi

tmux new-session -d -s "$SESSION" -n sepmark "$gpu2_shell"
tmux new-window -t "$SESSION" -n kadnet "$gpu7_shell"

printf 'started tmux session: %s\n' "$SESSION"
printf 'SepMark report: %s\nKAD-Net report: %s\n' "$SEP_REPORT" "$KAD_REPORT"
tmux list-windows -t "$SESSION"
