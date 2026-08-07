# 评委高压问答（证据一致版）

## 这是普通 Deepfake 检测吗？

不是。鉴源盾是主动来源核验：发布前嵌入并登记来源凭证，传播后按 `content_id` 执行 decode-only 核验。它不对任意未知图片作“真/假”分类。

## 你们究竟证明了什么来源关系？

保护接口为每份内容生成唯一消息，将其与请求方声明的应用侧 `creator_ref`、内容哈希、模型和 checkpoint 哈希登记。核验接口回答观测内容能否匹配这条预登记记录。`creator_ref` 不等于自然人身份认证，当前共享 API Key 也不建立租户、对象所有权或认证会话；这些关系必须由部署方的 IdP、租户边界和对象授权另行提供。

## 核验时会不会先嵌入再检测，造成自证成功？

不会。正式来源核验只调用 adapter `decode`。旧批量接口曾把 embed-then-decode 误作合规检测，现已 fail-closed 返回 `capability_unavailable`，直到盲检模型完成负样本校准。

## 没有模型权重时系统会怎样？

provenance 正式接口返回 503，不生成来源结论。单图 UI 演示可以运行确定性 simulation，但响应强制 `claim_valid=false`，不得生成正式证书或科研结论。

## MEA 的创新在哪里？

MEA 把后嵌入水印视为对先嵌来源凭证的覆盖攻击，分别测第一消息保留率、第二消息成功率和两阶段视觉损失。矩阵失败本身是红队发现；我们不会把红叉包装成防御成功。

## 不同模型消息长度不同，能直接比较吗？

不能简单比较。正式矩阵登记 LIDMark/KAD-Net/SepMark/WaveGuard 的 16/30/128/30 bit、主 decoder 与协议成功阈值；原始 bit accuracy 只作诊断。部署选择使用以各模型协议阈值为中心的归一化 margin、协议成功率和攻击后质量聚类下界，detector、tracer、ID bit、landmark 指标仍分别报告。

## 为什么 256 张图不能按 256 个独立样本算置信区间？

因为它们只有 217 个身份，24 个身份重复，重复簇涉及 63 张图，最大簇有 10 张。v2 策略先在身份内求均值、再对身份等权，以固定 seed 做 20,000 次 cluster bootstrap；单侧 Bonferroni 固定族覆盖 4 个候选 × 4 个攻击者 × 6 个指标，共 96 项，并把选择后报告纳入同一族。现场响应会显示身份审计、每比较 alpha、选择稳定率和旧 i.i.d. / 新 cluster 消融。

## 目前 Deepfake 实验是真实换脸吗？

是独立的真实换脸评测轨道。正式主张固定使用官方 SimSwap commit `bd7b7686a17f41dd11cfcd5d82f7e4c5eb94b780`、官方 generator/ArcFace 权重和 LFW n256 身份不重叠 pair；64 对只用于阈值 calibration，192 对 holdout 报告 TAR/FAR、Wilson 95% 区间、流程内身份迁移及 PSNR/SSIM。KAD-Net holdout TAR 为 191/192（0.99479167，95% 下界 0.97109250）；unwatermarked、wrong-message、cross-record 三类负控分别都是 0/192，单控制 Wilson 95% FAR 上界均为 0.01961515。pooled 0/576 与上界 0.00662502 只作为相关控制的描述统计，不称为 576 次独立试验。条件分组由 raw rows 复算：KAD-Net 在 clean-migrated 子集为 160/161、clean 与 watermarked 均 migrated 子集为 153/154；SepMark 对应为 151/161 和 150/159。同一 ArcFace checkpoint 同时用于 SimSwap source identity conditioning 和 cosine migration measurement，所以这些是流程内迁移证据，不是独立身份验证器结果。1024 条模型结果、1792 条嵌入、176 个可视化资产与 implementation hash 一并进入 release-core。`deepfake_proxy_v1` 保留为传播管线 smoke，不与该轨道混写。

## README 中的性能数字如何获得发布资格？

主张状态不由 README 文案决定。大体积 checkpoint、数据 manifest、逐图结果、实验上下文和视觉资产位于 runtime evidence roots，release manifest 以 logical path 与 SHA-256 将其闭包绑定到当前代码；`/api/claims` 现场执行逐行复算、精确成员检查和固定签名者验签。official-SimSwap/LFW n256 数字来自已经完成的固定实验闭包，其可发布状态仍由这条机器门禁即时决定。

## Ed25519 签名能否直接证明法律效力？

不等于。它证明指定密钥签过 canonical record，并可检测内容篡改。司法采信还涉及身份、取证程序、可信时间、密钥托管和外部信任锚。我们准确称其为“完整性签名记录”。

## 公钥和签名一起被替换怎么办？

仅靠本机文件无法防止整套替换。正式部署必须把公钥指纹固定到独立客户端、发布页或监管侧，并使用 HSM/密钥服务。系统响应会给出公钥指纹，便于外部固定。

## 如何避免上传图片攻击系统？

服务校验真实格式、MIME、字节数、像素数和批量数量；生产模式要求 API Key；GPU 默认单并发并设超时；checkpoint 只读挂载并用安全加载；容器非 root 且移除 Linux capabilities。

## 统计结果如何保证严谨？

正式结果必须保存逐图记录，按相同指标和相同样本做配对；seed 作为层级处理，不能把同一批图片在多个 seed 下重复计作互相独立的样本。共享同一 pair 的多个负控也不能合并后冒充独立试验：pooled FAR 可以描述，区间推断按每类负控的 192 个 pair 分开报告。阈值只在 calibration split 上用正负样本选择，再在隔离 holdout 报告 TAR、FAR、FRR 与区间。

## 四个模型都是本届学生原创吗？

不能仅凭平台集成作此结论。申报材料会逐模型列出作者、实验室既有成果、本届新增贡献、许可证、提交记录和训练日志。平台层的 provenance、MEA 治理、claims gate 和安全工程可由本仓库审计。

## 当前最强的竞争力是什么？

不是“多个模型满分”，而是把主动来源记录匹配、多水印红队评测和科研声明门禁做成同一个可审计系统。这使作品既能展示算法，也能展示信息安全中的声明主体引用、记录完整性、攻击面和证据边界。
