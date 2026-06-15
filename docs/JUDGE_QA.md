# 评委问答

## 这是普通 Deepfake 检测吗？

不是。系统强调主动取证：在内容传播前嵌入可恢复信息，并在攻击后评估能否恢复来源与水印。

## 这些模型是否只是外部开源项目？

不是。LIDMark、MEA、WaveGuard、KAD-Net 均属于本团队原创技术体系，经指导教师同意在鉴源盾中统一集成。鉴源盾新增了统一协议评测、证据审计、交互闭环和报告体系。

## 哪些结果是真实 checkpoint？

KAD-Net / SepMark / WaveGuard / HiDDeN 四模型均使用真实 checkpoint，完成 13,233 张 LFW 全量评测（n=13,233）。KAD-Net（EC_50，GEOM 微调）clean/jpeg/noise/resize 全部 ≥99%；几何攻击（crop≈68.9%，rotate≈43.7%）为已知硬限制。WaveGuard（model_state_16）clean/jpeg70+/noise/resize≈100%；**jpeg50 是真弱点**：bit-acc≈89%、成功率仅 37.3%，正在改进，不可称"已修复至100%"。SepMark（EC_115）bit-acc≈85-89%（clean 87.74%）。HiDDeN（epoch-300）clean/resize 好，JPEG 域 gap 为已知局限；**是有效对照 baseline，不是"损坏剔除"**。LIDMark 已完成 3 个独立 seed（20260603/04/05）的正式 checkpoint 训练，每 seed 评测 512 张；注意：当前上报的 99.93% 为 **landmark 定位成功率**，ID 比特精度（bit accuracy）评测进行中。

## 为什么 HiDDeN 指标不高还要展示？

这是信息安全评测的价值：同样是真实 checkpoint、同样是真实 LFW 数据和攻击链路，HiDDeN 在当前域上恢复接近随机，说明公开 watermark checkpoint 不能直接假定可迁移。SepMark 在同一条件下明显更稳，构成强弱对照。

## 当前最适合答辩的模型是哪一个？

四模型均已完成正式 checkpoint 评测，按场景推荐如下：

- **LIDMark（核心亮点）**：3-seed 正式训练，LFW 每 seed 512 张；landmark 定位成功率 99.93%（对攻击不敏感）；ID 比特精度（bit accuracy）评测进行中，待补充后更新。语义绑定（人脸关键点+用户 ID）是本组独创技术亮点，竞赛辨识度最高。
- **KAD-Net（比特精度首推）**：EC_50（GEOM 微调），LFW **13,233 张全量**，clean/jpeg/noise/resize 全部 ≥99%（clean=99.98%，jpeg50=99.09%）。CVPR 2026 方向，展示团队前沿研究实力。**几何攻击（crop≈68.9%，rotate≈43.7%）为已知硬限制**，须诚实向评委说明。
- **WaveGuard**：model_state_16，LFW **13,233 张全量**，clean/jpeg70+/noise/resize≈100%。**jpeg50 是真弱点**（bit-acc=88.97%，success=37.3%），答辩时须主动说明，不称"已修复"。
- **SepMark**：LFW 13,233 张（pre-trained checkpoint EC_115.pth），bit-acc≈85-89%（clean=87.74%）；success@0.9 为 59-72%（128-bit 长消息）；"decoder_RF 91.2%"偏高，以 ~88% 为准。

## 为什么 WaveGuard 有多个接近 100% 的指标？

当前结果来自真实 checkpoint 全量推理。我们已完成严格权重加载以及错误消息、无嵌入图像负对照：正确消息为 100%，两个负对照约为随机水平，因此没有发现明显消息泄漏。但现有攻击偏弱，仍不能直接宣称绝对领先。

## 为什么要做 MEA？

MEA 多重嵌入攻击体现信息安全攻防：攻击者可以通过二次嵌入或平台水印覆盖原始取证信号，导致溯源失败。

## 结果是否做了统计显著性分析？

已对 SepMark（13,233 张）逐图配对结果生成 Bootstrap 置信区间、配对符号翻转检验、效应量和 Holm 多重比较校正。LIDMark 的置信区间来自 3 个独立 seed（共 512×3=1,536 张，同一批 512 图重复 3 次），注意：这 3 个 seed 使用同批图像，between-seed 方差为训练随机性，建议配合互不重叠的更大样本重测。LIDMark 当前上报的"精度"为 landmark 定位成功率（99.93%），ID 比特精度评测进行中。WaveGuard 当前 n=13,233 全量，统计分析完整。

## 报告如何防篡改？

系统使用 Ed25519 对 canonical evidence manifest 签名，覆盖协议、诊断、统计、报告和 checkpoint 等文件（以 `evidence_audit` 接口实际返回的 `files_covered` 字段为准，TODO：统一 README 与本文件中的引用数字）。前端可下载 manifest、签名和公钥，修改任意已覆盖文件都会触发 `content_mismatch`。

## KAD-Net 的当前评测状态？

KAD-Net 已完成 GEOM 微调（checkpoint EC_50.pth），**LFW 13,233 张全量**评测结果：
- clean：bit-acc=**99.98%**，jpeg50=99.09%，jpeg70=99.79%，jpeg90=99.97%，noise=99.93%，resize=99.97%
- **几何攻击（已知硬限制）**：crop_center_0.8=68.92%（success=1.14%），rotate_5=43.73%（success=0%）——即便 GEOM 微调后仍实质失败

MEA 矩阵 KAD-Net↔WaveGuard 对角线外相对兼容（KAD→WG: 100%|100%，WG→KAD: 100%|100%），但 KAD→KAD first_acc=50%（自鲁棒性失效，与单模型 clean 100% 矛盾，口径 bug 排查中）。

---

## WaveGuard 在 JPEG-50 压缩下成功率为什么只有 37%，而 JPEG-70 是 99%？

**完整解释**（已做梯度实验验证）：

WaveGuard 使用 DTCWT（双树复小波变换）频域嵌入水印。JPEG 压缩对不同频段的量化阈值不同：
- WaveGuard 主要使用**高频子带**（LH/HL/HH）嵌入信息
- 高频子带的 JPEG 量化阈值约在 q≈60-65 处
- 原始权重 q=50 时高频子带被量化，detector 成功率 37.3%
- q=70 时高频子带受到保护 → detector 成功率 99.6%

我们对 50 张图像做了 q=40→90 的梯度实验，结论一致（q=60: 93%, q=70: 99.7%）。

**当前状态（model_state_16，n=13,233 全量）**：jpeg50 bit-acc=88.97%，但 **success@0.9=37.3%**（真弱点）；jpeg70/jpeg90/noise/resize≈100%；clean=100%。主流平台（q=75-85）始终≈100%。jpeg50 改进进行中，不可称"已修复至100%"。

---

## HiDDeN 的失效是域偏移还是别的原因？

HiDDeN 使用 **epoch-300 checkpoint**，完成 **n=13,233 全量评测**。结果：clean bit-acc=99.05%（好），resize=98.07%（好），noise=93.31%（中等）；**JPEG 系列失败**：jpeg50 bit-acc=57.09%、success=0%——这是**域 gap**（训练域与测试 LFW 的 JPEG 处理差异）。

HiDDeN 是**有效对照 baseline**，在同一评测框架下揭示了不同水印方案对 JPEG 攻击的鲁棒性差异，与 KAD-Net/WaveGuard 形成强弱对照。它**不是"损坏/已剔除"**——那是对一个更早的坏 checkpoint（epoch-200）的错误描述。答辩时可主动展示：同一评测框架下，HiDDeN 的 JPEG 局限 vs. KAD-Net/WaveGuard 的 JPEG 鲁棒性，体现平台的多模型横向对比价值。

---

## 为什么要用 3 个 seed 并行训练 LIDMark？

单 seed 的 Bootstrap CI 只反映图像采样不确定性，不能排除训练随机性带来的结果偏差。3 个独立 seed 可以：
1. 计算跨 seed 均值和方差，证明结果稳定性
2. 通过 Holm 多重比较校正，控制误报率
3. 向评委展示团队的科学性严谨程度——"我们知道一次实验不够，所以主动做了三次"

---

## 系统能在没有网络的情况下运行吗？

目前正在准备 Docker 离线部署包。核心模型权重（SepMark/WaveGuard/LIDMark/KAD-Net）在答辩前会打包到镜像中，支持无网络启动。
