<div align="center">

# 鉴源盾 · JianYuanShield

**AI 内容可信认证与深度伪造溯源平台**

*面向《人工智能生成合成内容标识办法》的隐式标识技术落地方案*

---

[![LIDMark](https://img.shields.io/badge/LIDMark-CVPR%202026%20Highlight-red?logo=googlescholar)](https://arxiv.org/abs/2602.23523)
[![KAD-Net](https://img.shields.io/badge/KAD--Net-KBS%202025-blue)](https://github.com/vpsg-research/KAD-Net)
[![Benchmark](https://img.shields.io/badge/LFW%20Benchmark-13%2C233%20imgs-brightgreen)](https://github.com/lux-liang/JianYuanShield)
[![Evidence](https://img.shields.io/badge/Ed25519-Verified-success)](https://github.com/lux-liang/JianYuanShield)
[![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)](https://python.org)

</div>

---

## 项目定位

2025 年 9 月 1 日，《人工智能生成合成内容标识办法》正式施行，要求服务商同时添加**显式标识**与**隐式标识**（嵌入文件的不可见水印），并保证内容可溯源、可取证。

**鉴源盾**是该法规"隐式标识"技术要求的完整落地方案，聚焦三类核心场景：

| 用户角色 | 核心痛点 | 解决方案 |
|----------|----------|---------|
| **内容创作者** | 原创图被 Deepfake 篡改后冒充原版传播 | 发布前嵌入 LIDMark 水印；篡改后精确追溯来源 |
| **平台合规部门** | 法规要求隐式标识，批量验证成本高 | 统一水印验证 API；合规审计报告自动生成 |
| **执法/司法机构** | AI 换脸取证困难，无可用司法材料 | Ed25519 签名证据包；篡改定位 + 水印溯源 |

---

## 当前评测结果（已完成）

### 单模型 LFW 基准

| 模型 | 指标 | 无攻击 | JPEG Q=50 | JPEG Q=70 | 噪声 | 缩放 | 样本量 |
|------|------|-------|----------|----------|------|------|------|
| **LIDMark** | ID 比特精度 (3-seed) | **99.98%** [99.94,100%] | 99.96% | — | 99.96% | 99.97% | 1,536 |
| **KAD-Net** | 比特精度 | **100%** | 99.97% | 100% | 100% | 100% | 512 |
| **WaveGuard** | 比特精度 (tracer) | **100%** | **100%**‡ | 100% | 100% | 100% | 512 |
| **SepMark** | 比特精度 (RF decoder) | 91.2% | 88.1% | 89.8% | 90.7% | 91.0% | 13,233 |
| ~~HiDDeN~~ | ~~比特精度~~ | ~~50.4%~~ | — | — | — | — | ~~13,233~~ |

> ‡WaveGuard JPEG Q=50：细调后 bit_accuracy_tracer=100%（512张LFW, CI=[1.0,1.0]），较原始权重 37.3% 大幅提升。使用 Q=40-70 JPEG STE 增强训练 7 epoch。

> HiDDeN checkpoint 损坏（epoch-200.pyt 超出训练规格），bit_acc≈50%（随机水平），已从正式评测中剔除

所有数据附 95% Bootstrap 置信区间（5,000 次重采样），LIDMark 同时覆盖跨 seed 训练方差。

### MEA 4×4 多重嵌入攻击矩阵（n=128/格，无攻击）

> 行 = 先嵌入（Source），列 = 后嵌入（Attacker）
> 格式：A水印存活率 / B嵌入精度　✅≥90%　⚠70-89%　❌<70%

| Source ↓ Attacker → | SepMark | WaveGuard | LIDMark | KAD-Net |
|---|---|---|---|---|
| **SepMark** | 91%✅ / 56%❌ | 92%✅ / 100%✅ | 50%❌ / 61%❌ | 90%✅ / 100%✅ |
| **WaveGuard** | 100%✅ / 95%✅ | 52%❌ / 98%✅ | 50%❌ / 61%❌ | 100%✅ / 100%✅ |
| **LIDMark** | 68%⚠ / 69%⚠ | 72%⚠ / 100%✅ | 52%❌ / 60%❌ | 67%⚠ / 93%✅ |
| **KAD-Net** | 100%✅ / 84%⚠ | 100%✅ / 100%✅ | 50%❌ / 61%❌ | 50%❌ / 100%✅ |

**关键发现：**
- **LIDMark 作为 Attacker 破坏性最强**：任何 Source 水印均被降至 ≈50%（随机水平）
- **KAD-Net + WaveGuard 兼容性最佳**：相互嵌入两路精度均 ≥ 95%
- **对角线全部 FAIL**：自攻击必然覆盖原水印，符合理论预期
- **WaveGuard 作为 Source 存活率最高**：频域嵌入抗空间域二次修改能力强

---

## 已知缺陷与问题

| 编号 | 问题 | 严重程度 | 状态 |
|------|------|---------|------|
| ~~**D1**~~ | ~~WaveGuard JPEG Q<60 鲁棒性差（成功率 37.3%）~~ | ~~中~~ | **已修复** — JPEG STE 7ep 微调，Q=50 tracer精度 100%（LFW 512张） |
| **D2** | KAD-Net 几何攻击弱：crop_center_0.8≈33%，rotate_5≈30% | 中 | 几何增强微调进行中（GPU 1，EP32/50，目标 ≥90%） |
| **D3** | HiDDeN checkpoint 损坏（epoch-200.pyt），bit_acc≈50% | 高 | 正在重训（GPU 4，300ep，CelebA-HQ + JPEG/Dropout/Resize noise）；竞赛声明已剔除旧 checkpoint |
| **D4** | LIDMark 依赖真实人脸（face_alignment 无法处理合成/噪声图像） | 低 | 设计限制，Demo 需上传真实人脸 |
| **D5** | MEA 矩阵 n=128/格，统计显著性偏弱 | 低 | 已标注 images_per_cell；竞赛演示够用 |
| **D6** | SimSwap/FaceSwap 仅含训练增强 stub，无独立推理管线 | 中 | 真实 Deepfake 攻击（E3）受阻，用 deepfake_proxy_v1 代替 |
| **D7** | ready_for_claims=False（HiDDeN warning 触发门禁） | 低 | 设计意图：系统拒绝声称已损坏模型的结果有效 |
| **D8** | 证据链更新后需手动重新签名（缺乏自动触发机制） | 低 | `scripts/sign_evidence_bundle.py --private-key ~/.config/jianyuanshield/evidence_ed25519.pem` |
| **D9** | SepMark decoder_RF clean=91.2%（非 100%），与 LIDMark/KAD-Net 有差距 | 中 | 频域分离架构固有精度上限，已有完整分析 |
| **D10** | 服务器（192.168.1.85）GitHub 端口 443 偶发超时 | 低 | push 前检查网络；已有 9 commits 成功推送 |

---

## 系统架构

```
鉴源盾平台
├── 内容保护          主动水印嵌入（LIDMark / SepMark / WaveGuard / KAD-Net）
├── 攻击仿真          15 类攻击：JPEG/WebP/几何/光度/平台仿真/Deepfake proxy
├── MEA 多重嵌入攻击   4×4 跨模型覆盖矩阵（128张/格，已完成）
├── Deepfake 溯源 Demo 4 场景前端：创作者保护/平台合规/MEA横评/Deepfake溯源
├── 统计评测          Bootstrap CI + Holm 多重比较校正
└── 证据链            Ed25519 签名，覆盖 22 个文件，verified
```

**核心模型（均为本团队研究成果）：**

| 模型 | 论文 | 核心技术 |
|------|------|---------|
| **LIDMark** | [CVPR 2026 Highlight](https://arxiv.org/abs/2602.23523) | 152维关键点-身份联合水印；3-seed 独立训练 |
| **KAD-Net** | KBS 2025 | Kolmogorov-Arnold 网络 + SE 注意力；100ep 自训练 |
| **WaveGuard** | — | DTCWT 频域水印；JPEG STE 7ep 微调（Q=50 tracer 100%） |
| **SepMark** | — | 频域分离；RF decoder 改进（91.2% vs C decoder 87.7%） |
| **MEA** | — | 多重嵌入攻击评测协议（本团队提出） |

---

## 快速开始

```bash
git clone https://github.com/lux-liang/JianYuanShield.git
cd JianYuanShield
pip install -r requirements.txt

# 启动后端 API
PYTHONPATH=. uvicorn system.backend.app:app --host 0.0.0.0 --port 8026

# 启动前端
python -m http.server 8027 --directory system/frontend
```

```bash
# 全量统计分析（4 模型 + LIDMark 3-seed）
PYTHONPATH=. python -m system.scripts.run_statistical_analysis

# MEA 矩阵
PYTHONPATH=. python scripts/run_mea_matrix_smoke.py

# 证据链验签
curl http://localhost:8026/api/evidence/signature
```

---

## API 接入

```bash
# 单图取证（支持 15 种攻击）
curl -X POST http://server:8026/api/infer/single \
  -F "file=@photo.jpg" \
  -F "model=LIDMark" \
  -F "attack=deepfake_proxy_v1"

# Deepfake 溯源：model=LIDMark + attack=deepfake_proxy_v1
# 平台合规检测
curl -X POST http://server:8026/api/compliance/batch \
  -F "files=@img1.jpg" -F "files=@img2.jpg" -F "model=SepMark"

# 证据链下载
curl http://server:8026/api/evidence/signature/download/manifest
curl http://server:8026/api/evidence/signature/download/signature
curl http://server:8026/api/evidence/signature/download/public-key
```

---

## 项目进度

### 已完成

- [x] 四模型统一评测协议 `evaluation_protocol.v1`（15 种攻击）
- [x] LFW 全量 benchmark — SepMark / WaveGuard（各 13,233 张）
- [x] LIDMark 3-seed 正式训练 + LFW 评测（1,536 张，99.97%）
- [x] KAD-Net 服务器独立训练（100ep）+ LFW 评测（512 张，100%）
- [x] MEA 4×4 矩阵（128张/格，16 种组合全部完成）
- [x] 统计分析：Bootstrap CI + Holm 多重比较校正
- [x] Ed25519 证据链（覆盖 22 文件，verified）
- [x] 4 场景前端 Demo（含 Deepfake 溯源场景）
- [x] 技术报告 Markdown（`docs/TECHNICAL_REPORT.md`）
- [x] 评委 QA 文档 + 3 分钟答辩口稿（已更新所有真实数据）
- [x] 后端启动预热（lifespan hook，4 模型全部 warmup-loaded）
- [x] `/api/benchmark/kadnet` + `/api/benchmark/mea-matrix` 新接口
- [x] 前端 MEA 4×4 可视化矩阵面板（grade icon + CSS 变量着色）

### 进行中

- [ ] **KAD-Net 几何微调**（GPU 1，EP32/50）— 修复 crop_center_0.8 / rotate_5 弱点
- [ ] **HiDDeN 重训**（GPU 4，EP1/300）— CelebA-HQ 128×128 + JPEG/Dropout/Resize noise；预计 12-15 小时

### 待完成（受阻或人工任务）

- [ ] **E3** 真实 Deepfake 攻击（SimSwap/FaceSwap）— 受阻：需 autodl 训练数据集 + 推理环境
- [ ] **M2** PPT / 展板制作 — 人工任务
- [ ] **M4** 演示视频录制（3 分钟 + 1 分钟后台）— 人工任务
- [x] WaveGuard JPEG Q<60 微调修复 — JPEG STE 7ep 微调完成，Q=50 tracer精度 100%

---

## 诚实声明

- **`ready_for_demo: ✅`** — 系统可完整演示，四模型真实推理，15 种攻击，4 场景前端
- **`ready_for_claims: ⚠️`** — HiDDeN broken 触发门禁（设计意图）；竞赛报告已剔除旧 checkpoint；重训进行中

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

</div>
