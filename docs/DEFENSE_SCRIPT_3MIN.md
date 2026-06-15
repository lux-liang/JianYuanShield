# 3 分钟答辩脚本

我们做的不是普通 Deepfake 分类器，而是“鉴源盾”：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台。

核心问题是：内容在生成、传播、二次编辑、多平台转发过程中，原始来源会丢失，攻击者还可以通过多重嵌入攻击破坏取证水印。因此系统必须同时具备保护、攻击评测、恢复和报告能力。

系统包含六个模块：内容保护、Deepfake 攻击模拟、MEA 多重嵌入攻击、取证恢复、安全评测、取证报告。

LIDMark、MEA、WaveGuard、KAD-Net 均是团队原创技术成果，鉴源盾把这些模型从独立算法升级为统一的主动取证平台。KAD-Net / SepMark / WaveGuard / HiDDeN 四模型均完成 13,233 张 LFW 全量评测；LIDMark 3 seed × 512 张。

KAD-Net（EC_50，GEOM 微调，n=13,233）JPEG/noise/resize 全部 ≥99%，几何攻击（crop≈68.9%/rotate≈43.7%）为已知局限；WaveGuard（model_state_16，n=13,233）除 jpeg50 外≈100%，jpeg50 bit-acc≈89%/成功率仅 37%，正在改进；SepMark（n=13,233）bit-acc≈85-89%（clean 87.74%）；HiDDeN（epoch-300，n=13,233）clean/resize 好，JPEG 域 gap 为已知局限，作有效对照 baseline——我们不把 HiDDeN 的 JPEG 局限隐藏，而是通过横向对照体现不同水印方案的鲁棒性差异。LIDMark 已完成 3 seed 正式训练，landmark 定位成功率 99.93%（ID 比特精度评测进行中）。

现场演示中，评委可以选择样本、模型和攻击链，一键生成保护图、攻击图、热力图、恢复指标与输入输出 SHA-256；随后查看全量评测、统计分析和双层发布门禁，并下载 JSON、CSV、Markdown 报告以及 Ed25519 manifest、签名和公钥。

当前系统可演示状态为 ready，但研究结论状态仍为 review。我们明确展示尚未完成的三 seed、真实 Deepfake、二次嵌入和正式 LIDMark/KAD-Net，不用产品完成度替代科学有效性。
