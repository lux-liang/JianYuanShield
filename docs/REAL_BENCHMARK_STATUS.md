# 真实评测状态

## 当前事实

- LFW 全量真实图片：13,233 张，来自 `datasets/lfw_full_upload/unknown/`。
- MEA/HiDDeN：使用真实 checkpoint `weights/mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/checkpoints/train-test-1--epoch-200.pyt`。
- MEA/SepMark：使用真实 checkpoint `weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth`，已接通 encoder、decoder_C、decoder_RF。
- LIDMark：使用 `weights/lidmark/smoke_128/checkpoints_distortions/checkpoint_epoch_2.pth`，这是 smoke checkpoint，不是官方 full model。
- WaveGuard：使用真实 checkpoint，13,233 张 LFW full benchmark 已完成。

## 指标使用边界

- HiDDeN LFW benchmark 已完成，可作为真实 checkpoint 在真实 LFW 数据上的正式系统评测结论。
- SepMark LFW benchmark 已完成，`progress.json` 为 complete。
- LIDMark 当前结果只能说明系统链路、数据组织和 smoke checkpoint 能运行，不能作为 LIDMark 正式性能结论。
- WaveGuard 已完成真实模型全量推理，但 detector 部分指标饱和，正式结论前需完成严格加载和数据泄漏复核。

## 输出

- HiDDeN：`system/reports/hidden_lfw_full_benchmark/results.csv`、`summary.json`、`progress.json`、`bad_cases.csv`
- SepMark：`system/reports/sepmark_lfw_benchmark/results.csv`、`summary.json`、`progress.json`、`bad_cases.csv`
- LIDMark：`runs/lidmark_lfw_eval_full/results.csv`、`summary.json`、`progress.json`
- WaveGuard：`system/reports/waveguard_lfw_full_benchmark/summary.json`、`results.csv`、`progress.json`
- 聚合：`system/reports/aggregate_real_benchmarks/method_comparison.csv`
- 报告：`system/reports/jianyuanshield_competition_report/report.md`

## 答辩表述

可以说：HiDDeN、SepMark、WaveGuard 均完成 13,233 张真实 LFW 全量评测；LIDMark 当前仍是 smoke checkpoint。四类模型均属于团队技术体系。

不能说：LIDMark smoke checkpoint 已达到正式模型性能，或在协议复核前把 WaveGuard 饱和指标直接解释为绝对领先。
