# 创新点

1. 团队原创 LIDMark、MEA、WaveGuard、KAD-Net 形成面向 Deepfake 后溯源的主动水印算法族，并由鉴源盾统一产品化。
2. 从单图检测升级到覆盖内容保护、传播攻击、恢复、评测和证据报告的完整链路。
3. 以 MEA 多重嵌入攻击协议构建主动取证红队评测，揭示多水印并存场景下后嵌入对先嵌入水印的破坏规律；据调研，多水印共存场景的系统性评测协议在文献中较少见。
4. 统一 real checkpoint、smoke checkpoint、协议审计和异常指标提示，保证结论可核验。
5. KAD-Net / SepMark / WaveGuard / HiDDeN 四模型均在 13,233 张 LFW 全量上完成真实评测（n=13,233）。KAD-Net（EC_50，GEOM 微调版）JPEG/noise/resize 全部 ≥99%，几何攻击（裁剪/旋转）仍实质失败，是已知局限；WaveGuard（model_state_16）除 jpeg50 外≈100%，jpeg50 bit-acc≈89%/成功率仅 37%，是真弱点；SepMark（EC_115，pre-trained）bit-acc≈85-89%（clean 87.74%）；HiDDeN（epoch-300）clean/resize 好，JPEG 域 gap 为已知局限，作为有效对照 baseline。四模型形成不同鲁棒性水平与场景覆盖的横向对照。LIDMark 为 512×3（同批图，landmark 定位成功率 99.93%，ID 比特精度评测进行中）。
6. 取证任务记录输入与输出 SHA-256，结合 Ed25519 签名生成可独立验签的证据包，为数字签名和防篡改报告提供完整实现。
7. 前端同时提供交互式单样本演示和全量 benchmark 证据，避免只展示静态页面。
