# 鉴源盾 · 迭代优化路线图

> 生成日期：2026-06-07  
> 目标赛事：全国大学生信息安全竞赛作品赛（国家一等奖）  
> 决赛时间：2026 年 8 月  
> 当前阶段：四模型全部联通，进入深度评测与材料冲刺阶段

---

## 一、当前基线快照

| 模型 | checkpoint 状态 | LFW bit_acc (clean) | PSNR | 主要短板 |
|------|----------------|---------------------|------|----------|
| LIDMark | ✅ real (3 seeds) | 99.8–100% (eval adapter) / **81.25% (backend)** | 33.8 | backend landmark 坐标系不对齐 |
| KAD-Net | ✅ real (自训练 100ep) | 100% | 37.5 | MEA 中 first_acc 偏低 (50%) |
| SepMark | ✅ pre-trained | 87.7% (LFW 13K) | 41–45 | clean 准确率低于预期 |
| WaveGuard | ✅ real | 100% (clean/jpeg70+) | 33.0 | JPEG50 success=36% |
| HiDDeN | ❌ 已排除 | ~50% | — | checkpoint 损坏，不参赛 |

---

## 二、技术性能优化

### T1 · LIDMark backend 精度对齐（P0 — 最高优先级）

- [x] **T1-1** 诊断 face_alignment v1.5.0 与训练时 dlib 坐标系的具体偏差量（输出两套 landmark 的坐标对比图）
- [x] **T1-2** 方案 A：在 `LIDMarkAdapter.run()` 中切换为 dlib 68 点检测器，与训练保持一致
- [ ] **T1-3** 方案 B：如果 dlib 安装困难，改用 face_alignment 但在输入时施加仿射校正（根据 T1-1 诊断结果选择）
- [ ] **T1-4** 验证修复后 backend bit_acc ≥ 97%（对齐 eval adapter 的 99.8%）
- [ ] **T1-5** 更新 `JUDGE_QA.md` 中 LIDMark 的性能描述

### T2 · WaveGuard JPEG50 问题处理（P1）

- [x] **T2-1** 在 WaveGuard 训练配置中加入 JPEG 数据增强（q=45–55），重新 fine-tune 至少 20 epoch
- [ ] **T2-2** 若无法 fine-tune，在 `docs/WAVEGUARD_JPEG_ANALYSIS.md` 中补充"修复路线图"章节，作为答辩备份
- [ ] **T2-3** 在前端 demo 中对 JPEG50 攻击加醒目注释，主动说明已知限制而非被追问

### T3 · SepMark clean 精度调查（P1）

- [ ] **T3-1** 检查 SepMark checkpoint 是否有更高版本（EC_115 → EC_200 等）
- [ ] **T3-2** 对比 SepMark 官方 repo 的评测脚本，确认预处理是否一致
- [ ] **T3-3** 若预处理偏差导致，修复 `system/evaluation/adapters/sepmark_adapter.py` 中的 resize/normalize 流程

### T4 · KAD-Net MEA 存活率提升（P2）

- [ ] **T4-1** 分析 KAD-Net first_acc=50% 的根因（MEA 矩阵中 KAD-Net 作为水印源时被覆盖率高）
- [ ] **T4-2** 在 KAD-Net 训练中加入 MEA-style 二次嵌入攻击数据增强
- [ ] **T4-3** 验证 KAD-Net first_acc ≥ 80% after fine-tune

---

## 三、评测体系完善

### E1 · 攻击覆盖补全（P0）

当前 MEA 矩阵只跑了 6/15 种攻击，缺少以下攻击类型：

- [x] **E1-1** crop_center_0.8（中心裁剪 80%）
- [x] **E1-2** rotate_5（5° 旋转）
- [ ] **E1-3** gaussian_blur_5（高斯模糊）
- [ ] **E1-4** brightness_0.85 / contrast_1.2（亮度/对比度）
- [ ] **E1-5** webp50（WebP 压缩 Q=50，抖音/快手实际使用）
- [ ] **E1-6** platform_wechat_v1（微信朋友圈压缩模拟：resize to 1080p + JPEG Q=75）
- [ ] **E1-7** platform_douyin_v1（抖音封面压缩模拟：resize to 720p + WebP Q=70）
- [ ] **E1-8** deepfake_proxy_v1 → 替换为真实 deepfake 模型（见 E3）
- [ ] **E1-9** 将上述攻击加入 `configs/evaluation_protocol.v1.json` 的 `attack_ids` 列表（当前为空数组）

### E2 · 多 seed 统计（P1）

- [x] **E2-1** 以 seed={20260603, 20260604, 20260605} 重跑完整 MEA 4×4 矩阵（每格 n=256）
- [x] **E2-2** 对每格输出 95% Bootstrap CI、配对 t 检验 p 值、Cohen's d 效应量
- [ ] **E2-3** 将 LIDMark 的 3 seed 单模型 LFW 结果纳入 `run_statistical_analysis.py`（当前只读 SepMark/WaveGuard CSV）
- [ ] **E2-4** 生成跨模型对比表格（mean ± std，格式与 SepMark/WaveGuard 一致）

### E3 · 真实 Deepfake 攻击（P1）

- [ ] **E3-1** 部署 SimSwap 或 FaceSwap（服务器 GPU4/7 空闲）
- [ ] **E3-2** 构建 deepfake 攻击 pipeline：原始人脸图 → deepfake 换脸 → 水印提取
- [ ] **E3-3** 对 SepMark/LIDMark/KAD-Net 各跑 512 张 deepfake 攻击，记录 success_rate
- [ ] **E3-4** 将 deepfake 攻击结果加入竞赛报告的"高级攻击"章节

### E4 · 跨域数据集（P2）

- [ ] **E4-1** 获取 CelebA-HQ 测试分割（10K 图），补充 LFW 之外的域泛化测试
- [ ] **E4-2** FaceForensics++ 帧提取（FF-c23），构建 deepfake 域评测集
- [ ] **E4-3** 对 LIDMark/KAD-Net 输出 CelebA-HQ 域的 bit_acc，与 LFW 域对比，证明域泛化能力

### E5 · 竞赛报告数据一致性（P1）

- [x] **E5-1** 将 `export_competition_report.py` 中 LIDMark 条目从 smoke_checkpoint 改为 real_checkpoint 数据
- [ ] **E5-2** 将 `evidence_gate.ready_for_claims` 从 false 改为 true（在完成 E1/E2 之后）
- [ ] **E5-3** 更新 `benchmark_complete` 状态，确保 LIDMark 的 `mode=smoke` 标注更正
- [ ] **E5-4** 修复 `evaluation_protocol.v1.json` 中 `attack_ids=[]` 的空数组 bug
- [ ] **E5-5** 将 KAD-Net `adapter_status` 从 `integration_pending` 改为 `full_benchmark`

---

## 四、系统工程完善

### S1 · 端到端 Deepfake 溯源 Demo 流程（P0 — 答辩核心）

- [x] **S1-1** 设计演示脚本：上传一张真人脸 → 嵌入 LIDMark 水印 → 经过 deepfake 换脸攻击 → 提取水印 → 证明溯源成功
- [ ] **S1-2** 前端实现"上传 + 实时处理 + 可视化对比"的单页 demo（原始/水印/攻击后/差异热力图）
- [ ] **S1-3** 接入 `/api/compliance/batch` 批量合规扫描，模拟平台侧的合规检测场景
- [ ] **S1-4** 录制 3 分钟演示视频（deepfake 传播链路：内容创作者 → 平台分发 → 监管取证）

### S2 · 证据链完整性（P1）

- [x] **S2-1** 将 Ed25519 签名流程集成到 `/api/infer/single` 的 response 中（当前 `evidence.sha256` 已有，但未签名）
- [ ] **S2-2** 提供公钥下载接口，使评委可以离线验证证据报告未被篡改
- [ ] **S2-3** 在前端"证据"页面展示签名验证 UI

### S3 · 合规接口标准化（P1）

- [ ] **S3-1** 对接《人工智能生成合成内容标识办法》第五条（隐式标识），明确 API 输出字段与法规条款的映射
- [ ] **S3-2** 在 `/api/compliance/batch` 中输出合规状态：`compliant` / `non_compliant` / `unverifiable`，每条给出法规条款引用
- [ ] **S3-3** 生成平台接入指南文档（技术报告附录）

### S4 · Docker 部署验证（P2）

- [ ] **S4-1** 验证 `docker-compose.yml` 在无 /data1 挂载的情况下能否正常启动 smoke 模式
- [ ] **S4-2** 在 `offline_deploy.sh` 中加入模型路径检查和 fallback 提示
- [ ] **S4-3** 构建 CI：push 后自动跑 `scripts/check_system.py`（当前 `run_tests.sh` 是否 pass）

---

## 五、竞赛材料准备

### M1 · 技术报告 PDF（P0 — 有提交截止日期）

- [ ] **M1-1** 确认竞赛官网的报告模板格式要求（页数限制、字体、章节要求）
- [x] **M1-2** 起草技术报告大纲：背景 → 技术路线 → 四模型原创性说明 → 评测结果 → 应用案例 → 结论
- [x] **M1-3** 写"评测结果"章节：包含 MEA 4×4 矩阵表、多模型 LFW 对比表、PSNR-Accuracy 曲线
- [x] **M1-4** 写"应用场景"章节：小红书内容创作者保护、平台合规 API、监管取证三个具体场景
- [x] **M1-5** 写"原创贡献"章节：明确说明 LIDMark/MEA/WaveGuard/KAD-Net 均为本团队研究成果
- [ ] **M1-6** 校对、排版、生成最终 PDF

### M2 · PPT / 展板（P1）

- [ ] **M2-1** 制作 12 页答辩 PPT（封面/背景/技术架构/四模型介绍/MEA矩阵/Demo截图/合规法规/结论）
- [ ] **M2-2** 制作竞赛展板（A0 尺寸）：系统架构图 + 核心数据可视化（MEA矩阵热力图、PSNR对比柱图）
- [ ] **M2-3** 生成水印不可见性对比图：原图 / 水印图 / 差值 × 10 放大（用 backend heatmap 接口批量生成）

### M3 · 答辩准备（P1）

- [x] **M3-1** 更新 `docs/JUDGE_QA.md`：补充 KAD-Net 性能数据、WaveGuard JPEG50 解释、LIDMark real checkpoint 数据
- [x] **M3-2** 更新 `docs/DEFENSE_SCRIPT_3MIN.md`：基于最新四模型数据重写 3 分钟答辩口稿
- [ ] **M3-3** 准备"评委最强质疑"预案：为什么选这四个模型？为什么 SepMark 只有 87.7%？deepfake 如何攻破水印？
- [ ] **M3-4** 团队内部进行至少 2 次模拟答辩

### M4 · 演示视频（P0）

- [ ] **M4-1** 录制端到端 demo 视频（3分钟）：包含 deepfake 传播链路完整演示
- [ ] **M4-2** 录制后台系统展示视频（1分钟）：MEA 矩阵生成过程 + 证据报告下载
- [ ] **M4-3** 视频上传到可访问链接（B站 / 网盘），准备现场播放备用

---

## 六、长线研究方向（竞赛后 → CVPR 2026 投稿）

### R1 · MEA 二次嵌入主动防御

- [ ] **R1-1** 设计"抗二次嵌入训练"策略：在训练时加入随机强度的二次嵌入攻击作为数据增强
- [ ] **R1-2** 理论分析：多重嵌入后水印信号的 SNR 下界推导
- [ ] **R1-3** 实验：在 MEA 矩阵中验证抗二次嵌入后的 first_acc 提升量

### R2 · 跨平台压缩自适应水印

- [ ] **R2-1** 建立各平台压缩参数数据库（微信/抖音/快手/B站/小红书）
- [ ] **R2-2** 训练平台感知的自适应解码器（输入压缩参数 → 调整解码阈值）
- [ ] **R2-3** 消融：统一解码器 vs 平台特定解码器的 success_rate 对比

### R3 · 密码学可证明水印安全性

- [ ] **R3-1** 形式化定义"取证水印安全性"：攻击者 unbind 不超过 bit_acc 阈值的概率上界
- [ ] **R3-2** 对 LIDMark 的 landmark 绑定机制给出安全性证明草稿
- [ ] **R3-3** 接入 Ed25519 + Merkle tree，构建可证明防篡改的证据链

### R4 · 合成内容检测 + 水印联合框架

- [ ] **R4-1** 调研 C2PA 标准（Content Credentials），与鉴源盾证据格式对接
- [ ] **R4-2** 实现"被动检测 + 主动水印"双路验证：先检测图片是否 AI 生成，再提取水印溯源
- [ ] **R4-3** 在 FaceForensics++ 上验证联合框架的溯源准确率

---

## 七、已知阻断项（需外部资源）

| 阻断项 | 原因 | 解锁条件 |
|--------|------|----------|
| FaceForensics++ 评测 | 数据集需申请许可 | 提交 FF++ 申请表单 |
| Celeb-DF v2 跨域测试 | 同上 | 提交申请 |
| WaveGuard fine-tune | 需确认是否有原始训练代码 | 与指导老师确认 |
| deepfake 模型（SimSwap）| 需配置独立推理环境 | GPU4/7 空闲，可直接部署 |

---

## 八、里程碑时间线

```
2026-06-07  基线：四模型全部联通，benchmark 数据完整
│
├── 2026-06-14  Week 1
│   ├── T1: LIDMark backend 精度修复 (目标 ≥97%)
│   ├── E1: 补全 9 种缺失攻击
│   └── S1-1/2: demo 流程设计 + 前端草稿
│
├── 2026-06-21  Week 2
│   ├── E2: 3-seed MEA 重跑
│   ├── E3: deepfake 攻击 pipeline
│   └── M3: JUDGE_QA + defense script 更新
│
├── 2026-06-28  Week 3
│   ├── M1: 技术报告 PDF 初稿
│   ├── S2: 证据签名接口上线
│   └── E4: CelebA-HQ 跨域测试（如数据可得）
│
├── 2026-07-07  Week 4–5
│   ├── M2: PPT + 展板定稿
│   ├── M4: demo 视频录制
│   └── T2/T3: WaveGuard/SepMark 性能优化
│
├── 2026-07-20  冻结代码，进入答辩冲刺
│   ├── 模拟答辩 × 2
│   ├── 证据包签名 + 报告最终版
│   └── 所有 TODO 状态审查
│
└── 2026-08-xx  决赛答辩
```

---

## 附：快速参考

**服务器**: `luxliang@192.168.1.85`  
**项目目录**: `/home/luxliang/JianYuanShield`  
**数据目录**: `/data1/luxliang/work/vpsg_competition_candidates/`  
**后端启动**: `JYS_INFER_DEVICE=cuda:2 /usr/bin/python3.10 -m uvicorn system.backend.app:app --host 0.0.0.0 --port 8026`  
**MEA 矩阵**: `JYS_INFER_DEVICE=cuda:6 PYTHONPATH=. /usr/bin/python3.10 scripts/run_mea_matrix_4x4.py --images-per-cell 256`  
**python**: 必须用 `/usr/bin/python3.10`（有 torch+cv2；默认 python3 缺 cv2）  
**可用 GPU**: cuda:4, cuda:6, cuda:7（0–3 被占用）
