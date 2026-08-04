# 构建与运行环境要求

本目录包含 Android 源码、文本配置和可校验的 Gradle Wrapper；Android SDK 与
第三方依赖缓存仍由构建机提供，不进入版本库。

## 开发工具链

| 组件 | 当前要求 |
|:---|:---|
| JDK | 17 |
| Android Studio | Koala 2024.1.1 或更新版本 |
| Android Gradle Plugin | 8.5.2 |
| Gradle | 8.7 |
| Kotlin | 2.0.20 |
| compileSdk / targetSdk | API 35 |
| minSdk | API 26（Android 8.0） |

构建机需要安装 `platforms;android-35` 与 Build Tools 35.0.0，并能访问
`google()` 与 `mavenCentral()`。仓库已固定 Gradle 8.7 Wrapper，直接执行：

```bash
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

## 主要依赖

版本以 `gradle/libs.versions.toml` 为准：

| 类别 | 依赖/版本 |
|:---|:---|
| Compose | Compose BOM 2024.10.01、Material 3 |
| AndroidX | Activity 1.9.2、Navigation 2.8.1、Lifecycle 2.8.6 |
| 网络 | Retrofit 2.11.0、OkHttp 4.12.0 |
| 序列化 | kotlinx.serialization 1.7.1 |
| 协程 | kotlinx.coroutines 1.8.1 |
| 图片 | Coil 2.7.0 |
| 持久化 | DataStore 1.1.1 |
| 视觉 | Haze 1.6.8、Graphics Shapes 1.0.1 |
| 二维码 | ZXing Core 3.5.3 |
| 创作者签名 | Google Tink 1.7.0 + Android Keystore AES-GCM 包装 |

## 运行期后端要求

客户端依赖可达的鉴源盾 FastAPI 后端，但不在端侧执行模型。

| 项目 | 要求 |
|:---|:---|
| debug 默认地址 | `http://10.0.2.2:8026` |
| debug 明文范围 | 仅 Android 模拟器宿主机 `10.0.2.2` |
| release 默认地址 | `https://jianyuanshield.invalid/`（安全失败占位） |
| release 网络 | 正式节点必须使用 HTTPS，禁止全部明文 HTTP |
| 权限 | `INTERNET`、`ACCESS_NETWORK_STATE` |
| API 鉴权 | 生产模式受保护路由要求 `X-API-Key` |
| CORS | 默认仅 localhost/127.0.0.1:8027，不是 `*` |

客户端在“服务器设置”中接受部署方签发的短期 Token，并由 OkHttp 运行时注入
`X-API-Key`。Token 不回显、不进入 URL 或日志、不写入 APK/`BuildConfig`/版本库，
且 DataStore 被排除在云备份与设备迁移之外。生产服务地址必须使用 HTTPS。

## 当前 API 语义要求

- `infer-single.v1` 始终 `claim_valid=false`；真实 checkpoint 执行也只代表
  单样本 embed-attack-decode 评估，不是既有图片来源盲检。
- `model-provenance-status.v1` 只有 `provenance_ready=true` 的模型可进入保护登记；
  `preferred_model` 也必须再次通过该门禁。
- `provenance-record.v2` 必须包含通过一次性挑战建立的创作者持钥证明；
  `creator_identity_verified=true` 不等于自然人实名身份。
- 移动端只把 `registered_blind_verification`、消息匹配、未撤销、checkpoint 一致、
  注册校准、Ed25519 签名字段与 `claim_valid=true` 全部成立的结果展示为可发布技术记录。
- 来源凭证 sidecar 必须通过服务端签名状态与 SHA-256 绑定；撤销必须由登记时同一
  创作者密钥签署一次性意图，成功后客户端要求 `revoked=true` 且 `claim_valid=false`。
- `compliance-batch.v2` 当前
  `capability_available=false`、`assessed=0`，统计字段为 nullable；
  UI 不得将 `null` 显示成 0% 或“无水印”。
- `/api/artifacts/status` 与 `/api/artifacts/{path}` 受鉴权且衍生产物有 TTL。
- 声明可发布性以 `/api/claims`、`/api/evidence/audit` 和签名 artifact 为准。
- 网络错误不得自动回退成模拟成功；本地演示只能由用户显式开启。

## 设备能力说明

相机采集使用系统 `ACTION_IMAGE_CAPTURE` / `TakePicture`，无需应用自行申请
`CAMERA` 运行时权限；相册使用 Android Photo Picker，无需传统存储权限。
