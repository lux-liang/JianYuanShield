#!/usr/bin/env bash
set -euo pipefail

ROOT="${JYS_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SESSION="${SESSION:-jianyuanshield_pipeline}"
PY="${JYS_BENCHMARK_PYTHON:-$ROOT/.venvs/lidmark/bin/python}"

tmux has-session -t "$SESSION" 2>/dev/null && {
  echo "tmux session already running: $SESSION"
  tmux list-windows -t "$SESSION"
  exit 0
}

tmux new-session -d -s "$SESSION" -n hidden "cd '$ROOT' && CUDA_VISIBLE_DEVICES=0 '$PY' system/scripts/run_hidden_benchmark_real_small.py --num_images 13233 --attacks clean jpeg resize noise --device cuda:0 | tee system/reports/hidden_lfw_full_benchmark/tmux.log"
tmux new-window -t "$SESSION" -n lidmark "cd '$ROOT' && CUDA_VISIBLE_DEVICES=0 '$PY' system/scripts/run_lidmark_lfw_eval.py --num_images 512 --attacks clean jpeg resize noise --res 128 --device cuda:0 | tee runs/lidmark_lfw_eval_full/tmux.log"
tmux new-window -t "$SESSION" -n waveguard "cd '$ROOT' && '$PY' system/scripts/run_waveguard_lfw_benchmark.py | tee system/reports/waveguard_lfw_benchmark/tmux.log"
tmux new-window -t "$SESSION" -n sepmark "cd '$ROOT' && CUDA_VISIBLE_DEVICES=0 '$PY' system/scripts/run_sepmark_lfw_benchmark.py --num-images 13233 --attacks clean jpeg resize noise --device cuda:0 | tee system/reports/sepmark_lfw_benchmark/tmux.log"
tmux new-window -t "$SESSION" -n aggregate "cd '$ROOT'; while true; do '$PY' system/scripts/aggregate_real_benchmarks.py; '$PY' system/scripts/export_competition_report.py; sleep 120; done"
tmux new-window -t "$SESSION" -n health "cd '$ROOT'; while true; do date; curl -s http://127.0.0.1:8026/api/health || true; echo; curl -s http://127.0.0.1:8026/api/artifacts/status | head -c 1000 || true; echo; sleep 60; done"

echo "started tmux session: $SESSION"
tmux list-windows -t "$SESSION"
