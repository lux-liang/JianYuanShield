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

## Quick Start

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Start backend and frontend:

```bash
./scripts/dev.sh
```

Open:

```text
http://127.0.0.1:8027
```

Optional local configuration:

```bash
cp .env.example .env
```

Supported service settings:

```text
JYS_BACKEND_HOST
JYS_BACKEND_PORT
JYS_FRONTEND_HOST
JYS_FRONTEND_PORT
JYS_LOG_LEVEL
JYS_MODE
JYS_VERSION
JYS_ENABLE_DEMO
```

Run a local system check:

```bash
python3 scripts/check_system.py
```

Run backend smoke tests:

```bash
python3 -m unittest discover -s tests
```

Open the Bruno API collection:

```text
bruno/
```

Use the `local` environment. With Bruno CLI:

```bash
bru run bruno --env-file bruno/environments/local.bru
```

Backend logs are written to:

```text
logs/backend.log
```

Use strict mode before a release/demo:

```bash
python3 scripts/check_system.py --strict
```

## Artifact Policy

Do not commit:

- `datasets/`
- `weights/`
- `runs/`
- `system/reports/`
- `system/assets/`
- checkpoint files such as `.pth`, `.pyt`, `.pt`, `.ckpt`

See `README_COMPETITION.md` and `docs/REAL_BENCHMARK_STATUS.md` for the current evaluation narrative.
