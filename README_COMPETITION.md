# 鉴源盾内容来源可信取证系统 V1.0：国家级信息安全作品赛评审说明

> 建议评审顺序：[竞赛主叙事](docs/COMPETITION_STORY.md) → [现场演示分镜](docs/DEMO_STORYBOARD.md) → [答辩证据索引](docs/EVIDENCE_INDEX.md) → 本文的完整技术主张地图。

## V1.0 软著与交付基线

- 软件全称：鉴源盾内容来源可信取证系统；版本号：V1.0。
- 全量自动化测试基线：398 项测试，其中 397 项通过、1 项因环境条件跳过；最终交付以发布 commit 归档的测试输出为准。
- 在线演示：[https://jianyuanshield.81.70.178.203.nip.io/jianyuanshield/](https://jianyuanshield.81.70.178.203.nip.io/jianyuanshield/)。边缘层终止 TLS、启用 HSTS 并将明文访问跳转到 HTTPS。
- Web 管理入口采用单管理员服务端 HMAC 签名会话，浏览器只持有 Secure/HttpOnly/SameSite Cookie；CSRF 校验、登录失败限速和后端 API Key 的网关注入均在服务端完成。
- 公网静态资源按不可变版本目录构建并通过原子 `current` 链接切换，旧版本保留用于显式回滚。

## 作品定位

鉴源盾面向人脸图像在生成、发布、编辑和再传播过程中“来源凭证丢失、鲁棒核验失真、多水印相互覆盖、实验结论不可复核”四类问题，将主动水印模型组织为一套可登记、可盲验、可标定、可签名、可追责的来源核验系统。

系统回答的核心问题是：**当前图像能否匹配某条预先存在、由指定模型与 checkpoint 生成的来源登记记录**。它不把单次 embed-then-decode、自报汇总值或页面演示当作正式证据。

```text
登记父记录 → 内容传播/攻击 → 基于 content_id 的 blind decode
           → 标定阈值判定 → 签名核验事件 → Claim-as-Code 发布门禁
```

## 国赛评审主张地图

| 评审维度 | 可审计机制 | 可执行证据 | 正式放行条件 |
|---|---|---|---|
| 主动溯源闭环 | 保护阶段生成唯一 `content_id`，把 `creator_ref`、消息摘要、原图/保护图摘要、模型、checkpoint 和阈值写入登记父记录；核验阶段只解码观测图，不重新嵌入 | `system/backend/provenance.py`、`system/backend/routes.py`、`tests/test_provenance.py` | checkpoint 已登记且字节哈希匹配；阈值标定有效；权重清单与标定 artifact 在签名包内；HMAC 消息密钥、父记录签名、核验事件签名和固定公钥指纹全部有效 |
| LIDMark 身份隔离 | 将 payload 明确拆成 landmark 分量与身份码；同一身份只进入一个数据 split；正式评测只在冻结 test identity 上执行 | `system/scripts/generate_lfw_lidmark.py`、`system/scripts/train_lidmark_stage1.py`、`system/scripts/select_lidmark_checkpoint.py`、`system/scripts/run_lidmark_lfw_benchmark.py` | train/validation/test 身份集合零交叉；checkpoint 选择报告、输入前后哈希审计和逐图身份消息一致；主判据只使用身份 bit accuracy，identity exact match 与 landmark AED 独立报告 |
| SepMark 判据固化 | 图像级确定性消息贯穿所有攻击；`decoder_C` 是唯一主判据，`decoder_RF` 只作为独立辅助指标 | `system/scripts/run_sepmark_lfw_benchmark.py`、`tests/test_sepmark_benchmark.py` | EC checkpoint 与冻结选择证据一致；逐图 `primary_decoder` 固定为 `decoder_C`；`success` 可由 C 分支原始 bit 指标和协议阈值重算 |
| WaveGuard 判据固化 | 图像级确定性消息、匿名 identity hash 与攻击派生 seed 同时入行；`tracer` 是唯一主判据，`detector` 单独报告 | `system/scripts/run_waveguard_lfw_benchmark.py`、`tests/test_waveguard_benchmark.py` | encoder、tracer、detector 严格加载同一冻结 checkpoint；逐图 `primary_decoder` 固定为 `tracer`；identity-aware dataset manifest、原始行、质量行和运行状态全部通过哈希审计 |
| KAD-Net 几何同步 | 对未对齐图像执行固定候选集搜索，以登记记录中的消息选择最大 bit accuracy 候选；禁止使用实验 ground truth 或真实变换参数选择候选 | `system/evaluation/synchronization.py`、`system/scripts/run_kadnet_geometry_sync_ablation.py`、`tests/test_synchronization.py`、`tests/test_kadnet_geometry_sync_ablation.py` | 当前入口固定为 `experimental_non_claim_ablation`；direct 与 sync 分别仅用 calibration split 选阈值，再在 identity-disjoint holdout 上报告；负对照包含 `unwatermarked`、`wrong_message`、`cross_record_watermarked` |
| 阈值标定与模型信任 | 对 `registered_roundtrip`、`unwatermarked`、`wrong_message` 三类控制逐攻击采样；阈值只由 calibration split 在目标 FAR 约束下选择 | `system/scripts/calibrate_provenance_threshold.py`、`scripts/register_calibrated_checkpoint.py`、`tests/test_threshold_calibration.py`、`tests/test_checkpoint_registration.py` | 标定覆盖完整、identity split 不交叉、holdout 未参与阈值选择、Wilson 区间与指标可重算；checkpoint 与标定文件通过 SHA-256 绑定后原子写入 `WEIGHT_MANIFEST.json` |
| 内容寻址证据与签名 | `benchmark-summary.v2` 绑定逐图原始结果、checkpoint、协议、数据清单、运行配置和实验上下文；Ed25519 签名清单固定文件集合、大小与 SHA-256 | `system/backend/benchmark_evidence.py`、`system/backend/signing.py`、`scripts/sign_evidence_bundle.py`、`tests/test_signing.py` | summary 完成、原始行覆盖无缺失/重复/错误、所有引用哈希重算一致、签名覆盖完整、签名者指纹与部署信任锚一致 |
| MEA 多重嵌入红队 | 把“第二个嵌入者覆盖第一个来源凭证”建模为顺序攻击，分别测第一消息保留、第二消息恢复及两阶段视觉质量 | `system/evaluation/adapters/multi_embedding.py`、`scripts/run_mea_matrix_4x4.py`、`tests/test_multi_embedding.py` | 各组成模型先具备单嵌真实 checkpoint 证据；不同容量和 decoder 语义分别解释；矩阵原始样本与单嵌基线共同进入签名证据包 |
| 身份聚类协同策略 | 从 MEA 逐图证据重建 256 图像 / 217 身份结构，以身份等权、20,000 次固定 seed cluster bootstrap 和 96 项同步选择族输出单模型部署建议、稳定率及新旧统计消融 | `configs/collaboration_policy.v2.json`、`system/backend/collaboration.py`、`tests/test_collaboration_policy.py` | 24 个重复身份、63 张重复簇图像、最大簇 10 与证据完全一致；模型消息/decoder 语义固定；只有归一化 margin、协议成功率、PSNR/SSIM 聚类 LCB 全部满足硬约束的 Pareto 候选可被推荐；`planned_*` 只表示建议、不代表动作已执行 |

## 三层证据闭环

### 第一层：来源记录

`POST /api/provenance/protect` 创建 `provenance-record.v2`，并绑定一次性创作者持钥挑战。原始图像参与编码与摘要计算，但不持久化；正式登记消息由 `content_id`、模型和部署密钥确定性派生。数据库同时保存可复算的消息绑定、保护图摘要和 canonical JSON 签名。

`POST /api/provenance/verify` 必须携带已有 `content_id`。核验事件记录观测图摘要、恢复消息摘要、运行 checkpoint 摘要、标定阈值和 `parent_record_sha256`。子事件的 `claim_valid` 只有在父登记记录仍有效且子事件自身通过同一信任链时才成立；篡改数据库字段、父记录、checkpoint、标定文件或签名都会使链路失效。

### 第二层：实验事实

逐图 CSV 是指标重算的事实源，summary 只是由事实源生成的索引。正式 runner 固定以下语义：

- LIDMark：身份 bit accuracy 为主判据；identity exact match、landmark AED、图像质量分别报告。
- SepMark：`decoder_C` 为主判据；`decoder_RF` 不参与成功判定。
- WaveGuard：`tracer` 为主判据；`detector` 不参与成功判定。
- KAD-Net 同步：只报告 direct-vs-sync 消融，并明确 `formal_claim_eligible=false`、`claim_valid=false`。

每个完成态 summary 必须绑定 protocol、seed、attack contract、dataset manifest、checkpoint、raw results、run config 与 experiment context。缺行、重复行、error row、非有限值、绝对宿主机路径、消息漂移、主判据漂移或哈希漂移都会阻止完成态进入发布门禁。

### 第三层：发布主张

[claims manifest](configs/claims_manifest.v1.json) 将每条申报结论绑定到状态、证据路径与机器门禁；`system/backend/claims.py` 重新计算 evidence 是否存在、benchmark gate 是否通过以及 required claim 是否全部可发布。

静态文档审查态：

- `ready_for_claims=false`
- 状态：`review required`

这是静态检查器的刻意 fail-closed 基线：它不读取可变 runtime gate，也不代表当前线上发布状态。现场唯一有效状态必须从 `/api/claims` 动态读取，并与当前 canonical summary、完整实验上下文、签名清单 membership 和固定签名者共同核对；运行日志、smoke、partial、诊断报告和历史同名目录均不能单独改变发布状态。

## 答辩现场复核主线

1. 先展示模型 checkpoint SHA-256、标定 artifact SHA-256、`WEIGHT_MANIFEST.json` 条目和固定公钥指纹，确认演示输入已经进入信任域。
2. 调用 `/api/provenance/protect`，核对 `content_id`、`creator_ref`、消息摘要、保护图摘要、checkpoint 摘要、标定阈值和父记录 Ed25519 签名。
3. 对保护图执行协议登记的传播变换，再调用 `/api/provenance/verify`；现场说明这是对已登记消息的 blind decode，而非重新嵌入后的自检。
4. 核对 `parent_record_sha256`、`parent_record_claim_valid`、观测图摘要、bit accuracy、阈值比较和子事件签名；随后各篡改一个字段，验签与 `claim_valid` 必须同步失败。
5. 从一个逐图原始行重算消息摘要、主 decoder bit accuracy 与 `success`，再由 CSV 重算 summary 聚合，证明“展示值—原始行—汇总”一致。
6. 执行 evidence bundle 验签，确认 summary 引用的 checkpoint、数据清单、原始结果、运行配置和实验上下文均在签名清单中。
7. 打开 `/api/claims`，逐条展示系统能力、协议创新与性能主张的独立门禁结果。

完整命令、canonical 目录和签名验收顺序以 [国赛实验执行手册](docs/EXPERIMENT_EXECUTION.md) 为唯一操作口径。

## 不能表述为既成事实

- 未经当前 `claims_manifest.v1.json` 与签名证据门禁放行的性能数字，不能进入摘要、海报、演示口播或申报书主结论。
- `deepfake_proxy_v1` 不能表述为真实换脸或真实平台回传实验。
- 真实换脸主结论只能引用 `simswap-lfw-robustness-n256-s20260603`：固定官方 SimSwap commit/权重、256 个身份不重叠 LFW pair、64/192 calibration-holdout、逐行四类对照、流程内 ArcFace 迁移及条件恢复分组与 exact implementation hash 均须通过签名门禁。同一 ArcFace checkpoint 同时参与生成与迁移测量，不得称为独立身份验证器。
- SepMark 的 C/RF、WaveGuard 的 tracer/detector、LIDMark 的身份 bit/landmark 指标不能混成一个“准确率”。
- KAD-Net 几何同步不能从“候选最大分数提高”直接表述为正式核验提升；多重假设搜索必须使用完整负对照重新标定 FAR。
- Ed25519 只能证明签名范围内内容与签名者身份锚的一致性，不能表述为可信时间戳、分布式共识或法律采信结论。
- 应用侧 `creator_ref` 是系统主体引用，不能表述为已核验的自然人实名身份。
- 同一图像的多个攻击或 seed 行不能表述为互相独立的受试样本。

## 提交验收

提交包必须形成一条可离线复算的链：

1. 协议与主判据冻结；
2. dataset manifest、checkpoint 选择证据与 SHA-256 冻结；
3. 逐图原始结果覆盖完整，summary 从原始行重算；
4. 源码、依赖、GPU、数据和运行命令写入 experiment context；
5. 当前 canonical artifact 全部进入 Ed25519 manifest 并通过固定公钥验签；
6. 文档检查、系统检查、单元测试和 `/api/claims` 门禁全部通过；
7. 再生成比赛报告，并将最终报告重新纳入签名清单。

任何输入、代码、协议、checkpoint、阈值或报告变化都产生新的证据版本；旧签名保持只读，不覆盖、不拼接。

## 成果归属

底层 LIDMark、SepMark、WaveGuard、KAD-Net 算法的作者和知识产权以论文、专利、实验室材料、提交记录及许可证为准。本届作品可由仓库直接证明的系统增量是：主动来源登记与父记录链、身份隔离数据协议、decoder 主判据固化、搜索感知同步消融、checkpoint 级阈值标定、内容寻址签名证据包、MEA 冲突协议和 Claim-as-Code 发布门禁。正式申报材料必须把底层算法归属与上述系统增量逐项列示。
