# 评委问答

## 这是普通 Deepfake 检测吗？

不是。系统强调主动取证：在内容传播前嵌入可恢复信息，并在攻击后评估能否恢复来源与水印。

## 这些模型是否只是外部开源项目？

不是。LIDMark、MEA、WaveGuard、KAD-Net 均属于本团队原创技术体系，经指导教师同意在鉴源盾中统一集成。鉴源盾新增了统一协议评测、证据审计、交互闭环和报告体系。

## 哪些结果是真实 checkpoint？

SepMark、WaveGuard 均使用真实 checkpoint，完成 13,233 张 LFW 全量评测。LIDMark 已完成 3 个独立 seed（20260603/04/05）的正式 checkpoint 训练，每 seed 评测 512 张，3-seed 合并 95% CI 为 [99.94%, 100%]。KAD-Net 已在服务器独立训练 100 epoch，完成 512 张 LFW 评测，clean/jpeg/noise/resize 全部 100%。HiDDeN checkpoint 损坏（精度≈50%），已从正式评测中剔除。

## 为什么 HiDDeN 指标不高还要展示？

这是信息安全评测的价值：同样是真实 checkpoint、同样是真实 LFW 数据和攻击链路，HiDDeN 在当前域上恢复接近随机，说明公开 watermark checkpoint 不能直接假定可迁移。SepMark 在同一条件下明显更稳，构成强弱对照。

## 当前最适合答辩的模型是哪一个？

四模型均已完成正式 checkpoint 评测，按场景推荐如下：

- **LIDMark（首推）**：3-seed 正式训练，LFW 1,536 张，ID 比特精度 99.97–99.98%，95% CI 全部 ≥ 99.88%。语义绑定（人脸关键点+用户 ID）是本组独创技术亮点，竞赛辨识度最高。
- **KAD-Net（算法精度首推）**：独立训练 100ep，LFW 512 张，clean/jpeg50/jpeg70/resize/noise 全部 **100%**。CVPR 2026 方向，展示团队前沿研究实力。几何增强微调进行中（EP17/50）；EP16 中间结果：crop=71.2%，rotate=39.8%，较原始 33%/30% 显著改善。
- **WaveGuard**：JPEG STE 7ep 微调后，LFW 512 张 JPEG Q=50 tracer 比特精度 **100%**（CI=[100%,100%]），完全修复原 37.3% 问题；JPEG70/noise/resize 同样 100%。
- **SepMark**：LFW 13,233 张，decoder_RF clean=91.19%（CI=[90.90%, 91.48%]），原 decoder_C=87.74%；RF 解码器是本组重新训练的改进版本。

## 为什么 WaveGuard 有多个接近 100% 的指标？

当前结果来自真实 checkpoint 全量推理。我们已完成严格权重加载以及错误消息、无嵌入图像负对照：正确消息为 100%，两个负对照约为随机水平，因此没有发现明显消息泄漏。但现有攻击偏弱，仍不能直接宣称绝对领先。

## 为什么要做 MEA？

MEA 多重嵌入攻击体现信息安全攻防：攻击者可以通过二次嵌入或平台水印覆盖原始取证信号，导致溯源失败。

## 结果是否做了统计显著性分析？

已对 13,233 张逐图配对结果生成 Bootstrap 置信区间、配对符号翻转检验、效应量和 Holm 多重比较校正。LIDMark 的置信区间来自 3 个独立 seed（共 1,536 张），同时捕捉图像采样和训练随机性不确定性。SepMark、WaveGuard 目前仍为单 seed，区间仅反映图像采样不确定性；如需 between-seed 方差，需补充重训。

## 报告如何防篡改？

系统使用 Ed25519 对 canonical evidence manifest 签名，当前覆盖协议、诊断、统计、报告和 checkpoint 等 19 个文件。前端可下载 manifest、签名和公钥，修改任意已覆盖文件都会触发 `content_mismatch`。

## KAD-Net 的当前评测状态？

KAD-Net 已完成服务器独立训练（100 epoch）和正式集成。LFW 512 张全量评测结果：
- clean / jpeg / jpeg50 / jpeg70 / resize / noise：全部 **100%**（或 99.97%）
- 几何增强微调中（EP17/50）；EP16 中间：crop_center_0.8 ≈ **71.2%**，rotate_5 ≈ **39.8%**（EP50 完成后更新）

MEA 矩阵显示 KAD-Net 与 WaveGuard 兼容性最佳（KAD→WG: 100% | 100%，WG→KAD: 100% | 100%）。

---

## WaveGuard 在 JPEG-50 压缩下成功率为什么只有 37%，而 JPEG-70 是 99%？

**完整解释**（已做梯度实验验证）：

WaveGuard 使用 DTCWT（双树复小波变换）频域嵌入水印。JPEG 压缩对不同频段的量化阈值不同：
- WaveGuard 主要使用**高频子带**（LH/HL/HH）嵌入信息
- 高频子带的 JPEG 量化阈值约在 q≈60-65 处
- 原始权重 q=50 时高频子带被量化，成功率 37.3%；已通过 JPEG STE 7ep 微调修复至 **100%**
- q=70 时高频子带受到保护 → 成功率 99.6%

我们对 50 张图像做了 q=40→90 的梯度实验，结论一致（q=60: 93%, q=70: 99.7%）。

**修复状态**：已通过 JPEG STE 微调修复，Q=40-70 全范围 tracer 比特精度 100%。主流平台（q=75-85）从未受影响。

---

## HiDDeN 的失效是域偏移还是别的原因？

**确认是 checkpoint 本身损坏**，而非域偏移。

我们做了闭环验证：对 CelebA-HQ 人脸图像（与训练域相似）做编码→解码，理论上应该接近 100% accuracy，实测仅 **49.6%（随机水平）**。

根本原因：checkpoint 文件为 `epoch-200.pyt`，但原始训练配置 `number_of_epochs=100`，说明训练被非标准地延长，过程中很可能发生了梯度发散。训练数据来自已不可访问的 AutoDL 平台，无法复现。

**这反而证明了鉴源盾的价值**：系统通过双层门禁（`ready_for_demo / ready_for_claims`）自动识别出 HiDDeN 的失效，并标记为 ⚠️ 待复核状态，而不是把失效结果暴露给用户。

---

## 为什么要用 3 个 seed 并行训练 LIDMark？

单 seed 的 Bootstrap CI 只反映图像采样不确定性，不能排除训练随机性带来的结果偏差。3 个独立 seed 可以：
1. 计算跨 seed 均值和方差，证明结果稳定性
2. 通过 Holm 多重比较校正，控制误报率
3. 向评委展示团队的科学性严谨程度——"我们知道一次实验不够，所以主动做了三次"

---

## 系统能在没有网络的情况下运行吗？

目前正在准备 Docker 离线部署包。核心模型权重（SepMark/WaveGuard/LIDMark/KAD-Net）在答辩前会打包到镜像中，支持无网络启动。
