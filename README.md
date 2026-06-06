<div align="center">

# 鉴源盾 · JianYuanShield

**AI 内容可信认证与溯源平台**

*面向《人工智能生成合成内容标识办法》的隐式标识技术落地方案*

---

[![LIDMark](https://img.shields.io/badge/LIDMark-CVPR%202026%20Highlight-red?logo=googlescholar)](https://arxiv.org/abs/2602.23523)
[![KAD-Net](https://img.shields.io/badge/KAD--Net-KBS%202025-blue)](https://github.com/vpsg-research/KAD-Net)
[![Training](https://img.shields.io/badge/Training-Live%20on%208×RTX4090-brightgreen?logo=nvidia)](https://github.com/lux-liang/JianYuanShield)
[![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi)](https://fastapi.tiangolo.com)

</div>

---

## 🔍 项目定位

2025 年 9 月 1 日，《人工智能生成合成内容标识办法》正式施行，要求服务商同时添加**显式标识**与**隐式标识**（嵌入文件的不可见水印），并保证内容可溯源、可取证。

**鉴源盾**是该法规"隐式标识"技术要求的完整落地方案，面向三类核心用户构建取证闭环：

| 用户角色 | 核心痛点 | 鉴源盾解决方案 |
|----------|----------|---------------|
| **内容创作者**（自媒体/博主） | 原创图被 Deepfake 篡改后冒充原版传播 | 发布前嵌入 LIDMark 水印；篡改后精确定位区域、追溯来源 |
| **平台合规部门**（小红书/抖音/微博） | 法规要求隐式标识，批量验证成本高 | 统一水印验证 API；合规审计报告自动生成 |
| **执法/司法机构** | AI 换脸取证困难，无可用司法材料 | Ed25519 签名证据包；篡改定位 + 水印溯源 |

---

## 🚀 训练状态（实时）

> 8× RTX 4090 全功率运行中

| 模型 | GPU | Seed | 当前进度 | id_BER@Val | PSNR |
|------|-----|------|---------|-----------|------|
| **LIDMark** | 2,3 | 20260603 | Epoch 5+ | **0.0%** | 29.2→↑ |
| **LIDMark** | 5,6 | 20260604 | Epoch 2+ | **0.0%** | 收敛中 |
| **LIDMark** | 7   | 20260605 | Epoch 2+ | **0.0%** | 收敛中 |
| **KAD-Net** | 4   | —        | Epoch 1  | ~50%→收敛 | — |

> LIDMark 第 2 个 epoch 即达到 id_BER=0%（身份水印完美恢复），收敛速度超出预期。

---

## 📊 已完成评测（LFW 13,233 张真实图像）

| 模型 | Checkpoint | clean Acc | JPEG-50 成功率 | PSNR | 状态 |
|------|-----------|-----------|--------------|------|------|
| **SepMark** | 官方真实 | 91.2% (RF) | 88.1% | 39.7 dB | ✅ 全量完成 |
| **WaveGuard** | 官方真实 | 100% (detector) | 37.3% | 33.3 dB | ✅ 全量完成 |
| **HiDDeN** | 官方真实 | 50.4% | — | 32.5 dB | ⚠️ 域偏移，复核中 |
| **LIDMark** | 训练中 | — | — | — | 🔄 3×seed 并行训练 |
| **KAD-Net** | 训练中 | — | — | — | 🔄 ST-branch 训练中 |

---

## 🎯 MEA 多重嵌入攻击矩阵（2×2 Smoke，16 图/格）

| Source → Attacker | 第一水印保留率 | 第二水印成功率 | 结论 |
|-------------------|:---:|:---:|------|
| SepMark → SepMark | 90% | 59% | 同模型重嵌入破坏原水印 |
| SepMark → WaveGuard | **91%** | **100%** | 跨域水印共存，频域不干扰空域 |
| WaveGuard → SepMark | **100%** | 97% | WaveGuard 极强鲁棒性 |
| WaveGuard → WaveGuard | 53% | **99%** | 同频域重嵌入覆盖 |

---

## 🔌 API 快速接入

### 单图取证（移动端 / 平台集成）

```bash
curl -X POST http://server:8026/api/infer/single \
  -F "file=@photo.jpg" \
  -F "model=SepMark" \
  -F "attack=jpeg50" \
  -F "return_b64=false"
```

返回：水印图、热力图、BER/PSNR/SSIM、Ed25519 哈希、合规结论。

### 平台批量合规检测

```bash
curl -X POST http://server:8026/api/compliance/batch \
  -F "files=@img1.jpg" -F "files=@img2.jpg" \
  -F "model=SepMark"
```

返回：每图合规状态（`watermark_verified` / `watermark_degraded` / `no_watermark`）+ 汇总报告。

### 模型状态

```bash
curl http://server:8026/api/models/status
```

---

## 🏗️ 系统架构

```
鉴源盾平台
├── 内容保护        主动水印嵌入（LIDMark / SepMark / WaveGuard / KAD-Net）
├── Deepfake 攻击模拟   15 类传播链路攻击
├── MEA 多重嵌入攻击    跨模型 5×5 攻击矩阵（2×2 已解锁）
├── 取证恢复        攻击后消息/身份/篡改位置恢复
├── 安全评测        统一 BER/PSNR/SSIM/Success Rate benchmark
└── 取证报告        JSON/CSV/Markdown + Ed25519 签名证据包
```

**核心算法**（团队原创）：

| 模型 | 论文 | 核心创新 |
|------|------|---------|
| **LIDMark** | [CVPR 2026 Highlight](https://arxiv.org/abs/2602.23523) | 152-D 地标-身份联合水印；FHD 分头解码；三功能取证 |
| **KAD-Net** | KBS 2025 | Kolmogorov-Arnold 网络 + 差分感知双解码头 |
| **MEA** | — | 多重嵌入攻击框架；跨模型覆盖评测 |
| **WaveGuard** | — | 频域主动水印；平台转码鲁棒性基线 |

---

## 🚀 快速开始

```bash
git clone https://github.com/lux-liang/JianYuanShield.git
cd JianYuanShield
pip install -r requirements.txt
cp .env.example .env

# 启动后端 API
PYTHONPATH=. uvicorn system.backend.app:app --host 0.0.0.0 --port 8026

# 启动前端
python -m http.server 8027 --directory system/frontend
```

```bash
# 系统就绪检查
PYTHONPATH=. python scripts/check_system.py --strict

# 测试套件（37 项）
bash scripts/run_tests.sh

# MEA 矩阵 smoke
PYTHONPATH=. python scripts/run_mea_matrix_smoke.py
```

---

## 🎬 三个核心演示场景

### Demo 1 · 创作者保护（小红书/微博）
原创图上传 → LIDMark 嵌入隐式水印 → 被 Deepfake 换脸篡改 → 鉴源盾检测：来源=原创作者、篡改区域=面部 → Ed25519 签名证据包可用于平台投诉/司法存证

### Demo 2 · 平台合规批量检测
批量内容流 → `/api/compliance/batch` → 返回每图合规状态 → 对应《标识办法》第五条技术要求

### Demo 3 · 多模型抗攻击横评（MEA）
同图，四种水印方案，相同攻击链 → 可视化 SepMark vs WaveGuard vs LIDMark vs KAD-Net → 为平台选型提供数据支撑

---

## 📁 目录结构

```
JianYuanShield/
├── system/
│   ├── backend/          FastAPI 后端
│   │   ├── model_adapters.py   SepMark + WaveGuard 真实推理 adapter
│   │   └── infer.py           单图取证 / 合规批量检测逻辑
│   ├── frontend/         静态前端 Dashboard
│   └── evaluation/
│       ├── adapters/     MEA ModelAdapter 接口（SepMark / WaveGuard 已实现）
│       └── metrics.py    统一指标库
├── scripts/
│   ├── run_mea_matrix_smoke.py    MEA 矩阵 smoke 测试
│   ├── launch_lidmark_training.py  LIDMark 多 seed 训练启动器
│   └── run_tests.sh               PYTHONPATH 正确的测试运行器
└── tests/                37 项自动化测试（全部通过）
```

---

## 🗺️ 路线图

- [x] 四模型统一评测协议 (`evaluation_protocol.v1`)
- [x] LFW 全量真实 benchmark（HiDDeN / SepMark / WaveGuard）
- [x] Ed25519 证据签名（覆盖 19 个文件）
- [x] 双层发布门禁（ready_for_demo / ready_for_claims）
- [x] Bootstrap CI + 统计显著性分析
- [x] 真实推理 API（/api/infer/single，/api/compliance/batch）
- [x] MEA 2×2 矩阵 adapter + smoke 验证
- [ ] **LIDMark 3-seed 正式训练完成**（进行中，预计 3-4 小时）
- [ ] **KAD-Net 正式训练完成**（进行中）
- [ ] LIDMark 正式 LFW benchmark（训练完成后）
- [ ] MEA 5×5 矩阵全格解锁（LIDMark + KAD-Net 完成后）
- [ ] 视频帧级水印扩展
- [ ] Docker 离线部署包

---

## 🔒 证据完整性

```bash
# 验证 Ed25519 签名
curl http://server:8026/api/evidence/signature

# 下载证据包
curl http://server:8026/api/evidence/signature/download/manifest
curl http://server:8026/api/evidence/signature/download/signature
curl http://server:8026/api/evidence/signature/download/public-key
```

---

## ⚠️ 诚实声明

- **`ready_for_demo: yes`** — 系统可演示，链路完整，SepMark/WaveGuard 真实推理就绪
- **`ready_for_claims: no`** — LIDMark/KAD-Net 正式训练进行中；HiDDeN 域偏移待复核

---

## 📄 引用

```bibtex
@inproceedings{wu2026lidmark,
  title     = {All in One: Unifying Deepfake Detection, Tampering Localization,
               and Source Tracing with a Robust Landmark-Identity Watermark},
  author    = {Junjiang Wu and Liejun Wang and Zhiqing Guo},
  booktitle = {CVPR},
  year      = {2026},
  note      = {Highlight}
}
```

---

<div align="center">

**鉴源盾** · 让每一张图片都有可验证的来源

*CVPR 2026 LIDMark · 《人工智能生成合成内容标识办法》技术落地 · 8× RTX 4090 实时训练中*

</div>
