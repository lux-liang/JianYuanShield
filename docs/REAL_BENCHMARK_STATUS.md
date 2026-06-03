# 真实评测状态

## 当前事实

- LFW 全量真实图片：13,233 张，来自 `datasets/lfw_full_upload/unknown/`。
- MEA/HiDDeN：使用真实 checkpoint `weights/mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/checkpoints/train-test-1--epoch-200.pyt`。
- MEA/SepMark：使用真实 checkpoint `weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth`，已接通 encoder、decoder_C、decoder_RF。
- LIDMark：使用 `weights/lidmark/smoke_128/checkpoints_distortions/checkpoint_epoch_2.pth`，这是 smoke checkpoint，不是官方 full model。
- WaveGuard：`weights/mea/WaveGuard/` 下 checkpoint 已完成单图真实 encode/decode smoke，完整 LFW benchmark 仍 pending。

## 指标使用边界

- HiDDeN LFW benchmark 已完成，可作为真实 checkpoint 在真实 LFW 数据上的正式系统评测结论。
- SepMark LFW benchmark 正在后台全量运行。运行中 partial 指标可用于工程进度说明，但最终答辩应使用 `progress.json` 标记 complete 后的 summary。
- LIDMark 当前结果只能说明系统链路、数据组织和 smoke checkpoint 能运行，不能作为 LIDMark 正式性能结论。
- WaveGuard 当前只能说明真实权重可加载且单图 encode/decode 链路已通，不能声称已完成 LFW benchmark。

## 输出

- HiDDeN：`system/reports/hidden_lfw_full_benchmark/results.csv`、`summary.json`、`progress.json`、`bad_cases.csv`
- SepMark：`system/reports/sepmark_lfw_benchmark/results.csv`、`summary.json`、`progress.json`、`bad_cases.csv`
- LIDMark：`runs/lidmark_lfw_eval_full/results.csv`、`summary.json`、`progress.json`
- WaveGuard：`system/reports/waveguard_lfw_benchmark/summary.json`、`system/reports/waveguard_lfw_benchmark/single_smoke.json`
- 聚合：`system/reports/aggregate_real_benchmarks/method_comparison.csv`
- 报告：`system/reports/jianyuanshield_competition_report/report.md`

## 答辩表述

可以说：系统已经接入 MEA/HiDDeN 和 MEA/SepMark 真实 checkpoint，并在真实 LFW 图片上进行 clean、JPEG、resize、noise 攻击评测；LIDMark smoke checkpoint 和 WaveGuard checkpoint load smoke 已纳入统一平台。

不能说：LIDMark smoke checkpoint 是官方 full model，或 WaveGuard 已完成完整 LFW benchmark。
