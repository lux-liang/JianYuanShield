# 鉴源盾：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台

鉴源盾面向 AIGC/Deepfake 内容传播链路中的来源丢失、篡改不可见和多重嵌入攻击问题，构建主动取证、攻击模拟、取证恢复、安全评测和报告导出的闭环系统。

## 当前状态

- **KAD-Net**：EC_50.pth（GEOM 微调版），13,233 张 LFW 全量评测已完成。JPEG/noise/resize ≥99%；**几何攻击（crop≈68.9%，rotate≈43.7%）为已知硬限制**。
- **SepMark**：EC_115.pth（pre-trained），13,233 张 LFW 全量评测已完成。bit-acc≈85-89%（clean 87.74%）。
- **WaveGuard**：model_state_16.pth，13,233 张 LFW 全量评测已完成。clean/jpeg70+/noise/resize≈100%；**jpeg50 是真弱点（bit-acc≈89%，success=37.3%）**，正在改进。
- **HiDDeN**：epoch-300 checkpoint（有效），13,233 张 LFW 全量评测已完成。clean/resize 好；**JPEG 域 gap 为已知局限（jpeg50 success=0%）**；有效对照 baseline。
- **LIDMark**：3-seed 正式 checkpoint 已完成，512×3 张评测；landmark 定位成功率 99.93%；**ID 比特精度（bit accuracy）评测进行中**。
- 系统：后端 8026，前端 8027，提供交互式取证演示、全量真实评测、双层发布门禁、统计分析、Ed25519 证据签名和报告下载。

## 技术归属

LIDMark、MEA、WaveGuard、KAD-Net 与鉴源盾统一平台均属于团队原创技术体系。本项目在指导教师同意下进行统一集成、协议化评测和产品化呈现。

## 六个模块

- 内容保护：主动水印/主动取证信号生成与可视化。
- Deepfake 攻击模拟：15 类统一攻击，覆盖 JPEG/WebP、resize、crop、rotate、blur、亮度/对比度、平台转码代理和显式标注的局部编辑代理。
- MEA 多重嵌入攻击：以团队多种主动取证模型为对象开展跨模型覆盖和红队评测。
- 取证恢复：从攻击后图像恢复消息、身份或定位信号。
- 安全评测：统一展示 BER、bit accuracy、PSNR、SSIM、success rate。
- 取证报告：导出 JSON、CSV、Markdown 证据材料。

## 关键路径

- HiDDeN LFW benchmark：`system/reports/hidden_lfw_full_benchmark/`
- SepMark LFW benchmark：`system/reports/sepmark_lfw_benchmark/`
- LIDMark smoke eval：`runs/lidmark_lfw_eval_full/`
- WaveGuard full benchmark：`system/reports/waveguard_lfw_full_benchmark/`
- 聚合评测：`system/reports/aggregate_real_benchmarks/`
- 图表：`system/assets/aggregate_real_benchmarks/`
- 取证报告：`system/reports/jianyuanshield_competition_report/`
- 协议审计：`system/reports/protocol_audit/`
- 统计分析：`system/reports/statistical_analysis/`
- 攻击库 smoke：`system/reports/attack_library_smoke/`
- Ed25519 证据包：`system/reports/evidence_signature/`
- LIDMark/KAD-Net gate：`system/reports/lidmark_training/`、`system/reports/kadnet_integration/`

## 重要声明

系统严格区分真实结果、smoke sanity 和 pending 状态，不把 smoke 结果伪装成正式结论。
四模型（KAD-Net/SepMark/WaveGuard/HiDDeN）均已完成 13,233 张 LFW 全量评测，结果属实；LIDMark 为 512×3（landmark 定位成功率有效，ID 比特精度评测进行中）。已知局限诚实标注：WaveGuard jpeg50 成功率仅 37%、KAD-Net 几何攻击实质失败、HiDDeN JPEG 域 gap。不称 HiDDeN 为"损坏/剔除"——是有效 baseline。
当前 `ready_for_demo=yes`；LIDMark ID 比特精度、WaveGuard jpeg50 改进、真实 Deepfake 评测仍是研究结论阻断项。
