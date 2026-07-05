<div align="center">

# 🛡️ 鉴源盾 · Android 客户端

**JianYuanShield · Deepfake 溯源与取证移动端**

基于 Kotlin + Jetpack Compose + Material 3，调用鉴源盾统一 REST API

[![Kotlin](https://img.shields.io/badge/Kotlin-2.0-7F52FF?style=flat-square&logo=kotlin&logoColor=white)](https://kotlinlang.org)
[![Compose](https://img.shields.io/badge/Jetpack_Compose-Material_3-4285F4?style=flat-square&logo=jetpackcompose&logoColor=white)](https://developer.android.com/jetpack/compose)
[![minSdk](https://img.shields.io/badge/minSdk-26-3DDC84?style=flat-square&logo=android&logoColor=white)](https://developer.android.com)
[![API](https://img.shields.io/badge/统一REST_API-FastAPI后端-009688?style=flat-square)](../JianyuanShield)

</div>

---

## 一、项目定位

鉴源盾 Android 客户端是「鉴源盾五端覆盖（Web / **Android** / iOS / 微信小程序 / 鸿蒙）」中的移动端实现。
它**不内置模型推理**，而是把图片上传到鉴源盾 FastAPI 后端，由后端的四模型水印平台
（LIDMark / KAD-Net / WaveGuard / SepMark）完成水印嵌入、攻击仿真、溯源解码与证据链签名，
客户端负责**采集、上传、可视化与取证展示**。

UI 风格借鉴国家级公共安全 / 反诈类政务应用的视觉语言——**安全蓝主色、盾牌标识、宫格导航、卡片化信息层级**，
并按 Figma / Canva 的设计规范打磨：渐变 Hero、语义化状态色、统一圆角与留白，做到「简单不简约」。

> ⚠️ 本仓库只包含**源代码 + 文档**，不含 Gradle Wrapper 二进制（`gradle-wrapper.jar`）与第三方依赖包。
> 首次构建请用 Android Studio 打开，或在已联网环境执行 `gradle wrapper` 生成 wrapper，再 `./gradlew assembleDebug`。

---

## 二、功能总览

| 模块 | 入口 | 对应后端 API | 说明 |
|:---|:---|:---|:---|
| 🏠 **首页** | `首页` Tab | `/api/health`、`/api/models/status`、`/api/modules` | 后端状态、四模型加载状态、平台能力宫格 |
| 🔍 **溯源取证** | `溯源` Tab | `POST /api/infer/single` | 选图 → 选模型/攻击 → 嵌入水印、攻击仿真、取证指标、SHA-256 证据 |
| ✅ **合规检测** | `合规` Tab | `POST /api/compliance/batch` | 多图批量验证隐式水印，输出合规率与逐项结果 |
| ⚖️ **证据链** | `证据` Tab | `GET /api/evidence/audit` | Ed25519 签名状态、评测完整性、协议与审计发现 |
| 📊 **基准评测** | 首页 → 基准评测 | `GET /api/benchmark/{model}` | LIDMark / KAD-Net / WaveGuard / SepMark 的 LFW 全量基准 |
| ⚙️ **我的** | `我的` Tab | `GET /api/health` | 配置后端地址、测试连通性、关于信息 |

---

## 三、技术栈

| 层 | 选型 | 说明 |
|:---|:---|:---|
| UI | **Jetpack Compose + Material 3** | 声明式 UI，自定义品牌色与语义状态色 |
| 架构 | **MVVM + 单向数据流** | `ViewModel` + `StateFlow` + `UiState<T>` 状态机 |
| 导航 | **Navigation-Compose** | 底部导航 5 Tab + 基准评测二级页 |
| 网络 | **Retrofit + OkHttp** | `multipart/form-data` 上传图片 |
| 序列化 | **kotlinx.serialization** | `ignoreUnknownKeys` 容错，开放字段用 `JsonObject` |
| 图片 | **Coil** | 加载后端 `/artifacts/**` 产物图 |
| 持久化 | **DataStore Preferences** | 保存后端 Base URL |
| 依赖注入 | **手写 AppContainer** | 轻量、零反射，避免引入 Hilt |

---

## 四、目录结构

```
app/src/main/java/com/vpsg/jianyuanshield/
├── JianYuanShieldApp.kt          # Application，持有 AppContainer
├── MainActivity.kt               # 单 Activity，承载 Compose
├── core/                         # 容器、错误映射、URL/指标格式化、相机工具
│   ├── AppContainer.kt
│   ├── ErrorMapper.kt            # 异常 → 友好中文文案
│   ├── MetricFormat.kt           # JsonObject 指标 → 展示行
│   ├── UrlUtils.kt / CaptureUtils.kt / ViewModelExt.kt
├── data/
│   ├── UiState.kt                # Idle / Loading / Success / Error
│   ├── remote/
│   │   ├── ApiService.kt         # Retrofit 接口
│   │   ├── NetworkModule.kt      # OkHttp + Retrofit + Json 工厂
│   │   ├── HostSelectionInterceptor.kt  # 运行时切换 Base URL
│   │   └── dto/ApiModels.kt      # 与后端契约一一对应的数据类
│   ├── repository/ShieldRepository.kt   # 唯一数据入口（含 multipart 组装）
│   └── settings/SettingsRepository.kt   # DataStore
├── domain/Catalog.kt             # 模型 / 攻击类型静态目录
└── ui/
    ├── theme/                    # Color / Type / Theme（品牌安全蓝）
    ├── navigation/               # 路由 + 底部导航 + NavHost
    ├── components/               # Hero、宫格、卡片、状态、指标、选择器等可复用组件
    └── screens/                  # home / infer / compliance / evidence / benchmark / settings
```

每个 `screens/<feature>/` 下为 `XxxScreen.kt`（UI）+ `XxxViewModel.kt`（状态与业务）。

---

## 五、运行步骤

### 1. 启动后端

参见上层仓库 `../JianyuanShield`：

```bash
JYS_INFER_DEVICE=cuda:0 PYTHONPATH=. \
  uvicorn system.backend.app:app --host 0.0.0.0 --port 8026
```

后端 CORS 已放开（`allow_origins=["*"]`），可直接被移动端访问。

### 2. 配置 Base URL

| 运行环境 | 推荐 Base URL |
|:---|:---|
| Android 模拟器（访问宿主机） | `http://10.0.2.2:8026`（默认值） |
| 真机（与后端同局域网） | `http://<后端电脑IP>:8026` |

默认值通过 `app/build.gradle.kts` 的 `DEFAULT_API_BASE` 注入到 `BuildConfig`，
也可在 App 内「我的 → 后端服务地址」运行时修改并测试连通性。

### 3. 构建运行

```bash
# 推荐：Android Studio (Koala+) 直接打开本目录，Sync 后点 Run

# 命令行（需先有 gradle-wrapper.jar 或本机 gradle）：
gradle wrapper          # 仅首次：生成 wrapper（联网）
./gradlew assembleDebug # 产出 app/build/outputs/apk/debug/app-debug.apk
./gradlew installDebug  # 安装到已连接设备
```

> 关于明文 HTTP：后端默认走 HTTP，已在 `res/xml/network_security_config.xml` 放开 cleartext，
> 仅用于本地 / 局域网联调；生产环境请改用 HTTPS 并收紧该配置。

---

## 六、与后端的数据契约

客户端 DTO（`data/remote/dto/ApiModels.kt`）严格对齐后端 `docs/API_CONTRACT.md`：

- `POST /api/infer/single` → `infer-single.v1`：`metrics`（开放字典，用 `JsonObject`）、`artifacts`（相对 URL）、`evidence.sha256`、`compliance.verdict`
- `POST /api/compliance/batch` → `compliance-batch.v1`：`compliant / degraded / no_watermark / compliance_rate / results[]`
- `GET /api/evidence/audit` → `evidence-audit.v1`：`signature.verified`、`benchmark_complete`、`protocol`、`findings[]`
- `GET /api/benchmark/{model}` → 单模型基准，优先取 `normalized.attacks[]`（WaveGuard 会从 `full_benchmark` 兜底）
- 错误统一为 `{ ok:false, error:{ code, message, path } }`，由 `core/ErrorMapper.kt` 转为中文提示

模型标识：`LIDMark` / `KAD-Net` / `WaveGuard` / `SepMark`；攻击标识见 `domain/Catalog.kt`
（`clean`、`jpeg_50/70/90`、`webp_80`、`resize`、`crop`、`rotate_5`、`blur`、`noise`、`brightness`、`contrast`、
`platform_wechat_v1`、`platform_douyin_v1`、`deepfake_proxy_v1`）。

---

## 七、设计说明（UI）

- **品牌色**：安全蓝 `#1457B8`（主色）+ 渐变 Hero `#0B4DA2 → #2E86E0`，语义色 成功绿 / 警示琥珀 / 危险红。
- **信息层级**：Hero（品牌 + 后端状态）→ 宫格核心功能 → 状态卡 → 结果卡，圆角 18–20dp、卡片轻投影。
- **状态反馈**：每个请求都有 Loading / Error（带重试）/ Empty / Success 四态，错误文案本地化。
- **取证可视化**：原图 / 含水印 / 攻击后 / 热力图 / 残差五图对比 + 指标卡 + SHA-256 证据。
- **深色模式**：随系统切换，品牌蓝在暗色下自动调亮。

---

## 八、与其他端的关系

```
        ┌──────────── 统一 REST API (FastAPI :8026) ────────────┐
   Web │  Android(本仓库)  │   iOS   │  微信小程序  │   鸿蒙        │
        └──────────────────────── 四模型水印平台 ────────────────┘
                   LIDMark · KAD-Net · WaveGuard · SepMark
```

五端共用同一后端契约，本客户端为 Android 端参考实现。

---

<div align="center">

🛡️ **鉴源盾 Android** · 新疆大学 VPSG 实验室 · 《人工智能生成合成内容标识办法》技术落地

</div>
