# 当前限制与安全边界

## 研究证据

- 模型权重、数据与正式逐图结果位于仓库外的受控 runtime roots；`ready_for_claims` 只能由当前 claims manifest、完整 runtime evidence、固定成员签名和 signer fingerprint 动态计算，文档不预设其值。
- `deepfake_proxy_v1` 是局部编辑/传播退化代理；真实换脸证据由独立 official SimSwap/LFW n256 轨道给出，结论范围固定为该 commit、该权重、256 个身份不重叠 pair、四个登记 checkpoint 与 64/192 calibration-holdout 划分。
- official SimSwap 的 source identity conditioning 与迁移测量复用同一个固定 ArcFace checkpoint；161/192 迁移率及其条件恢复分组属于流程内身份迁移证据，不是独立身份验证器或跨识别模型复核。
- 不同模型的 detector、tracer、ID bit、landmark 指标不可直接合并排名。
- 当前历史材料中的多 seed 区间需要按层级结构重算，不能把重复图片池化为独立样本。
- MEA 已固定 `mea-4x4-protocol-v1-s20260603-n256` 五件套及证据驱动协同策略；其结论范围限于登记的四个 checkpoint、有向二次嵌入协议和各模型自身的 decoder/消息容量语义，不能外推为未登记模型或任意传播攻击的通用排序。

## 展示图与正式证据边界

- `docs/PRESENTATION_HEATMAP.md` 描述的 PPT 热力图是从用户提供图逐格重建的展示资产，目的是避免截图放大模糊；它不改变 benchmark 数据、阈值、checkpoint 或签名状态。
- 展示图可以解释趋势，但不能单独放行 `claim_valid`。正式数字仍以当前运行时的 claims、audit、manifest 和逐图 artifact 为准。
- 展示服务不可用时，页面只读展示已签名离线证据；证据不完整、协议未知、输入未登记或签名漂移时，统一显示 `review_required` / `unverifiable`，不沿用旧数字。

## 产品能力

- 来源登记中的 `creator_ref` 是应用侧引用，不代表平台已验证现实身份。
- provenance API 依赖实现 `encode/decode` 合约的真实模型 checkpoint；缺失时返回 503。
- 合规批检尚无校准后的 blind detector，因此返回 `capability_unavailable`，不输出合规率。
- 单图 infer 的 simulation 只验证 UI 流程，`claim_valid=false`。
- Android 和小程序已接入 provenance API，但正式发布仍依赖可信 HTTPS 域名、各平台网络安全配置与真机验收；旧“真假鉴定/AI 生成识别”文案不可用于发布。

## 证据与法律边界

- Ed25519 能证明某密钥对 canonical record 签名并检测内容篡改。
- 当前实现不自动提供可信时间、现实身份认证、外部固定信任锚、证据保全程序或司法采信资格。
- 因而统一称“完整性签名记录”，不扩大解释为法律采信或分布式存证。

## 部署边界

- SQLite 适合单机竞赛原型，不适合多租户生产集群。
- H100 API Key 只在服务端网关注入，Web 入口使用签名 HttpOnly 会话与 CSRF 校验；当前仍是单管理员部署，不等同于多用户 OIDC/RBAC，公开只读接口也不提供对象级权限。
- 公网入口必须通过 HTTPS；生产脚本使用独立、持久化的 UI 口令与会话签名密钥，禁止把口令写入前端或版本库。
- 资产改由受 API Key 保护的 `/api/artifacts/{path}` 提供；单样本衍生工件已有默认 1 小时 TTL 清理，公开部署仍需对象级授权、短期下载令牌和集中生命周期任务。
- 推理超时无法强制终止已在线程中运行的 GPU 内核；长期方案应使用独立 worker 进程和任务队列。
- 正式发布已经强制哈希 lockfile、CycloneDX SBOM、基础镜像 digest 与构建 provenance；仍须执行镜像漏洞扫描并在目标 GPU 环境完成 clean-start 验证。
