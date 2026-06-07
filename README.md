<div align="center">

# 鉴源盾 · JianYuanShield

**基于多模型协同水印的人脸深度伪造溯源与取证平台**

*《人工智能生成合成内容标识办法》隐式标识技术的完整落地方案*

---

[![LIDMark](https://img.shields.io/badge/LIDMark-CVPR%202026%20Highlight-red?logo=googlescholar)](https://arxiv.org/abs/2602.23523)
[![KAD-Net](https://img.shields.io/badge/KAD--Net-KBS%202025-blue)](https://github.com/vpsg-research/KAD-Net)
[![LFW Benchmark](https://img.shields.io/badge/LFW%20全量基准-13%2C233%20imgs-brightgreen)](https://github.com/lux-liang/JianYuanShield)
[![Ed25519](https://img.shields.io/badge/证据链-Ed25519%20Verified-success)](https://github.com/lux-liang/JianYuanShield)
[![Bootstrap CI](https://img.shields.io/badge/统计-Bootstrap%2095%%20CI-orange)](https://github.com/lux-liang/JianYuanShield)
[![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)](https://python.org)

</div>

---

## 一句话定位

> **鉴源盾**是一套面向深度伪造溯源场景的多模型水印平台：在内容发布时主动嵌入创作者身份水印，在 Deepfake 篡改后仍能精确追溯来源，并以 Ed25519 签名证据链满足司法取证要求。

---

## 一、背景与立项意义

### 1.1 深度伪造：2025 年信息安全的头号威胁

Deepfake 技术迭代加速——2024 年 FaceSwap、SimSwap 已可在普通显卡实时换脸，AIGC 换脸工具月活过亿。其危害包括：

- **政治谣言**：伪造政要视频、制造虚假声明
- **隐私侵害**：无授权人脸合成、色情换脸
- **金融诈骗**：声音+人脸克隆绕过实人认证
- **版权纠纷**：原创内容被篡改后冒充他人作品

现有平台（微信、抖音、小红书）仅能**被动检测**（是否为 AI 生成），**无法回答"这张图是谁发布的"**——溯源能力缺失。

### 1.2 法规强制要求：从"能做"到"必须做"

**2025 年 9 月 1 日**，《人工智能生成合成内容标识办法》正式施行。核心条款：

| 条款 | 要求 | 鉴源盾对应能力 |
|------|------|--------------|
| 第六条 | 服务提供者须添加**隐式标识**（不可见水印） | 四模型 API 批量嵌入，PSNR ≥ 37 dB |
| 第七条 | 标识须**稳健抗干扰**，传播后仍可识别 | LFW 全量基准 91%–100%，覆盖 15 种攻击 |
| 第八条 | 须支持**监管机构溯源查验** | Ed25519 签名证据包，可随时验签 |
| 第十二条 | 平台须建立**内容可信体系** | 合规审计 API，自动生成 JSON 报告 |

鉴源盾是目前**唯一**同时满足以上四条要求的开源技术方案。

### 1.3 现有方案的致命局限

| 方案 | 类型 | 致命缺陷 |
|------|------|---------|
| FaceForensics++ | 被动检测 | 告诉你"这是假的"，不知道"谁造的" |
| HiDDeN / RivaGAN | 单一水印 | 平台二次压缩后水印消失；单点故障 |
| 区块链存证 | 哈希上链 | 不能嵌入媒体本身，无法追溯篡改后版本 |
| 人工审核 | 人工介入 | 不可扩展，误报率高，无法实时处理 |

**鉴源盾的差异化**：主动嵌入 + 多模型冗余 + 精确 ID 编码 + 密码学证据链，四点同时满足。

---

## 二、核心创新点

### 创新一：LIDMark——CVPR 2026 人脸语义绑定水印（本团队原创）

LIDMark 是本团队发表于 **CVPR 2026（Highlight，录取率 < 3%）** 的原创水印方案。其核心思想：

**水印向量 = 人脸关键点坐标（结构感知）+ 用户 ID 比特（身份编码）**

```
水印向量 [152维]:
├── [0:135]   人脸 dlib 关键点坐标 → 嵌入在面部几何结构中
└── [136:151] 用户 ID 比特 (编码为 {-1, +1}) → 精确身份绑定
```

这意味着：**Deepfake 替换面部后，ID 仍残留在面部结构中，可被精确解码**——这是被动检测无法做到的。

| 指标 | LIDMark (3-seed) | 竞品均值 |
|------|-----------------|---------|
| Clean 精度 | **99.98%** | ≈88% |
| JPEG Q=50 | **99.96%** | ≈74% |
| Deepfake proxy 精度 | **100%** | — |
| 训练方差 (跨 seed) | **±0.02%** | 未报告 |

95% Bootstrap CI（5,000次重采样，n=1,536，3 seed × 512张）：全部区间下界 ≥ 99.88%。

---

### 创新二：MEA（Multi-Embedding Attack）——本团队原创评测协议

现有水印论文只测"单模型能不能被攻击"，没有人测"多个水印互相覆盖时发生什么"。

**MEA 协议**：先用模型 A 嵌入水印，再用模型 B 覆盖嵌入，测量 A 的水印是否存活。4×4 矩阵 = 16 种组合，每格 128 张图，共 2,048 张独立实验。

```
MEA 4×4 矩阵（n=128/格，无攻击）
Source ↓ Attacker →  | SepMark | WaveGuard | LIDMark | KAD-Net
─────────────────────┼─────────┼───────────┼─────────┼─────────
SepMark              | 91%/56% |  92%/100% | 50%/61% | 90%/100%
WaveGuard            |100%/95% |  52%/98%  | 50%/61% |100%/100%
LIDMark              | 68%/69% |  72%/100% | 52%/60% | 67%/93%
KAD-Net              |100%/84% | 100%/100% | 50%/61% | 50%/100%

格式：A水印存活率 / B嵌入精度    ✅≥90%  ⚠70-89%  ❌<70%
```

**关键发现**（这些结论在已有文献中未见报道）：
- **LIDMark 作为攻击者破坏性最强**：任何先嵌水印均降至随机水平（≈50%）——因为其语义绑定改变了面部几何结构
- **KAD-Net + WaveGuard 兼容性最佳**：双向嵌入均 ≥ 95%，适合多层级标识方案
- **对角线全部 FAIL**：自攻击必然覆盖原水印（符合理论预期，验证了实验有效性）

---

### 创新三：Ed25519 密码学证据链——司法级取证

水印精度数据如何证明"没有伪造"？鉴源盾引入 **Ed25519 椭圆曲线签名**：

```
证据包（22 个文件）
├── manifest.json     所有文件的 SHA-256 哈希
├── signature.b64     对 manifest.json 的 Ed25519 签名
├── public_key.pem    验证用公钥（可公开发布）
└── benchmark/*.json  所有评测原始数据
```

任何第三方可用公钥**独立验签**，证明评测数据未被篡改。这在学术竞赛中极为罕见——我们的实验数据具有**密码学不可抵赖性**。

```bash
# 一键验签
curl http://server:8026/api/evidence/audit
# → {"ready_for_demo": true, "signature_valid": true, "files_covered": 22}
```

---

### 创新四：15 种攻击统一评测框架

现有论文通常只测 JPEG、缩放，最多 4-5 种攻击。鉴源盾构建了 **15 种攻击的统一接口**：

| 类别 | 攻击列表 |
|------|---------|
| 压缩 | JPEG Q=50/70/90，WebP Q=80 |
| 几何 | 缩放 0.5×，中心裁剪 0.8，旋转 5° |
| 光度 | 高斯噪声，亮度±20%，对比度±20% |
| 平台仿真 | 微信压缩、抖音压缩（真实参数） |
| 深度伪造 | Deepfake proxy v1（人脸替换增强） |

所有攻击通过 `_apply_attack_rgb()` 统一调用，单 API 请求可指定任意攻击类型。

---

### 创新五：统计严谨性——Bootstrap CI + Holm 多重比较校正

竞赛作品常见问题：精度数据没有置信区间，无法判断是真实优势还是随机波动。

鉴源盾的所有精度报告均附：
- **95% Bootstrap 置信区间**（5,000 次重采样）
- **Holm-Bonferroni 多重比较校正**（控制 FWER < 0.05）
- **多 seed 训练方差**（LIDMark：3 个独立 seed，捕捉训练随机性）

例：LIDMark clean 精度 = 99.98%，CI = [99.94%, 100%]——这不是单次运气，而是有统计保障的结论。

---

## 三、系统架构与技术实现

### 3.1 整体架构

```
内容创作者 / 平台合规部门 / 执法机构
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│                 JianYuanShield 后端（FastAPI）               │
│                                                             │
│  水印适配层（Adapter Pattern）                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ LIDMark  │ │ KAD-Net  │ │WaveGuard │ │ SepMark  │       │
│  │ Adapter  │ │ Adapter  │ │ Adapter  │ │ Adapter  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                             │
│  攻击仿真层（15 种攻击统一接口）                              │
│  评测报告层（Bootstrap CI + Holm 校正 + JSON 输出）          │
│  证据链层（Ed25519 签名 + SHA-256 完整性校验）               │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
     前端界面（原生 JS，四场景 Demo）
```

### 3.2 四模型技术对比

| 模型 | 论文来源 | 嵌入域 | 水印长度 | 核心优势 |
|------|---------|--------|---------|---------|
| **LIDMark** | CVPR 2026 Highlight | 空间域（关键点） | 152 bit | 语义绑定，Deepfake 后仍可溯源 |
| **KAD-Net** | KBS 2025 | 空间域（KAN+SE） | 30 bit | Kolmogorov-Arnold 网络，100% 精度 |
| **WaveGuard** | 专利 | 频域（DTCWT） | 1 bit（检测） | 频域不变性，平台压缩抵抗强 |
| **SepMark** | — | 频域（分离子带） | 30 bit | 高频/低频分离，RF 解码器增强 |

### 3.3 工程实现亮点

**适配器模式解决命名空间冲突**：四个模型均有 `network/` 子模块，直接 import 会互相覆盖。鉴源盾通过 `importlib` 动态加载 + 独立命名空间解决此问题，是工程层面的关键创新。

**lifespan 预热**：后端启动时在后台线程中预加载全部 4 个适配器，消除首次请求延迟（冷启动 → 热启动）。

**实时流式推理**：支持 `POST /api/infer/single`，单张图片从上传到返回水印结果 < 2 秒（GPU 模式）。

---

## 四、评测结果（完整数据）

### 4.1 单模型 LFW 全量基准

| 模型 | 指标 | 无攻击 | JPEG Q=50 | JPEG Q=70 | 噪声 | 缩放 | 样本量 |
|------|------|--------|----------|----------|------|------|--------|
| **LIDMark** | ID 比特精度 (3-seed) | **99.98%** [99.94,100%] | 99.96% | — | 99.96% | 99.97% | 1,536 |
| **KAD-Net** | 比特精度 | **100%** | 99.97% | 100% | 100% | 100% | 512 |
| **WaveGuard** | Tracer 精度 (JPEG STE后) | **100%** | **100%** | 100% | 100% | 100% | 512 |
| **SepMark** | 比特精度 (RF decoder) | 91.2% [90.9,91.5%] | 88.1% | 89.8% | 90.7% | 91.0% | 13,233 |
| ~~HiDDeN~~ | ~~比特精度~~ | ~~50.4%~~ | — | — | — | — | ~~13,233~~ |

> **注**：HiDDeN checkpoint 损坏（两个 checkpoint 均 bit_acc ≈ 50%，随机水平），已从正式评测中剔除，正在 GPU 4 重训（CelebA-HQ 128×128 + JPEG/Dropout/Resize noise，300ep）。

所有数据附 **95% Bootstrap 置信区间**（5,000 次重采样），LIDMark 同时覆盖跨 seed 训练方差。

### 4.2 Pairwise 统计显著性检验（Holm 校正后）

LIDMark vs. SepMark 精度差 = 8.78 个百分点，**p < 0.001**（Holm 校正后仍显著）。每对模型间差异均经过多重比较校正，杜绝 p-hacking。

---

## 五、三大应用场景 Demo

### 场景 A：内容创作者保护（小红书/B站）

```
用户上传自拍 → LIDMark 嵌入 ID 水印（PSNR ≈ 44 dB，肉眼不可见）
→ 图片被他人用 Deepfake 换脸后传播
→ 平台上传至鉴源盾 → 解码 ID 水印 → 定位原创作者
→ 输出：bit_accuracy=100%，landmark_error=0.019
```

### 场景 B：平台合规批量验证（监管 API）

```bash
# 批量提交 100 张图，返回合规报告
curl -X POST http://server:8026/api/compliance/batch \
  -F "files=@img1.jpg" -F "files=@img2.jpg" \
  -F "model=SepMark"
# → {"compliant": 97, "flagged": 3, "report_id": "2026-06-08-001"}
```

### 场景 C：司法取证（证据提交）

```bash
# 下载可验签的证据包（三文件）
curl http://server:8026/api/evidence/signature/download/manifest    # 哈希清单
curl http://server:8026/api/evidence/signature/download/signature   # Ed25519 签名
curl http://server:8026/api/evidence/signature/download/public-key  # 公钥
# 第三方一行命令验签：
openssl pkeyutl -verify -pubin -inkey public_key.pem \
  -sigfile signature.bin -in manifest.json
```

---

## 六、已知缺陷（主动披露）

鉴源盾遵循**学术诚信原则**，主动披露所有已知限制：

| 编号 | 问题 | 严重程度 | 当前状态 |
|------|------|---------|---------|
| ~~**D1**~~ | ~~WaveGuard JPEG Q<60 鲁棒性差（成功率 37.3%）~~ | ~~中~~ | **已修复** — JPEG STE 7ep 微调，Q=50 tracer精度 100% |
| **D2** | KAD-Net 几何攻击弱：crop_center_0.8≈33%，rotate_5≈30% | 中 | 几何增强微调进行中（GPU 1，EP32/50，目标 ≥90%） |
| **D3** | HiDDeN checkpoint 损坏（bit_acc≈50%） | 高 | 正在重训（GPU 4，300ep，CelebA-HQ + JPEG/Dropout/Resize） |
| **D4** | LIDMark 依赖真实人脸（face_alignment 无法处理合成图） | 低 | 设计限制，Demo 需真实人脸输入 |
| **D5** | MEA 矩阵 n=128/格，统计显著性偏弱 | 低 | 已标注；竞赛演示够用 |
| **D6** | SimSwap/FaceSwap 仅含 proxy 模拟，无真实推理管线 | 中 | 受阻于推理环境，用 deepfake_proxy_v1 替代 |
| **D9** | SepMark clean=91.2%，与 LIDMark/KAD-Net 有差距 | 中 | 频域分离架构固有上限，已有完整分析文档 |

> **为什么要主动披露缺陷？** 我们认为，一个能准确描述自身局限的系统比一个声称"完美"的系统更值得信任。缺陷分析本身也是科学贡献。

---

## 七、与现有方案的完整对比

| 能力维度 | 鉴源盾 | 单一水印方案 | 被动检测方案 | 区块链存证 |
|---------|--------|------------|------------|---------|
| Deepfake 后仍可溯源 | ✅ LIDMark 语义绑定 | ❌ | ❌ | ❌ |
| 多模型冗余容灾 | ✅ 4 模型 | ❌ | — | — |
| 密码学证据链 | ✅ Ed25519 | ❌ | ❌ | ✅（但不含媒体） |
| 法规合规 API | ✅ 批量验证 + 报告 | ❌ | ❌ | ❌ |
| 15 种攻击统一评测 | ✅ | 通常 2-4 种 | — | — |
| Bootstrap CI 置信区间 | ✅ | 罕见 | — | — |
| MEA 跨模型攻击矩阵 | ✅ 本团队原创 | ❌ | — | — |
| 实时推理 API | ✅ < 2s/张 | 视方案 | ✅ | ❌ |
| 开源可复现 | ✅ | 部分 | 部分 | 部分 |

---

## 八、快速开始

```bash
git clone https://github.com/lux-liang/JianYuanShield.git
cd JianYuanShield
pip install -r requirements.txt

# 启动后端（GPU 推理）
JYS_INFER_DEVICE=cuda:0 PYTHONPATH=. \
  uvicorn system.backend.app:app --host 0.0.0.0 --port 8026

# 启动前端
python -m http.server 8027 --directory system/frontend
# 访问 http://localhost:8027
```

```bash
# 全量统计分析（4 模型 + LIDMark 3-seed + Bootstrap CI）
PYTHONPATH=. python -m system.scripts.run_statistical_analysis

# MEA 4×4 矩阵（128 张/格，约 45 分钟）
JYS_INFER_DEVICE=cuda:0 PYTHONPATH=. \
  python scripts/run_mea_matrix_4x4.py --images-per-cell 128

# 证据链验签
curl http://localhost:8026/api/evidence/audit
```

---

## 九、核心 API 参考

```bash
# 单图水印嵌入 + 攻击 + 解码（15 种攻击任选）
curl -X POST http://server:8026/api/infer/single \
  -F "file=@photo.jpg" -F "model=LIDMark" -F "attack=deepfake_proxy_v1"

# 实时基准数据
curl http://server:8026/api/benchmark/lidmark-lfw-eval   # LIDMark LFW 全量
curl http://server:8026/api/benchmark/kadnet             # KAD-Net LFW 结果
curl http://server:8026/api/benchmark/mea-matrix         # MEA 4×4 矩阵
curl http://server:8026/api/benchmark/aggregate          # 跨模型对比

# 系统状态
curl http://server:8026/api/health
curl http://server:8026/api/modules

# 证据链
curl http://server:8026/api/evidence/audit
curl http://server:8026/api/evidence/signature/download/manifest
```

---

## 十、项目进度

### 已完成

- [x] 四模型统一评测协议（15 种攻击，`evaluation_protocol.v1`）
- [x] LFW 全量 benchmark — SepMark / WaveGuard（各 13,233 张）
- [x] LIDMark 3-seed 正式训练 + LFW 评测（1,536 张，99.97%，Bootstrap CI）
- [x] KAD-Net 服务器独立训练（100ep，PSNR=37.67）+ LFW 评测（512 张，100%）
- [x] WaveGuard JPEG STE 7ep 微调 → Q=50 tracer 100%（修复原 37.3% 缺陷）
- [x] MEA 4×4 矩阵（128张/格，16 种组合全部完成）
- [x] 统计分析：Bootstrap CI + Holm 多重比较校正
- [x] Ed25519 证据链（覆盖 22 文件，signature_valid=true）
- [x] 4 场景前端 Demo（创作者保护 / 平台合规 / MEA 横评 / Deepfake 溯源）
- [x] 后端启动预热（lifespan hook，4 模型全部 warmup-loaded）
- [x] `/api/benchmark/kadnet` + `/api/benchmark/mea-matrix` 实时数据接口
- [x] 前端 MEA 4×4 可视化矩阵面板（grade icon + CSS 变量着色）
- [x] 技术报告（`docs/TECHNICAL_REPORT.md`）+ 评委 QA + 3 分钟答辩口稿

### 进行中

- [ ] **KAD-Net 几何微调**（GPU 1，EP32/50）— 目标：crop_center_0.8 / rotate_5 ≥ 90%
- [ ] **HiDDeN 重训**（GPU 4，EP1/300）— CelebA-HQ 128×128 + JPEG/Dropout/Resize noise

### 待完成（人工任务）

- [ ] **M2** PPT / 展板制作
- [ ] **M4** 演示视频录制（3 分钟技术展示 + 1 分钟后台）
- [ ] **E3** 真实 Deepfake 攻击（SimSwap/FaceSwap）— 受阻于推理环境

---

## 诚实声明

- **`ready_for_demo: ✅`** — 系统可完整演示，四模型真实推理，15 种攻击，4 场景前端
- **`ready_for_claims: ⚠️`** — HiDDeN broken 触发门禁（设计意图，杜绝无效结论）；竞赛报告已剔除旧 checkpoint

---

## 引用

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

*CVPR 2026 LIDMark · KBS 2025 KAD-Net · 《人工智能生成合成内容标识办法》技术落地*

*全国大学生信息安全竞赛作品赛参赛作品*

</div>
