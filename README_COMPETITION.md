# 鉴源盾：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台

鉴源盾面向 AIGC/Deepfake 内容传播链路中的来源丢失、篡改不可见和多重嵌入攻击问题，构建主动取证、攻击模拟、取证恢复、安全评测和报告导出的闭环系统。

## 当前状态

- MEA/HiDDeN：真实 checkpoint 已接入，LFW full benchmark 已完成。
- MEA/SepMark：真实 checkpoint 已接入，LFW full benchmark 后台运行中，当前是最有答辩价值的鲁棒 watermark baseline。
- LIDMark：smoke checkpoint 已接入，LFW eval sanity 已支持。
- WaveGuard：真实 checkpoint 已上传并完成单图 encode/decode smoke，完整 LFW benchmark 仍 pending。
- 系统：后端 8026，前端 8027，提供全量真实评测页面和报告导出路径。

## 六个模块

- 内容保护：主动水印/主动取证信号生成与可视化。
- Deepfake 攻击模拟：JPEG、resize、noise 等传播链路扰动。
- MEA 多重嵌入攻击：以 HiDDeN/WaveGuard 等 baseline 为对象做攻防评测。
- 取证恢复：从攻击后图像恢复消息、身份或定位信号。
- 安全评测：统一展示 BER、bit accuracy、PSNR、SSIM、success rate。
- 取证报告：导出 JSON、CSV、Markdown 证据材料。

## 关键路径

- HiDDeN LFW benchmark：`system/reports/hidden_lfw_full_benchmark/`
- SepMark LFW benchmark：`system/reports/sepmark_lfw_benchmark/`
- LIDMark smoke eval：`runs/lidmark_lfw_eval_full/`
- WaveGuard smoke：`system/reports/waveguard_lfw_benchmark/`
- 聚合评测：`system/reports/aggregate_real_benchmarks/`
- 图表：`system/assets/aggregate_real_benchmarks/`
- 取证报告：`system/reports/jianyuanshield_competition_report/`

## 重要声明

系统严格区分真实结果、smoke sanity 和 pending 状态，不把 smoke 结果伪装成正式结论。
