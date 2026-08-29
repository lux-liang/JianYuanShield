# 创新点：从算法输出到可验证来源证据

鉴源盾的创新主线，是把主动水印从一次推理结果提升为可登记、可盲验、可校准、可签名、可被机器拒绝的来源证据。每项创新均按“安全问题—机制增量—可执行证据—否决条件”陈述，评审可以沿源码、逐图原始记录和签名包复算。

## 1. 创作者引用绑定的主动溯源与父记录链

### 安全问题

只展示 embed-then-decode 不能证明跨请求溯源：模型可能刚嵌入就读取同一消息，无法回答传播后的图像是否对应一条早已存在的来源记录。

### 机制增量

保护阶段创建唯一 `content_id`，将应用侧 `creator_ref`、模型、checkpoint SHA-256、原始/保护内容 SHA-256、消息 SHA-256、消息派生方式、验证阈值和创作者持钥证明写入 `provenance-record.v2`。正式消息由部署密钥、`content_id` 和模型确定性派生；原图不落库。

核验阶段根据 `content_id` 取回登记消息，只对观测图做 decode。`provenance-verification.v1` 记录 `parent_record_sha256` 和 `parent_record_claim_valid`；最终 `claim_valid` 是“父登记记录有效”与“当前核验事件有效”的合取，而不是数据库中的可编辑布尔值。

### 可执行证据

- 实现：`system/backend/provenance.py`、`system/backend/routes.py`
- 测试：`tests/test_provenance.py`
- 可复核字段：父子 schema、内容摘要、消息摘要、checkpoint 摘要、阈值、父记录摘要、父子 Ed25519 签名

### 否决条件

checkpoint 未登记/未标定、权重清单不在有效签名包中、部署密钥不满足要求、签名者指纹未固定、父记录失效、运行 checkpoint 漂移或消息绑定不一致，任一项成立即 fail-closed。

## 2. LIDMark 的身份隔离数据协议与多任务指标解耦

### 安全问题

人脸图像随机切分会让同一人物同时进入训练与测试，身份泄漏会把记忆能力误写成泛化能力；同时把 landmark 回归与身份消息恢复合成单一“准确率”会掩盖任务语义。

### 机制增量

数据生成器先按人物身份整体分配 train/validation/test，再为每个身份生成无碰撞的固定身份码；同一身份的所有图像共享该码。payload 同时携带 landmark 坐标和身份码，但正式来源判据只由身份 bit accuracy 决定，identity exact match 与 landmark AED 独立报告。

训练、checkpoint 选择和评测形成连续输入审计：评测只读取冻结 test split，验证 identity map 与 split manifest 一致、三组身份零交叉，并在推理前后重新散列源码、训练配置、选择报告、checkpoint、协议、数据和 evaluator。

### 可执行证据

- 数据：`system/scripts/generate_lfw_lidmark.py`
- 训练：`system/scripts/train_lidmark_stage1.py`
- 选择：`system/scripts/select_lidmark_checkpoint.py`
- 评测：`system/scripts/run_lidmark_lfw_benchmark.py`
- 测试：`tests/test_lidmark_stage1_tools.py`、`tests/test_lidmark_benchmark.py`

### 否决条件

身份交叉、非 test identity、payload/code 不一致、checkpoint 未被选择报告绑定、输入前后哈希漂移或把 landmark 指标并入身份成功判据，均阻止完成态证据生成。

## 3. 双解码模型的主判据协议化

### 安全问题

SepMark 与 WaveGuard 都输出两组 decoder 信号。实验后选择更高的一组、取两者最大值或在文档中混称“恢复准确率”，会产生不可复现的指标选择偏差。

### 机制增量

主/辅 decoder 在 runner、run config、逐图行和 summary 四处同时登记：

| 模型 | 登记消息 | 唯一主判据 | 辅助指标 | `success` 来源 |
|---|---|---|---|---|
| SepMark | 图像级确定性消息 | `decoder_C` bit accuracy | `decoder_RF` bit accuracy | 仅由 C 分支与协议阈值比较 |
| WaveGuard | 图像级确定性消息并绑定匿名 identity hash | `tracer` bit accuracy | `detector` bit accuracy | 仅由 tracer 分支与协议阈值比较 |

证据审计器按模型语义定位主 accuracy/error 列，逐行验证二者互补关系、消息稳定性、`primary_decoder` 一致性和 `success` 可重算性，从结构上阻止事后换判据。

### 可执行证据

- SepMark：`system/scripts/run_sepmark_lfw_benchmark.py`、`tests/test_sepmark_benchmark.py`
- WaveGuard：`system/scripts/run_waveguard_lfw_benchmark.py`、`tests/test_waveguard_benchmark.py`
- 独立复核：`system/backend/benchmark_evidence.py`

### 否决条件

checkpoint 或选择证据漂移、主 decoder 字段漂移、消息在攻击间变化、success 与主分支不一致、原始行与 summary 不一致，任一项均使 benchmark gate 失败。

## 4. KAD-Net 的登记消息驱动几何同步与搜索感知标定

### 安全问题

旋转和裁剪会造成几何失配。直接用攻击真值反变换会泄漏 benchmark label；在多个候选中取最大分数又会扩大零假设尾部，沿用单次 decode 阈值会低估 FAR。

### 机制增量

同步器冻结 identity、逆旋转和近似逆中心裁剪候选及顺序，对每个候选独立 decode，仅用预先存在的登记消息计算 bit accuracy；按最大登记消息分数选择，平分时使用声明顺序。接口显式禁止未登记的实验 ground truth 参与候选选择，并输出候选 contract SHA-256、全部候选分数、选择规则和“需要重新标定 FAR”标志。

独立 KAD-Net 消融对 direct 与 sync 分别标定阈值。identity-grouped calibration/holdout 完全隔离；阈值只看 calibration；holdout 仅用于最终 TAR/FAR/FRR 与 Wilson 区间。除 `registered_roundtrip` 外，负对照同时包含 `unwatermarked`、`wrong_message` 和 `cross_record_watermarked`，覆盖多重假设搜索最关键的误接受路径。

### 可执行证据

- 搜索实现：`system/evaluation/synchronization.py`
- 独立消融：`system/scripts/run_kadnet_geometry_sync_ablation.py`
- 测试：`tests/test_synchronization.py`、`tests/test_kadnet_geometry_sync_ablation.py`

### 否决条件

该入口固定输出 `experimental_non_claim_ablation`、`formal_claim_eligible=false` 和 `claim_valid=false`。候选 contract、checkpoint、攻击域或数据域改变后，必须对完整搜索重新标定；单纯的最大分数增量不能进入正式性能主张。

## 5. checkpoint 级阈值标定与原子信任注册

### 安全问题

使用统一经验阈值、在测试集上调阈值或只测正样本，会让“验证成功”缺少可解释的误接受边界；只在配置文件写一个 checkpoint 路径也不能证明运行字节可信。

### 机制增量

`threshold-calibration.v1` 将模型、checkpoint SHA-256、canonical attack、数据清单、identity split、逐控制样本、覆盖审计、阈值选择输入、calibration 指标和 holdout 指标封装为一个可复算 artifact。选择目标固定为在 calibration empirical FAR 约束下最大化 true accept rate，holdout 不参与选择。

注册脚本先验证 checkpoint 与 calibration 的文件位置和 SHA-256，再复算样本 ID、身份归属、消息摘要、完整笛卡尔覆盖、阈值候选、负对照指标和 Wilson 区间；所有语义通过后才原子替换 `WEIGHT_MANIFEST.json`。运行时仍会重新验证该 artifact，而不是信任注册时写入的摘要字段。

### 可执行证据

- 标定：`system/scripts/calibrate_provenance_threshold.py`
- 注册：`scripts/register_calibrated_checkpoint.py`
- 运行时复核：`system/backend/provenance.py`
- 测试：`tests/test_threshold_calibration.py`、`tests/test_checkpoint_registration.py`

### 否决条件

缺少任一控制、split 身份交叉、holdout 参与选择、覆盖不完整、非有限指标、文件哈希不符、checkpoint 字节变化或标定 artifact 未被签名覆盖，均不进入可信权重清单。

## 6. 内容寻址的科研证据包与 Ed25519 信任锚

### 安全问题

只有 summary 无法证明汇总值来自哪组样本、哪份 checkpoint 和哪次运行；仅签 summary 又无法阻止替换原始 CSV、数据清单或运行环境。

### 机制增量

正式 `benchmark-summary.v2` 引用并散列 checkpoint、protocol、dataset manifest、raw results、quality results、run config 和 experiment context。证据审计器重新检查逐图键覆盖、消息与样本绑定、攻击 contract、聚合值、质量 reference 和所有引用哈希；Ed25519 manifest 再把每个证据对象的逻辑路径、大小和 SHA-256 纳入统一签名。

来源登记与核验事件另行签署 canonical JSON。公钥 fingerprint 从嵌入公钥重新计算，并与部署配置中的信任锚比较，不能靠可编辑 fingerprint 字段自证。

### 可执行证据

- benchmark 审计：`system/backend/benchmark_evidence.py`
- 签名与验签：`system/backend/signing.py`、`scripts/sign_evidence_bundle.py`
- 上下文冻结：`scripts/capture_experiment_context.py`
- 测试：`tests/test_evaluation_evidence.py`、`tests/test_signing.py`、`tests/test_provenance.py`

### 否决条件

summary 不完整、原始行不可重算、任一引用文件缺失/变化、签名集合缺少被 summary 引用的对象、验签失败或 signer fingerprint 未固定，均使证据状态回到 review required。

## 7. MEA 多重嵌入冲突的安全评测

### 安全问题

现实传播链中，后续平台或攻击者可以再次嵌入水印。只报告各模型单独嵌入效果，无法发现来源凭证被覆盖、后嵌消息抢占或视觉失真累积。

### 机制增量

MEA 将“来源模型先嵌—攻击模型后嵌—两模型分别解码”固化为有方向的红队协议，同时记录第一消息保留、第二消息恢复、首次嵌入质量、二次结果相对原图质量和二次结果相对第一重水印质量。矩阵中的方向、容量与 decoder 语义保留，不用一个总分掩盖冲突类型。

### 可执行证据

- 核心协议：`system/evaluation/adapters/multi_embedding.py`
- 矩阵入口：`scripts/run_mea_matrix_4x4.py`
- 严格验链：`system/backend/mea_evidence.py`
- 正式五件套：`reports/mea-4x4-protocol-v1-s20260603-n256/{dataset_manifest.json,run_config.json,raw_results.csv,progress.json,summary.json}`
- 测试：`tests/test_multi_embedding.py`、`tests/test_mea_matrix_4x4.py`

### 否决条件

组成模型缺少单嵌真实 checkpoint 证据、消息容量未对齐、主 decoder 语义未登记、缺少逐样本行或只给矩阵平均值时，MEA 结果不进入发布主张。

## 8. 由红队矩阵驱动的可解释模型协同策略

### 安全问题

多模型并列接入并不等于协同。固定选一个模型无法适应不同平台的二次嵌入分布，简单平均分又会掩盖最差场景覆盖和累积视觉损失；若策略与实验 artifact 分离，修改矩阵或参数即可改变推荐而不留证据。

### 机制增量

协同引擎把正式 MEA 有向矩阵转换成带身份相关性控制的约束优化问题。逐图证据中的 256 张 LFW 图像实际只有 217 个身份；引擎先在身份内求均值，再对身份等权，并用固定 seed 的 20,000 次 identity-cluster bootstrap 估计置信下界。单侧 95% Bonferroni 固定族覆盖 4 个候选 × 4 个攻击者 × 6 个指标，共 96 项并包含选择后报告。各模型不同的消息长度、主 decoder 和成功阈值在策略中逐项登记；原始 bit accuracy 仅作诊断，跨模型决策改用以各自协议阈值为中心的归一化 margin 与协议成功率。只有同时满足 margin、成功率、攻击后 PSNR/SSIM 聚类 LCB 硬约束的候选进入三维 Pareto 前沿。

被选模型的每个有向 cell 进一步基于归一化 margin 与协议成功率的聚类 LCB，被解释为 `coexistence`、`source_dominant`、`source_overwritten` 或 `destructive_collision`。输出只提供明确标为 `planned_*` 的部署 policy hint，不把尚未实现的双来源登记或自动双水印描述成现有能力。策略不是静态经验表：每次调用都会证明 policy 自身和 MEA 五件套均处于钉扎 signer 的固定 release membership，使用单描述符读取并在返回前复核文件 identity 与 SHA-256；证据、语义或 TOCTOU 漂移即 fail-closed。响应还暴露身份数、聚类规模、seed、重采样次数、固定选择族、选择稳定率与旧 i.i.d. / 新 cluster 消融，供评审独立复算。

### 可执行证据

- 固定策略：`configs/collaboration_policy.v2.json`
- 决策与验链：`system/backend/collaboration.py`
- 平台接口：`POST /api/collaboration/recommend`
- 测试：`tests/test_collaboration_policy.py`

### 否决条件

policy 或 MEA 五件套未被钉扎签名覆盖、哈希不符、coverage 不完整、身份簇审计不等于 256/217/24/63/10、模型消息/decoder 语义不一致、checkpoint 完整性未验证、输入前后哈希漂移、TOCTOU 变化、重复威胁/候选、类型强制转换、非有限权重，或不存在同时满足归一化 margin/协议成功率/攻击后质量聚类置信下界的候选，均不得输出模型推荐。

## 9. 流程内身份迁移可复算的真实换脸四对照评测

### 安全问题

把局部编辑 proxy 改名为 Deepfake，或只展示若干换脸图片，既不能证明使用了真实模型，也不能证明输出确实从 target 身份迁移到 source，更无法区分登记消息恢复与随机消息误接受。

### 机制增量

独立轨道固定官方 SimSwap commit/tree、官方 generator 与 ArcFace 权重、四个水印 checkpoint 和 LFW n256 身份不重叠 pair。64 个 calibration pair 只选择逐模型 minimax FAR/FRR 阈值，192 个 holdout pair 才报告结果；每条模型结果同时计算登记正例、无水印负例、错误消息负例、同 split 跨记录负例，并用 ArcFace embedding 重算 clean/watermarked swap 的 source-target cosine margin 与迁移标志。严格验证器进一步从 pair manifest 与 raw rows 计算 clean-migrated、clean-and-watermarked-migrated 两个 registered-positive 条件分组。KAD-Net 两组为 160/161、153/154，SepMark 为 151/161、150/159。证据闭包还绑定 1024 条原始结果、1792 条归一化嵌入、176 个视觉资产以及 runner 的全部 project-owned transitive implementation hash。

SimSwap generator 的 source identity conditioning 与上述 cosine migration measurement 使用同一个固定 ArcFace checkpoint，因此该指标只称“流程内身份迁移证据”，不称独立身份验证器。

### 可执行证据

- 协议：`configs/simswap_lfw_robustness.v1.json`
- runner：`system/scripts/run_simswap_lfw_robustness.py`
- 严格验链：`system/backend/simswap_evidence.py`
- 固定八件套：`reports/simswap-lfw-robustness-n256-s20260603/`
- API：`GET /api/benchmark/simswap-lfw`
- 测试：`tests/test_simswap_lfw_robustness.py`、`tests/test_simswap_conditioned_migration.py`

### 否决条件

SimSwap source/权重漂移、身份复用、calibration/holdout 交叉、消息或对照不可重算、ArcFace embedding/hash/cosine 或条件迁移分组不一致、流程内 ArcFace scope 被误标为独立验证器、任一 error/missing row、summary 聚合不一致、implementation 漂移、视觉资产缺失或 release 签名覆盖不完整，均使真实换脸主张 fail-closed。

## 创新证据总表

| 创新层级 | 机器可读事实源 | 独立复核入口 | 发布控制 |
|---|---|---|---|
| 来源事件 | `provenance-record.v2`、`provenance-verification.v1` | `verify_payload_signature` 与父记录重算 | 父子 `claim_valid` 合取 |
| 模型实验 | 逐图 CSV、dataset manifest、run config | `benchmark_claim_status` | `benchmark-summary.v2` 完成门禁 |
| 阈值信任 | `threshold-calibration.v1`、`WEIGHT_MANIFEST.json` | 运行时完整语义复算 | 未标定 checkpoint 不进入正式来源主张 |
| 证据完整性 | Ed25519 manifest、signature、public key | bundle verify 与 signer pinning | 文件 membership 和内容哈希同时成立 |
| 模型协同 | `collaboration-policy.v2`、MEA 逐图 4×4 正式矩阵 | `/api/collaboration/recommend`、identity-cluster bootstrap 与消融复算 | 哈希/身份簇/模型语义/96 项选择族/硬约束任一失败即拒绝推荐 |
| 真实换脸 | official SimSwap/LFW n256 八件套、流程内 ArcFace 嵌入、条件迁移分组与四类对照 | `validate_simswap_lfw_evidence` | identity/coverage/implementation/signature 任一失败即拒绝主张 |
| 对外结论 | [`claims_manifest.v1.json`](../configs/claims_manifest.v1.json) | `/api/claims` | required claim 全部 publishable 才放行 |

实验运行、canonical 目录、上下文冻结和签名顺序统一执行 [国赛实验执行手册](EXPERIMENT_EXECUTION.md)。文档不登记运行中进度、临时哈希或未验收性能值。

## 原创性与成果边界

本仓库可以直接证明的作品增量是：主动溯源父记录链、身份隔离数据协议、主/辅 decoder 语义固化、登记消息驱动同步消融、搜索感知阈值标定、checkpoint 原子信任注册、内容寻址签名证据包、MEA 冲突评测、证据驱动的风险感知模型协同、流程内身份迁移可复算的真实换脸四对照评测和 Claim-as-Code 门禁。

底层 LIDMark、SepMark、WaveGuard、KAD-Net 的算法作者与知识产权必须依据论文、专利、实验室材料、代码提交历史和许可证单独认定；平台集成不自动转化为底层算法原创证明。对外材料中的每一条性能或原创性结论，都必须在 [`claims_manifest.v1.json`](../configs/claims_manifest.v1.json) 中拥有明确状态、证据对象和否决条件，并保持 fail-closed。
