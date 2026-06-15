# 训练/微调交接说明（WaveGuard jpeg50 强化 · KAD-Net 几何鲁棒）

> 状态：以下两项是 `TODO_DEEP_REVIEW.md` 阶段二-B 的「长训练」项。经核查，**当前 box 上的训练入口不可一键复跑**（stale 路径 / 无 resume 逻辑 / 原始微调命令未留存），为避免误配置浪费 GPU 或覆盖现有可用 checkpoint，**未自动盲跑**，改为给出经核对的可执行步骤交接。所有 eval 类做实（KAD 13,233、LIDMark id-bit、MEA 大样本）已自动完成，见 `REAL_BENCHMARK_STATUS.md`。

## 环境
```bash
ssh -p 10085 luxliang@127.0.0.1            # 隧道
cd ~/JianYuanShield
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate pytorch_env   # py3.8 / torch2.4.1
nvidia-smi   # 选空闲卡（0/2-6 常空，7 为 gaze 占用）
```

## 1. WaveGuard —— 强化 JPEG Q=50（当前真值：bit-acc 88.97% / success@0.9 仅 37.3%）
目标：把 Q=50 的 success_rate 从 37% 提升（bit-acc 已 89%，缺的是稳定过 0.9 阈值）。

**已发现的坑（必须先修）**：
- `WaveGuard/config/train.yaml` 的 `dataset_path` 仍是 stale 的 AutoDL 路径 `/root/autodl-tmp/CelebAMask-HQ/train`，box 上不存在。需改为 box 真实 CelebA（候选：`~/JianYuanShield/datasets/celeba_hq_kadnet` 或 `datasets/celeba_hq_small`，确认含训练图）。
- `WaveGuard/main.py` **无 resume/load checkpoint 逻辑**：直接跑会从随机初始化训练 8 epoch（`epochs: 8`），**不会**从 `runs/waveguard_jpeg_ft/model_state_16.pth` 继续。
- JPEG STE 已在 `main.py:108`（`u_embedded + jpeg(input)` 直通梯度）实现，噪声层在 `network/noise_layers`。

**建议做法（二选一）**：
- **A. 继续微调（推荐，改动小）**：在 `main.py` 训练循环前加载 `model_state_16.pth`（`self.load_state_dict(torch.load(.../model_state_16.pth, map_location=device, weights_only=True))`），再多训 8–16 epoch，**提高 JPEG 噪声层权重 / 把 jpeg quality 采样下探到 40–50** 强化低质量鲁棒；输出到**新目录**（勿覆盖 model_state_16）。
- **B. 提高 message 冗余 / 调 `wm_factor`、`encoder_w`** 重训，权衡 PSNR 与 Q=50 success。

**核对/launch（修好路径与 resume 后）**：
```bash
# 改 config/train.yaml: dataset_path -> 真实CelebA; device cuda:<free>; 可调 epochs
CUDA_VISIBLE_DEVICES=<free> nohup python WaveGuard/main.py > runs/waveguard_jpeg_ft2.log 2>&1 &
# 训完用权威全量脚本重测(勿用已废弃的 run_waveguard_lfw_benchmark.py):
PYTHONPATH=. python system/scripts/run_waveguard_lfw_small_benchmark.py   # 或 *_full_benchmark
```
**验收**：Q=50 success@0.9 明显 > 37%，且 clean/其余攻击仍 ~100%；把真实新数值回填 `REAL_BENCHMARK_STATUS.md` / 前端。**若提升不显著，保留现状并诚实标注 Q=50 为已知弱点即可（已在文档标注）。**

## 2. KAD-Net —— 几何鲁棒（当前真值：crop 68.9% / rotate 43.7%，EC_50 GEOM 微调后仍失败）
**现实判断**：`EC_50.pth` 已是几何微调版仍失败，几何不变性是该架构的硬限制，**继续同构微调预期收益低**。除非改架构（加 STN / 几何增强对抗训练 / 等变结构），否则建议**作为已知局限诚实呈现**（已在 `LIMITATIONS.md` / `THREAT_MODEL.md` 标注），把 GPU 投到更高回报项。

若仍要尝试更强几何增强微调：
```bash
# KAD-Net 训练入口: scripts/launch_kadnet_training.py（base ST 100ep）
# 几何微调用的是 GEOM 配置: KAD-Net 下 cfg/train_KAD_Net_geom.yaml(若存在)
# 需: 加大 crop/rotate 增强幅度与比例, 从 EC_50 resume 继续, 输出新目录
CUDA_VISIBLE_DEVICES=<free> nohup python scripts/launch_kadnet_training.py <gpu> > runs/kadnet/geom_ft2.log 2>&1 &
# 重测(含几何): PYTHONPATH=. python system/scripts/run_kadnet_lfw_benchmark.py --num-images 13233
```

## 3. LIDMark —— 完整配置 ID 比特正测（补 P0-2 真值）
当前 `run_lidmark_idbit_eval.py` 用 MEA 模式（landmark 维度置零）测得 clean 62%。真值需在**完整 landmark+id 配置**下测：
- 用 `system/backend/model_adapters.py` 的 LIDMark 路径（含 `face_alignment` 真实关键点），对 LFW encode（landmark+id）→ attack → decode id，统计 16-bit 比特准确率。
- 依赖：`pip install face_alignment`（已加入 requirements）。
- 若完整配置 clean 仍低 → LIDMark 确实弱在 id 比特，强在 landmark 定位（叙事据此定）。

## 备注
- box 无法访问 GitHub（GFW），代码同步：本地 push GitHub → 团队在 box 用其它通道拉取，或我经隧道按文件同步。
- eval 类已自动做实并回填；上述训练项请按真实结果回填文档/前端，**严禁再用旧的夸大数值**。
