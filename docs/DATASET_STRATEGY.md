# 数据集策略与 Deepfake 溯源实验计划

> 编制人：鉴源盾技术负责人 ｜ 日期：2026-06-15 ｜ 算力：8×4090，/data1 余 12TB
> 依据：`docs/THREAT_MODEL.md`（§3 真实失效边界 / §4 evasion 计划）、`TODO_DEEP_REVIEW.md`（P1-12 威胁模型缺位、阶段三增值）、orchestrator 实测数据集现状、三维度调研 findings。

---

## 一、【结论先行】

**一句话：干净人脸"够用且优于现成 deepfake 库"，真正的刚需不是"再下一个干净库"，而是"自建一条嵌水印→换脸→再解码的溯源闭环管线"；新 deepfake 数据是从加分到刚需的分级品——最该今天先做的是用现有 CelebA-HQ/LFW 跑通 P1 闭环 + 同步提交 FF++/DF40 申请表单。**

要点（5 条）：

1. **干净人脸够了，不必再下。** 已有 CelebA-HQ（训练 ~27k×3 副本）+ LFW（评测 13,233）完全覆盖"嵌水印源人脸"。FFHQ 仅在需要高清/多族群源时作可选补充，**不重训**。
2. **deepfake 数据是"分级刚需"，不是"全都刚需"。** 核心缺口是"溯源闭环"——而现成 deepfake 库（Celeb-DF/DFDC/DF40/FF++）的假脸**都不是基于你嵌过水印的脸生成的**，它们只能验证"检测/泛化"，**无法直接验证"水印被换脸后还能否溯源"**。溯源闭环必须靠"干净脸→自己嵌水印→自己跑换脸模型"。
3. **最该先搞的是 P1（零新数据）：** `CelebA-HQ 取子集 → KAD/LIDMark 嵌水印 → InSwapper/SimSwap 换脸 → 解水印`。这条链今天就能开工，直接补 THREAT_MODEL §2 档位 2 与 TODO P1-12 的核心空白，且回答评委必问的"嵌水印的脸被换脸后还能溯源吗"。
4. **现成 deepfake 库的作用是"配套校准 + 检测基线 + 方法泛化"**，优先级：Celeb-DF v2（Kaggle 可脚本化，14GB，必须）> FF++ c23 子集（提供原始↔操纵**配对**，最契合，需申请）> DF40 FS/FR 子集（方法多样性，需申请）> DFDC（470GB，方法单一，可选）。
5. **时间瓶颈是申请审批：** FF++ 与 DF40 走 Google 表单人工批准（1–3 天），**我无法自动下，今天必须人工提交**，否则成为 P2 阶段的死路。无审批项（FFHQ 缩略图 / Celeb-DF v2 Kaggle 镜像）今天即可脚本化拉取。

---

## 二、【现有 vs 缺口】

| 现有数据 / 能支撑什么 | 缺什么 / 为什么 |
|---|---|
| **CelebA-HQ**（kadnet 27172 / hidden 27172 / lidmark 29995，128px，训练用）→ 支撑 KAD/HiDDeN/LIDMark 编解码器训练 | **缺"嵌水印后被换脸/重演"的目标域** → 训练域全是干净脸，从未见过"已嵌水印的脸经 deepfake 重生成"的样本，无法证明水印跨 deepfake 存活 |
| **LFW**（lfw_full_upload 13233，128px，评测用）→ 支撑常规失真鲁棒性全量评测（已得 KAD jpeg/noise/resize≥99% 等真值） | **缺真实 deepfake 攻击下的解码结果** → 现 §3 失效边界只覆盖 JPEG/几何/多水印，**deepfake 这一列全空**；THREAT_MODEL §2 档位 2/3 的"换脸/重演/扩散净化"无任何实测数据点 |
| **LIDMark landmark 定位 99.93%**（真实强项）→ 支撑"关键点驱动嵌入"叙事 | **LIDMark 16-bit id-bit 准确率 = null（TODO P0-2）** → 号称"Deepfake 穿透溯源"的核心模型，连干净条件 id-bit 都没测，更别说换脸后 → **溯源主张当前零比特级证据** |
| **MEA 跨模型双嵌矩阵**（红队诊断，first_acc≈0.5）→ 支撑"多水印共存失效"诚实发现 | **MEA 是"水印 vs 水印"，不是"水印 vs deepfake"** → 覆盖攻击是二次嵌入，不覆盖换脸/重演这类语义级重生成 |
| **签名/证据链**（Ed25519 + SHA-256，演示级）→ 支撑完整性自校验 | 与本计划无关，不在数据缺口内 |
| 空占位目录 `/data1/luxliang/datasets/{celebdf_v2,dfdc,faceforensics,deepfakebench,df40}`（今天建，0 文件） | **有目录无内容** → deepfake 检测基线 / 跨方法泛化 / 原始↔操纵配对（用于标定换脸先验）全部缺位 |

**一句话定性缺口**：号称"Deepfake 溯源"，但全流程**从未让 deepfake 碰过你的水印**。补法不是堆数据集，而是补"嵌水印→被 deepfake→再解码"这一条因果链的实测。

---

## 三、【优先级数据获取清单】

> 体积全部远小于 12TB（合计推荐子集约 60GB）。**标注 [需人工签 EULA/表单，我无法自动下]** 的项必须由你今天手工提交。

### 1. FFHQ — 高清/多族群干净人脸源（可选，无审批，可直下）
- **用途**：作为"干净脸→嵌水印→换脸"闭环的**高清/多族群补充源**（现有 CelebA-HQ 已够，仅当需要 256px+ 或族群多样性时用）；亦可做域外泛化一次性评测（findings 多样性维度建议的 FFHQ 1000 张下采样评测）。
- **获取**：NVlabs 官方脚本，**无 EULA/无表单，可直接拉**；HF 有镜像。
- **体积**：128px 缩略图 ~1.95GB；1024px 全量 ~89GB（不需要）；in-the-wild 955GB（绝不下）。
- **优先级**：可选（建议只下缩略图备用）。
- **最小可用子集**：`--thumbs`（128px，1.95GB），或抽 1000 张 1024px 做域外评测。
- **命令骨架**：
  ```bash
  git clone https://github.com/NVlabs/ffhq-dataset
  python download_ffhq.py --thumbs   # 128px, ~1.95GB → /data1/luxliang/datasets/ffhq
  # 备用 HF 镜像：
  # huggingface-cli download --repo-type dataset marcosv/ffhq-dataset --local-dir /data1/luxliang/datasets/ffhq
  ```

### 2. Celeb-DF v2 — deepfake 检测基线 + 泛化评测（必须，可脚本化）
- **用途**：验证"检测 deepfake"与"对换脸方法泛化"的最快真实数据；**注意：其假脸非基于你的水印脸，只能验证检测/泛化，不能验证水印溯源存活。**
- **获取**：官方走 Google/腾讯表单 + 邮件审批（慢）；**但 Kaggle 有完整非官方镜像 `reubensuju/celeb-df-v2`，只需 Kaggle 账号 + 接受条款即可 API 直拉，绕过官方表单。** 需先在 `~/.kaggle/kaggle.json` 放 token（这一步是你账号的，我无法替你登录）。
- **体积**：完整视频 ~14–16GB（极小）。590 真 + 5639 假视频，单一改进版 DeepFake 换脸，无重演。
- **优先级**：必须（体积小、可即下、检测基线刚需）。
- **最小可用子集**：先全量（才 14GB），评测重点用官方 `List_of_testing_videos.txt` 测试集。
- **命令骨架**：
  ```bash
  pip install kaggle   # token 放 ~/.kaggle/kaggle.json
  kaggle datasets download -d reubensuju/celeb-df-v2 \
    -p /data1/luxliang/datasets/celebdf_v2 --unzip
  ```

### 3. FaceForensics++ (FF++) — 原始↔操纵配对，溯源核心校准集（必须，[需人工签 EULA/表单])
- **用途**：1000 原始 + 4 种操纵（Deepfakes/FaceSwap 换脸 + Face2Face/NeuralTextures 重演），**提供逐序列原始↔操纵配对 + mask**，最契合"同一张脸被换脸/重演前后"的对照；用于标定换脸先验、训练/评测溯源模型在真实换脸上的行为。
- **获取**：**[需人工签 EULA/表单，我无法自动下]** — 必须先填 Google 表单（`docs.google.com/forms/d/e/1FAIpQLSdRRR3L5zAv6tQ_CKxmK4W96tAab_pfBu2EKAgQbeDVhmXagg`），审批通过后才发 `download-FaceForensics.py` 链接。Kaggle 有非官方 c23 镜像 `xdxd003/ff-c23` 可应急。
- **体积**：raw 全量 ~500GB；**c23（高质量压缩）全方法仅 ~10GB**；c40 ~2GB。
- **优先级**：必须（但受审批阻塞）。
- **最小可用子集**：c23，`-d` 只取 **Deepfakes（换脸代表）+ NeuralTextures（重演代表）+ original**，几 GB。
- **命令骨架**（拿到脚本后）：
  ```bash
  python download-FaceForensics.py /data1/luxliang/datasets/faceforensics \
    -d Deepfakes -c c23 -t videos --server EU2
  # 重复换 -d original / -d NeuralTextures
  ```
- **行动项：今天就提交表单（审批 1–3 天），是 P2 时间瓶颈。**

### 4. DF40 — 换脸+重演方法多样性（建议，[需人工签 EULA/表单])
- **用途**：40 种伪造技术（10 换脸 / 13 重演 / 12 整脸合成 / 5 编辑，含 DiT/HeyGen 等 SoTA），测"溯源对多样换脸/重演方法的泛化"。
- **获取**：**[需人工签 EULA/表单，我无法自动下]** — 填 Google 表单（`docs.google.com/forms/d/1ESAWoWusOEGEEVnXCH_emv-wJqCYMhCbD6-85RMIoDk`），通过后发 Google Drive + 百度网盘链接（非 HF）。许可 CC BY-NC 4.0（仅非商业，竞赛用途符合）。
- **体积**：测试 ~93GB + 训练 ~50GB ≈ 143GB。
- **优先级**：建议。
- **最小可用子集**：只取 face-swapping (FS) + face-reenactment (FR) 两类，跳过 EFS/FE，约几十 GB。
- **命令骨架**（表单通过后）：
  ```bash
  gdown --folder <提供的Drive链接> -O /data1/luxliang/datasets/df40
  # 国内服务器若 Drive 不通：走百度网盘手动转存
  ```
- **行动项：与 FF++ 同步今天提交表单。**

### 5. DFDC — 大规模检测训练（可选，Kaggle 接受规则即可下）
- **用途**：仅当需要大规模检测模型训练时考虑；方法单一（2 种换脸）、与水印脸无配对关系。
- **获取**：Kaggle 竞赛数据，**需登录 Kaggle + 在竞赛页点一次"Accept Rules"（免邮件免表单，但要人工点同意一次）**，之后 API 拉。
- **体积**：全量训练集 ~470GB；**Preview 仅 4GB**（5K 视频）。
- **优先级**：可选（最低）。
- **最小可用子集**：Preview 4GB，或全量取 1 个分片 `train_part_00.zip` ~10GB。
- **命令骨架**：
  ```bash
  # 先在网页接受规则
  kaggle competitions download -c deepfake-detection-challenge \
    -f dfdc_train_part_0.zip -p /data1/luxliang/datasets/dfdc
  ```

### 6. 换脸/重演模型权重（非数据集，但 P1 闭环必备，可直下）
- **InSwapper / InsightFace**（换脸）、**SimSwap**（换脸）、可选 **First-Order-Motion / face-vid2vid**（重演）。这些是开源模型权重，无 EULA，是 P1 自建闭环的"操纵器"。
- 命令骨架：`pip install insightface`（自动拉 inswapper_128.onnx）；SimSwap 走 GitHub release 权重。

---

## 四、【Deepfake 溯源实验计划】

> 统一协议：复用 `configs/evaluation_protocol.v1.json`，success@0.9 阈值，bit-acc 与 success 双指标，报 n 与 CI，样本与训练域不重叠（呼应 TODO P2-8）。
> GPU 量级以单台 8×4090 估算（4090 ≈ 0.4–0.5×A100 训练吞吐，推理可并行 8 卡）。

### P1 — 立即可做（零新数据，今天开工）

**P1.0 · LIDMark 干净 id-bit 基线补测（前置，TODO P0-2 死结）**
- 输入数据：现有 CelebA-HQ/LFW 留出集。
- 模型：LIDMark 3-seed。
- 指标：16-bit id-bit 准确率（clean），3-seed 用**互不重叠样本**，报 between-seed n=3 + within-seed CI。
- 预期结论：把 `mean_bit_accuracy=0.0/null` 补成真实数字；若 clean 都低（findings 预测可能 ~62% 偏随机），则**溯源主张需重新限定**。
- GPU：极低，单卡 <1h。
- 补强：直接修 TODO P0-2，是后续一切"溯源"实验的比特级地基。**没有这个，P1.1 无意义。**

**P1.1 · 嵌水印→换脸→解码 溯源闭环（核心缺口直击）**
- 输入数据：CelebA-HQ/LFW 取留出子集（建议 1000–2000 张）。
- 流程：干净脸 →（KAD-Net / LIDMark）嵌水印 → InSwapper/SimSwap 换脸 → 解水印。
- 模型：KAD-Net（EC_50）、LIDMark；操纵器 InSwapper（128px，与现 pipeline 分辨率匹配）。
- 指标：换脸前 bit-acc / 换脸后 bit-acc / success@0.9 / CI / n；对比"clean vs swapped"衰减曲线。
- 预期结论：诚实预期——**水印很可能在换脸后大幅失效**（换脸是语义级人脸区域重生成，128px 嵌入信号大概率被覆盖）；这正是 THREAT_MODEL §2 档位 2/3 缺的实测点。若部分存活（如背景/非人脸区域嵌入），则量化"哪部分溯源信号能跨 deepfake"。
- GPU：小，8 卡并行半天内完成 2000 张。
- 补强：**首次给"嵌水印的脸被换脸后能否溯源"一个真实答案**，无论正负都是诚实证据，直接补 THREAT_MODEL deepfake 列空白、回应评委必问、修 TODO P1-12。

**P1.2 · 重演（reenactment）闭环（P1.1 的重演版）**
- 输入数据：同 P1.1 子集（需视频或驱动帧，可用现有静态脸 + First-Order-Motion 驱动）。
- 模型：First-Order-Motion / face-vid2vid 做重演；KAD/LIDMark 解码。
- 指标：同 P1.1。
- 预期结论：重演保留身份、改表情/姿态，水印存活率可能高于换脸（人脸纹理部分保留）——量化换脸 vs 重演的溯源差异。
- GPU：小到中，1 天内。
- 补强：补"重演"这一与换脸并列的 deepfake 类别。

### P2 — 需新数据（FF++/Celeb-DF 到货后）

**P2.1 · 真实换脸数据上的"被动检测 vs 主动溯源"对照**
- 输入数据：FF++ c23（original + Deepfakes + NeuralTextures）、Celeb-DF v2（Kaggle 镜像）。
- 模型：复用现有 KAD/LIDMark 解码器跑被动侧；可挂 deepfakebench 现成检测器做被动检测基线。
- 指标：被动检测 AUC/ACC vs 主动水印 bit-acc（在 FF++ original 上嵌水印后再用 FF++ 同源换脸方法重做 P1.1）。
- 预期结论：明确"被动检测 ≠ 主动溯源"的边界——被动检测器能判真假但不能溯源到具体来源，主动水印能溯源但跨 deepfake 脆弱；二者互补。
- GPU：中，需预处理视频抽帧裁脸 + 多模型推理，2–3 天。
- 补强：用**真实 deepfake 数据**而非自建管线给出第二个独立证据源，提升说服力；FF++ 原始↔操纵配对让"换脸前后同一张脸"对照更严谨。

**P2.2 · 几何/扩散净化 evasion 在真实 deepfake 链上的叠加（THREAT_MODEL §4 E1/E2 落地）**
- 输入数据：P1.1/P2.1 的换脸输出 + 几何攻击（crop/rotate）+ 扩散净化。
- 模型：KAD/WaveGuard/SepMark。
- 指标：失真强度 → success@0.9 曲线 + 对手代价（LPIPS/SSIM）。
- 预期结论：复现并量化"换脸 + 后续传播失真"组合链的失效拐点。
- GPU：中，2 天。
- 补强：把 THREAT_MODEL §4 的 E1/E2 从"计划"变"实测"。

### P3 — 完整（DF40 到货 + 跨方法泛化）

**P3.1 · 跨 deepfake 方法泛化矩阵**
- 输入数据：DF40 的 FS（10 换脸）+ FR（13 重演）子集。
- 模型：P1 闭环 pipeline 在每种方法上跑一遍。
- 指标：方法 × (bit-acc / success@0.9) 矩阵 + CI。
- 预期结论：给出"水印溯源对 N 种换脸/重演方法的存活率"全景，定位最易/最难穿透的方法族。
- GPU：中到大，DF40 子集多方法多样本，3–5 天。
- 补强：从"测了 1–2 种换脸"升级到"测了几十种 SoTA 方法"，是答辩"泛化能力"的硬证据。

**P3.2 · 端到端溯源 demo + THREAT_MODEL 回填**
- 输入数据：P1–P3 全部产物。
- 指标：把 deepfake 列正式写进 §3 失效边界主表（标 FAIL/部分存活，附 n/CI）。
- 预期结论：`demo.py` 的 `security_conclusion` 改为基于真实 deepfake-后 bit/tracer 阈值判定（修 TODO P1-12 收尾）。
- GPU：低。
- 补强：闭合"创作者→deepfake 传播→监管溯源→验签"叙事（TODO 阶段三增值）。

---

## 五、【务实提醒】

1. **不必搞的数据 / 避免为数据而数据：**
   - **DFDC 全量（470GB）不下** — 方法单一、与水印脸无配对、信息增益低，最多 Preview 4GB 试水。
   - **FFHQ 全量 70000×1024px 不下、绝不重训** — 重训会重跑 13,233 全量 benchmark，风险（数字变动）远大于收益；现有 CelebA-HQ 已够嵌水印源。FFHQ 只在需要时下缩略图。
   - **VGGFace2 全量（330 万张/36GB）不跑** — findings 多样性维度结论：水印鲁棒性是图像级操作、对身份不敏感，跨身份泛化信息增益极低，是重复劳动。
   - **不爬互联网亚洲人脸** — 版权风险 + 质量不可控；若要做族群泛化，从 CASIA-WebFace/MS-Celeb 取 500–1000 张做一次 clean+jpeg50 快评即可（GPU ~15 分钟），结论入 LIMITATIONS.md 即可。
   - **deepfakebench/DF40 不当"干净人脸扩充源"用** — 它们是 deepfake 库，混进训练域会污染。

2. **诚实定位现成 deepfake 库的能力边界（写进答辩，避免被打脸）：**
   - Celeb-DF/DFDC/DF40/FF++ 的假脸**都不是基于你嵌过水印的脸生成的**，它们只能验证"检测/分类"与"对换脸方法泛化"，**不能直接证明"水印被换脸后还能溯源"**。
   - 真正的溯源闭环只能靠 **CelebA-HQ/FFHQ 干净脸 → 自己嵌水印 → 自己跑 SimSwap/InSwapper/重演 → 再解码**（即 P1）。这一点必须在文档中讲清，否则评委会问"你拿 Celeb-DF 怎么证明溯源"——答不上来就翻车。

3. **版权/合规：**
   - FF++ / DF40 走 EULA/表单，**仅限非商业研究**（DF40 明确 CC BY-NC 4.0），竞赛用途符合，但产出物不得商用、需在文档致谢数据来源。
   - Celeb-DF v2 用 Kaggle 镜像绕过官方表单是**便利但非官方授权途径**，正式材料中引用时仍应注明原始论文与官方许可，避免被质疑数据来源合规性。
   - 所有 deepfake 数据含真实人物肖像，demo/截图避免传播可识别个人的合成换脸结果。

4. **时间排序（行动项，今天必做）：**
   1. **今天人工提交 FF++ + DF40 两个 Google 表单**（我无法代提，审批 1–3 天，否则 P2/P3 卡死）。
   2. 今天脚本化拉 FFHQ 缩略图（1.95GB）+ Celeb-DF v2 Kaggle 镜像（14GB）（需你先放好 `~/.kaggle/kaggle.json`）。
   3. 今天即可开工 **P1.0（LIDMark id-bit 基线）→ P1.1（嵌水印换脸闭环）**，零新数据依赖。
   4. 拉换脸模型权重（InSwapper/SimSwap，无 EULA）。
   5. 表单通过后下 FF++ c23 子集（~5GB）+ DF40 FS/FR 子集（~40GB），启动 P2/P3。
   - 推荐子集合计：FFHQ 2GB + Celeb-DF 14GB + FF++ c23 子集 ~5GB + DF40 子集 ~40GB ≈ **60GB**，对 12TB 毫无压力。

5. **不要让数据获取抢占 TODO P0 资源：** P0 诚信止血（LIDMark id-bit 补测 = 本计划 P1.0、几何鲁棒如实标注、硬编码拔除）优先级最高；本计划 P1.0 与 P0-2 重合，先做这个一举两得。P2/P3 是阶段三增值，时间允许再推进，**不应在 P0 未清前为下数据而下数据**。

相关文件（绝对路径）：
- `/home/winbeau/liangjia_liang/JianYuanShield/docs/THREAT_MODEL.md`（§3 失效边界待补 deepfake 列、§4 E1/E2 待落地）
- `/home/winbeau/liangjia_liang/JianYuanShield/TODO_DEEP_REVIEW.md`（P0-2 LIDMark id-bit、P1-12 威胁模型、阶段三增值）
- `/home/winbeau/liangjia_liang/JianYuanShield/docs/LIMITATIONS.md`（建议补"评测集同分布 + deepfake 溯源边界"说明）
- 数据落地目录：`/data1/luxliang/datasets/{ffhq,celebdf_v2,faceforensics,df40,dfdc}`
