# 构建与运行环境要求 · REQUIREMENTS

本文件列出鉴源盾 Android 客户端的开发/构建环境与依赖清单。
**本仓库仅含源码与文档，不含任何已下载的依赖包或 SDK**；以下版本是“目标兼容版本”，实际下载在构建机联网时由 Gradle 完成。

---

## 一、开发工具链

| 组件 | 版本 / 要求 | 说明 |
|:---|:---|:---|
| JDK | **17**（LTS） | AGP 8.5 要求 JDK 17；`sourceCompatibility = 17` |
| Android Studio | **Koala 2024.1.1** 或更新 | 内置 AGP 8.5 支持；可一键 Sync/Run |
| Android Gradle Plugin (AGP) | **8.5.2** | 见 `gradle/libs.versions.toml` |
| Gradle | **8.7** | 见 `gradle/wrapper/gradle-wrapper.properties` |
| Kotlin | **2.0.20** | 含 Compose Compiler Gradle 插件（K2） |
| Android SDK Platform | **API 34**（compileSdk / targetSdk） | 需安装 `platforms;android-34` |
| Min SDK | **API 26**（Android 8.0） | 覆盖绝大多数在网设备，支持自适应图标 |
| Build Tools | 34.0.0（随 AGP 自动选择） | — |

> 命令行构建前提：构建机需能访问 `google()` 与 `mavenCentral()`，并已安装上述 SDK Platform。
> Wrapper 二进制（`gradle-wrapper.jar`）未随仓库提供，请用 Android Studio 打开，或执行 `gradle wrapper` 生成后再 `./gradlew` 构建。

---

## 二、Gradle 依赖清单

所有依赖通过版本目录 `gradle/libs.versions.toml` 统一管理。核心依赖如下：

### Jetpack Compose / AndroidX
| 依赖 | 版本 | 用途 |
|:---|:---|:---|
| `androidx.compose:compose-bom` | 2024.09.02 | Compose 物料清单（统一各 compose 库版本） |
| `androidx.compose.material3:material3` | （由 BOM 提供，1.3.x） | Material 3 组件 |
| `androidx.compose.material:material-icons-extended` | （BOM） | 图标集（Shield / Fingerprint 等） |
| `androidx.activity:activity-compose` | 1.9.2 | `setContent`、PhotoPicker、TakePicture |
| `androidx.navigation:navigation-compose` | 2.8.1 | 导航 |
| `androidx.lifecycle:lifecycle-viewmodel-compose` | 2.8.6 | `viewModel()` |
| `androidx.lifecycle:lifecycle-runtime-compose` | 2.8.6 | `collectAsStateWithLifecycle` |
| `androidx.core:core-ktx` | 1.13.1 | KTX、`FileProvider`、`WindowCompat` |

### 网络与序列化
| 依赖 | 版本 | 用途 |
|:---|:---|:---|
| `com.squareup.retrofit2:retrofit` | 2.11.0 | REST 客户端 |
| `com.jakewharton.retrofit:retrofit2-kotlinx-serialization-converter` | 1.0.0 | kotlinx 转换器 |
| `com.squareup.okhttp3:okhttp` | 4.12.0 | HTTP 引擎、multipart |
| `com.squareup.okhttp3:logging-interceptor` | 4.12.0 | Debug 日志 |
| `org.jetbrains.kotlinx:kotlinx-serialization-json` | 1.7.1 | JSON 解析（含 `JsonObject`） |
| `org.jetbrains.kotlinx:kotlinx-coroutines-android` | 1.8.1 | 协程 |

### 图片与持久化
| 依赖 | 版本 | 用途 |
|:---|:---|:---|
| `io.coil-kt:coil-compose` | 2.7.0 | 加载远程/本地图片 |
| `androidx.datastore:datastore-preferences` | 1.1.1 | 保存后端 Base URL |

### 视觉增强（曜石·极光设计语言）
| 依赖 | 版本 | 用途 |
|:---|:---|:---|
| `dev.chrisbanes.haze:haze` | 1.6.8 | 悬浮 Dock 真实背景模糊（玻璃拟态） |
| `dev.chrisbanes.haze:haze-materials` | 1.6.8 | iOS 风格磨砂材质预设（ultraThin 等） |
| `androidx.graphics:graphics-shapes` | 1.0.1 | M3 Expressive 形状变形（首页盾牌光环） |

> 可选增强（放入文件即生效，无需改代码）：品牌字体——将思源黑体/Noto Sans SC 四个字重
> 放入 `app/src/main/assets/fonts/`，文件名 `brand_regular.otf / brand_medium.otf /
> brand_bold.otf / brand_black.otf`，缺失时自动回退系统字体。

### Gradle 插件
| 插件 | 版本 |
|:---|:---|
| `com.android.application` | 8.5.2 |
| `org.jetbrains.kotlin.android` | 2.0.20 |
| `org.jetbrains.kotlin.plugin.compose` | 2.0.20 |
| `org.jetbrains.kotlin.plugin.serialization` | 2.0.20 |

### 测试（可选）
| 依赖 | 版本 |
|:---|:---|
| `junit:junit` | 4.13.2 |
| `androidx.test.ext:junit` | 1.2.1 |
| `androidx.test.espresso:espresso-core` | 3.6.1 |
| `androidx.compose.ui:ui-test-junit4` | （BOM） |

---

## 三、运行期依赖（后端）

| 依赖 | 要求 |
|:---|:---|
| 鉴源盾 FastAPI 后端 | 运行于可达地址（默认 `http://10.0.2.2:8026`），见 `../JianyuanShield` |
| 网络权限 | `INTERNET`、`ACCESS_NETWORK_STATE`（已在 `AndroidManifest.xml` 声明） |
| 明文 HTTP | 已通过 `network_security_config.xml` 放开（仅联调用，生产请用 HTTPS） |

> 相机采集走 `ACTION_IMAGE_CAPTURE`（`TakePicture`），由系统相机应用完成，**无需 `CAMERA` 运行时权限**；
> 相册选择使用 Android Photo Picker，同样无需存储权限。

---

## 四、最小构建命令

```bash
# 1) 生成 Gradle Wrapper（首次，需联网）
gradle wrapper --gradle-version 8.7

# 2) 编译 Debug APK
./gradlew assembleDebug

# 3) 安装到设备/模拟器
./gradlew installDebug
```

产物：`app/build/outputs/apk/debug/app-debug.apk`
