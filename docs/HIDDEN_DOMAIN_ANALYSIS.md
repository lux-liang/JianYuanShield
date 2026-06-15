# HiDDeN 基线分析（更新：2026-06-15）

> **状态更正**：使用的 checkpoint 是 `hidden_celeba_noise--epoch-300.pyt`（有效，n=13,233 全量评测），**不是之前描述的 epoch-200（旧的损坏 checkpoint）**。以下分析已更新为正确的 epoch-300 checkpoint 结论。

**结论（epoch-300）**：HiDDeN epoch-300 checkpoint **有效**——clean/resize/noise 结果正常；JPEG 系列失败属于**域 gap**（训练-测试 JPEG 处理差异），而非 checkpoint 损坏。

---

## 真实评测结果（n=13,233，checkpoint epoch-300）

| 攻击 | bit-acc | success@0.9 |
|------|---------|-------------|
| 无攻击 | **99.05%** | 99.73% |
| 缩放 | 98.07% | 97.45% |
| 噪声 | 93.31% | 68.30% |
| JPEG Q=50 | **57.09%** | **0.0%** |
| JPEG Q=70 | ~59.65% | ~0% |
| JPEG Q=90 | ~66.94% | ~0% |

**clean/resize 正常（好），JPEG 系列全部失败（域 gap）。**

---

## 域 gap 分析

HiDDeN 训练于 CelebA-Noise 数据集（无 JPEG 数据增强），测试于 LFW + JPEG 攻击：

- **训练域**：CelebA-HQ + 高斯噪声增强 → 模型对噪声鲁棒（93%），但未见 JPEG 量化
- **测试域**：LFW + JPEG Q=50 → JPEG 量化破坏嵌入信号，解码坍缩
- **这是域 gap**，不是 checkpoint 损坏——clean 99.05% 证明 checkpoint 本身正常

---

## 答辩叙事策略（更新）

HiDDeN 是**有效对照 baseline**，展示了同一评测框架下不同水印方案对 JPEG 攻击的鲁棒性差异：

> "在相同的 LFW 13,233 张全量评测下，HiDDeN 在 clean 条件下 bit-acc=99.05%，但 JPEG Q=50 时 success 降至 0%，这是训练没有 JPEG 增强导致的域 gap。相比之下，KAD-Net 同等测试集上 jpeg50=99.09%，WaveGuard jpeg50 bit-acc=88.97%——横向对照体现了不同训练策略对 JPEG 鲁棒性的影响。"

**不要称 HiDDeN 为"损坏/剔除"——这是有效的 baseline 对比数据。**

**改写对比表**：

| 模型 | 指标类型 | Clean | JPEG Q=50 | 状态 | 备注 |
|------|---------|-------|----------|------|------|
| **KAD-Net** | 比特精度 | 99.98% | 99.09% | ✅ 极强 | n=13,233，几何攻击为局限 |
| **WaveGuard** | bit-acc / succ@0.9 | 100% | 88.97% / **37.3%** | ⚠️ jpeg50 弱点 | n=13,233 |
| **SepMark** | 比特精度 | ~88% | 87.75% | ✅ 稳定 | n=13,233，pre-trained |
| **HiDDeN** | 比特精度 | 99.05% | **57.09%（0%）** | ⚠️ JPEG 域 gap | n=13,233，有效 baseline |
| **LIDMark** | landmark 成功率 | 99.93% | — | 🔄 ID 比特精度评测中 | 512×3 |

---

## 处置决定（更新）

- [x] **纳入正式对照表**：HiDDeN 是有效 baseline，13,233 全量评测结果有意义
- [x] **标注 JPEG 局限**：明确域 gap 原因，honest 叙事
- [ ] **如需改进**：可重训 HiDDeN 加入 JPEG 数据增强（非竞赛必选项）
- [x] **答辩时主动提及**：用 HiDDeN 的 JPEG 局限 vs. KAD-Net 的 JPEG 强鲁棒性，体现横向对比价值

---

## 答辩叙事策略

HiDDeN（epoch-300）是**有效对照 baseline**，揭示了训练未加 JPEG 增强的水印方案在 JPEG 攻击下的局限：

> "在相同 LFW 13,233 张全量评测框架下，HiDDeN（epoch-300）clean bit-acc=99.05%（正常），但 jpeg50 success=0%——这是训练域不含 JPEG 增强导致的域 gap。与 KAD-Net（jpeg50=99.09%）、WaveGuard（jpeg50 bit-acc=88.97%）形成横向对照，体现了不同训练策略对 JPEG 鲁棒性的影响。"

**真实对比表（以权威 benchmark 数据为准）**：

| 模型 | 指标类型 | Clean | JPEG Q=50 | 状态 | 备注 |
|------|---------|-------|----------|------|------|
| **KAD-Net** | 比特精度 | 99.98% | 99.09% | ✅ 极强（JPEG/noise/resize）| 13,233 张；**几何失败为已知局限** |
| **WaveGuard** | bit-acc / succ@0.9 | 100% | 88.97% / **37.3%** | ⚠️ jpeg50 真弱点 | 13,233 张 |
| **SepMark** | 比特精度 RF | ~88%（87.74%）| 87.75% | ✅ 稳定 | 13,233 张，pre-trained |
| **LIDMark** | landmark 成功率 | 99.93% | 99.93% | 🔄 ID 比特精度评测中 | 3-seed，512×3 张 |
| **HiDDeN** | 比特精度 | 99.05% | **57.09%（success=0%）** | ⚠️ JPEG 域 gap | 13,233 张，有效 baseline |

---

## 处置决定（更新）

- [x] **纳入正式对照表**：HiDDeN epoch-300 是有效 baseline，13,233 全量数据有意义
- [x] **标注 JPEG 局限**：诚实标注域 gap，而非称"损坏"
- [ ] **如需改进**：可重训 HiDDeN 加入 JPEG 增强（非竞赛必选项）
- [x] **更新 ready_for_claims 说明**：HiDDeN 失效原因已明确，不再是 blocking finding
- [ ] **答辩时主动提及**：展示系统自检能力

---

**生成时间**：2026-06-07  
**验证脚本**：`scripts/hidden_roundtrip_test.py`  
**诊断报告**：`system/reports/diagnostics/hidden_roundtrip.json`
