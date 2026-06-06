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
| LIDMark | RGB | 128×128 | smoke |
| HiDDeN | RGB | checkpoint config | full benchmark |
| SepMark | RGB | 256×256 | full benchmark |
| WaveGuard | YUV | 256×256 | full benchmark |
| KAD-Net | RGB | model config | integration pending |

## 攻击 ID

统一攻击 ID 为 `clean`、`jpeg50`、`jpeg70`、`jpeg90`、`resize_0.5x`、`gaussian_noise_sigma_3`。历史输出中的 `resize` 和 `noise` 在聚合时需要映射到新 ID。

## 迁移规则

现有全量 CSV 不覆盖。审计脚本先为历史结果生成统计与语义风险报告；完成 adapter 和统一指标库接入后，再生成 protocol v1 的新报告目录。
