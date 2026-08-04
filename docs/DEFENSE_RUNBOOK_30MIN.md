# 国赛 30 分钟答辩与实测 Runbook

本手册固定答辩节奏、展示证据和操作顺序。所有正式数字只从已验签的 `/api/claims`、`/api/benchmark/*` 与原始证据读取；现场不手工改 summary，不使用 demo simulation 生成结论。

## 1. 时间轴与分工

| 时间 | 主讲/操作 | 内容 | 必须落到的证据 |
|---:|---|---|---|
| 00:00–01:00 | A 主讲 | 一句话问题与作品定位 | “匹配预登记来源记录”，不表述为自然人实名认证 |
| 01:00–04:00 | A 主讲 | Deepfake 传播链、传统真假检测的缺口 | protect → 传播 → blind verify → 签名事件 |
| 04:00–07:00 | B 主讲 | 创新一：来源登记与父子证据链 | content ID、消息摘要、checkpoint、标定、父记录哈希 |
| 07:00–10:00 | B 主讲 | 创新二：MEA 二次嵌入冲突治理 | 4096/4096 行、16/16 组合、同时置信下界硬约束 |
| 10:00–13:00 | C 主讲 | 创新三：Claim-as-Code 与发布闭包 | release-core、固定 signer fingerprint、fail-closed |
| 13:00–16:00 | C 主讲 | 真实 SimSwap/LFW n256 | 256 对、64/192、1024 行、1792 嵌入、四类消息对照 |
| 16:00–21:00 | B 操作 | 现场 protect → 攻击 → verify | 只选 `provenance_ready=true` 的模型；展示父子记录与签名 |
| 21:00–23:00 | C 操作 | MEA 策略交互 | 改威胁权重与硬约束，展示可行域、Pareto 与拒绝路径 |
| 23:00–25:00 | C 操作 | SimSwap 证据与篡改检测 | 查看四模型指标；对证据副本改单字节后验签失败 |
| 25:00–27:00 | A 主讲 | 工程完整度 | Android、小程序、Web、生产镜像、SBOM、断网复算 |
| 27:00–30:00 | 全员 | 评委问答 | 按本手册第 7 节由对应负责人回答并打开证据 |

角色固定：A 负责价值与边界，B 负责模型/协议，C 负责系统/证据，D 负责计时和现场命令。主讲人不同时操作终端。

## 2. PPT 固定 14 页

1. 项目名与一句话主张。
2. 场景：发布前登记、传播后盲验，而非事后只判真假。
3. 威胁模型与信任边界。
4. 系统架构与三端入口。
5. 来源记录、消息派生和父子事件链。
6. checkpoint/阈值/签名的信任闭包。
7. MEA 有向二次嵌入协议。
8. 风险策略引擎：同时置信下界、硬约束、Pareto。
9. official SimSwap/LFW n256 协议与身份隔离。
10. Deepfake 结果：KAD-Net 与 SepMark；同时呈现失效模型。
11. Claim-as-Code：源码、原始行、summary、签名、前端同一状态。
12. 现场演示路线图。
13. 工程安全与供应链：非 root、只读挂载、锁定依赖、SBOM、镜像 digest。
14. 贡献边界、局限与下一步。

每页只保留一个结论、一个图和一个可复核路径。性能页同时显示样本量、留出集、估计值和区间；不得只显示百分比。

## 3. T−30 分钟预检

在断网条件下完成，输出保存到本次答辩记录目录：

```bash
docker version
nvidia-smi
export JYS_BUNDLE=/media/readonly/JianYuanShield-competition
export JYS_SIGNER_FINGERPRINT='<登记表中的 64 位 SHA-256>'

bash "$JYS_BUNDLE/deployment/offline_deploy.sh" preflight \
  --bundle "$JYS_BUNDLE" \
  --signer-fingerprint "$JYS_SIGNER_FINGERPRINT"

# /var/tmp/jys-defense-session 必须尚不存在；三个 secret 文件权限均为 0600。
bash "$JYS_BUNDLE/deployment/offline_deploy.sh" restore \
  --bundle "$JYS_BUNDLE" \
  --signer-fingerprint "$JYS_SIGNER_FINGERPRINT" \
  --secret-dir /secure/jys-competition-secrets \
  --state-dir /var/tmp/jys-defense-session
```

然后核对四个门禁：

```bash
curl -fsS http://127.0.0.1:8027/api/health | jq .
curl -fsS http://127.0.0.1:8027/api/claims | jq .
curl -fsS http://127.0.0.1:8027/api/evidence/signature | jq .
curl -fsS http://127.0.0.1:8027/api/models/status | jq .
bash "$JYS_BUNDLE/deployment/offline_deploy.sh" status \
  --state-dir /var/tmp/jys-defense-session
```

必须看到：固定公钥指纹一致；release-core 验签通过；required claims 全部 publishable；KAD-Net `provenance_ready=true`；模型预热完成；剩余磁盘满足写入储备。

## 4. 五分钟现场演示脚本

### 4.1 保护与登记（60 秒）

1. Web 选择显示为 `provenance_ready` 的 KAD-Net。
2. 输入明确标注为“请求方声明主体”的 `creator_ref`，上传预置人脸样本。
3. 点击保护，展示 `content_id`、登记消息摘要、原图/保护图摘要、checkpoint SHA-256、标定阈值、父记录签名与 `claim_valid=true`。
4. 下载保护图，并复制 `content_id`。说明 `content_id` 是登记索引，需要与内容一同交付或由业务系统保存。

### 4.2 传播后盲验（60 秒）

1. 使用预生成的协议攻击版本，不在现场等待批量计算。
2. 输入原 `content_id` 与攻击后图片，调用 decode-only verify。
3. 展示恢复 bit accuracy、阈值比较、父记录哈希、观测图摘要、事件签名和 `claim_valid=true`。
4. 明确核验阶段没有重新嵌入消息。

### 4.3 MEA 冲突治理（60 秒）

1. 打开协同策略面板，先展示 4096/4096、16/16，以及 256 图像 / 217 身份 / 24 重复身份 / 63 张重复簇图像 / 最大簇 10 的审计。
2. 选择均匀威胁与“均衡”配置，展示 20,000 次 identity-cluster bootstrap、固定 96 项选择族、SepMark 为唯一可行候选，以及被选模型 100% 重采样选择稳定率。
3. 对照旧 i.i.d. 原始准确率诊断与新 cluster 归一化策略的消融；强调原始 bit accuracy 因 16/30/128/30 bit 与 decoder 不同而不参与跨模型排名。
4. 切换“安全优先”将 minimum 提高到 0.70，展示系统返回 `constraint_unsatisfied`，而不是给出伪推荐。

### 4.4 真实换脸证据（60 秒）

1. 打开 SimSwap n256 卡片，确认 256/64/192、1024/1024、1792/1792、0 error 和 identity overlap 0。
2. 主结论：KAD-Net holdout TAR 191/192，Wilson 95% 下界 0.97109250；三个相关负控制各自均为 0/192，单控制 Wilson 95% 上界 0.01961515。
3. pooled 0/576 只作为描述性汇总，不把三个相关控制称为 576 次独立试验。
4. 同屏展示 WaveGuard 的高 FAR，说明策略引擎为什么不能“一套模型打所有威胁”。

### 4.5 篡改检测（60 秒）

只操作预先复制到临时目录的证据副本：修改一个 JSON 数字或 CSV 字节，立即运行独立验签。展示 SHA-256 membership/签名验证失败和 claim fail-closed。canonical evidence、签名包和正式数据库不在演示中修改。

## 5. 断网验收路径

答辩包必须包含带 SLSA provenance 与 SPDX SBOM attestation 的 OCI 归档、同构 Docker-loadable 归档、镜像/源码/依赖/SBOM 记录、模型源码、冻结权重、LFW 选择所需数据、正式 reports/assets、release-core 公钥与签名，以及不含长期秘密的部署清单。整个 bundle manifest 再由同一固定 Ed25519 signer 签名；`preflight` 同时复核外部公钥指纹、精确成员、全部 SHA-256、两类镜像归档、release-core 和第三方许可证。API、前端、模型与证据均在本机运行，不依赖 GitHub、CDN、在线字体或第三方推理服务。

断网启动后按顺序验收：外部 signer fingerprint → bundle 签名与精确成员 → OCI attestation → Docker-loadable image ID → 只读模型/数据/reports 挂载 → GPU preflight → health → evidence signature → claims → models/status → 模型预热 → protect/verify。恢复命令只从只读答辩包重建全新的 project-scoped state/assets/audit-anchor 卷，不复用已被修改的状态目录；浏览器只访问 `127.0.0.1:8027`，内置同源 gateway 在服务端注入 API key，8026 不对宿主发布。

录屏只用于证明同一冻结版本的完整操作顺序；现场结论仍由本机可复算证据给出，录屏不替代验签。

## 6. 现场展示纪律

- 不打开私钥、API key、provenance secret、绝对宿主路径或个人数据。
- 不执行训练、不下载依赖、不临时切换 checkpoint、不修改 canonical artifact。
- 不说“证明图片真实”“证明自然人身份”“司法级不可抵赖”。
- 使用“匹配预登记来源记录”“请求方声明主体”“达到冻结阈值”“签名范围内字节完整”。
- 不把 `deepfake_proxy_v1` 称作真实 Deepfake；真实换脸只引用 official SimSwap/LFW n256。
- 不把 C/RF、tracer/detector、landmark/identity 或不同消息容量混成同一个准确率。
- 失败模型和负结果必须保留在表格中，它们是威胁自适应选择的证据。

## 7. 八个必答问题

1. **与真假检测有什么不同？** 回答来源登记匹配与盲验闭环，打开父子记录。
2. **如何证明不是 embed-then-decode 自测？** 指出 verify 只接收观测图和既有 content ID，并展示消息登记先于核验。
3. **为什么相信性能数字？** 从一个原始行重算，再展示 summary、implementation manifest 和 release-core membership。
4. **为什么 FAR 不是 0？** 报告观测值和 Wilson 上界；KAD 按每个相关控制 0/192 给出保守上界。
5. **换脸流程是否产生 source 方向迁移？** 展示流程内 ArcFace clean swap 向 source 迁移的 161/192，以及 KAD-Net 160/161、153/154 和 SepMark 151/161、150/159 的条件恢复；主动说明生成与测量使用同一 ArcFace checkpoint，不是独立身份验证器。
6. **为什么不只用 KAD-Net？** Deepfake 轨道最强不等于所有二次嵌入威胁都最强；展示 MEA 可行域。
7. **签名能证明什么？** 证明固定密钥对签名范围内字节签名及其未被修改；不证明自然人身份、可信时间或内容真实性。
8. **第三方模型是不是你们的创新？** 区分第三方底层算法与本项目的登记链、隔离协议、负控制、协同策略、证据门禁和工程系统。

## 8. 结束验收

答辩结束后保存 health、claims、签名状态、模型状态和现场事件 ID；对临时状态目录做哈希归档。正式证据保持只读，现场产生的来源记录和核验事件单独归档，不并入原正式实验签名。
