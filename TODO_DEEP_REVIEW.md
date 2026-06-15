# 鉴源盾（JianYuanShield）信息安全作品赛——首席评审锐评 + 迭代 TODO

> **一句话定性**：这是一个**主题选得对、底层工程有功底、但被一层系统性夸大叙事包裹的"半成品旗舰"**——核心技术若如实呈现本可冲奖，可眼下对外文档/前端/报告把"512 图小样本、tracer 随机水平、对角线全 FAIL、landmark 定位率"统统包装成"全量 13,233 / 100% 已修复 / 创新有效 / 比特精度 99.97%"，任何一位评委交叉核对一次 artifact 即可当场证伪，**当前最大的失分点不是技术不行，而是诚信会先翻车**。

---

## 一、深度锐评（毫不留情，但有据）

1. **"诚信"是这个项目的头号风险，不是技术。** 对外材料（README/TECHNICAL_REPORT/JUDGE_QA/DEFENSE_SCRIPT/前端/报告导出器）与真实 artifact 之间存在**至少 5 处可一键证伪的硬冲突**：WaveGuard tracer Q=50 真实 52% vs 宣称"100% 已修复"、KAD-Net 512 图 vs 宣称"13,233 全量"、LIDMark landmark 定位率 99.93% 被当成"99.97% 比特精度"、MEA 对角线全 FAIL 被当"创新有效"、同一 KAD-Net 一处 100% 一处 50%。这些不是观点分歧，是数值层面的实锤矛盾。

2. **旗舰创新 MEA 当前是"自爆现场"。** 真实产物 `mea_4x4_1781010787.json` 对角线（模型自鲁棒性）大面积 FAIL，LIDMark 整行整列≈随机（49–73%）。把"我们最大的原创"做成一张以红叉为主的矩阵，还用"符合理论预期"话术兜底——评委只会问一句"你的水印连自己都解不出来？"叙事就崩了。**MEA 真正的价值是"诚实的红队发现"，现在被错误地当成了"我们很强"的卖点。**

3. **指标语义被系统性偷换。** detector（有没有水印的二分类）被当 tracer（谁的水印）报；landmark 定位成功率被塞进 `bit_accuracy` 语境并做显著性检验；16-bit / 30-bit / 128-bit 三种不同长度、不同解码器的 accuracy 被并进同一张矩阵用同一套阈值评级。这不是笔误，是贯穿文档+代码的口径错误，懂统计/懂水印的评委会逐条点破。

4. **"统计严谨"人设站不住。** 把 3 个 seed × 512 图拍平成 1536 个"独立样本"做 bootstrap，是经典 pseudoreplication，所以才会冒出 `CI=[1.0,1.0]`、`[99.94%,100%]` 这种零方差/过紧区间。本想当亮点的"3-seed + 95%CI"，在内行眼里是减分项。

5. **"司法级证据链"是安全剧场。** 实现只是"对一份扁平 manifest 签一次 Ed25519 + 记 SHA-256"——没有链式哈希/Merkle、没有可信时间戳（用的是本机 `time.time()`）、私钥与验签器同机同目录生成无任何密钥管理。叫"链"却没有链，叫"法庭取证"却时间戳可伪造。作为"信息安全"作品，这是最容易被深挖的地方。

6. **作为"安全系统"，后端自身不安全。** 上传图片→`torch.load(weights_only=False)`（pickle RCE 面）、端点零鉴权零限流零体积校验、`sample_id`/`task_id` 路径穿越、CORS `allow_origins=["*"]+allow_credentials=True` 违规组合。一个号称"主动取证"的平台被匿名 DoS / 路径穿越，是自我打脸。

7. **可复现性接近为零。** 模型族全部在外部 `/data1` 目录（本地仓库根本没有 weights/runs/datasets），`requirements.txt` 全用 `>=` 下界且写了不存在的 `torch>=2.12`、缺 pytorch_wavelets/einops/face_alignment 等推理必需包，单元测试不加载任何真实权重、无 CI。评委拿到 git 仓库一个 import 都跑不起来。

8. **内外文档已经分裂，团队其实自己知道。** `README_COMPETITION.md` 写 `ready_for_claims=no`、`JUDGE_QA` 写"HiDDeN 已剔除"、远端有 5 个"把夸大 claim 往回改"的未提交修改——说明团队已意识到风险，但**本地这份（也是本次审查/可能答辩用的版本）仍是夸大版**。版本分叉本身就是高危：极易误用旧版本提交。

> **公允声明**：底层指标库（`metrics.py`/`statistics.py`/`attacks.py`，真实 cv2 编解码而非可微代理）、攻击与种子派生设计、FastAPI 结构、凭证处理（`.env` 已 gitignore、私钥 `chmod 600`、`.env.example` 无真密钥）**写得专业，是真亮点**。原创性归属经团队确认为本组成果、无侵权（见证据简报 §7），**本文不作抄袭指控**；涉及"原创性举证""WaveGuard 是否另有大样本运行"等仅作"需团队自查/举证"处理，不冤判。

---

## 二、【P0 致命·必须先改】

> 标准：会让评委当场质疑诚信或直接掉分。每条均已本地复核 file:line。

### P0-1 WaveGuard "Q=50 tracer 100% 已修复" vs 真实 tracer 52%（detector 冒充 tracer）
- **问题**：到处宣称 WaveGuard JPEG Q=50 tracer 比特精度 100%、"完全修复原 37.3%"、`CI=[1.0,1.0]`；真实负责溯源的 tracer 在 Q=50 仅 ≈52%（随机），100% 实为 detector（二分类）。把弱指标冒充强指标。
- **证据**：`docs/WAVEGUARD_JPEG_ANALYSIS.md:1-3`、`docs/JUDGE_QA.md:25,66`、`docs/DEFENSE_SCRIPT_3MIN.md:11`、`system/frontend/app.js:505,507`；真实值见证据简报 §4（远端修正 detector=89%/tracer=52%）。
- **对评分影响**：核心鲁棒性卖点被一击证伪；`CI=[1.0,1.0]` 在 512 图小样本上极易被识破为训练域过拟合，连带拉垮整体可信度。
- **迭代动作（算力充足→首选做实）**：
  - [ ] 在**独立留出集（非 7ep 微调训练域）、>512 张**上重测，分报 detector / tracer 双指标，区间用真实非退化 CI。
  - [ ] 若 tracer 仍不达标，文档/前端/脚本统一改为真实值（detector 89% / tracer 52%），删除"100%/完全修复/CI=[1.0,1.0]"，明确"tracer 微调进行中"。
  - [ ] 同步修 `app.js:505,507`、`docs/WAVEGUARD_JPEG_ANALYSIS.md`、`docs/JUDGE_QA.md:25,66`、`docs/DEFENSE_SCRIPT_3MIN.md:11`。
- **工作量**：文案止血 S；做实重训 M。

### P0-2 LIDMark "99.97% 比特精度" 实为 landmark 定位成功率，bit_acc=null
- **问题**：旗舰模型对外 99.97/99.98% 被表述为"ID 比特精度/bit accuracy"并进显著性检验，但真实产物 `mean_bit_accuracy=0.0`、per-seed `bit_accuracy=null`，99.93% 是 landmark 定位成功率（对攻击不敏感、与水印鲁棒性无关）。
- **证据**：`README.md:35,114,219,336`、`docs/TECHNICAL_REPORT.md`、`docs/JUDGE_QA.md:23`、`system/frontend/index.html`（"3-SEED CLEAN BIT-ACC"）；真实值见证据简报 §2。
- **对评分影响**：项目首推模型的 hero 数字、徽章、统计显著性全建立在误标之上；评委一问"这 99.97% 是消息恢复还是关键点检测"即翻车，且意味着 Deepfake 穿透溯源的核心能力当前**无比特级证据**。
- **迭代动作**：
  - [ ] **真正测出并上报 LIDMark bit-level ID 准确率**（当前 null 必须补），3-seed 用**互不重叠样本**而非同 512 图重复。
  - [ ] 全文/前端区分 `landmark_success_rate`（99.93%）与 `id_bit_acc`（待测）两套指标，hero/徽章禁用"bit-acc"。
  - [ ] 统计显著性表先删除对 LIDMark 比特精度的 p 值，待真实 bit_acc 跑出再上。
- **工作量**：M（含实验）。

### P0-3 KAD-Net 512 图被写成"LFW 13,233 全量 / 全攻击 ≥99.5%"（样本量约 26×）
- **问题**：报告导出器与 README 把 KAD-Net 写成 13,233 全量、所有攻击≥99.5%；真实只跑 512 图且仅温和攻击，几何攻击实质失败（crop 68.9% / rotate 43.7%）。
- **证据**：`system/scripts/export_competition_report.py:73,75`、`README.md:337`（`512→13,233 †`）、`README.md:342`（自注"运行中"，与正文自相矛盾）；真实值见证据简报 §1。
- **对评分影响**：`export_competition_report.py` 产出的是答辩取证报告，硬编码 13,233 会进入正式证据材料，与 `n_images=512` 一键对不上。
- **迭代动作**：
  - [ ] **首选做实**：把 KAD-Net 真跑 LFW 13,233 全量，并补 crop/rotate 几何微调到达标，让"13,233 + 几何鲁棒"成为真结果。
  - [ ] 在做实前：`export_competition_report.py:73,75`、`README.md:337` 统一标 512、仅温和攻击 100%、几何 partial，删除"→13,233"暗示。
- **工作量**：文案 S；做实 M–L。

### P0-4 旗舰创新 MEA 矩阵对角线全 FAIL / LIDMark 整行随机，却作"创新有效"卖点
- **问题**：MEA 5×5 真实结果以 FAIL/MARGINAL 为主（SepMark second 56%、WaveGuard 62.8%、LIDMark 51.8/60.2%、KAD-Net first 50.2%、HiDDeN 51.3% 全 FAIL；LIDMark 整行≈49–73% 随机），被当"填补空白/创新有效"宣传。
- **证据**：`docs/TECHNICAL_REPORT.md:172-184`、`README.md:241-261`、`docs/INNOVATION_POINTS.md`；真实 artifact 证据简报 §3。
- **对评分影响**：评委看到一张红叉矩阵 + 自家模型自鲁棒性随机，会判"提出了协议但未证明价值"。
- **迭代动作**：
  - [ ] **重定位叙事**：MEA 改为"诊断性红队发现——揭示多水印共存下后嵌入会摧毁先嵌入水印溯源"，明确区分"协议创新"与"结果有效"。准备"对角线 FAIL = 安全发现而非缺陷"的答辩话术。
  - [ ] 先修 P0-5 口径 bug，再 128→大样本重跑；每格补 CI、n、decoder、msg_len 标注。
  - [ ] 对 LIDMark 整行随机给出解释或限定结论。
- **工作量**：M。

### P0-5 同一 KAD-Net 两套 benchmark 互斥：单模型 clean 100% vs MEA 自对角 first_acc 50%
- **问题**：同模型同 clean 条件，单模型 benchmark `bit_acc=1.0`，MEA 矩阵 `first_acc=0.50`（随机）。两套官方产物互斥，且 first/second_acc 定义、阈值在产物中无自解释。
- **证据**：`README.md:337` / `docs/TECHNICAL_REPORT.md:145,175`；真实值证据简报 §1/§3。代码侧 `system/evaluation/adapters/multi_embedding.py:41-51`（first 是"被二次嵌入覆盖后第一重水印残留率"，与单嵌 clean 非同一量）。
- **对评分影响**：评测可复现性/有效性是核心评分项，互斥数据同屏展示=造假嫌疑。
- **迭代动作**：
  - [ ] 排查 `multi_embedding.py` 与 `kadnet_adapter` 的 first/second_acc 定义；**首先怀疑 `strict=False` 加载静默丢权重导致随机**（见 P1-后端）。
  - [ ] 文档加"口径对照表"：单模型 clean = 单嵌+单攻击 bit_acc；MEA first = 经第二模型二次嵌入后第一重水印残留 bit_acc。
  - [ ] 消除或解释 100%↔50% 矛盾，统一 MEA 随机种子为协议 seed（当前硬编码 42）。
- **工作量**：M。

### P0-6 后端核心安全硬伤：torch.load 反序列化面 + 零鉴权/零校验上传（"安全系统不安全"）
- **问题**：匿名请求可上传任意大小/内容文件触发推理；`torch.load(weights_only=False)` 是 pickle 全功能反序列化（RCE 面）；端点无鉴权/限流/体积/像素/MIME 校验，批量端点无张数上限。
- **证据**：`system/backend/routes.py:168-186`（无 Depends）、`system/backend/infer.py:39-49`、`system/backend/model_adapters.py:293,413,532`、`system/evaluation/adapters/{lidmark,kadnet}_adapter.py:57,75`（均 weights_only=False）。
- **对评分影响**：安全赛评委必问"你这套取证系统自己安全吗"，这是致命自爆点。
- **迭代动作**：
  - [ ] 自家 `.pth` 只存权重张量 → 全部改 `torch.load(..., weights_only=True)`；或加载前 SHA-256 白名单校验。
  - [ ] infer/compliance 端点加：Content-Length/像素上限（如 ≤5MB）、MIME 白名单（png/jpeg）、Pillow 解码异常兜底、最简 API key 鉴权、限流（slowapi）、批量张数上限。
- **工作量**：M。

### P0-7 合规批检接口在无模型时用图像熵"伪装检测"且不告知调用方
- **问题**：`get_adapter()` 返回 None 时，`/api/compliance/batch` 不报错、用灰度熵生成"看似真实"的合规判定，对任何图像恒返回 `status='no_watermark'` + "❌ 未检测到合规隐式水印"。
- **证据**：`system/backend/infer.py:140-157`（"Heuristic simulation … classify based on image statistics"）。
- **对评分影响**：现场 checkpoint 链断（换机/symlink 失效）→ 合规模块完全失效但界面照常出报告，评委发现即质疑整个取证链路。
- **迭代动作**：
  - [ ] fallback 分支返回 HTTP 503 或在结果加 `mode:'no_model_fallback'` + 顶层 `warning:'adapter_unavailable'`，明确结论无效。
- **工作量**：S。

---

## 三、【P1 严重】

### P1-1 内外文档口径分裂（README "全部兑现" vs COMPETITION/JUDGE_QA "ready_for_claims=no"）
- **问题**：主 `README.md` 是"13,233/99.98%/已修复"全兑现姿态；`README_COMPETITION.md:46` 明写 `ready_for_claims=no`、`docs/JUDGE_QA.md:13` 写"HiDDeN 已剔除"。评委交叉读即抓包。
- **证据**：`README.md:11-13,35-46` vs `README_COMPETITION.md:46`、`docs/JUDGE_QA.md:13`。
- **影响**：诚信硬伤，连带使真实成果也被怀疑。
- **动作**：
  - [ ] 以 COMPETITION 诚实口径为准重写 README，所有数字标真实样本量与 stage/seed 状态；删除/脚注"13,233 全量"徽章（仅 SepMark 成立）。
  - [ ] 三份文档建立单一数据源（自动报告回填），杜绝漂移。
- **工作量**：M。

### P1-2 WaveGuard / INNOVATION_POINTS 借用 SepMark 的 13,233 样本量
- **问题**：多处称 WaveGuard 也完成 13,233 全量、INNOVATION_POINTS 把"13,233 大规模对照"扩张到 HiDDeN+SepMark+WaveGuard 三模型；真实唯一 13,233 的是 SepMark，WaveGuard=512、HiDDeN 损坏。
- **证据**：`docs/JUDGE_QA.md:13`、`docs/DEFENSE_SCRIPT_3MIN.md:9`、`docs/WAVEGUARD_JPEG_ANALYSIS.md:13`、`system/frontend/index.html:404,408`（"LFW FULL"）、`docs/INNOVATION_POINTS.md:7`；真实值证据简报 §6。（注：`JUDGE_QA.md:25` 已写"512 张"，存在文内不一致，需团队自查 WaveGuard 是否另有 13,233 运行。）
- **影响**：可一键证伪的样本量夸大，与 `CI=[1.0,1.0]` 叠加更显刻意。
- **动作**：
  - [ ] 统一标注各模型真实样本量（SepMark 13,233 / WaveGuard 512 / HiDDeN 小样本且损坏）；去掉 `index.html:404,408` 的 FULL 标注。
- **工作量**：S。

### P1-3 HiDDeN "损坏剔除" 与 "300ep 有效纳入" 状态自相矛盾
- **问题**：一处"checkpoint 损坏、≈随机、已剔除、不能说有效"，另一处"300ep 有效 clean 99.1%、纳入 MEA 对照"，JPEG success=0%。
- **证据**：`docs/REAL_BENCHMARK_STATUS.md:11,28`、`docs/JUDGE_QA.md:13` vs `system/scripts/export_competition_report.py:74,111`、`system/backend/benchmarks.py:253,279`；适配器层 `system/evaluation/adapters/__init__.py:37-39` 仍注册 HiDDeN 为可用。
- **影响**：评委并排看即发现"又死又活"，削弱"证据可核验"卖点本身。
- **动作**：
  - [ ] 二选一全局对齐：(a) 真剔除——从 `get_available_adapters` 与 MEA 移除；或 (b) 仅作"失败案例 baseline"——矩阵/汇总显式标 clean≈99.1% 但 JPEG 0%、checkpoint 来源存疑、不作能力。
- **工作量**：S。

### P1-4 MEA grade 阈值 0.85/0.65 凭空硬编码，与协议 success_threshold=0.9 冲突
- **问题**：`grade()` 硬编码 PASS≥0.85 / MARGINAL≥0.65，与统一协议明文 0.9 且"不允许脚本硬编码"冲突；旗舰矩阵的 PASS/FAIL 结论建立在未论证的任意阈值上。
- **证据**：`scripts/run_mea_matrix_4x4.py:32-37` vs `configs/evaluation_protocol.v1.json:4`（success_threshold=0.9）、`system/evaluation/adapters/multi_embedding.py:31`（默认 0.9）。
- **影响**：同项目两套成功阈值，旗舰矩阵评级站不住。
- **动作**：
  - [ ] `grade()` 从协议读阈值（统一 0.9），或在报告给出 0.85/0.65 的实验校准依据（基于随机基线+CI 分级）；每格补 CI 与 n。
- **工作量**：S。

### P1-5 MEA 跨模型把 16/30/128-bit 不同长度、不同解码器的 accuracy 并列同一阈值
- **问题**：LIDMark 16-bit（仅 id 位、136 维 landmark 置零）、KAD/WaveGuard 30-bit、SepMark 128-bit，且 detector / decoder_C / decoder_RF 语义不同，被放进同一矩阵同一 grade()，本质 apples-to-oranges。
- **证据**：`lidmark_adapter.py:96-100`（zeros(152), 仅 16 位 id）、`kadnet_adapter`/`waveguard_adapter` MSG_LEN=30、`sepmark_adapter` MSG_LEN=128；`run_mea_matrix_4x4.py:94-97`。
- **影响**："LIDMark 破坏性最强"等跨行列比较可能是 bit 长度/解码器伪影。
- **动作**：
  - [ ] 矩阵每格并列标注 msg_len/decoder；first_acc 报相对随机基线归一化指标 (acc-0.5)/0.5 + CI；区分"检测器存在性"与"消息可溯源性"，不混入同一评级。
- **工作量**：M。

### P1-6 "3-seed 95%CI" 统计口径错误（pseudoreplication）
- **问题**：把 3 seed × 512 图拍平成 1536 个"独立样本"做 bootstrap，得到的是被严重低估的图像采样 CI，不是 between-seed 方差，故出现 `[99.94%,100%]` 过紧区间，却宣称"真实 between-seed 方差(n=1,536)"。
- **证据**：`run_statistical_analysis.py:49-70,132,135,197`、`docs/TECHNICAL_REPORT.md:263`。
- **影响**：本想当亮点的统计严谨性，被内行当场指出无意义→减分。
- **动作**：
  - [ ] between-seed 方差用 3 个 seed-level 均值（坦诚 n=3 仅供参考）；或固定单 seed 明确标"within-seed image-sampling CI"；修正 limitations/报告措辞。
- **工作量**：M。

### P1-7 指标定义混用进显著性检验（landmark 成功率 vs id_bit vs detector vs message BER 跨指标配对）
- **问题**：至少 4 种不同量被并入"bit accuracy/精度"语境并互相做 paired_sign_flip + Holm；"99.98% > 91.2%"是不同指标的错误比较。
- **证据**：`run_statistical_analysis.py:63-64,147-168,177`、`docs/TECHNICAL_REPORT.md` 9.1/9.2。
- **影响**：汇总表与显著性结论度量不自洽，易被判"指标误标/夸大"。
- **动作**：
  - [ ] 每个数值标准确指标名（landmark_success_rate / id_bit_acc / detector_bit_acc / message_BER），分指标单独成表，只在同一指标内部做配对检验。
- **工作量**：M。

### P1-8 攻击覆盖 cherry-pick：几何攻击实质失败被淡化、不进 summary
- **问题**：协议定义了 crop/rotate/blur，但各模型 headline 与 summary 只呈现 clean/jpeg/noise/resize，几何 rotate≈随机被措辞为"微调进行中"。
- **证据**：`configs/evaluation_protocol.v1.json:76-96`、`system/evaluation/attacks.py:32-34`（实现真实）、证据简报 §1（crop 68.9%/rotate 43.7% 仅 partial）。
- **影响**：裁剪/旋转是社交转发最常见操作，回避=鲁棒性高估。
- **动作**：
  - [ ] 主表统一列全部攻击（含 crop/rotate/blur）真实数值，失败如实标 FAIL；算力充足则微调达标后再上真结果。
- **工作量**：M。

### P1-9 benchmarks.py / 前端硬编码已证伪指标，与 artifact 脱钩
- **问题**：`benchmarks.py` `model_status` 与 `app.js` 主结论字符串写死 "99.97%/KAD 100%/WaveGuard 100%/STE 100%"，不随后端真实数据变化，使"前端展示全量真实证据"卖点名不副实。
- **证据**：`system/backend/benchmarks.py:261,288`、`system/frontend/app.js:504-507`、`system/frontend/index.html:482,497`（审计页副标题也写死 "99.97%"/"tracer 100%"）。
- **影响**：现场点开 RAW JSON 即见展示层与数据层脱节，且硬编码 100% 正是 P0 误导的传播载体。
- **动作**：
  - [ ] `model_status`/mainConclusion/contrastConclusion/boundaryConclusion 与审计页副标题改为从 summary.json 真实字段渲染；null 时显示"评测进行中"，不显示数字。
- **工作量**：M。

### P1-10 后端工程性 P1（线程安全 / 硬编码路径 / 阻塞 / strict=False / chdir / CORS）
- [ ] **strict=False 静默丢权重**（`model_adapters.py:193-195,298-300,414`）：SepMark/WaveGuard/LIDMark 改 `strict=True` 或显式 white-list，加载后 assert 关键层 norm 非随机初始值——**这极可能是 P0-5 KAD↔MEA 50% 的根因之一**。S
- [ ] **sys.modules/sys.path 全局污染**（`model_adapters.py:168-174,272-274,399-401,523-525`）：warmup 线程并发 `del sys.modules` 互相破坏，合并到单一 import_lock 串行化或 ProcessPool 隔离。M
- [ ] **os.chdir() 进程级副作用**（`model_adapters.py:267-280`）：改 `importlib.util.spec_from_file_location` 绝对路径导入，消除 chdir。S
- [ ] **async 路由裸调同步推理阻塞事件循环**（`routes.py:169-186`）：用 `run_in_executor` 或改普通 `def`。S
- [ ] **硬编码 `/data1` 绝对路径**（`model_adapters.py:22,515-516`、`benchmarks.py:191`）：统一从 `JYS_MODEL_SOURCE_ROOT` 派生。S
- [ ] **CORS `*`+credentials 违规组合**（`app.py:60-66`）：明确前端 origin 白名单或关 credentials；收紧 methods/headers。S
- [ ] **sample_id/task_id 路径穿越**（`routes.py:53-55,63-68`、`demo.py:21-26`）：白名单正则 `^[A-Za-z0-9_-]{1,64}$` + `is_relative_to(base)` 断言。S

### P1-11 "防篡改证据链/法庭取证"措辞夸大（安全剧场）—— 收敛措辞或做实
- **问题**：实为单次 manifest 签名+哈希，无链式哈希/Merkle、无 RFC3161 可信时间戳（用 `time.time()`）、私钥与验签器同机生成无密钥管理。
- **证据**：`signing.py:86-104,91,107-138`（grep `prev|chain|merkle` 无命中）、`docs/TECHNICAL_REPORT.md:68,211,232`、`docs/JUDGE_QA.md:40-42`。
- **影响**：核心安全卖点，评委一问"私钥怎么管/时间戳谁背书/链在哪"即难自圆。
- **动作（需团队定夺：收敛 or 做实）**：
  - [ ] 措辞降级为"完整性自校验 + 来源签名（demo 级，演示密钥）"；或做实：私钥离线生成仅导出公钥、接入 RFC3161 TSA、manifest 升级为带 prev_hash 的追加式链。
- **工作量**：M。

### P1-12 威胁模型缺位，且真实 benchmark 已显示溯源在攻击下失效
- **问题**：全仓无对手能力建模/去水印 evasion 实验；而真实数值（WaveGuard tracer Q=50=52%、LIDMark 跨模型≈随机）恰恰说明普通二压/缩放就能让溯源失效，安全主张与实测相矛盾。
- **证据**：docs 全仓 grep 威胁模型/对手/evasion 仅命中 `ITERATION_ROADMAP.md:167,170`（且非对手建模）；`demo.py:188` security_conclusion 仅按有无 attack 二值贴标签。
- **影响**：安全赛必问"对手能去掉/伪造你的水印吗"，无威胁模型+随机级溯源是答辩重灾区。
- **动作**：
  - [ ] 补正式威胁模型章节（被动/主动/自适应三档对手）；补去水印 evasion 实验（几何/扩散净化/对抗扰动）并诚实标失效项；security_conclusion 改基于真实 bit/tracer 阈值。
- **工作量**：L。

### P1-13 可复现性致命阻断（symlink / requirements / WaveGuard 主脚本不算分 / offline_deploy 无权重 / 无 CI）
- [ ] **模型族全在外部 `/data1`**（本地仓库无 weights/runs/datasets）：核心路径统一走 `JYS_MODEL_SOURCE_ROOT`，`kadnet_adapter.py:15-16`/`lidmark_adapter.py:16-17`/`adapters/__init__.py:21-27` 改用 `runtime.py` 的 `MODEL_SOURCE_ROOT`；README 提供 setup.sh 挂载步骤。M
- [ ] **requirements.txt 全 `>=` 且 `torch>=2.12`（无效版本）+ 缺 pytorch_wavelets/einops/face_alignment 等**：全改 `==` pin，合并 Dockerfile 额外包，修 torch 为 `~=2.1.2`。S
- [ ] **WaveGuard 主 benchmark 脚本仅做 torch.load 存活检查、非真实推理**（`system/scripts/run_waveguard_lfw_benchmark.py:22-54`，status=`checkpoint_load_ok`）：改为调用 `WaveGuardModelAdapter` 真跑 encode→attack→decode，或整合进已有完整推理的 `run_waveguard_lfw_small_benchmark.py`。S
- [ ] **offline_deploy.sh 未打包权重/数据**（`docker-compose.yml:19` 挂载不存在的 `/data1`）：补权重打包步骤 + 相对路径挂载 + 就绪校验脚本。M
- [ ] **单测不加载任何真实权重、无 CI**：补一个端到端集成测试（SepMark 真权重 encode→decode→断言 clean_acc>0.85）+ 绑定 CI workflow。M

---

## 四、【P2 一般】

- [ ] **P2-1 Ed25519 覆盖文件数 22 vs 19 不一致**：`README.md:38,141,267,531` 写 22，`docs/JUDGE_QA.md:42` 写 19；以 `evidence_audit_payload()` 真实返回为准统一全文，`README:531` 示例输出来自真实接口而非硬编码。S
- [ ] **P2-2 README MEA 标"初步估算/假设/进行中"但数值与真实 artifact 一致**（`README.md:248,257`）：artifact 真实存在则统一标真实实验结果，删"估算/假设/进行中"，与 TECHNICAL_REPORT 对齐。S
- [ ] **P2-3 MEA 状态三处互斥**：`LIMITATIONS.md:12`（25 格 blocked）vs `README:248`（估算/进行中）vs `benchmarks.py:279`（complete n=128）——统一为 complete。S
- [ ] **P2-4 KAD-Net/SepMark 质量指标 PSNR/SSIM 不含攻击、攻击列恒等**（`system/scripts/run_kadnet_lfw_benchmark.py:184-186`、`run_sepmark_lfw_benchmark.py:275`）：每攻击分支算 attacked_vs_original，与 watermarked_vs_original 分两列。S
- [ ] **P2-5 MEA first_acc 是"覆盖残留率"却与 second 共用阈值、无覆盖前基线**（`multi_embedding.py:41-51`、`run_mea_matrix_4x4.py:32-37`）：加单嵌基线列，first_acc 改名 first_message_retention，独立阈值/配色。M
- [ ] **P2-6 两套同名"矩阵脚本"，`system/scripts/run_multi_embedding_matrix.py` 不算分**：合并/重命名（不算分的改 plan_*），README 标唯一入口。S
- [ ] **P2-7 噪声攻击全局固定 seed，所有图共享同一 noise pattern**（`run_lidmark_lfw_eval.py:68`、`run_hidden_benchmark_real_small.py:141`）：改 `derived_seed(20260603, image_id, 'noise')`，与 `attacks.py:169` 对齐，重跑受影响指标。S
- [ ] **P2-8 训练域自测、无 cross-split/泄漏防护**：划身份不相交 train/eval split，3-seed 用不重叠样本，run_metadata 记 split 来源。L
- [ ] **P2-9 HiDDeN adapter 多重 fallback + 运行时改 message_length**（`hidden_adapter.py:21-23,97`）：checkpoint/msg_len 显式锁定写入 run_metadata。M
- [ ] **P2-10 sha256_file 两处定义签名不一致**（`evidence.py:13` 返回 str|None vs `signing.py:27` 返回 str）：合并到 utils.py 统一语义。S
- [ ] **P2-11 LIDMark face_alignment 异常被吞、静默降级零向量水印**（`model_adapters.py:453-462`）：改 log warning + 返回 `landmark_fallback:True`。S
- [ ] **P2-12 demo metrics 用幻数系数（0.42/1.8/12.0/0.18）反推 BER**（`demo.py:118-127`）+ **simulation 模式无醒目标注**（前端 `app.js:836`）：simulation 改 `schema_version='...-simulation.v1'` + 顶层 `simulation:true` + 前端橙色 banner，合规结论强制显示"—（模拟）"。S
- [ ] **P2-13 前端文案错误**：MEA 横评 `app.js:913` 称"4 个模型"实只调 SepMark/WaveGuard；Benchmark 标题/顶栏静态写死 "13,233"（`app.js:686`、`index.html:114`）；KAD-Net 卡 fallback 写死 "512·geo-finetuned(EP50)"（`app.js:497`）——全部改动态拼接或如实标注。S
- [ ] **P2-14 PWA 有 manifest 无 Service Worker**：补最简 SW 缓存兜底，或删 `styles.css:4` 的"离线可用"宣传。M
- [ ] **P2-15 compliance/batch 回显原始异常文本**（`infer.py:167-174`）：改 `logger.exception` + 对外通用文案。S
- [ ] **P2-16 export_competition_report.py:42 残留 `/data1` 硬编码**：改 `ROOT / 'system/reports/.../summary.json'`。S
- [ ] **P2-17 答辩缺技术难度/工作量量化 + 多端"开发中"画饼**：答辩稿加 GPU 训练时数/代码量/测试数；多端降级为"后端 API 已就绪，移动端为后续规划"。M

---

## 五、【P3 锦上添花】

- [ ] **P3-1 凭证处理基线合格（保持）**：补一句"演示用 Ed25519 私钥由运行方现场生成、绝不入库"于 JUDGE_QA/部署文档，巩固诚信叙事。S
- [ ] **P3-2 normalization.py 每请求两次 `protocol_summary()`**（`:96-97`）：缓存为单次调用。S
- [ ] **P3-3 几何攻击代码已存在但未进 summary**（`attacks.py:32-34`）：纳入主表如实展示。M
- [ ] **P3-4 summary-row 固定 5 列但有 6 个 stat 卡**（`styles.css:1507` vs `index.html:149-178`）：改 `repeat(6,…)` 或 auto-fill。S
- [ ] **P3-5 KADNet/mea_dir 路径不受 env 覆盖**（与 P1-13 合并处理）。S
- [ ] **P3-6 绝对化措辞"全球首个/唯一/填补空白"无可证伪依据**（`README.md:84,126,130,132,207`，团队 TODO_ROADMAP:122 已识别未执行）：改"面向 Deepfake 后溯源的主动水印方案""据我们调研较少覆盖多水印并存评测"，技术报告补 related-work 定位（对比 C2PA/被动检测/单水印）。S
- [ ] **P3-7 原创性举证三件套（加分项）**：补设计/数学动机、消融表、与 SepMark·HiDDeN 同协议同数据差异化对比表（归属已无侵权风险，纯为应对"凭什么叫原创"）。M

---

## 六、冲奖优先级路线图

> 原则：**先止血（诚信纠偏）→ 再补强（真实大样本 + 几何鲁棒 + MEA 红队叙事）→ 后增值**。算力充足，故能做实的优先做实而非下调声明。

### 阶段一 · 止血（必须做，1–3 天，决定"会不会当场翻车"）
- [ ] **统一权威版本**：合并远端"claim 回退修正"到本地，确定唯一答辩版本，建立"文档数字必引用 artifact"校对清单（复用 `scripts/check_documentation.py`），提交前跑数值一致性检查。【必须】
- [ ] **拔掉所有可一键证伪的硬编码**：`benchmarks.py:261,288`、`app.js:504-507`、`index.html:482,497`、`export_competition_report.py:73,75,42`、Ed25519 22/19 全部改为读真实字段或如实标注。【必须】
- [ ] **指标语义纠偏**：全文/前端区分 detector vs tracer、landmark_success_rate vs id_bit_acc；删除"100% 已修复/CI=[1.0,1.0]/99.97% 比特精度"等误标。【必须】
- [ ] **HiDDeN 状态二选一并全局对齐**；**MEA 状态统一为 complete 并改红队叙事**。【必须】
- [ ] **README 以 COMPETITION 诚实口径重写**，样本量按真实标注（SepMark 13,233 / 其余 512）。【必须】
- [ ] **后端安全 P0 急修**：torch.load weights_only=True、上传体积/MIME 校验、compliance fallback 503/warning。【必须】

### 阶段二 · 补强（必须做，3–10 天，决定"技术成色"）
- [ ] **先修口径 bug 再大规模重算**：修 `strict=False` 静默丢权重、统一 MEA 协议 seed、排查 KAD 100%↔50%——否则大规模重跑只是放大错误。【必须】
- [ ] **做实大样本**：KAD-Net 512→13,233 全量；LIDMark 真测 bit-level id_acc（不重叠样本 3-seed）；WaveGuard 独立留出集 >512 重训 tracer 报双指标。【必须】
- [ ] **几何鲁棒做实**：KAD-Net crop/rotate 微调至达标，全部攻击进主 summary。【必须】
- [ ] **MEA 128→大样本重跑**，每格补 CI/n/decoder/msg_len，叙事定为"诚实红队发现"。【必须】
- [ ] **统计口径修正**：between-seed 用 n=3、分指标成表、只同指标内做配对检验。【必须】
- [ ] **可复现性兜底**：requirements pin + 补包、路径走 env、offline_deploy 打包权重、补 1 个端到端集成测试 + CI。【必须】

### 阶段三 · 增值（加分项，时间允许再做）
- [ ] 威胁模型章节 + 去水印 evasion 实验（被动/主动/自适应三档）。【加分】
- [ ] 证据链做实：RFC3161 时间戳 + prev_hash 追加式链 + 离线私钥（或诚实降级措辞）。【加分】
- [ ] 原创性三件套（数学动机/消融/差异化对比表）+ related-work 定位，去绝对化措辞。【加分】
- [ ] 端到端"创作者→Deepfake 传播→监管溯源→验签"单页 demo + 3 分钟录屏 backup；答辩稿加工作量量化。【加分】
- [ ] 前端细节（SW 离线兜底、文案修正、布局、simulation 醒目标注、PSNR/SSIM 分列）。【加分】

> **底线判断**：本项目技术底子足以冲奖，**但只要带着当前这版夸大文档上场，第一道交叉核对就会先扣诚信分、再波及全部真实成果**。阶段一止血不做完，阶段二、三的技术增量都救不回来——**先诚实，再强大**。
