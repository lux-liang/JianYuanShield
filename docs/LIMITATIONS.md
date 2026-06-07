# 当前限制

- LIDMark 当前只有 smoke checkpoint，尚无官方 full checkpoint。
- LIDMark 官方 watermark 数据已存在，但配套 CelebA-HQ 图像缺失，正式训练当前被数据 gate 阻断。
- KAD-Net 源码已接入，但服务器没有 KAD-Net checkpoint，且原始运行环境与统一环境存在版本差异。
- 当前正式全量评测集中在 LFW，仍需补 CelebA-HQ、FaceForensics++、Celeb-DF 等跨域数据。
- HiDDeN 接近随机；阈值错误已排除，当前更可能是域偏移或 checkpoint/训练协议不匹配。
- WaveGuard JPEG Q=50 已通过 JPEG STE 7ep 微调修复（100%，CI=[1.0,1.0]）；detector 与 tracer 严格加载已验证。
- 三套历史 benchmark 的预处理和 PSNR/SSIM 参考语义尚未完全统一。
- 已提供逐图 Bootstrap CI、配对检验、效应量和 Holm 校正，但历史结果仅 1 seed，不能替代多 seed 重跑。
- 已完成 100 图、15 类传播/编辑攻击库 smoke；真实 Deepfake 模型攻击和模型级全量结果仍缺失。
- 二次嵌入 5×5 adapter 合约与矩阵计划已建立，但真实模型 adapter 尚未完成，当前 25 格均 blocked。
