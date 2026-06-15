# 真实评测状态（更新：2026-06-15）

## 当前事实（各数值来自真实 artifact，非声明）

| 模型 | Checkpoint | 样本量 | 指标类型 | Clean | JPEG Q=50 | 几何攻击 | 状态 |
|------|-----------|-------|---------|-------|----------|---------|------|
| **LIDMark** | 3-seed 正式训练 (s1/s2/s3) | 512×3=1,536 张（同批 512 图） | landmark 定位成功率 + ID比特 | 99.93%（landmark）| landmark 99.93% | ID比特 clean **62.3%**（512图实测）| ✅ real；landmark 强，**16-bit ID 比特≈随机** |
| **KAD-Net** | EC_50.pth (GEOM 微调版) | **13,233 张**（真全量） | 比特精度 | 99.98% | 99.09% | **crop≈68.9%，rotate≈43.7%（GEOM 微调后仍失败）**| ✅ real；几何为已知局限 |
| **SepMark** | EC_115.pth (pre-trained) | **13,233 张** | 比特精度 RF | 87.74%（decoder_RF）；decoder_C 87.7% | 87.75% | — | ✅ real |
| **WaveGuard** | model_state_16.pth | **13,233 张**（真全量） | bit-acc / success@0.9 | 100% / 100% | bit-acc=**88.97%** / succ=**37.3%**（Q=50 真弱点）| — | ✅ real；jpeg50 是真弱点，不可称"已修复100%" |
| **HiDDeN** | epoch-300 | **13,233 张**（真全量） | 比特精度 | 99.05% | **57.09%**（success=0%）| — | ✅ real；**有效对照 baseline，JPEG 域 gap 为已知局限** |

## 指标说明（防止混用）

- **LIDMark 99.93%**：landmark 定位成功率（`success_rate`），**不是** ID 比特精度。新脚本 `system/scripts/run_lidmark_idbit_eval.py` 实测 16-bit ID 比特准确率（512 图，s1 ep100，MEA 模式 landmark 维度置零）：**clean 62.3% / jpeg50 70% / resize·noise ≈62%，success@0.9≈0%**——即该配置下 ID 比特水印接近随机（50% 基线）。⚠️ MEA 模式置零 136 维 landmark 属 out-of-distribution，可能低估真实能力；完整 landmark+id 配置（需人脸检测器）的真值待补测。**结论：LIDMark 的强项是 landmark 定位/篡改定位，而非可溯源的 ID 比特。**
- **WaveGuard jpeg50**：bit-acc=88.97%，但 success@0.9 仅 37.3%——这是真弱点。checkpoint `model_state_16.pth`，n=13,233。不可称"Q=50 已修复至100%"。
- **KAD-Net 几何**：GEOM 微调版（EC_50.pth）在 13,233 全量上，crop_center_0.8=68.92%、rotate_5=43.73%，几何攻击仍实质失败，是已知硬限制。
- **HiDDeN**：使用 epoch-300 checkpoint，13,233 全量评测。clean/resize 好，JPEG 系列失败（域 gap）。是有效对照 baseline，不是"损坏/已剔除"。
- **SepMark**：bit-acc≈85-89%（decoder_RF 结果），"91.2%" 为特定 decoder 结果，以 ~88% 为通常引用值；success@0.9 仅 59-72%。
- **样本量**：KAD-Net / SepMark / WaveGuard / HiDDeN 四模型均为 13,233 全量；LIDMark 为 512×3（同批 512 图重复 3 seed）。

## 关键进展（2026-06-07 → 2026-06-15）

- **KAD-Net（GEOM 微调，EC_50.pth，13,233 全量）**：JPEG/resize/noise 全部 ≥99%；几何攻击（裁剪/旋转）仍实质失败——这是已知硬限制，须诚实标注
- **WaveGuard（model_state_16，13,233 全量）**：clean/jpeg90/noise/resize≈100%；jpeg50 是真弱点（bit-acc 89%，succ 37%）
- **HiDDeN（epoch-300，13,233 全量）**：有真实评测结果，clean/resize 好，JPEG 失败（域 gap）；作为有效对照 baseline
- **LIDMark**：3-seed 正式 checkpoint 训练完成，landmark 定位成功率 99.93%；ID 比特精度评测待补充

## 答辩表述（诚实口径）

可以说：
- WaveGuard（model_state_16，n=13,233）clean/jpeg70+/noise/resize≈100%；**jpeg50 是真弱点**：bit-acc≈89%，成功率仅 37%，正在改进
- KAD-Net（EC_50，n=13,233）JPEG/noise/resize 全部 ≥99%；**几何攻击（裁剪/旋转）仍实质失败**，是已知局限
- HiDDeN（epoch-300，n=13,233）有真实评测，clean/resize 好，JPEG 域 gap 为已知局限；作为有效对照 baseline
- LIDMark 3-seed 正式训练，landmark 定位成功率 99.93%（ID 比特精度评测进行中）
- SepMark（n=13,233）bit-acc≈85-89%（clean 87.74%）
- KAD-Net / SepMark / WaveGuard / HiDDeN 四模型均已完成 13,233 全量评测

不能说：
- WaveGuard "Q=50 已修复至100%"（实测 bit-acc 89%、succ 37%）
- LIDMark 99.93% 是 "比特精度"（是 landmark 定位成功率；bit_accuracy=null）
- HiDDeN "损坏/已剔除"（有真实 13,233 评测，是有效 baseline）
- "唯一全量是 SepMark"（KAD-Net/WaveGuard/HiDDeN 也是 13,233 全量）
- MEA 矩阵"创新有效"（当前对角线多 FAIL，应以"诚实红队诊断"叙事为准）
