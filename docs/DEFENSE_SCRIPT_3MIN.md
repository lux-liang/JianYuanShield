# 3 分钟答辩脚本

我们做的不是普通 Deepfake 分类器，而是“鉴源盾”：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台。

核心问题是：内容在生成、传播、二次编辑、多平台转发过程中，原始来源会丢失，攻击者还可以通过多重嵌入攻击破坏取证水印。因此系统必须同时具备保护、攻击评测、恢复和报告能力。

系统包含六个模块：内容保护、Deepfake 攻击模拟、MEA 多重嵌入攻击、取证恢复、安全评测、取证报告。

LIDMark、MEA、WaveGuard、KAD-Net 均是团队原创技术成果，鉴源盾把这些模型从独立算法升级为统一的主动取证平台。当前 HiDDeN、SepMark、WaveGuard 均已完成 13,233 张 LFW 全量评测。

HiDDeN 在当前协议下恢复接近随机，阈值错误已排除；SepMark 更稳定；WaveGuard detector 指标饱和，但严格加载和错误消息、无嵌入负对照已通过。我们不回避异常结果，而是通过证据审计模块明确标记边界。LIDMark 当前仍只使用 smoke checkpoint，KAD-Net 也因 checkpoint 缺失不进入排名。

现场演示中，评委可以选择样本、模型和攻击链，一键生成保护图、攻击图、热力图、恢复指标与输入输出 SHA-256；随后查看全量评测、统计分析和双层发布门禁，并下载 JSON、CSV、Markdown 报告以及 Ed25519 manifest、签名和公钥。

当前系统可演示状态为 ready，但研究结论状态仍为 review。我们明确展示尚未完成的三 seed、真实 Deepfake、二次嵌入和正式 LIDMark/KAD-Net，不用产品完成度替代科学有效性。
