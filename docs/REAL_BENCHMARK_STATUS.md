# 真实评测状态（更新：2026-06-07）

## 当前事实

| 模型 | Checkpoint | 样本量 | JPEG Q=50 | 状态 |
|------|-----------|-------|----------|------|
| **LIDMark** | 3-seed 正式训练 (s1/s2/s3, 各100ep) | 1,536 张（512×3） | 99.96% | ✅ real |
| **KAD-Net** | 独立训练 100ep + GEOM 微调进行中 | 512 张 | 99.97% | ✅ real |
| **SepMark** | EC_115.pth (pre-trained) | 13,233 张 | 88.1% | ✅ real |
| **WaveGuard** | **model_state_7.pth (JPEG STE 微调)** | 512 张 | **100%** ✅ | ✅ real |
| HiDDeN | 损坏 (epoch-200.pyt) | — | — | ❌ 已剔除 |

## 关键进展（2026-06-07）

- **WaveGuard JPEG Q=50 已修复**：通过 JPEG STE 7ep 微调，tracer bit_acc=100%（CI=[1.0,1.0]），从 37.3% 完全修复。新 checkpoint：
- **KAD-Net 几何增强微调**：进行中（EP17/50），EP16 中间：crop_center_0.8=71.2%，rotate_5=39.8%（原 33%/30%）
- **LIDMark**：3-seed 正式 checkpoint 训练完成，3-seed 合并 95% CI=[99.94%, 100%]

## 答辩表述（已更新）

可以说：
- WaveGuard JPEG Q=50 已通过 JPEG STE 微调修复至 100%，不再是缺陷
- LIDMark 3-seed 正式训练，99.97%，覆盖图像采样和训练随机性两类不确定性
- KAD-Net 几何增强微调进行中，已有明显改善

不能说：
- KAD-Net 几何攻击已完全修复（EP50 完成前不能作为最终结论）
- HiDDeN 结果有效（checkpoint 损坏，bit_acc≈50%）
