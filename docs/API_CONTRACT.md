# JianYuanShield API 语义契约

本文描述当前后端的安全边界和稳定语义。字段级定义以运行实例的 `/openapi.json` 为准；任何接口可用不代表相应科研或合规结论已经通过发布门禁。

## 基础约定

- 默认地址：`http://127.0.0.1:8026`。
- 上传接口使用 `multipart/form-data`。
- 生产模式默认要求请求头 `X-API-Key`；密钥不得出现在 URL、仓库或日志中。
- 正式 Web 使用同源 `/api` 网关：网关完成用户会话与对象授权后向回环 API 注入 `X-API-Key`，并移除浏览器伪造的同名头；前端不得保存长期服务密钥或直连 8026。
- `content_id` 是本系统登记记录的标识，不是自然人身份凭证。
- 模型缺失、checkpoint 不兼容或能力未实现时必须 fail-closed，不得用 simulation 代替正式结论。
- simulation 响应必须包含 `claim_valid=false` 和清晰 warning。

## 统一错误响应

受控异常使用非 2xx HTTP 状态码，并返回：

```json
{
  "ok": false,
  "error": {
    "code": "http_error",
    "message": "request cannot be completed",
    "path": "/api/example"
  }
}
```

常见状态：

| HTTP | 语义 |
|---:|---|
| 401 | API Key 缺失或不正确 |
| 404 | 登记记录、报告或文件不存在 |
| 413 | 上传或批量数量超过配置上限 |
| 415 | 文件声明类型或实际格式不支持 |
| 422 | 参数、标识符、图片像素或消息结构无效 |
| 503 | 真实模型、checkpoint 或所需能力不可用 |
| 504 | 推理超过配置超时 |

内部堆栈、宿主机绝对路径和原始异常对象不属于公开契约。

## 来源凭证接口

### 保护与登记

```http
POST /api/provenance/protect
X-API-Key: <secret>
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | JPEG、PNG 或 WebP 图片 |
| `creator_ref` | 是 | 长度受限的应用侧主体引用 |
| `model` | 否 | 已注册且具备真实 checkpoint 的模型名 |

成功响应的稳定语义：

```json
{
  "schema_version": "provenance-record.v1",
  "content_id": "<32-char-hex-id>",
  "creator_ref": "creator-reference",
  "model": "model-name",
  "original_sha256": "<sha256>",
  "protected_sha256": "<sha256>",
  "checkpoint_sha256": "<sha256-or-null>",
  "checkpoint_registered": false,
  "checkpoint_calibrated": false,
  "verification_threshold": 0.0,
  "weight_manifest_sha256": "<sha256-or-null>",
  "message_length": 0,
  "message_sha256": "<sha256>",
  "protocol": "evaluation_protocol.v1",
  "evidence_signature": {
    "signed": false,
    "status": "not_configured"
  },
  "claim_valid": false,
  "evidence_status": "operational_unverified",
  "protected_image": {
    "url": "/api/artifacts/provenance/<content-id>/protected.png",
    "png_base64": "<base64>"
  },
  "privacy": {
    "original_persisted": false,
    "creator_ref_persisted": true
  }
}
```

`claim_valid=true` 要求真实 adapter 执行、checkpoint SHA-256 已在部署方 `WEIGHT_MANIFEST.json` 中审核通过、模型专属阈值通过身份隔离 calibration/holdout 与三类对照逐样本校准、签名 evidence bundle 完整覆盖当前 weight manifest/checkpoint/calibration、来源消息由至少 32 字符的服务端密钥派生、事件 Ed25519 签名可验证，并且由 `JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT` 独立固定的公钥指纹与签名公钥一致。缺少任一条件时，操作可以完成，但必须返回 `operational_unverified`；生产模式缺少来源密钥时直接 503。该字段仍不是性能或法律效力结论。

### Decode-only 核验

```http
POST /api/provenance/verify
X-API-Key: <secret>
Content-Type: multipart/form-data
```

表单字段：`file`、`content_id`。

稳定响应字段包括：

```text
schema_version
event_id
content_id
creator_ref
model
observed_sha256
exact_protected_file_match
bit_accuracy
success_threshold
verification_threshold
verified
checkpoint_sha256
runtime_checkpoint_sha256
checkpoint_registered
checkpoint_calibrated
parent_record_claim_valid
parent_record_sha256
evidence_signature
claim_valid
decoder
```

`verified=true` 表示恢复消息与指定登记记录匹配且达到版本化协议阈值；`claim_valid` 另行表示 checkpoint 清单、事件签名验签和固定公钥指纹是否同时放行。它不表示图片未被编辑，也不表示图片是真实拍摄或具有当然的法律效力。

### 查询登记记录

```http
GET /api/provenance/records/{content_id}
X-API-Key: <secret>
```

响应不返回服务端保存的原始消息比特。公开部署需要在现有 API Key 之外增加对象级授权。

受保护图片通过需要 API Key 的资产接口读取：

```http
GET /api/artifacts/{path}
X-API-Key: <secret>
```

签名下载接口除当前 bundle 的 `manifest`、`signature`、`public-key` 外，还提供
`core-manifest`、`core-signature`、`core-public-key`。后三项是 final 发布必须纳入的
独立 `release-core` 验签链，final 签名不会覆盖它们。

`path` 必须经过路径白名单与目录边界校验；旧的匿名静态资产路径不属于当前安全契约。

## 演示与合规接口

### 单样本模型演示

```http
POST /api/infer/single
```

表单字段：`file`、`model`、`attack`、`return_b64`。`attack` 推荐使用协议中的 canonical ID：`clean`、`jpeg50/70/90`、`webp50`、`resize_0.5x`、`crop_center_0.8`、`rotate_5`、`gaussian_blur_5`、`gaussian_noise_sigma_3`、`brightness_0.85`、`contrast_1.2`、`platform_wechat_v1`、`platform_douyin_v1`、`deepfake_proxy_v1`；旧的 `resize/noise/blur` 仅作兼容。

该接口只执行嵌入—攻击—恢复的单样本能力演示，不是对任意上传图片进行盲检，当前契约固定返回 `claim_valid=false`。研究性能只能由满足 checkpoint、数据清单、逐图结果、协议版本和签名门禁的独立 benchmark artifact 发布。

### 批量合规能力状态

```http
POST /api/compliance/batch
```

当前 adapter 不提供经过正负样本校准的 blind detector，因此接口返回：

```json
{
  "schema_version": "compliance-batch.v2",
  "mode": "capability_unavailable",
  "claim_valid": false,
  "capability": "blind_watermark_detection",
  "capability_available": false,
  "assessed": 0,
  "compliance_rate": null
}
```

调用方不得把该响应解释为“未检测到水印”或“内容不合规”。

### 证据驱动的多模型协同决策

```http
POST /api/collaboration/recommend
X-API-Key: <secret>
Content-Type: application/json
```

请求给出可能发生二次嵌入的模型及暴露权重、候选来源模型、风险厌恶系数、视觉质量权重和最差场景“协议阈值归一化 margin”聚类置信下界。暴露权重由服务端归一化，重复威胁模型、重复候选、未知字段、布尔/字符串数值、非有限数或越界参数均返回 422；请求不得把该下界降到签名策略的 0.45 以下。

```json
{
  "threats": [
    {"model": "LIDMark", "exposure": 1.0},
    {"model": "KAD-Net", "exposure": 1.0},
    {"model": "SepMark", "exposure": 1.0},
    {"model": "WaveGuard", "exposure": 1.0}
  ],
  "risk_aversion": 0.6,
  "fidelity_weight": 0.2,
  "minimum_worst_case_protocol_normalized_margin": 0.45
}
```

`collaboration-recommendation.v2` 从逐图 CSV 重建 LFW 身份簇：256 张图像对应 217 个身份，其中 24 个身份重复、共覆盖 63 张图像、最大簇为 10。每个 cell 先在身份内求图像均值，再对 217 个身份等权；随后以 `numpy PCG64`、seed `20260603` 做 20,000 次确定性身份簇 bootstrap。单侧 95% Bonferroni 固定族同时覆盖 `4 candidates × 4 attackers × 6 metrics = 96` 个比较，包含来源/攻击者的协议归一化 margin 与成功率、攻击后 PSNR/SSIM，因而覆盖候选选择与选择后报告。各模型 16/30/128/30 bit、主 decoder 和 0.9 成功阈值均由签名策略逐项登记；原始 bit accuracy 只作诊断，不参与跨模型排名。

硬约束要求：最差来源协议归一化 margin 聚类 LCB 不低于请求值、最差来源协议成功率聚类 LCB 不低于 0.5、最差攻击后 PSNR/SSIM 聚类 LCB 分别不低于 20 dB/0.6。只有满足全部硬约束的候选进入三维 Pareto 前沿。响应返回完整统计方法、seed、重采样次数、固定族、身份审计、选择稳定率，以及旧 i.i.d. 原始准确率规则与新 identity-cluster 规则的消融。每个有向 cell 的动作字段只是 `planned_*` policy hint；接口不声称已执行双来源登记或自动双水印。不存在可行候选时返回 `constraint_unsatisfied`。

该接口只读取 [`collaboration_policy.v2.json`](../configs/collaboration_policy.v2.json) 钉扎的正式 MEA 五件套。每次决策前重新验证 policy 自身与五件套均被固定 signer fingerprint 的 `release-core`/`release` 清单覆盖，复核 4096/4096 行、16/16 cell、逐图键、消息长度、主 decoder、协议阈值、checkpoint 和输入前后审计。policy、summary、progress、原始 CSV、数据清单、运行配置及签名清单均使用单文件描述符读取并在决策结束前复核 identity 与 SHA-256，跨读取发生变化即按 TOCTOU 攻击返回 503。

### 旧演示任务

```text
GET  /api/samples
GET  /api/samples/{sample_id}/image
POST /api/tasks/demo-run
GET  /api/reports/{task_id}
GET  /api/real-evals
```

这些接口用于界面演示或读取既有报告。任务完成状态不等于真实模型模式；客户端必须同时检查 `mode`、`claim_valid`、warning 和 evidence 状态。

## 声明与证据接口

### Claim-as-Code

```http
GET /api/claims
```

关键字段：

```text
schema_version
manifest_schema_version
manifest_sha256
ready_for_claims
status
policy
summary
claims[]
```

每条 claim 同时返回 evidence 的存在性和 SHA-256。只有发布状态在允许集合内且所列 evidence 完整时，该 claim 才是 `publishable=true`。所有要求提交的 claim 都可发布时，运行时才可能把 `ready_for_claims` 设为 true；文档不得硬编码该状态。

### Evidence audit 与签名包

```text
GET /api/evidence/audit
GET /api/evidence/signature
GET /api/evidence/signature/download/{manifest|signature|public-key}
```

Ed25519 响应证明指定密钥签过 canonical 内容并可检测内容变化。可信时间、现实身份、外部公钥信任锚和法律程序不在该接口的保证范围内。

## 状态与历史结果接口

```text
GET /api/health
GET /api/projects
GET /api/artifacts/status
GET /api/models/status
GET /api/modules
GET /api/benchmark/hidden-lfw-full
GET /api/benchmark/lidmark-lfw-eval
GET /api/benchmark/sepmark
GET /api/benchmark/waveguard
GET /api/benchmark/mea-matrix
GET /api/benchmark/simswap-lfw
POST /api/collaboration/recommend
GET /api/benchmark/kadnet
GET /api/benchmark/aggregate
GET /api/competition-report
GET /api/competition-report/download/{json|csv|markdown}
```

benchmark 和 competition-report 路由保留用于兼容历史 UI。其 `complete`、文件存在或行数只说明 artifact 结构状态；是否可对外引用必须以 `/api/claims` 和 `/api/evidence/audit` 为准。

`GET /api/benchmark/mea-matrix` 只读取固定 run
`mea-4x4-protocol-v1-s20260603-n256`。响应的 `claim_valid=true` 要求 5 件套精确成员、
`mea-matrix-summary.v1`、16/16 cell 与 4096/4096 row 覆盖、逐行消息和指标复算、
checkpoint/协议/实现/输入的前后审计及钉扎 Ed25519 签名覆盖全部同时通过。

`GET /api/benchmark/simswap-lfw` 只读取固定 run
`simswap-lfw-robustness-n256-s20260603`。响应的 `claim_valid=true` 要求 256/256 身份不重叠 pair、1024/1024 四模型结果、1792/1792 ArcFace 嵌入、0 error、64/192 calibration-holdout 隔离、四类消息对照逐行复算、精确 implementation manifest、八件套与 176 个可视化资产、官方 SimSwap/ArcFace 和四水印 checkpoint 全部被钉扎 Ed25519 release 签名覆盖。

严格验证结果通过 `evidence_validation.model_results.<model>.registered_positive_conditioned_on_identity_migration` 暴露两个由 holdout raw rows 与 pair manifest 重算的分组：`clean_swap_migrated` 和 `clean_and_watermarked_swap_migrated`；每组包含 `successes`、`total`、`estimate` 与 Wilson 95% 区间。`evidence_validation.identity_migration_evidence_scope` 固定声明：同一个 ArcFace checkpoint 同时用于 SimSwap source identity conditioning 与 cosine migration measurement，`independent_identity_verifier=false`。`/api/claims` 的 Deepfake gate 以 `observed_registered_positive_conditioned_on_identity_migration` 和 `observed_identity_migration_evidence_scope` 返回同一精确闭包；字段漂移会使 `claim_valid=false`。

## 客户端必须遵守的状态规则

1. `simulation`：持续显示不可移除的“模拟数据”标识，禁用正式证书与结论导出。
2. `review_required` / `blocked`：可以展示研究过程和阻断原因，不展示为已验证性能。
3. `publishable`：仍需展示模型、checkpoint、数据、样本量、指标和 evidence 链接。
4. 网络错误不得自动替换为模拟成功结果。
5. `0`、`false` 和 `null` 语义不同，客户端不得用 truthy 回退把合法零值当成缺失。

## 兼容性规则

- 已发布的 schema version 内不删除或重命名稳定字段；新增字段应保持向后兼容。
- 语义变化必须提升 schema version。
- 模型特有指标放入开放字典，不强行改名成统一“准确率”。
- API Key、数据库、图片与签名密钥的生命周期由部署方管理，不通过此契约默认承诺。
