# 统一评测协议

机器可读协议位于 `configs/evaluation_protocol.v1.json`，代码入口位于 `system/evaluation/`。

## 统一原则

- 对外比较使用 RGB、`uint8`、`[0,255]` 作为规范图像表示。
- 模型内部允许使用 RGB/YUV 和不同值域，但必须通过模型 adapter 显式转换。
- `BER = mean(original_bits != decoded_bits)`。
- `ACC = 1 - BER`。
- 默认成功定义为 `ACC >= 0.9`，阈值从协议读取，不允许脚本自行硬编码。
- `watermarked_vs_original` 衡量嵌入不可见性。
- `attacked_vs_original` 衡量完整传播后的图像质量。
- 旧报告中的 `mean_psnr`、`mean_ssim` 保留，但在完成统一重跑前标记为 legacy 语义。
- 随机攻击使用全局 seed 与 image ID 派生每图 seed，不重复使用同一噪声模板。

## 当前模型适配状态

| 模型 | 原生颜色空间 | 输入尺寸 | 当前状态 |
|---|---|---:|---|
| LIDMark | RGB | 128×128 | real checkpoint (3-seed) |
| HiDDeN | RGB | checkpoint config | epoch-300 checkpoint（有效），13,233 全量评测已完成；clean/resize 好，JPEG 域 gap 为已知局限；有效对照 baseline |
| SepMark | RGB | 256×256 | full benchmark |
| WaveGuard | YUV | 256×256 | model_state_16.pth，13,233 全量评测已完成；jpeg50 为真弱点（succ=37.3%），除 jpeg50 外≈100% |
| KAD-Net | RGB | 128×128 | EC_50.pth (GEOM 微调版)，13,233 全量评测已完成；几何攻击为已知局限 |

## 统计口径（不确定性与显著性）

统计分析入口为 `system/scripts/run_statistical_analysis.py`，统计原语在
`system/evaluation/statistics.py`。为避免 pseudoreplication 与跨指标误比较，
统一遵守以下口径：

### 两类不确定性分开报，不混

- **within-seed image-sampling CI**：固定**单个 seed**，对该 seed 的逐图指标做
  bootstrap，量化的是**图像采样噪声**。它**不是** between-seed（模型重训）方差。
- **between-seed CI**：以**每个 seed 的图像级均值**为样本（n = 独立训练 seed 数），
  用 Student-t 区间或给出 seed 均值的 `mean ± std`。本项目仅 LIDMark 有 3 个 seed，
  故 `n=3`，区间**仅供参考，非严格统计结论**。

> 禁止把 `3 seed × 512 图` 拍平成 `1536` 个「独立样本」做一次 bootstrap——那会把
> 图像采样噪声误当作 between-seed 方差，得到被严重低估的区间（如 `[99.94%,100%]`）。
> 旧 `statistical-analysis.v1` 的该做法已废弃，现版本为 `v2`：`image_sampling_ci`
> 与 `between_seed_ci` 两张表分别输出（`image_sampling_ci.csv` / `between_seed_ci.csv`）。

### 指标语义不同，分指标成表

各模型上报的「量」并非同一指标，**不可互相比较或跨指标做配对检验**：

| 指标名 | 含义 | 涉及模型 |
|---|---|---|
| `landmark_success_rate` | 关键点定位成功率（与水印鲁棒性无关） | LIDMark（定位强项，非 bit-acc） |
| `id_bit_acc` | 16-bit ID 水印逐位准确率 | LIDMark |
| `detector_bit_acc` | 检测器存在性二分类准确率（非溯源 tracer） | WaveGuard |
| `message_bit_acc` | 消息解码逐位准确率（30/128-bit） | HiDDeN / KAD-Net / SepMark |

- 每个指标**单独成表**；`run_statistical_analysis.py` 输出中以 `metric` 列与
  `metrics_by_method` 标注每个数值的真实指标名。
- `paired_sign_flip_test` / Holm 校正等配对检验**只允许在同一指标、同一攻击内部**做。
  跨指标的「99.98% > 91.2%」式比较是不同量的错误比较，已禁用（`comparisons` 恒空，
  并在 `comparisons_note` 中说明原因）。
- 不同消息长度（16/30/128-bit）与不同解码器（detector / decoder_C / decoder_RF）
  的 accuracy 不并入同一阈值评级。

## 攻击 ID

统一攻击 ID 为 `clean`、`jpeg50`、`jpeg70`、`jpeg90`、`resize_0.5x`、`gaussian_noise_sigma_3`。历史输出中的 `resize` 和 `noise` 在聚合时需要映射到新 ID。

## 迁移规则

现有全量 CSV 不覆盖。审计脚本先为历史结果生成统计与语义风险报告；完成 adapter 和统一指标库接入后，再生成 protocol v1 的新报告目录。
