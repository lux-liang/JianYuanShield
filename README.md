<div align="center">

# 鉴源盾 · JianYuanShield

**AI 内容可信认证与溯源平台**

*面向《人工智能生成合成内容标识办法》的隐式标识技术落地方案*

---

[![LIDMark](https://img.shields.io/badge/LIDMark-CVPR%202026%20Highlight-red?logo=googlescholar)](https://arxiv.org/abs/2602.23523)
[![KAD-Net](https://img.shields.io/badge/KAD--Net-KBS%202025-blue)](https://github.com/vpsg-research/KAD-Net)
[![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

## 🔍 项目定位

2025 年 9 月 1 日，国家网信办等四部门联合颁布的《人工智能生成合成内容标识办法》正式施行，要求平台和服务商对 AI 生成内容同时添加**显式标识**（可见水印/标签）与**隐式标识**（嵌入文件元数据的不可见水印），并保证内容可溯源、可取证。

**鉴源盾**是该法规"隐式标识"技术要求的完整落地方案，面向三类核心用户场景构建取证闭环：

| 用户角色 | 核心痛点 | 鉴源盾解决方案 |
|----------|----------|---------------|
| **内容创作者**（自媒体/博主） | 原创图/视频被 Deepfake 篡改后冒充原版传播，无法举证 | 发布前嵌入 LIDMark 水印；被篡改后精确定位篡改区域、追溯原始来源 |
| **平台合规部门**（小红书/抖音/微博） | 法规要求隐式标识，但批量验证成本高、缺乏统一技术标准 | 统一水印嵌入/验证 API；合规审计报告自动生成 |
| **执法/司法机构** | 处置 AI 换脸诈骗时缺乏可在法庭使用的数字取证材料 | Ed25519 签名证据包；文件哈希 + 篡改定位 + 水印溯源，可作司法存证 |

---

## 🏗️ 系统架构

```
鉴源盾平台
├── 内容保护        主动水印嵌入（LIDMark / SepMark / WaveGuard / KAD-Net）
├── Deepfake 攻击模拟   15 类传播链路攻击（JPEG / WebP / resize / 平台转码 / Deepfake 代理）
├── MEA 多重嵌入攻击    跨模型红队评测（5×5 攻击矩阵）
├── 取证恢复        攻击后消息/身份/篡改位置恢复
├── 安全评测        统一 BER / PSNR / SSIM / Success Rate benchmark
└── 取证报告        JSON / CSV / Markdown 导出 + Ed25519 签名证据包
```

**核心算法**（团队原创，均已发表）：

| 模型 | 论文 | 核心创新 |
|------|------|---------|
| **LIDMark** | [CVPR 2026 Highlight](https://arxiv.org/abs/2602.23523) | 152-D 地标-身份联合水印；FHD 分头解码器；Deepfake 检测+定位+溯源三合一 |
| **KAD-Net** | KBS 2025 | Kolmogorov-Arnold 网络 + 差分感知；稳健+敏感双解码头 |
| **MEA** | — | 多重嵌入攻击（Multi-Embedding Attack）框架；跨模型覆盖评测 |
| **WaveGuard** | — | 频域主动水印；Deepfake 鲁棒性基线 |

---

## 📊 真实评测结果（LFW 13,233 张）

> 所有结果来自真实 checkpoint 在真实 LFW 数据集上的全量推理，数据已通过 Ed25519 签名存证。

| 模型 | checkpoint | clean Acc | JPEG-50 成功率 | PSNR | 评测状态 |
|------|-----------|-----------|--------------|------|---------|
| **SepMark** | 官方 | 91.2% (RF) | 88.1% | 39.7 dB | ✅ 全量完成 |
| **WaveGuard** | 官方 | 100% (detector) | 37.3% | 33.3 dB | ✅ 全量完成 |
| **HiDDeN** | 官方 | 50.4% | — | 32.5 dB | ⚠️ 域偏移，复核中 |
| **LIDMark** | 训练中 | — | — | — | 🔄 正式训练中（CVPR 2026）|
| **KAD-Net** | 训练中 | — | — | — | 🔄 正式训练中 |

---

## 🚀 快速开始

### 环境要求

```
Python 3.10+  |  PyTorch 2.x  |  CUDA 12.x（推理）
```

### 安装

```bash
git clone https://github.com/lux-liang/JianYuanShield.git
cd JianYuanShield
pip install -r requirements.txt
cp .env.example .env   # 按需修改端口和路径
```

### 启动服务

```bash
# 后端 API（端口 8026）
uvicorn system.backend.app:app --host 0.0.0.0 --port 8026

# 前端 Dashboard（端口 8027）
python -m http.server 8027 --directory system/frontend
```

打开 `http://127.0.0.1:8027` 进入证据工作台。

### 系统检查

```bash
# 演示就绪检查
PYTHONPATH=. python scripts/check_system.py --strict

# 运行测试套件（37 项）
bash scripts/run_tests.sh
```

---

## 🎬 三个核心演示场景

### Demo 1 · 创作者保护

```
原创图片上传  →  LIDMark 嵌入隐式水印  →  图片被 Deepfake 换脸篡改
→  鉴源盾检测：来源 = 原创作者，篡改区域 = 面部，置信度 = 98%
→  输出 Ed25519 签名证据包（可用于平台投诉/司法存证）
```

### Demo 2 · 平台合规检测

```
平台批量内容流  →  API 调用 /api/infer/batch
→  返回：合规水印已有 / AI 生成无标识 / 疑似篡改
→  合规报告（对应《标识办法》第五条技术要求）
```

### Demo 3 · 多模型抗攻击横评（MEA）

```
同一图片，四种水印方案，同一攻击链
→  可视化：SepMark vs WaveGuard vs LIDMark vs KAD-Net
→  结论：哪种方案在"平台转码"真实攻击下最抗打
→  为平台选型提供数据支撑
```

---

## 📁 目录结构

```
JianYuanShield/
├── system/
│   ├── backend/          FastAPI 后端（路由/取证逻辑/签名/评测）
│   ├── frontend/         静态前端 Dashboard
│   ├── evaluation/       统一评测协议（BER/PSNR/SSIM/攻击矩阵）
│   └── scripts/          Benchmark 脚本 / 报告生成 / 数据准备
├── configs/              评测协议配置 / 训练配置
├── tests/                37 项自动化测试
├── bruno/                API 测试集合（Bruno CLI）
├── docs/                 竞赛答辩材料 / 评测协议文档
└── scripts/              系统检查 / 训练启动 / 数据准备
```

> **大文件不进仓库**：`datasets/`、`weights/`、`runs/`、`system/reports/` 均通过符号链接指向 `/data1`，见 `.gitignore`。

---

## 🔒 证据完整性

系统使用 **Ed25519** 对 canonical evidence manifest 进行签名，当前覆盖 19 个证据/模型/报告文件：

```bash
# 验证证据签名
curl http://127.0.0.1:8026/api/evidence/signature

# 下载证据包
curl http://127.0.0.1:8026/api/evidence/signature/download/manifest
curl http://127.0.0.1:8026/api/evidence/signature/download/signature
curl http://127.0.0.1:8026/api/evidence/signature/download/public-key
```

任何已签名文件被修改，验证结果均返回 `content_mismatch`。

---

## 📋 评测协议

统一协议版本：`evaluation_protocol.v1`

- **数据集**：LFW 13,233 张真实人脸图像
- **攻击集**：15 类（JPEG/WebP/resize/crop/rotate/blur/亮度/对比度/高斯噪声/平台转码代理×2/Deepfake 编辑代理）
- **指标**：BER、Bit Accuracy、PSNR（watermarked vs original）、SSIM、Success Rate（阈值 90%）
- **统计**：Bootstrap CI、配对符号翻转检验、效应量、Holm 多重比较校正

---

## 🗺️ 路线图

- [x] 四模型统一评测协议
- [x] LFW 全量真实 benchmark（HiDDeN / SepMark / WaveGuard）
- [x] Ed25519 证据签名
- [x] 双层发布门禁（ready\_for\_demo / ready\_for\_claims）
- [x] Bootstrap CI + 统计显著性分析
- [ ] LIDMark 正式训练完成（训练中）
- [ ] KAD-Net 正式训练完成（训练中）
- [ ] MEA 5×5 跨模型攻击矩阵（依赖正式 checkpoint）
- [ ] 视频帧级水印扩展
- [ ] Docker 离线部署包
- [ ] 区块链存证集成

---

## 📄 相关论文

```bibtex
@inproceedings{wu2026lidmark,
  title     = {All in One: Unifying Deepfake Detection, Tampering Localization,
               and Source Tracing with a Robust Landmark-Identity Watermark},
  author    = {Junjiang Wu and Liejun Wang and Zhiqing Guo},
  booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision
               and Pattern Recognition (CVPR)},
  year      = {2026},
  note      = {Highlight}
}
```

---

## ⚠️ 重要声明

系统严格区分：

- **`ready_for_demo: yes`** — 系统可演示，链路完整
- **`ready_for_claims: no`** — LIDMark/KAD-Net 正式训练尚未完成，正式性能结论待出

当前 HiDDeN 接近随机、WaveGuard 部分指标饱和，均已在系统审计中明确标注，不包装为绝对优越性结论。

---

<div align="center">

**鉴源盾** · 让每一张图片都有可验证的来源

*Powered by CVPR 2026 LIDMark · 《人工智能生成合成内容标识办法》技术落地*

</div>
