# 后续 14 天计划

1. 补齐合法 CelebA-HQ 配对图像，先通过 LIDMark 单 batch、resume 和验证集 gate，再启动三个 seed 的正式训练。
2. 取得团队 KAD-Net ST/FD checkpoint，修复路径和兼容环境，完成 strict-load 与 16 图负对照。
3. 从 HiDDeN、SepMark、WaveGuard、LIDMark 脚本拆出真实 adapter，逐格解锁 5×5 二次嵌入矩阵。
4. 用统一攻击库重跑至少 512 图，包括 crop、rotate、WebP、平台转码和真实 Deepfake 模型攻击。
5. 对统一协议结果完成三个 seed、跨数据集和效应量分析，旧协议结果不参与最终排名。
6. 完成移动端/离线演示验收、CI 安全扫描，并重新生成和签署最终答辩证据包。
