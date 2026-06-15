# 真实评测状态（更新：2026-06-15）

## 当前事实（各数值来自真实 artifact，非声明）

| 模型 | Checkpoint | 样本量 | 指标类型 | Clean | JPEG Q=50 | 几何攻击 | 状态 |
|------|-----------|-------|---------|-------|----------|---------|------|
| **LIDMark** | 3-seed 正式训练 (s1/s2/s3) | 512×3=1,536 张（同批 512 图） | landmark 定位成功率 | 99.93% | 99.93%（攻击不敏感）| 未测 | ✅ real；**ID 比特精度 null，评测进行中** |
| **KAD-Net** | 独立训练 100ep + GEOM 微调进行中 | 512 张 | 比特精度 | 100% | 99.97% | crop≈68.9%，rotate≈43.7%（EP50，partial）| ✅ real；几何 partial |
| **SepMark** | EC_115.pth (pre-trained) | **13,233 张**（唯一真全量） | 比特精度 RF | 91.2% | 88.1% | — | ✅ real |
| **WaveGuard** | model_state_7.pth (JPEG STE 7ep) | 512 张 | detector（二分类）/ tracer（溯源） | detector 100% | detector=89% / **tracer≈52%** | — | ✅ real；tracer Q=50 仍接近随机 |
| HiDDeN | 损坏 (epoch-200.pyt) | — | 比特精度 | ≈50% | 0% | — | ❌ checkpoint 损坏，作失效案例对照 |

## 指标说明（防止混用）

- **LIDMark 99.93%**：landmark 定位成功率（`success_rate`），**不是** ID 比特精度；真实 `bit_accuracy=null`。
- **WaveGuard detector vs tracer**：detector=有无水印二分类；tracer=溯源比特精度。两者**不可混用**。STE 7ep 微调仅有效提升 detector，tracer Q=50 仍约随机（52%）。
- **KAD-Net 几何**：EP50 的 crop/rotate 结果为 partial（微调未完成），不代表最终几何鲁棒性。
- **样本量**：唯一真正 13,233 张全量评测的是 SepMark。WaveGuard/KAD-Net/LIDMark 均为 512 张（LIDMark 用同批 512 图重复 3 seed）。

## 关键进展（2026-06-07 → 2026-06-15）

- **WaveGuard JPEG STE 7ep 微调**：detector Q=50=89%（从 37.3% 大幅提升），tracer Q=50≈52%（进一步微调进行中）
- **KAD-Net 几何增强微调**：EP50 中间结果 crop≈68.9%，rotate≈43.7%（较原始 33%/30% 有改善，EP50 后更新最终值）
- **LIDMark**：3-seed 正式 checkpoint 训练完成，landmark 定位成功率 99.93%；ID 比特精度评测待补充

## 答辩表述（诚实口径）

可以说：
- WaveGuard JPEG STE 7ep 微调后 detector Q=50 达 89%，Q=70 达 99.7%，clean=100%
- LIDMark 3-seed 正式训练，landmark 定位成功率 99.93%（对攻击具鲁棒性）
- KAD-Net 温和攻击（jpeg/noise/resize）全部 100%，几何增强微调进行中
- SepMark 13,233 张全量评测 RF decoder clean 91.2%

不能说：
- WaveGuard tracer 100%（实测≈52%）
- LIDMark 99.97% 比特精度（bit_accuracy=null）
- KAD-Net/WaveGuard 在 13,233 全量上评测（样本量均为 512）
- HiDDeN 结果有效（checkpoint 损坏，bit_acc≈50%）
- MEA 矩阵"创新有效"（当前对角线多 FAIL，应以"诚实红队诊断"叙事为准）
