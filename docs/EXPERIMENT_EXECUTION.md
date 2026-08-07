# 鉴源盾国赛实验执行手册

更新时间：2026-08-04

本文件只描述当前可执行、可复核的正式实验流程。评测语义唯一来源是 `configs/evaluation_protocol.v1.json`，发布门禁唯一来源是 `configs/claims_manifest.v1.json`。实验人员不手工填写性能结论，也不手工修改 `claim_valid`；所有结论必须从逐图原始记录、内容哈希和签名清单生成。

## 1. 固定运行环境

正式实验使用服务器的 **H100 2/7**。物理 GPU 2 串行执行 LIDMark、SepMark，物理 GPU 7 串行执行 KAD-Net、WaveGuard；同一物理 GPU 同时只运行一个正式任务。设置 `CUDA_VISIBLE_DEVICES=2` 或 `7` 后，进程内设备统一写作 `cuda:0`。

仓库只保存代码、协议和小型索引；数据、权重、报告及可视化放在仓库外的 `JYS_RUNTIME_ROOT`。从仓库根目录执行：

```bash
export JYS_PROJECT_ROOT="$(pwd -P)"
: "${JYS_RUNTIME_ROOT:?必须设置仓库外的 JianYuanShield runtime 目录}"

export JYS_MODEL_SOURCE_ROOT="$JYS_RUNTIME_ROOT/model-sources"
export JYS_WEIGHT_ROOT="$JYS_RUNTIME_ROOT/weights"
export JYS_DATA_ROOT="$JYS_RUNTIME_ROOT/data"
export JYS_REPORT_ROOT="$JYS_RUNTIME_ROOT/reports"
export JYS_ASSET_ROOT="$JYS_RUNTIME_ROOT/assets"

export JYS_BENCHMARK_PYTHON="${JYS_BENCHMARK_PYTHON:-$JYS_PROJECT_ROOT/.venv/bin/python}"
test -x "$JYS_BENCHMARK_PYTHON" || {
  echo "缺少项目虚拟环境；先按 README 的锁文件安装命令创建 .venv" >&2
  exit 2
}
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$JYS_PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p \
  "$JYS_MODEL_SOURCE_ROOT" \
  "$JYS_WEIGHT_ROOT" \
  "$JYS_DATA_ROOT" \
  "$JYS_REPORT_ROOT" \
  "$JYS_ASSET_ROOT"

cd "$JYS_PROJECT_ROOT"
nvidia-smi -i 2,7 \
  --query-gpu=index,name,uuid,memory.total,memory.used,memory.free,utilization.gpu \
  --format=csv
df -h "$JYS_RUNTIME_ROOT" "$JYS_PROJECT_ROOT"
```

解释器必须使用项目内由 `requirements.lock` 创建的隔离环境；不得借用其他项目或模型仓库的虚拟环境。`PYTHONDONTWRITEBYTECODE=1` 防止模型源码快照因导入产生未登记的 `__pycache__` 变化。

## 2. 协议门禁

正式基准固定使用协议 seed、15 个 canonical attack ID 和 `0.9` success threshold。四个正式入口均从协议加载这些值；Stage C 命令不得传入缩减攻击集，也不得使用 `jpeg`、`resize`、`noise` 等旧别名。

启动任何 GPU 任务前执行：

```bash
"$JYS_BENCHMARK_PYTHON" - <<'PY'
import json
from pathlib import Path

protocol = json.loads(Path("configs/evaluation_protocol.v1.json").read_text())
attack_ids = [item["id"] for item in protocol["attacks"]]
assert protocol["schema_version"] == "evaluation_protocol.v1"
assert protocol["seed"] == 20260603
assert protocol["success_threshold"] == 0.9
assert len(attack_ids) == 15
assert len(set(attack_ids)) == 15
print({"seed": protocol["seed"], "threshold": protocol["success_threshold"], "attacks": attack_ids})
PY

"$JYS_BENCHMARK_PYTHON" -c \
  'import cv2, easydict, kornia, lpips, pywt, pytorch_wavelets, skimage, torch; print(torch.__version__)'

"$JYS_BENCHMARK_PYTHON" scripts/check_documentation.py
"$JYS_BENCHMARK_PYTHON" scripts/check_system.py
"$JYS_BENCHMARK_PYTHON" -m unittest discover -s tests -v
```

canonical attack 顺序为：

```text
clean
jpeg50
jpeg70
jpeg90
resize_0.5x
gaussian_noise_sigma_3
crop_center_0.8
rotate_5
gaussian_blur_5
brightness_0.85
contrast_1.2
webp50
platform_wechat_v1
platform_douyin_v1
deepfake_proxy_v1
```

`platform_*` 与 `deepfake_proxy_v1` 是协议登记的确定性代理攻击，不替代真实平台回传或真实换脸实验。

## 3. 冻结输入

### 3.1 数据目录

当前正式入口使用以下冻结数据：

| 模型 | 数据根 | 输入规格 | 选择方式 |
|---|---|---:|---|
| LIDMark | `data/lfw/lidmark_identity_disjoint` | 128×128 RGB、152-D payload | 冻结的 identity-disjoint test split |
| KAD-Net | `data/lfw/processed/image/lfw_128` | 128×128 RGB | dataset-relative path 排序 |
| SepMark | `data/lfw/processed/image/lfw_256` | 256×256 RGB | dataset-relative path 排序 |
| WaveGuard | `data/lfw/processed/image/lfw_256` | 256×256 RGB | dataset-relative path 排序，并生成 identity-aware manifest |

不得再使用已废弃的 `lfw_full_upload/unknown` 路径。正式入口会冻结逐文件大小和 SHA-256；LIDMark 还复核 split、identity map、image/payload 配对及身份集合零交叉，WaveGuard 还记录匿名 identity hash 与身份分布摘要。

### 3.2 checkpoint 与选择证据

| 模型 | 正式 checkpoint | 选择约束 |
|---|---|---|
| LIDMark | `weights/lidmark/lfw-id-s20260603-128/checkpoint_epoch_20.pth` | 必须由 `reports/lidmark-train-lfw-id-s20260603-128/model_selection.json` 选择 epoch 20，并匹配冻结 training config、checkpoint 大小和 SHA-256 |
| KAD-Net | `weights/KAD-Net/ST/128/models/EC_100.pth` | 显式固定路径，strict adapter load |
| SepMark | `weights/MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth` | 必须匹配 `sepmark-official-smoke-20260804` 的冻结同样本选择证据及 SHA-256 |
| WaveGuard | `weights/MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth` | 固定内容地址；encoder、tracer、detector 均 `weights_only=True`、`strict=True` |

LIDMark 的 `model_selection.json` 必须满足：训练状态 complete、20 个 epoch 的 checkpoint 完整性全部通过、候选指标与梯度全部有限、strict CPU reload 通过，再按登记策略选择。正式评测入口会在推理前后重新散列源码、training config、selection report、checkpoint、协议、数据和评测实现；任一变化都会终止完成态。

源码快照至少保留 remote、commit、许可证和 tree hash：

```bash
git -C "$JYS_MODEL_SOURCE_ROOT/LIDMark" remote -v
git -C "$JYS_MODEL_SOURCE_ROOT/LIDMark" rev-parse HEAD
git -C "$JYS_MODEL_SOURCE_ROOT/KAD-Net" remote -v
git -C "$JYS_MODEL_SOURCE_ROOT/KAD-Net" rev-parse HEAD
git -C "$JYS_MODEL_SOURCE_ROOT/MEA" remote -v
git -C "$JYS_MODEL_SOURCE_ROOT/MEA" rev-parse HEAD
```

## 4. 当前 evidence-grade 入口

| 模型 | 唯一正式入口 | 主判据 | 正式原始结果 |
|---|---|---|---|
| LIDMark | `system/scripts/run_lidmark_lfw_benchmark.py` | 16-bit identity `bit_accuracy >= 0.9` | `raw_results.csv`，同时记录 identity exact match 与 landmark AED |
| KAD-Net | `system/scripts/run_kadnet_lfw_benchmark.py` | 30-bit `bit_accuracy >= 0.9` | `results.csv` 与 `watermarked_quality.csv` |
| SepMark | `system/scripts/run_sepmark_lfw_benchmark.py` | `decoder_C bit_accuracy >= 0.9` | `results.csv`；`decoder_RF` 仅独立报告 |
| WaveGuard | `system/scripts/run_waveguard_lfw_benchmark.py` | `tracer bit_accuracy >= 0.9` | `results.csv`；`detector` 仅独立报告 |

以下入口不再用于正式证据：

- `system/scripts/run_lidmark_lfw_eval.py`；
- 历史 WaveGuard full/small runner 与历史同名产物；
- 任何只做 checkpoint smoke、随机消息或旧攻击别名展开的脚本。

每个正式 runner 都把成功判据锁进 `run_config.json`，错误写入对应逐图原始行。出现 error row、missing row、重复 key、NaN、消息漂移、攻击配置漂移、绝对 host path 或哈希不一致时，不得生成完成态 `benchmark-summary.v2`。

## 5. Stage B：真实 checkpoint 小样本门禁

小样本门禁只验证真实模型链路与证据结构，不登记性能结论。报告目录必须是新的 smoke 目录。SepMark、KAD-Net、WaveGuard 只使用 canonical attack ID；LIDMark 入口固定执行完整协议攻击集。

GPU 2 串行执行：

```bash
set -euo pipefail
export SMOKE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"

CUDA_VISIBLE_DEVICES=2 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_lidmark_lfw_benchmark.py \
  --num-images 16 \
  --device cuda:0 \
  --expected-physical-gpu 2 \
  --report-dir "$JYS_REPORT_ROOT/smoke/lidmark-$SMOKE_TAG"

CUDA_VISIBLE_DEVICES=2 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_sepmark_lfw_benchmark.py \
  --num-images 16 \
  --attacks clean jpeg70 resize_0.5x gaussian_noise_sigma_3 crop_center_0.8 rotate_5 \
  --device cuda:0 \
  --report-dir "$JYS_REPORT_ROOT/smoke/sepmark-$SMOKE_TAG" \
  --asset-dir "$JYS_ASSET_ROOT/smoke/sepmark-$SMOKE_TAG"
```

GPU 7 串行执行：

```bash
set -euo pipefail
export SMOKE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"

CUDA_VISIBLE_DEVICES=7 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_kadnet_lfw_benchmark.py \
  --num-images 16 \
  --attacks clean jpeg70 resize_0.5x gaussian_noise_sigma_3 crop_center_0.8 rotate_5 \
  --device cuda:0 \
  --report-dir "$JYS_REPORT_ROOT/smoke/kadnet-$SMOKE_TAG" \
  --asset-dir "$JYS_ASSET_ROOT/smoke/kadnet-$SMOKE_TAG"

CUDA_VISIBLE_DEVICES=7 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_waveguard_lfw_benchmark.py \
  --num-images 16 \
  --attacks clean jpeg70 resize_0.5x gaussian_noise_sigma_3 crop_center_0.8 rotate_5 \
  --device cuda:0 \
  --report-dir "$JYS_REPORT_ROOT/smoke/waveguard-$SMOKE_TAG" \
  --asset-dir "$JYS_ASSET_ROOT/smoke/waveguard-$SMOKE_TAG"
```

后一条命令只在同一 GPU 上前一条命令退出码为 0 后启动。smoke 目录不得复用为 Stage C 正式目录。

## 6. Stage C：正式 LFW 基准

Stage C 不设置手写样本数，不传 `--attacks`，直接使用各 runner 的冻结默认样本集、协议 seed、全 15 项攻击和 `0.9` threshold。KAD-Net、SepMark、WaveGuard 始终写入新的 run-specific reports/assets 同名目录；canonical 名称只由验收脚本创建为 symlink，runner 不得直接写入。只有完全相同的 run config 才允许在原 run-specific 目录断点续跑。

### 6.1 GPU 2 队列：LIDMark → SepMark

```bash
set -euo pipefail
export SEPMARK_RUN_ID="sepmark-lfw-protocol-v1-full-s20260603"
export SEPMARK_REPORT_DIR="$JYS_REPORT_ROOT/$SEPMARK_RUN_ID"
export SEPMARK_ASSET_DIR="$JYS_ASSET_ROOT/$SEPMARK_RUN_ID"

mkdir -p \
  "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1" \
  "$SEPMARK_REPORT_DIR" \
  "$SEPMARK_ASSET_DIR"

CUDA_VISIBLE_DEVICES=2 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_lidmark_lfw_benchmark.py \
  --device cuda:0 \
  --expected-physical-gpu 2 \
  --report-dir "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1" \
  --flush-every 25 \
  2>&1 | tee "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1/stdout.log"

CUDA_VISIBLE_DEVICES=2 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_sepmark_lfw_benchmark.py \
  --device cuda:0 \
  --report-dir "$SEPMARK_REPORT_DIR" \
  --asset-dir "$SEPMARK_ASSET_DIR" \
  --artifact-limit 16 \
  --flush-every 100 \
  2>&1 | tee "$SEPMARK_REPORT_DIR/stdout.log"

```

### 6.2 GPU 7 队列：KAD-Net → WaveGuard

```bash
set -euo pipefail
export KADNET_RUN_ID="kadnet-lfw-protocol-v1-full-s20260603"
export KADNET_REPORT_DIR="$JYS_REPORT_ROOT/$KADNET_RUN_ID"
export KADNET_ASSET_DIR="$JYS_ASSET_ROOT/$KADNET_RUN_ID"
export WAVEGUARD_RUN_ID="waveguard-lfw-protocol-v1-full-s20260603"
export WAVEGUARD_REPORT_DIR="$JYS_REPORT_ROOT/$WAVEGUARD_RUN_ID"
export WAVEGUARD_ASSET_DIR="$JYS_ASSET_ROOT/$WAVEGUARD_RUN_ID"

mkdir -p \
  "$KADNET_REPORT_DIR" \
  "$KADNET_ASSET_DIR" \
  "$WAVEGUARD_REPORT_DIR" \
  "$WAVEGUARD_ASSET_DIR"

CUDA_VISIBLE_DEVICES=7 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_kadnet_lfw_benchmark.py \
  --device cuda:0 \
  --report-dir "$KADNET_REPORT_DIR" \
  --asset-dir "$KADNET_ASSET_DIR" \
  --artifact-limit 16 \
  --flush-every 100 \
  2>&1 | tee "$KADNET_REPORT_DIR/stdout.log"

CUDA_VISIBLE_DEVICES=7 PYTHONDONTWRITEBYTECODE=1 \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_waveguard_lfw_benchmark.py \
  --device cuda:0 \
  --report-dir "$WAVEGUARD_REPORT_DIR" \
  --asset-dir "$WAVEGUARD_ASSET_DIR" \
  --artifact-limit 16 \
  --flush-every 100 \
  2>&1 | tee "$WAVEGUARD_REPORT_DIR/stdout.log"

```

两个 GPU 队列可以并行；每个队列内部严格串行。不得在同一物理 GPU 上同时运行 benchmark、训练、诊断或可视化任务。

### 6.3 断点续跑

LIDMark 使用同一条正式命令并增加 `--resume`。SepMark、KAD-Net、WaveGuard 直接重复同一条正式命令，runner 会验证现有 manifest、run config 与 raw rows，并只重跑 missing/error 行。续跑时不得改变 checkpoint、seed、样本数、攻击列表、report/asset 目录或 artifact limit。

任何 runner 返回非零、`summary.json` 为 incomplete、`progress.json` 非 complete 或存在 error row 时，队列立即停止，后续模型不得启动。

## 7. 正式产物与验收

### 7.1 runner 原生证据

LIDMark 正式目录必须包含：

```text
reports/lidmark_lfw_identity_test_epoch20_protocol_v1/
├── dataset_manifest.json
├── raw_results.csv
├── run_config.json
├── progress.json
├── summary.json
└── stdout.log
```

SepMark、KAD-Net 的 run-specific 报告目录必须包含：

```text
dataset_manifest.json
results.csv
watermarked_quality.csv
run_config.json
progress.json
summary.json
stdout.log
```

WaveGuard 在上述对象之外还必须包含 `artifact_manifest.json`；其 `summary.json` 还记录 runner、兼容入口、progress 与 artifact manifest 的 SHA-256。三个模型的同名 run-specific asset 目录只能包含 `sample_<五位序号>` 形式目录内的 PNG 与可选 `grid.png`。逐图错误直接保留在 raw CSV 的 `error` 字段，不另造与 runner 不一致的 `failures.csv`。

### 7.2 `summary.json` 完成门禁

每个正式 summary 必须同时满足：

- `schema_version == "benchmark-summary.v2"`；
- `status == "complete"`，且 progress 同为 complete；
- `attack_ids` 与协议顺序完全一致，`expected_result_rows == sample_count * 15`；
- `error_rows == 0`、`missing_rows == 0`，逐图 key 唯一；
- checkpoint、protocol、dataset manifest、raw results 的 SHA-256 非空且与文件重算一致；
- SepMark/WaveGuard 的 primary/secondary decoder 与协议一致，success 只由 primary decoder 决定；
- watermarked quality 与 attacked quality 使用各自登记的 reference，不得互换；
- LIDMark 的 `input_integrity_audit.status == "verified"`、`preflight_postflight_match == true`、identity overlap 全为零，并绑定 epoch-20 selection report；
- WaveGuard 的 identity distribution、quality CSV、run config、artifact manifest、progress 与 runner hash 全部存在。

完成后抽查哈希：

```bash
export SEPMARK_RUN_ID="sepmark-lfw-protocol-v1-full-s20260603"
export KADNET_RUN_ID="kadnet-lfw-protocol-v1-full-s20260603"
export WAVEGUARD_RUN_ID="waveguard-lfw-protocol-v1-full-s20260603"

sha256sum \
  "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1/summary.json" \
  "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1/raw_results.csv" \
  "$JYS_REPORT_ROOT/$SEPMARK_RUN_ID/summary.json" \
  "$JYS_REPORT_ROOT/$SEPMARK_RUN_ID/results.csv" \
  "$JYS_REPORT_ROOT/$KADNET_RUN_ID/summary.json" \
  "$JYS_REPORT_ROOT/$KADNET_RUN_ID/results.csv" \
  "$JYS_REPORT_ROOT/$WAVEGUARD_RUN_ID/summary.json" \
  "$JYS_REPORT_ROOT/$WAVEGUARD_RUN_ID/results.csv"
```

`stdout.log` 是运行诊断记录；用于答辩证据时必须另外登记 SHA-256。summary 和逐图原始记录才是指标重算的权威来源。

## 8. 冻结实验上下文

正式 summary 完成后，用 `scripts/capture_experiment_context.py` 生成源码、checkpoint、依赖、GPU、磁盘与 dataset manifest 证据，并把这些对象的路径和 SHA-256 回写到 summary。以下函数用于四个正式 run：

```bash
set -euo pipefail
export SEPMARK_RUN_ID="sepmark-lfw-protocol-v1-full-s20260603"
export KADNET_RUN_ID="kadnet-lfw-protocol-v1-full-s20260603"
export WAVEGUARD_RUN_ID="waveguard-lfw-protocol-v1-full-s20260603"

capture_context() {
  run_id="$1"
  source_root="$2"
  checkpoint="$3"
  report_dir="$4"
  results_name="$5"
  shift 5

  "$JYS_BENCHMARK_PYTHON" scripts/capture_experiment_context.py \
    --output "$JYS_REPORT_ROOT/experiment_context/$run_id" \
    --source "$source_root" \
    --checkpoint "$checkpoint" \
    --dataset-manifest "$report_dir/dataset_manifest.json" \
    --summary "$report_dir/summary.json" \
    --benchmark-command "$@"

  sha256sum "$report_dir/$results_name" "$report_dir/summary.json"
}

capture_context \
  lidmark_lfw_identity_test_epoch20_protocol_v1 \
  "$JYS_MODEL_SOURCE_ROOT/LIDMark" \
  "$JYS_WEIGHT_ROOT/lidmark/lfw-id-s20260603-128/checkpoint_epoch_20.pth" \
  "$JYS_REPORT_ROOT/lidmark_lfw_identity_test_epoch20_protocol_v1" \
  raw_results.csv \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_lidmark_lfw_benchmark.py

capture_context \
  "$SEPMARK_RUN_ID" \
  "$JYS_MODEL_SOURCE_ROOT/MEA" \
  "$JYS_WEIGHT_ROOT/MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth" \
  "$JYS_REPORT_ROOT/$SEPMARK_RUN_ID" \
  results.csv \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_sepmark_lfw_benchmark.py

capture_context \
  "$KADNET_RUN_ID" \
  "$JYS_MODEL_SOURCE_ROOT/KAD-Net" \
  "$JYS_WEIGHT_ROOT/KAD-Net/ST/128/models/EC_100.pth" \
  "$JYS_REPORT_ROOT/$KADNET_RUN_ID" \
  results.csv \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_kadnet_lfw_benchmark.py

capture_context \
  "$WAVEGUARD_RUN_ID" \
  "$JYS_MODEL_SOURCE_ROOT/MEA" \
  "$JYS_WEIGHT_ROOT/MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth" \
  "$JYS_REPORT_ROOT/$WAVEGUARD_RUN_ID" \
  results.csv \
  "$JYS_BENCHMARK_PYTHON" system/scripts/run_waveguard_lfw_benchmark.py
```

每个 context 使用对应 run ID 独占目录，且只能包含 `source_manifest.json`、`checkpoint_manifest.json`、`environment.json` 和 `hashes.sha256`。回写后的 summary 必须包含对应的 `*_path` 与 `*_sha256` 字段；checkpoint 与 dataset manifest 若和 summary 不一致，context 工具会拒绝绑定。

### 8.1 统一 canonical 晋升

KAD-Net、SepMark、WaveGuard 必须先执行同一套只读 dry-run，再执行晋升。`promote_benchmark_run.py` 会复算完整协议、checkpoint、dataset、raw/quality、run config、progress、run-specific context 与 asset 结构；任一门禁失败时不写 canonical。正式晋升只接受安全 run ID 和同模型旧 symlink，拒绝实体目录、绝对链接、跨根链接、reports/assets 部分状态及未登记文件，并使用相对临时 symlink 原子替换两端；第二端失败时回滚第一端。

```bash
promote_run() {
  model="$1"
  run_id="$2"
  "$JYS_BENCHMARK_PYTHON" scripts/promote_benchmark_run.py \
    --model "$model" --run-id "$run_id" --dry-run
  "$JYS_BENCHMARK_PYTHON" scripts/promote_benchmark_run.py \
    --model "$model" --run-id "$run_id"
}

promote_run sepmark "$SEPMARK_RUN_ID"
promote_run kadnet "$KADNET_RUN_ID"
promote_run waveguard "$WAVEGUARD_RUN_ID"
```

晋升成功后，`sepmark_lfw_benchmark`、`kadnet_lfw_benchmark`、`waveguard_lfw_benchmark` 在 reports 与 assets 下必须分别是指向同一 run ID 的相对 symlink。历史目录不得成为 canonical 目标，也不得进入本次签名清单。

### 8.2 official SimSwap/LFW n256 真实换脸轨道

正式 Deepfake 主张只读取固定目录 `reports/simswap-lfw-robustness-n256-s20260603/`。输入为 256 个 LFW 身份不重叠 source-target pair，其中前 64 对仅用于逐模型阈值 calibration，后 192 对只用于 holdout；每个 pair 对 LIDMark、KAD-Net、SepMark、WaveGuard 生成 registered-positive、unwatermarked、wrong-message、cross-record 四类分数，并保存官方 ArcFace 的 source、target、clean swap 与四个 watermarked swap 嵌入。

```bash
CUDA_VISIBLE_DEVICES=0 \
  "$JYS_BENCHMARK_PYTHON" \
  system/scripts/run_simswap_lfw_robustness.py \
  --num-pairs 256 \
  --calibration-pairs 64 \
  --seed 20260603 \
  --device cuda:0 \
  --artifact-limit 16 \
  --flush-every 1 \
  --report-dir "$JYS_REPORT_ROOT/simswap-lfw-robustness-n256-s20260603" \
  --asset-dir "$JYS_ASSET_ROOT/simswap-lfw-robustness-n256-s20260603"
```

报告目录的固定成员只能是 `pair_manifest.json`、`message_registry.json`、`run_config.json`、`identity_embeddings.csv`、`results.csv`、`progress.json`、`assets_manifest.json`、`summary.json`。验收必须达到 256/256 pair、1024/1024 模型结果、1792/1792 ArcFace 嵌入、0 error、0 identity overlap；`run_config.implementation_files` 精确绑定 runner、identity/runtime、四适配器及其 backend 推理依赖。严格验证器重新执行 content-addressed pair 选择、消息派生、四类控制分数、嵌入 hash/cosine/迁移标志、calibration 阈值、holdout TAR/FRR/FAR、Wilson 区间、PSNR/SSIM、summary 聚合与 176 个可视化资产 hash，并从 pair manifest 与 raw rows 重算 registered-positive 的 clean-migrated、clean-and-watermarked-migrated 条件分组。正式值为 KAD-Net 160/161、153/154，SepMark 151/161、150/159。

同一个固定 ArcFace checkpoint 既用于 SimSwap generator 的 source identity conditioning，也用于 source-vs-target cosine migration measurement。该字段必须标记 `scope=pipeline_internal_identity_migration_evidence` 与 `independent_identity_verifier=false`；不得把它改写成独立身份验证结论。

## 9. Ed25519 签名与发布门禁

私钥必须位于仓库和 runtime 之外的受控路径，权限为 `0600`。发布采用无循环的两阶段签名：`release-core` 先固定四模型科学证据和 MEA 4×4 正式矩阵，最终 `release` 再把审计、统计、报告和快照纳入同一发布集合。所有正式 summary 完成并绑定 context 后执行：

```bash
: "${JYS_EVIDENCE_PRIVATE_KEY:?必须设置受控 Ed25519 私钥路径}"

"$JYS_BENCHMARK_PYTHON" scripts/sign_evidence_bundle.py \
  --profile release-core \
  --private-key "$JYS_EVIDENCE_PRIVATE_KEY"

"$JYS_BENCHMARK_PYTHON" scripts/sign_evidence_bundle.py --verify-only
```

签名验收必须同时满足：

- core 阶段 `profile == "release-core"`；最终阶段 `profile == "release"`；两个阶段都要求 `status == "verified"`、`verified == true`、`signature_valid == true`；
- `mismatches` 为空；
- `manifest.json` 中实际包含四个当前正式 summary，以及 summary 引用的 checkpoint、dataset manifest、raw results、quality CSV、run config 和 context 文件；KAD-Net、SepMark、WaveGuard 必须分别经 canonical symlink 解析到本次 run-specific 目录；
- MEA 固定目录只能是 `reports/mea-4x4-protocol-v1-s20260603-n256/`，且 `dataset_manifest.json`、`run_config.json`、`raw_results.csv`、`progress.json`、`summary.json` 五件套必须精确进入 core；验证器逐行重算 4×4 有向矩阵的 4096 个键、消息摘要、指标、覆盖率、checkpoint/协议/实现哈希和 summary 聚合；
- SimSwap 固定目录只能是 `reports/simswap-lfw-robustness-n256-s20260603/`；八件套、176 个可视化资产、官方 checkpoints.zip/generator/ArcFace 权重、四个水印 checkpoint、协议、runner、implementation_files、条件迁移验证器与测试必须进入 core，n64 smoke 不得替代该固定成员；
- `collaboration_policy.v2.json`、协同引擎、API schema/route 与回归测试必须和 MEA 五件套共同进入 core；策略必须固定 256 图像 / 217 身份审计、模型消息与主 decoder 语义、seed 20260603、20,000 次 identity-cluster bootstrap 和 96 项选择族；`requirements.lock`、`supply-chain/build-manifest.json`、`supply-chain/python-dependencies.cdx.json` 及其全部生成输入也必须通过 `scripts/supply_chain.py check` 后进入同一精确集合；
- LIDMark 条目必须指向 `lidmark_lfw_identity_test_epoch20_protocol_v1`，不得复制到旧目录或用旧路径的文件代替；
- 签名清单不得包含历史 `waveguard_lfw_full_benchmark` 或 `waveguard_lfw_small_benchmark`；
- 公钥 fingerprint 在提交登记表、答辩机和离线验签包中一致；
- 签名后任一文件变化都必须重新生成 manifest 和签名并重新验签。

core 阶段会把独立验签三件套固定保存在
`reports/evidence_signature/release-core/{manifest.json,manifest.sig,public_key.pem}`，
其实际内容位于按 manifest 摘要命名的不可混写 generation 目录，并通过原子 symlink 交换发布；相同输入二次运行复用同一 generation。同时更新当前签名视图。final 阶段不得覆盖该目录；最终固定成员集合必须精确纳入这三件套、
派生报告生成器源码、审计/统计/聚合/报告与快照，且拒绝任何额外成员、缺失成员或 role 漂移。
比赛报告中的 `evidence_gate.signature.manifest_sha256` 必须等于归档 core manifest 的实际哈希。

如果签名器的 evidence registry 尚未登记当前正式目录，签名结果不满足上述 membership 门禁；先更新并审计 registry，再签名，不能靠复制文件或手工编辑 manifest 绕过。

core 签名放行后依次生成协议审计、统计分析、四模型聚合和比赛报告；任一命令返回非零立即停止：

```bash
"$JYS_BENCHMARK_PYTHON" system/scripts/audit_benchmark_results.py
"$JYS_BENCHMARK_PYTHON" system/scripts/run_statistical_analysis.py
"$JYS_BENCHMARK_PYTHON" system/scripts/aggregate_real_benchmarks.py

"$JYS_BENCHMARK_PYTHON" system/scripts/export_competition_report.py --check-only

"$JYS_BENCHMARK_PYTHON" system/scripts/export_competition_report.py \
  --output "$JYS_REPORT_ROOT/jianyuanshield_competition_report"

# 在已提交且 git clean 的发布提交上生成最终快照。
"$JYS_BENCHMARK_PYTHON" scripts/create_release_snapshot.py

# 把审计、统计、聚合、最终报告与快照纳入 final release。
"$JYS_BENCHMARK_PYTHON" scripts/sign_evidence_bundle.py \
  --profile release \
  --private-key "$JYS_EVIDENCE_PRIVATE_KEY"
"$JYS_BENCHMARK_PYTHON" scripts/sign_evidence_bundle.py --verify-only
```

`export_competition_report.py` 返回 blocked 时不生成替代报告，不把 smoke、partial 或诊断结果写成正式性能结论。

## 10. 专项实验边界

WaveGuard 正式基准同时记录 tracer 与 detector 的逐 bit 指标，但 success 仅由 tracer 决定。当前正式 runner 不把 detector 结果表述为经过负样本校准的存在性 ROC/FAR/FRR；此类结论必须另建带无水印、错误消息、跨样本负对照和 calibration/holdout 隔离的独立实验。

KAD-Net 几何同步消融使用 `system/scripts/run_kadnet_geometry_sync_ablation.py`，属于独立 non-claim ablation，不回写主 benchmark，不用 ground-truth geometry 选择候选，也不替换协议主结果。

HiDDeN 保持独立 diagnostic 轨道。MEA 多重嵌入只在各组成模型的单嵌真实 checkpoint 证据完整后运行；其 LFW 输入必须来自当前 processed tree，不再引用废弃路径。真实平台回传和真实换脸分别使用独立 manifest、attack ID、模型/参数哈希与身份隔离证明，不与 deterministic proxy 混写。

## 11. 提交冻结

最终提交以签名 manifest 中的文件集合为准，包括：协议与 claims manifest、四个正式 summary、MEA 五件套、SimSwap/LFW n256 八件套与 176 个视觉资产、协同策略与引擎、逐图原始记录、quality CSV、dataset/run config、checkpoint 与选择证据、experiment context、`requirements.lock`、构建清单、CycloneDX SBOM、审计输出、最终比赛报告和公钥 fingerprint。

本 Markdown 不登记运行中的进度、临时进程号、性能数字或临时哈希。任何输入、代码、协议、checkpoint、阈值、数据或报告变化都会产生新的证据集合并重新签名；旧结果保留原签名，不覆盖、不拼接。
