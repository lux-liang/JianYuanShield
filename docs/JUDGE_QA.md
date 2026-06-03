# 评委问答

## 这是普通 Deepfake 检测吗？

不是。系统强调主动取证：在内容传播前嵌入可恢复信息，并在攻击后评估能否恢复来源与水印。

## 哪些结果是真实 checkpoint？

MEA/HiDDeN 和 MEA/SepMark 是真实 checkpoint。HiDDeN LFW full benchmark 已完成，SepMark LFW full benchmark 正在后台运行。MEA/WaveGuard 当前已完成真实 checkpoint 单图 encode/decode smoke。LIDMark 当前是 smoke checkpoint，不能作为官方 full model 结论。

## 为什么 HiDDeN 指标不高还要展示？

这是信息安全评测的价值：同样是真实 checkpoint、同样是真实 LFW 数据和攻击链路，HiDDeN 在当前域上恢复接近随机，说明公开 watermark checkpoint 不能直接假定可迁移。SepMark 在同一条件下明显更稳，构成强弱对照。

## 当前最适合答辩的模型是哪一个？

SepMark。它已经接入真实 checkpoint，支持 encoder、decoder_C、decoder_RF，并输出 clean、JPEG、resize、noise 下的 BER、bit accuracy、PSNR、SSIM 和 success rate。

## 为什么要做 MEA？

MEA 多重嵌入攻击体现信息安全攻防：攻击者可以通过二次嵌入或平台水印覆盖原始取证信号，导致溯源失败。
