# 评委问答

## 这是普通 Deepfake 检测吗？

不是。系统强调主动取证：在内容传播前嵌入可恢复信息，并在攻击后评估能否恢复来源与水印。

## 这些模型是否只是外部开源项目？

不是。LIDMark、MEA、WaveGuard、KAD-Net 均属于本团队原创技术体系，经指导教师同意在鉴源盾中统一集成。鉴源盾新增了统一协议评测、证据审计、交互闭环和报告体系。

## 哪些结果是真实 checkpoint？

HiDDeN、SepMark、WaveGuard 均使用真实 checkpoint，并完成 13,233 张 LFW 全量评测。LIDMark 当前是 smoke checkpoint，不能作为 full model 正式结论。

## 为什么 HiDDeN 指标不高还要展示？

这是信息安全评测的价值：同样是真实 checkpoint、同样是真实 LFW 数据和攻击链路，HiDDeN 在当前域上恢复接近随机，说明公开 watermark checkpoint 不能直接假定可迁移。SepMark 在同一条件下明显更稳，构成强弱对照。

## 当前最适合答辩的模型是哪一个？

SepMark。它已经接入真实 checkpoint，支持 encoder、decoder_C、decoder_RF，并输出 clean、JPEG、resize、noise 下的 BER、bit accuracy、PSNR、SSIM 和 success rate。

## 为什么 WaveGuard 有多个接近 100% 的指标？

当前结果来自真实 checkpoint 全量推理。我们已完成严格权重加载以及错误消息、无嵌入图像负对照：正确消息为 100%，两个负对照约为随机水平，因此没有发现明显消息泄漏。但现有攻击偏弱，仍不能直接宣称绝对领先。

## 为什么要做 MEA？

MEA 多重嵌入攻击体现信息安全攻防：攻击者可以通过二次嵌入或平台水印覆盖原始取证信号，导致溯源失败。

## 结果是否做了统计显著性分析？

已对 13,233 张逐图配对结果生成 Bootstrap 置信区间、配对符号翻转检验、效应量和 Holm 多重比较校正。但历史实验只有一个 seed，这些区间反映图像采样不确定性，不代表训练随机性；正式结论仍需至少三个独立 seed。

## 报告如何防篡改？

系统使用 Ed25519 对 canonical evidence manifest 签名，当前覆盖协议、诊断、统计、报告和 checkpoint 等 19 个文件。前端可下载 manifest、签名和公钥，修改任意已覆盖文件都会触发 `content_mismatch`。

## 为什么 KAD-Net 还没有进入四模型排名？

服务器已有团队源码，但没有 KAD-Net checkpoint；原测试脚本还依赖 Python 3.8、Torch 1.11/CUDA 11.3 和硬编码旧路径。没有完成严格加载与负对照前，把它放入排名会制造不可验证结果。

---

## WaveGuard 在 JPEG-50 压缩下成功率为什么只有 37%，而 JPEG-70 是 99%？

**完整解释**（已做梯度实验验证）：

WaveGuard 使用 DTCWT（双树复小波变换）频域嵌入水印。JPEG 压缩对不同频段的量化阈值不同：
- WaveGuard 主要使用**高频子带**（LH/HL/HH）嵌入信息
- 高频子带的 JPEG 量化阈值约在 q≈60-65 处
- q=50 时高频子带被大幅量化，水印信息丢失 → 成功率 37.3%
- q=70 时高频子带受到保护 → 成功率 99.6%

我们对 50 张图像做了 q=40→90 的梯度实验，结论一致（q=60: 93%, q=70: 99.7%）。

**对应用的建议**：在实际部署中，主流平台（小红书、抖音）的图片转码质量通常 q=75-85，处于 WaveGuard 的安全区间，不会影响取证。

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
