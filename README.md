# JianYuanShield

鉴源盾：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台。

This repository contains the competition system code, benchmark orchestration scripts, frontend dashboard, backend APIs, and defense materials. Large datasets, pretrained checkpoints, runtime reports, and generated assets are intentionally excluded from Git.

## Modules

- 内容保护
- Deepfake 攻击模拟
- MEA 多重嵌入攻击
- 取证恢复
- 安全评测
- 取证报告

## Repository Layout

```text
system/backend/      FastAPI backend
system/frontend/     Static dashboard
system/scripts/      Benchmark, aggregation, and report scripts
docs/                Competition defense materials
README_COMPETITION.md
```

## Runtime Ports

- Backend: `8026`
- Frontend: `8027`

## Artifact Policy

Do not commit:

- `datasets/`
- `weights/`
- `runs/`
- `system/reports/`
- `system/assets/`
- checkpoint files such as `.pth`, `.pyt`, `.pt`, `.ckpt`

See `README_COMPETITION.md` and `docs/REAL_BENCHMARK_STATUS.md` for the current evaluation narrative.

