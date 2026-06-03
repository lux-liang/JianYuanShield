# 3 分钟答辩脚本

我们做的不是普通 Deepfake 分类器，而是“鉴源盾”：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台。

核心问题是：内容在生成、传播、二次编辑、多平台转发过程中，原始来源会丢失，攻击者还可以通过多重嵌入攻击破坏取证水印。因此系统必须同时具备保护、攻击评测、恢复和报告能力。

系统包含六个模块：内容保护、Deepfake 攻击模拟、MEA 多重嵌入攻击、取证恢复、安全评测、取证报告。

当前系统已经接入 MEA/HiDDeN 和 MEA/SepMark 真实 checkpoint，并在 LFW 真实图片上运行 clean、JPEG、resize、noise 攻击评测。HiDDeN 在 LFW 上 bit accuracy 接近随机，因此我们把它作为真实弱对照；SepMark 的 decoder_C 和 decoder_RF 在相同数据和攻击设置下明显更稳，是当前答辩主线 baseline。

我们没有把 smoke 结果包装成正式结果：LIDMark 当前只使用 smoke checkpoint，WaveGuard 当前只完成 checkpoint load smoke。系统前端和报告都会明确标注 real、smoke、pending，保证评测证据链可信。
