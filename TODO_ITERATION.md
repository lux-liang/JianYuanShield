# JianYuanShield Iteration Backlog

更新时间：2026-06-06  
工作目录：`/home/luxliang/JianYuanShield`  
状态标记：`[x]` 已完成，`[~]` 进行中，`[ ]` 未开始，`[!]` 阻塞/需外部资源。

## 基线保护

- [x] **BASE-01 建立当前可演示基线**
  - 目标：确保后续迭代始终以可回退、可验证状态推进。
  - 涉及文件：`.deployed_commit`、`.code_backup_*`、`tests/test_backend.py`、`scripts/check_system.py`。
  - 具体修改点：记录部署提交；保存代码备份；确认数据、权重、报告和资产符号链接。
  - 验证方式：`python3 -m unittest discover -s tests -v`；`python3 scripts/check_system.py --strict`。
  - 预期产物：12 项测试通过；`ready_for_demo: yes`；可回退备份。

## P0 必须修

- [x] **P0-01 建立四模型统一评测协议注册表**
  - 目标：让 LIDMark、HiDDeN/SepMark（MEA）、WaveGuard、KAD-Net 使用同一套可机器读取的预处理、攻击和指标契约。
  - 涉及文件：新增 `system/evaluation/protocol.py`、`system/evaluation/__init__.py`、`configs/evaluation_protocol.v1.json`、`docs/EVALUATION_PROTOCOL.md`；修改 benchmark 脚本。
  - 具体修改点：定义 RGB/YUV 颜色空间、resize/crop 策略、值域、插值方式、随机种子、攻击参数、画质参考对象和成功阈值；为模型声明必要适配项。
  - 验证方式：协议 JSON schema 自检；单元测试检查四模型均有注册项、攻击 ID 唯一、阈值合法。
  - 预期产物：`evaluation_protocol.v1`；四模型协议差异表；benchmark 可引用统一配置。

- [x] **P0-02 统一 PSNR / SSIM / BER / ACC / success rate 定义**
  - 目标：消除历史报告中同名指标参考对象不同的问题。
  - 涉及文件：新增 `system/evaluation/metrics.py`；修改 `normalization.py`、三个全量 benchmark 脚本、聚合脚本和 API 文档。
  - 具体修改点：明确 `quality_watermarked_vs_original` 与 `quality_attacked_vs_original`；BER 必须由原始消息和解码消息计算；ACC=`1-BER`；success threshold 从协议读取；保留 legacy 字段但标注语义。
  - 验证方式：构造已知数组测试 PSNR/SSIM；构造 bit vector 测 BER/ACC；检查 normalized 输出含 `metric_semantics`。
  - 预期产物：统一指标库、兼容旧结果的 schema v2、指标定义文档。
  - 完成说明：已提供统一指标库和 normalized 语义字段；历史 CSV 保留 legacy 语义，公平重跑归入后续任务。

- [x] **P0-03 对现有全量结果生成统计与一致性审计报告**
  - 目标：不重跑 23 万余行结果，先从 CSV 自动计算均值、标准差、95% CI、分位数、成功率置信区间和异常分布。
  - 涉及文件：新增 `system/scripts/audit_benchmark_results.py`；输出 `system/reports/protocol_audit/`；修改证据审计 API。
  - 具体修改点：流式读取 CSV；按模型/攻击/指标汇总；检查 `BER+ACC≈1`、行数、重复键、NaN、常数列和 PSNR/SSIM 语义风险。
  - 验证方式：运行脚本；审计报告覆盖 HiDDeN、SepMark、WaveGuard、LIDMark；错误时非零退出。
  - 预期产物：`audit.json`、`audit.md`、`statistics.csv`。
  - 完成说明：审计覆盖 240,242 行；无重复键、无 BER/ACC 配对错误；输出均值、标准差、95% CI 和分位数。

- [x] **P0-04 排查 HiDDeN 接近随机**
  - 目标：区分模型真实跨域失效与 checkpoint/消息编码/预处理集成错误。
  - 涉及文件：新增 `system/scripts/diagnose_hidden.py`；修改 HiDDeN benchmark；输出 `system/reports/diagnostics/hidden/`。
  - 具体修改点：记录 checkpoint/options 哈希；检查 state dict 覆盖；比较 round/threshold 解码；固定图像固定消息重复测试；测试官方 noiser 路径和当前外部攻击路径；输出前 100 张逐 bit 偏置。
  - 验证方式：CPU 完成静态和 checkpoint 检查；GPU 可用时运行 16/100 图诊断；结论必须标记 `integration_issue`、`domain_shift` 或 `inconclusive`。
  - 预期产物：诊断 JSON/Markdown、加载覆盖率、消息分布图、可答辩结论边界。
  - 完成说明：16 图 GPU 诊断中 round/0.5 阈值最高 54.79%，0 阈值 47.92%，错误消息负控 45.21%；排除简单判决阈值错误，结论为域偏移或训练协议/checkpoint 不匹配。

- [x] **P0-05 排查 WaveGuard 指标饱和**
  - 目标：确认接近 100% 的 detector ACC 是否来自真实鲁棒性、任务定义差异或数据泄漏。
  - 涉及文件：新增 `system/scripts/diagnose_waveguard.py`；修改 WaveGuard benchmark；输出 `system/reports/diagnostics/waveguard/`。
  - 具体修改点：严格核对 encoder/decoder_t/decoder_d state dict；检查空子字典和 missing keys；做消息置乱、跨图消息、全零/随机输入负控；分别报告 tracer 与 detector。
  - 验证方式：静态 checkpoint 审计必须无空前缀；GPU 运行负控后，错误消息准确率应接近随机。
  - 预期产物：严格加载报告、负控结果、饱和指标解释。
  - 完成说明：encoder/decoder_t/decoder_d 严格加载无缺失；正确消息 ACC=100%，错误消息约 46.67%，无嵌入 detector 约 46.25%，未发现明显消息泄漏。

- [x] **P0-06 修复 benchmark 路径硬编码与可追踪运行元数据**
  - 目标：新代码目录与 `/data1` 资产目录解耦，任意部署路径均可运行。
  - 涉及文件：所有 `system/scripts/run_*.py`、`.env.example`、`system/backend/config.py`。
  - 具体修改点：统一读取 `JYS_PROJECT_ROOT`、`JYS_ASSET_ROOT`、`JYS_MODEL_SOURCE_ROOT`；报告写入命令、Git/部署提交、Python/Torch/CUDA、seed、协议版本和 checkpoint SHA-256。
  - 验证方式：扫描源码不再出现 `/home/luxliang/work/vpsg_competition_candidates`；临时目录配置测试。
  - 预期产物：可迁移 benchmark 脚本和完整 run metadata。
  - 完成说明：7 个 Python benchmark 脚本和 tmux 管线已改为 `JYS_*` 根目录；正式汇总写入协议/checkpoint 哈希、seed、命令、Python/Torch/CUDA/GPU 与部署提交。

- [x] **P0-07 将证据审计升级为发布门禁**
  - 目标：`ready_for_demo` 与“结果可信度”分层，避免资产齐全被误解为研究结论已验证。
  - 涉及文件：`system/backend/evidence.py`、`artifacts.py`、`scripts/check_system.py`、前端审计区域。
  - 具体修改点：新增 `ready_for_demo`、`ready_for_claims`、`blocking_findings`；支持 `--strict-claims`；把协议、统计和诊断报告纳入审计。
  - 验证方式：当前演示仍为 ready；未解决 HiDDeN/WaveGuard 告警时 claims 状态必须为 review。
  - 预期产物：两级发布状态和机器可读门禁报告。
  - 完成说明：API、前端和系统检查均区分 `ready_for_demo`/`ready_for_claims`；`--strict-claims` 可用于自动化发布门禁，当前研究结论按真实未决问题保持 review。

- [x] **P0-08 保持兼容并扩充回归测试**
  - 目标：所有 P0 修改不破坏现有 12 项测试、API 和前端。
  - 涉及文件：`tests/test_backend.py`、新增 `tests/test_protocol.py`、`tests/test_metrics.py`、`tests/test_audit.py`。
  - 具体修改点：覆盖协议注册、指标计算、审计统计、下载接口、任务哈希和错误输入。
  - 验证方式：`compileall`、unittest、Node syntax、临时 uvicorn HTTP smoke、严格系统检查。
  - 预期产物：不少于 25 项自动测试；`ready_for_demo: yes`。
  - 完成说明：服务器 Python 环境 25 项 unittest 全部通过，compileall/Node 语法通过，严格演示检查退出码 0；`ready_for_demo=yes` 且 `ready_for_claims=no` 符合真实证据状态。

## P1 重要增强

- [~] **P1-01 实现跨模型二次嵌入攻击矩阵**
  - 目标：形成 LIDMark、HiDDeN、SepMark、WaveGuard、KAD-Net 的 source→attacker 全矩阵。
  - 涉及文件：新增 `system/evaluation/adapters/`、`system/scripts/run_multi_embedding_matrix.py`。
  - 具体修改点：统一 encode/decode adapter；记录第一次和第二次消息；测试同模型重复嵌入与跨模型覆盖。
  - 验证方式：先跑每组合 16 图 smoke，再跑 512/全量；每格输出原消息保留率、攻击消息成功率和图像质量。
  - 预期产物：矩阵 CSV/JSON、热力图、失败案例。
  - 当前进展：已实现统一 encode/decode adapter 合约、双消息保留/覆盖评测语义和 5×5 机器可读矩阵计划；真实模型 adapter 尚未从各自 benchmark 脚本中拆出，因此所有格子保持 blocked，未生成伪性能。

- [~] **P1-02 扩展传播与编辑攻击库**
  - 目标：加入 crop、rotate、blur、brightness、contrast、WebP、平台转码和 Deepfake 编辑。
  - 涉及文件：新增 `system/evaluation/attacks.py`、平台转码配置、Deepfake adapter。
  - 具体修改点：攻击参数分级；固定 seed 但每图派生不同随机流；保存攻击配置哈希。
  - 验证方式：攻击尺寸/范围测试；视觉样例；每类至少 100 图 smoke。
  - 预期产物：攻击库 v1、攻击样例网格、benchmark 报告。
  - 当前进展：已实现 crop、rotate、blur、brightness、contrast、WebP、两类平台转码代理及显式标注的 Deepfake 局部编辑代理；待真实 Deepfake 模型接入与模型级 100 图 smoke 后完成。

- [~] **P1-03 多 seed、置信区间和显著性分析**
  - 目标：给模型排序提供统计依据。
  - 涉及文件：统计模块、benchmark CLI、聚合脚本。
  - 具体修改点：至少 3 个 seed；Bootstrap CI；配对检验；效应量；多重比较校正。
  - 验证方式：同数据同攻击配对；报告 CI 和 p-value；排序不只依赖均值。
  - 预期产物：统计报告、显著性矩阵、可答辩图表。
  - 当前进展：已实现 Bootstrap CI、配对差值 CI、配对符号翻转检验、配对效应量和 Holm 校正，并可对三模型历史逐图结果生成统计报告；历史结果仅 1 seed，至少 3 seed 重跑仍未完成。

- [!] **P1-04 训练 LIDMark 正式 checkpoint**
  - 目标：替换 smoke checkpoint，建立正式训练、验证、测试闭环。
  - 涉及文件：LIDMark 配置、训练脚本、数据 manifest、训练日志接入。
  - 具体修改点：确认数据授权和划分；固定配置；断点训练；最佳模型选择；独立测试集。
  - 验证方式：训练曲线、验证集早停、独立 LFW/CelebA-HQ 测试、checkpoint SHA-256。
  - 预期产物：正式 checkpoint、模型卡、训练报告、消融结果。
  - 阻塞说明：官方 watermark 59,990 文件已存在，但配套 CelebA-HQ 图像为 0，无法形成合法训练 pair；二阶段 SimSwap/UniFace/CSCS/StarGAN/InfoSwap 资产也不完整。已新增三 seed 正式训练配置与 readiness gate，数据补齐前拒绝把 LFW 或 smoke 训练包装成正式 checkpoint。

- [!] **P1-05 接入 KAD-Net 四模型统一对照**
  - 目标：KAD-Net 完成 adapter、checkpoint、smoke 和统一 benchmark。
  - 涉及文件：KAD-Net 环境、adapter、benchmark API、前端。
  - 具体修改点：解决旧 Torch/CUDA 依赖；加载权重；映射统一指标；增加 API 卡片。
  - 验证方式：16 图 smoke、512 图 benchmark、加载覆盖率、与三模型同协议输出。
  - 预期产物：KAD-Net 报告和四模型对照表。
  - 阻塞说明：源码已核查，但 `/data1/luxliang` 未找到任何 KAD-Net checkpoint；原测试脚本硬编码旧 `/root/autodl-tmp` 路径，声明环境为 Python 3.8/Torch 1.11/CUDA 11.3。已新增集成审计，取得团队 checkpoint 并完成兼容环境严格加载前不得进入排名。

- [x] **P1-06 数字签名和报告防篡改验证**
  - 目标：从文件哈希升级到可验证签名证据包。
  - 涉及文件：新增 `system/backend/signing.py`、签名 CLI、验证 API 和前端。
  - 具体修改点：canonical JSON；Ed25519 签名；公钥指纹；manifest 覆盖输入、输出、模型和协议。
  - 验证方式：正常报告验证成功；篡改一个字节验证失败；私钥不进入仓库。
  - 预期产物：`.sig`、evidence manifest、验证页面和 CLI。
  - 完成说明：服务器仓库外私钥已生成并以 `0600` 管理；当前 manifest 覆盖 19 个证据/模型文件，Ed25519 验证成功且篡改测试会返回 `content_mismatch`。

- [~] **P1-07 完善前端证据链与审计报告**
  - 目标：让评委看到任务时间线、协议、模型哈希、指标语义和验证状态。
  - 涉及文件：`index.html`、`app.js`、`styles.css`、后端 API。
  - 具体修改点：任务详情抽屉；证据文件下载；审计 finding 分级；统计 CI；签名验证按钮。
  - 验证方式：桌面和移动端；离线演示；错误状态；API 断线降级。
  - 预期产物：完整证据链 UI。
  - 当前进展：已展示双层发布门禁、finding 分级、诊断结论、签名状态和 manifest/签名/公钥下载；任务详情抽屉、CI 图表和移动端专项验收待完成。

- [x] **P1-08 同步答辩材料与自动报告**
  - 目标：文档只引用自动生成的当前状态，杜绝 pending/complete 漂移。
  - 涉及文件：`README_COMPETITION.md`、`docs/*`、报告生成器。
  - 具体修改点：报告嵌入协议版本、审计状态、统计结论和边界；增加文档状态检查脚本。
  - 验证方式：扫描过期关键词；报告与 API 数值一致。
  - 预期产物：答辩稿、评委问答、限制说明、自动报告。
  - 完成说明：自动报告、竞赛 README、3 分钟答辩稿、评委问答、限制和 14 天计划已同步协议、claims gate、诊断、统计、攻击 smoke、签名及真实阻断；新增文档/API 状态一致性检查脚本。

## P2 加分项

- [ ] **P2-01 跨数据集与视频评测**
  - 目标：覆盖 CelebA-HQ、FFHQ、FaceForensics++、Celeb-DF 和视频转码。
  - 涉及文件：数据 manifest、loader、视频攻击 pipeline。
  - 验证方式：跨域表格、身份分组、视频帧一致性。
  - 预期产物：跨域 benchmark 报告。

- [ ] **P2-02 一键离线部署与环境锁定**
  - 目标：无 GitHub 环境下可复现系统。
  - 涉及文件：Dockerfile、compose、Conda lock、资产验证脚本。
  - 验证方式：新目录离线启动；资产哈希一致；GPU/CPU 两种模式。
  - 预期产物：离线发布包和部署文档。

- [ ] **P2-03 CI、代码质量和安全加固**
  - 目标：持续验证 API、前端、报告与依赖安全。
  - 涉及文件：CI 配置、lint/type/security 配置。
  - 验证方式：ruff/mypy/测试/依赖扫描；CORS 和下载路径安全测试。
  - 预期产物：质量门禁和安全报告。

- [ ] **P2-04 性能、并发和任务队列**
  - 目标：支持异步模型任务、进度查询、取消和资源隔离。
  - 涉及文件：任务服务、队列、GPU 调度、前端进度条。
  - 验证方式：并发压测、任务恢复、GPU OOM 保护。
  - 预期产物：任务中心和性能报告。

- [ ] **P2-05 成果固化与竞赛材料**
  - 目标：形成论文式技术报告、软著/专利材料、查新对照和离线视频。
  - 涉及文件：`paper/`、`competition/`、模型卡与数据卡。
  - 验证方式：材料中的每个数字可追溯到报告和签名证据。
  - 预期产物：完整国家级答辩包。

## 每轮强制验证

1. `python3 -m compileall -q system scripts tests`
2. `python3 -m unittest discover -s tests -v`
3. `python3 scripts/check_system.py --strict`
4. `node --check system/frontend/app.js`（服务器有 Node 时）
5. 临时启动后端，验证 `/api/health`、`/api/artifacts/status`、`/api/evidence/audit`
6. 更新本文件状态、验证记录与风险说明

## 当前风险

- 历史 CSV 已完成但指标语义不完全统一，不能无条件用于最终公平排名。
- HiDDeN 和 WaveGuard 异常结论在完成负控实验前只能标记为待复核。
- LIDMark 正式训练、KAD-Net 接入、Deepfake 模型依赖和全量重跑需要 GPU 时间与数据/权重确认。
- 报告签名私钥必须由项目负责人线下管理，不能写入仓库。
