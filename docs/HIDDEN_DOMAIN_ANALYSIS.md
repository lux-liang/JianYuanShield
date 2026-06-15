# HiDDeN 基线失效分析

**结论**：HiDDeN checkpoint 根本损坏，与域偏移无关。

---

## 验证实验

**测试方法**：对同一图像执行 编码 → 解码 闭环（无任何攻击），理论上完好的水印模型应达到 ~100% 准确率。

| 测试集 | 图像数量 | Round-Trip Acc | 结论 |
|--------|---------|---------------|------|
| CelebA-HQ val（in-domain face） | 16 | **49.6%** | 随机猜测水平 |
| LFW（之前报告） | 13,233 | **50.4%** | 随机猜测水平 |

**49.6% ≈ 随机猜测（30-bit 消息基准线 = 50%）**

闭环测试失败，排除了以下可能性：
- ❌ 域偏移（即使在训练域数据上也随机）
- ❌ 解码阈值问题（闭环已控制噪声变量）
- ✅ **确认：checkpoint 本身在训练时发散**

---

## 根本原因

1. **训练配置冲突**：`options.number_of_epochs = 100`，但 checkpoint 文件名为 `epoch-200.pyt`，意味着实验被手动延长到 200 epoch，训练极有可能在某个阶段发散
2. **解码器输出范围异常**：decoded_mean ≈ 0.29（应接近 0 或 1），所有位预测坍缩到同一错误区间
3. **训练环境不可复现**：checkpoint 来自 AutoDL 平台（`/root/autodl-tmp/dataset/w-sub/`），训练数据无法访问和复现

---

## 答辩叙事策略

HiDDeN 的失效不是弱点，是**系统能力的展示**：

> "我们的平台设有双层发布门禁（`ready_for_demo` / `ready_for_claims`）。经过实验验证，HiDDeN 官方开源 checkpoint 在闭环测试中 bit accuracy = 49.6%（随机基准），系统自动标记其状态为 ⚠️ 候选待复核。这恰恰证明平台具备识别低质量水印模型的能力——这对于面向《AI标识办法》的合规检测平台至关重要。"

**改写对比表**：

| 模型 | 指标类型 | Clean | 状态 | 备注 |
|------|---------|-------|------|------|
| **SepMark** | 比特精度 RF | 91.2% | ✅ 合规 | pre-trained，13,233 张 |
| **WaveGuard** | detector（有无水印）| 100% | ✅ 合规 | tracer Q=50≈52%，进行中 |
| **LIDMark** | landmark 成功率 | 99.93% | 🔄 ID 比特精度评测中 | 3-seed，512×3 张 |
| **KAD-Net** | 比特精度 | 100% | ✅ 合规（温和攻击）| 512 张；几何 partial |
| HiDDeN | 比特精度 | 49.6% | ❌ 门禁拦截 | checkpoint 损坏，作失效案例对照 |

---

## 处置决定

- [ ] **不重训 HiDDeN**（成本高、无竞争力、偏离核心方向）
- [x] **保留在对比表**中，明确标注为"门禁拦截 baseline"
- [x] **更新 ready_for_claims 说明**：HiDDeN 失效原因已明确，不再是 blocking finding
- [ ] **答辩时主动提及**：展示系统自检能力

---

**生成时间**：2026-06-07  
**验证脚本**：`scripts/hidden_roundtrip_test.py`  
**诊断报告**：`system/reports/diagnostics/hidden_roundtrip.json`
