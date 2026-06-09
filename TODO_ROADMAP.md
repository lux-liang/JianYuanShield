# 鉴源盾 · 冲刺一等奖迭代路线图

更新时间：2026-06-09  
负责人：lux-liang（后端 / 模型集成 / 评测）  
状态标记：`[x]` 已完成 `[→]` 进行中 `[ ]` 未开始 `[!]` 阻塞  

---

## 当前实际状态速查（基于服务器数据 2026-06-09）

| 模型 | 数据 | Checkpoint | 集成状态 | LFW精度 |
|---|---|---|---|---|
| **LIDMark** | ✅ 30k images + 60k NPY | ✅ 3-seed epoch100 (stage1) | ⚠️ smoke | 99.98% (仅distortion，无deepfake) |
| **SepMark** | ✅ | ✅ EC_115.pth | ✅ 已集成 | 91.2% |
| **WaveGuard** | ✅ | ✅ model_state_7.pth | ✅ 已集成 | ~100% |
| **HiDDeN** | ✅ CelebA训练完成 | ✅ epoch-300 BER=0.021 | ❌ 未接入 | 当前50%（旧ckpt） |
| **KAD-Net** | ✅ | ✅ EC_79.pth, D_96.pth | ⚠️ adapter写了未验证 | 未测 |

**核心结论：集成问题 > 训练问题。新ckpt已在但未部署。**

---

## PHASE 0 · 立即修复（0–3天）最高收益

### [→] P0-A 接入HiDDeN新checkpoint（预计1天，收益最大）

**背景**：`/data1/luxliang/work/vpsg_competition_candidates/MEA/codes/HiDDeN/runs/hidden_celeba_noise 2026.06.07--23-58-20/checkpoints/hidden_celeba_noise--epoch-300.pyt`  
训练300轮，验证集BER≈0.021（~98%精度），但当前平台读的是旧checkpoint，导致LFW全量评测BER=0.496（随机）。

- [ ] 找到 `system/scripts/run_hidden_lfw_benchmark.py`，更新 checkpoint 路径指向 epoch-300.pyt
- [ ] 确认 HiDDeN 原始代码预处理：CelebA是否需要 crop/resize 到固定尺寸，LFW benchmark是否对齐此预处理
- [ ] 用16张图 smoke test，验证 BER 显著低于0.1
- [ ] 跑 LFW 全量 13,233张 benchmark（估计1-2小时GPU）
- [ ] 更新 `system/reports/hidden_lfw_full_benchmark/results.csv`
- [ ] 更新 `ready_for_claims` 状态（HiDDeN解除blocking_finding后可放行）
- [ ] 更新 `README.md` 中HiDDeN指标

**验收**：HiDDeN clean bit_accuracy > 90%，LFW全量跑完并写入报告

---

### [ ] P0-B 验证KAD-Net adapter真正可用（预计1天）

**背景**：`system/evaluation/adapters/kadnet_adapter.py` 已写，checkpoint `EC_79.pth/D_96.pth` 在 `/data1/luxliang/work/vpsg_competition_candidates/runs/kadnet/results/ST/128/ST_KAD_Net_128_30_.../models/`，但从未在平台里跑过。

- [ ] 启动后端，调用 `/api/infer/single?model=KAD-Net` 用1张图测试
- [ ] 若报错：检查 adapter 的 `_latest_run_and_ckpt()` 路径逻辑，KAD-Net code path 是否正确
- [ ] 若成功：用16张图验证 BER < 0.1（KAD-Net是30bit，噪声抗性理论上好）
- [ ] 跑 LFW 512图 smoke benchmark，确认成功率
- [ ] 若512图结果正常，跑 LFW 全量 13,233张
- [ ] 更新 `weights/WEIGHT_MANIFEST.json` kadnet 状态从 pending → deployed
- [ ] 将 KAD-Net 从 README 的 `❌ 无checkpoint` 改为真实评测数字

**验收**：KAD-Net clean bit_accuracy > 85%，全量结果写入 `system/reports/kadnet_lfw_benchmark/`

---

### [ ] P0-C 重跑聚合报告和统计分析（修完A/B后，约半天）

- [ ] 运行 `PYTHONPATH=. python -m system.scripts.aggregate_real_benchmarks` 重新生成聚合
- [ ] 运行 `PYTHONPATH=. python -m system.scripts.run_statistical_analysis` 更新Bootstrap CI
- [ ] 确认 `ready_for_claims` 状态：HiDDeN修复后 blocking_findings 是否清零
- [ ] 更新 Ed25519 证据包（重新对新报告签名）
- [ ] 运行 `python3 -m unittest discover -s tests -v` 确保37项全通过

---

## PHASE 1 · 核心能力完整化（1–2周）

### [ ] P1-A 完成真实MEA跨模型攻击矩阵（核心原创贡献，约3天）

**背景**：矩阵框架已写，adapter合约已定义，但4个模型adapter未连通跑通。HiDDeN和KAD-Net修好后，矩阵就能跑起来。

目标矩阵（Source → Attacker，每格128张图）：

| Source ↓ \ Attacker → | HiDDeN | SepMark | WaveGuard | KAD-Net | LIDMark |
|---|---|---|---|---|---|
| HiDDeN | - | [ ] | [ ] | [ ] | [ ] |
| SepMark | [ ] | - | [ ] | [ ] | [ ] |
| WaveGuard | [ ] | [ ] | - | [ ] | [ ] |
| KAD-Net | [ ] | [ ] | [ ] | - | [ ] |
| LIDMark | [ ] | [ ] | [ ] | [ ] | - |

执行步骤：
- [ ] 确认 `system/evaluation/adapters/multi_embedding.py` 中所有5个adapter已注册
- [ ] 先跑 smoke（每格16张）验证无报错
- [ ] 跑正式矩阵（每格128张）：`JYS_INFER_DEVICE=cuda:0 PYTHONPATH=. python scripts/run_mea_matrix_4x4.py --images-per-cell 128`
- [ ] 生成热力图（原始消息保留率 + 攻击消息成功率）
- [ ] 提取关键 findings（对角线、跨模型兼容/不兼容组合）
- [ ] 写入 `system/reports/mea_matrix/` 并签名
- [ ] 更新 README 中的矩阵数字为真实结果

**验收**：20格矩阵全部有真实数字（非blocked），关键findings可在答辩中陈述

---

### [ ] P1-B LIDMark Stage 2 Deepfake微调（高收益，约1周，需外部模型）

**背景**：Stage1已训练3 seeds（epoch100，纯distortion），LFW精度99.98%是真实的但只代表扭曲鲁棒性。Stage2需要 SimSwap/UniFace/CSCS/StarGAN-v2 做deepfake操作器。

**阻塞项确认**：
- [ ] 检查 SimSwap 官方仓库 checkpoint 是否可下载
- [ ] 检查 UniFace / CSCS / StarGAN-v2 checkpoints 状态
- [ ] 若4个deepfake模型都能获取：进行 Stage2 fine-tuning（`python main.py tune_deepfakes --res 128`，估计24-48h/seed）
- [ ] 若只能获取部分：用已有的做partial fine-tuning，在README中注明
- [ ] 若完全无法获取：将LIDMark的评测范围限定在common distortions，诚实说明

**执行（获取deepfake模型后）**：
- [ ] 准备 `LIDMark/model/SimSwap/`, `UniFace/`, `CSCS/`, `StarGAN/` checkpoint
- [ ] 运行 Stage2：`python main.py tune_deepfakes --res 128` × 3 seeds（并行3个GPU）
- [ ] 测试 deepfake 场景下的检测率和篡改定位精度
- [ ] 更新 LIDMark README/评测报告，区分 Stage1 和 Stage2 结果

---

### [ ] P1-C 修复README虚假宣传（约半天，必须做）

以下是当前README里与实际不符的内容，每一项都是答辩地雷：

- [ ] 把移动端 `📱 Android · 🍎 iOS · 💬 小程序 · 🌸 鸿蒙` 改为"多端客户端（规划中，由团队成员负责）"或完全移出徽章
- [ ] LIDMark 99.98% 加注：Stage1（distortion鲁棒），Stage2（deepfake鲁棒）进行中
- [ ] MEA矩阵表格改为在P1-A完成后的真实数字；修复前标注 "updating"
- [ ] "唯一满足四条要求的开源技术方案" 改为 "面向法规的开源实现方案"（去掉"唯一"，无法证伪）
- [ ] `ready_for_claims` 在修复HiDDeN后更新为 `yes`
- [ ] Badge中 `最高精度-99.98%` 改为 `LIDMark精度-99.98%(S1)` 或添加注脚

---

### [ ] P1-D 补全攻击鲁棒性评测（约2天）

当前15种攻击中 deepfake proxy 是代理实现，需要真实deepfake结果来强化。

- [ ] 确认15种攻击在SepMark + WaveGuard + HiDDeN（修复后）+ KAD-Net 上都已跑
- [ ] 补充 WebP Q=80 攻击（当前结果是否包含？）
- [ ] 平台转码代理：微信/抖音压缩参数是否有真实测量数据支撑
- [ ] 生成攻击鲁棒性退化曲线（JPEG Q 50/70/90，各模型在同一图上对比）
- [ ] 更新聚合报告中的攻击鲁棒性章节

---

## PHASE 2 · 竞赛加分项（2–4周）

### [ ] P2-A 强化证据链答辩叙事

当前证据链是技术亮点但答辩叙事不够强，评委不一定理解为什么这比区块链好。

- [ ] 写 "Ed25519 vs 区块链存证 vs 哈希上链" 对比一页PPT材料
- [ ] 补充司法取证场景的完整walkthrough：从创作者上传→Deepfake传播→溯源→生成证据包→法庭验签
- [ ] 在 Web Demo 中增加可视化证据链 timeline 页面
- [ ] 测试"5秒验签"演示的稳定性（答辩时live demo）

---

### [ ] P2-B 统计严谨性材料化（约1天）

当前Bootstrap CI和Holm校正代码是有的，但没有做成评委能看懂的可视化。

- [ ] 生成 pairwise 比较图（每对模型的差值分布 + CI）
- [ ] 生成显著性矩阵热力图（p-value heatmap，Holm校正后）
- [ ] 整合到答辩PPT的"评测方法"一页
- [ ] 在 Web Demo 中展示 CI 区间（不只是均值）

---

### [ ] P2-C 合规审计API增强（约1天）

- [ ] `/api/compliance/batch` 增加对《AI内容标识办法》各条款的逐条检查结果
- [ ] 生成 JSON 合规报告（带条款引用）
- [ ] Demo 页面增加"合规检查"场景，输入图片输出合规报告
- [ ] 补充《AI内容标识办法》第六/七/八/十二条的API对应关系文档

---

### [ ] P2-D 答辩材料体系化（约2天）

- [ ] 制作3分钟答辩口稿（现已有，检查是否与最新数据一致）
- [ ] 制作完整答辩PPT（推荐：背景/问题 → 现有方案局限 → 鉴源盾方案 → 实验结果 → 工程演示 → 总结）
- [ ] 准备评委高频问题QA（至少10题）：
  - 为什么水印在deepfake后还能恢复？（LIDMark语义绑定机制）
  - HiDDeN为什么之前精度差？（域偏移，已修复）
  - MEA矩阵的实际意义是什么？（多重嵌入场景下的竞争攻击）
  - 和FaceForensics++有什么区别？（主动溯源 vs 被动检测）
  - Ed25519为什么比区块链好？（无延迟、离线可验、媒体嵌入）
- [ ] 准备离线Demo包（无网络环境下可运行）

---

### [ ] P2-E 代码和工程质量提升

- [ ] 完善 `requirements.txt`（确保完整可复现）
- [ ] 写 `INSTALL.md`（从零到可运行的步骤）
- [ ] 检查API安全：CORS配置、文件上传路径遍历防护、请求大小限制
- [ ] 更新 `system/reports/evidence_signature/`（重新签名更新后的报告）
- [ ] 确保 `python3 -m unittest discover -s tests -v` 37项全通过

---

## 一等奖达标检查清单

以下所有项目达成，才具备冲刺一等奖的实力：

### 技术深度（必须）
- [ ] 4个模型全部有真实LFW benchmark（不含smoke/random）
- [ ] HiDDeN bit_accuracy > 90%（修复后）
- [ ] KAD-Net bit_accuracy > 85%（验证后）
- [ ] LIDMark bit_accuracy > 95%（stage1已达，stage2 deepfake场景待定）
- [ ] MEA矩阵全20格有真实数字
- [ ] 所有benchmark附Bootstrap 95% CI

### 工程完整度（必须）
- [ ] Web Demo完全可运行（当前已达）
- [ ] Ed25519证据链可现场演示（当前已达）
- [ ] API文档完整
- [ ] 不含无法验证的宣称（移动端、唯一等）

### 创新性（已有，需讲清楚）
- [ ] MEA跨模型攻击矩阵有完整真实结果（VPSG原创）
- [ ] LIDMark语义绑定机制在answer中能清楚解释
- [ ] 法规合规框架逐条对应《AI内容标识办法》

### 答辩材料（必须）
- [ ] 3分钟答辩口稿（数字全部与最新报告一致）
- [ ] PPT（不超过15页）
- [ ] QA准备（至少10题）
- [ ] 离线Demo包

---

## 执行优先级总结

```
本周必做（最高ROI）：
  P0-A: 接入HiDDeN epoch-300 ckpt        → HiDDeN从随机→98%，解除claims阻断
  P0-B: 验证KAD-Net adapter               → 第四个真实模型上线
  P0-C: 重跑聚合+签名                      → 报告数字全部更新

下周必做：
  P1-C: 修复README虚假宣传                 → 防止答辩被抓包
  P1-A: 跑MEA矩阵                          → 核心原创贡献落地
  P1-D: 补全攻击鲁棒性                     → 表格更完整

两周内：
  P1-B: LIDMark Stage2（如果deepfake模型能获取）
  P2-A/B/C: 证据链叙事 + 统计可视化 + 合规API
  P2-D: 答辩PPT + QA + 离线包
```

---

## 风险登记

| 风险 | 影响 | 应对 |
|---|---|---|
| HiDDeN接入后LFW精度仍差 | 中 | 检查预处理对齐（LFW需同CelebA训练时的resize/normalize） |
| deepfake模型下载受阻 | 高 | LIDMark Stage2延期，答辩中诚实说明Stage1范围 |
| KAD-Net adapter有bug | 中 | 备用：直接用原始KAD-Net测试脚本跑LFW，结果导入系统 |
| MEA矩阵OOM | 低 | 每格batch_size=1，顺序跑 |
| 答辩时Demo崩溃 | 中 | 预录视频作为backup |
