# 鉴源盾 Android 客户端

**JianYuanShield · 主动水印来源核验客户端**

本目录是 Kotlin + Jetpack Compose 编写的 Android 客户端。默认入口为公众版
`PubApp`，负责选图、明确上传授权、调用统一 REST API，并按后端声明门禁展示结果。
模型推理不在手机本地执行。

> 当前 `/api/infer/single` 是“新嵌入 → 攻击 → 解码”的单请求评估接口，
> 不是对既有图片的来源盲检；它始终返回 `claim_valid=false`。客户端不得据此生成、
> 保存或分享正式来源/合规凭证。

## 当前能力与边界

| 能力 | 后端接口 | Android 行为 |
|:---|:---|:---|
| 服务探测 | `GET /api/health` | 展示实际连接状态；网络失败不会自动伪装成成功 |
| 来源保护登记 | `POST /api/provenance/protect` | 原始字节上传；只允许 `provenance_ready=true` 模型；展示 `content_id`、checkpoint、签名和声明门禁 |
| 创作者持钥证明 | `POST /api/creator/challenges` | 设备 Ed25519 密钥签署一次性挑战；证明密钥持有，不声明自然人实名身份 |
| 来源凭证 | 保护响应 + `POST /api/provenance/verify` | 导出签名 JSON sidecar；另一设备可导入 sidecar 定位登记记录并核验 |
| 指定记录核验 | `POST /api/provenance/verify` | 图片与 `content_id` 或签名来源凭证同时提交；只把 `registered_blind_verification + claim_valid=true` 展示为可发布技术记录 |
| 签名撤销 | revocation intent + revoke | 获取一次性撤销意图，用登记时同一创作者密钥签名；撤销后强制 `claim_valid=false` |
| 模型来源门禁 | `GET /api/models/status` | 解析 `model-provenance-status.v1` 元数据；优先模型若未 ready 则拒绝并选择首个 ready 模型 |
| 主动水印流程评估 | `POST /api/infer/single` | 展示嵌入、攻击、恢复与画质技术输出，并固定标明不可发布 |
| 显式演示模式 | 本地 `MockData` | 只有用户主动开启才使用；不写入正式历史，不生成凭证 |
| 盲检能力检查 | `POST /api/compliance/batch` | 按 `compliance-batch.v2` 展示“能力不可用”，不显示虚构合规率 |
| 声明与证据 | `GET /api/claims`、`GET /api/evidence/audit` | 可发布性以后端 claims gate 和签名 artifact 为准 |
| 服务设置 | DataStore + 运行时 Host/Auth 拦截器 | 用户注入短期 Token；release 仅 HTTPS；Token 不进 URL、日志、安装包或备份 |

默认公众版底栏“登记核验”已实现
`POST /api/provenance/protect` → `POST /api/provenance/verify` 完整垂直切片。保护响应中的
受保护 PNG 会原样写入应用缓存，随后可直接作为 verify 输入，避免二次 JPEG 压缩破坏
精确文件哈希或水印消息。签名来源凭证可单独导出、跨设备导入；“签名撤销”页执行
一次性意图签名与不可恢复撤销。

创作者 Ed25519 私钥由 Tink 生成，并用 Android Keystore 中不可导出的 AES-GCM 密钥
包装后落盘；私钥不进入 UI、网络、备份或设备迁移。`creator_ref` 仍只是应用侧引用，
`creator_identity_verified=true` 精确表示设备密钥持有证明，不表示自然人实名身份。

## 后端契约

### `infer-single.v1`

`POST /api/infer/single` 即使成功运行真实 checkpoint，也只证明本次单样本
embed-attack-decode 评估执行成功。当前响应语义为：

- `claim_valid=false`：始终不能发布正式来源、合规、科研或司法结论；
- `execution_valid=true` 只表示兼容 checkpoint 确实执行；
- `result_provenance=checkpoint_single_sample_evaluation` 或
  `deterministic_ui_simulation`；
- `compliance.assessment_status=not_assessed`，
  `watermark_detected=null`，`verdict=not_assessed`；
- 原始上传图不持久化；衍生 artifact 按后端
  `JYS_ARTIFACT_TTL_SECONDS` 清理。

Android 目录使用 `evaluation_protocol.v1` canonical attack ID：

`clean`、`jpeg50`、`jpeg70`、`jpeg90`、`webp50`、
`resize_0.5x`、`crop_center_0.8`、`rotate_5`、
`gaussian_blur_5`、`gaussian_noise_sigma_3`、
`brightness_0.85`、`contrast_1.2`、`platform_wechat_v1`、
`platform_douyin_v1`、`deepfake_proxy_v1`。

其中 `deepfake_proxy_v1` 是确定性的局部人脸编辑代理，不是真实 Deepfake
模型或真实平台传播实测。

### `compliance-batch.v2`

当前 `POST /api/compliance/batch` 明确返回：

- `mode=capability_unavailable`；
- `capability=blind_watermark_detection`；
- `capability_available=false`、`claim_valid=false`、`assessed=0`；
- `compliant`、`degraded`、`no_watermark`、`compliance_rate` 均为 `null`；
- 每个文件为 `assessment_unavailable`。

这不表示“没有水印”，也不表示内容合规或不合规。

### 鉴权、artifact 与 CORS

后端路由采用 `X-API-Key` 策略；`JYS_MODE=production` 时强制鉴权。
`/api/infer/single`、`/api/compliance/batch`、`/api/artifacts/status`、
`/api/artifacts/{path}`、models、benchmark 和 evidence 路由均受保护。
`/api/health` 与 `/api/claims` 可用于未鉴权状态探测。

“服务器设置”接受部署方签发的短期 Token；`ApiAuthInterceptor` 在发送时注入
`X-API-Key`，并先移除调用方伪造的同名头。Token 不在界面回显，不进入 URL，HTTP
日志固定隐藏该头，DataStore 目录也从云备份与设备迁移中排除。源码、`BuildConfig`
和版本库均无长期服务密钥。

CORS 不是通配配置。后端默认只允许：

- `http://127.0.0.1:8027`
- `http://localhost:8027`

如 Web 部署域名不同，应显式设置 `JYS_CORS_ORIGINS`。Android 原生 HTTP 客户端
不受浏览器 CORS 限制，但不会绕过 API 鉴权。

## 网络与构建变体

| 变体 | 默认 Base URL | 明文 HTTP |
|:---|:---|:---|
| debug | `http://10.0.2.2:8026` | 仅允许模拟器宿主机 `10.0.2.2` |
| release | `https://jianyuanshield.invalid/` | 全部禁止 |

`.invalid` 是保留的不可用域名，用于在尚未配置正式 HTTPS 服务时 fail closed。
release 必须在 App 中配置已授权的 HTTPS 节点。真机和局域网联调也应使用 HTTPS；
debug 不再放行任意局域网明文 IP。

后端开发启动示例：

```bash
PYTHONPATH=. uvicorn system.backend.app:app --host 0.0.0.0 --port 8026
```

Android 构建：

```bash
# 推荐用 Android Studio 打开 android/ 并 Sync
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

仓库已提交 Gradle 8.7 Wrapper；Android SDK 与依赖缓存由构建机提供，首次构建需
可访问 `google()` 与 `mavenCentral()`。

## 代码结构

```text
app/src/main/java/com/vpsg/jianyuanshield/
├── MainActivity.kt                 # 默认承载 PubApp
├── core/                           # URL、格式化、错误映射
├── data/
│   ├── remote/                     # Retrofit、OkHttp、DTO
│   ├── repository/                 # multipart 与数据入口
│   ├── settings/                   # DataStore 设置
│   └── history/                    # 本地历史
├── domain/Catalog.kt               # 模型与 canonical attack 目录
└── ui/
    ├── pub/                        # 默认公众版流程（含 provenance 完整闭环）
    ├── screens/                    # 保留的专家/旧版功能页
    ├── components/
    └── theme/
```

发布任何性能、合规或来源声明前，应以 `/api/claims`、
`/api/evidence/audit` 和对应签名 artifact 的实时状态为唯一依据。
