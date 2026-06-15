# 3 分钟答辩脚本

我们做的不是普通 Deepfake 分类器，而是“鉴源盾”：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台。

核心问题是：内容在生成、传播、二次编辑、多平台转发过程中，原始来源会丢失，攻击者还可以通过多重嵌入攻击破坏取证水印。因此系统必须同时具备保护、攻击评测、恢复和报告能力。

系统包含六个模块：内容保护、Deepfake 攻击模拟、MEA 多重嵌入攻击、取证恢复、安全评测、取证报告。

LIDMark、MEA、WaveGuard、KAD-Net 均是团队原创技术成果，鉴源盾把这些模型从独立算法升级为统一的主动取证平台。SepMark 已完成 13,233 张 LFW 全量评测（decoder_RF 91.2%）；WaveGuard、LIDMark、KAD-Net 各评测 512 张（LIDMark 3 seed × 512 张）。

HiDDeN 已剔除（精度≈50%，checkpoint 损坏，作失效案例对照保留）；SepMark RF decoder 91.2%；WaveGuard JPEG STE 7ep 微调后 detector Q=50=89%，Q=70=99.7%（tracer 溯源比特 Q=50 实测≈52%，进一步微调进行中）。我们不回避异常结果，而是通过证据审计模块明确标记边界。LIDMark 已完成 3 seed 正式训练，landmark 定位成功率 99.93%（ID 比特精度评测进行中）。KAD-Net 独立训练 100ep，clean/jpeg/noise/resize 全部 100%，已全部进入正式评测（几何攻击 partial，crop≈68.9%/rotate≈43.7%，微调进行中）。

现场演示中，评委可以选择样本、模型和攻击链，一键生成保护图、攻击图、热力图、恢复指标与输入输出 SHA-256；随后查看全量评测、统计分析和双层发布门禁，并下载 JSON、CSV、Markdown 报告以及 Ed25519 manifest、签名和公钥。

当前系统可演示状态为 ready，但研究结论状态仍为 review。我们明确展示尚未完成的三 seed、真实 Deepfake、二次嵌入和正式 LIDMark/KAD-Net，不用产品完成度替代科学有效性。
