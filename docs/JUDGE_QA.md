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
