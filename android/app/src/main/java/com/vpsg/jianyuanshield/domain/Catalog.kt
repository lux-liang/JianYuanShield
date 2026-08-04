package com.vpsg.jianyuanshield.domain

/**
 * Static catalogs of the watermark models and attack types supported by the
 * backend (see system/backend/model_adapters.py and demo.py).
 */

data class ModelOption(
    val id: String,
    val label: String,
    val description: String,
    val accentName: ModelAccent,
)

enum class ModelAccent { Blue, Green, Amber, Purple }

val MODELS: List<ModelOption> = listOf(
    ModelOption("LIDMark", "LIDMark", "关键点水印 · 模型适配器", ModelAccent.Blue),
    ModelOption("KAD-Net", "KAD-Net", "KAN + SE 结构 · 模型适配器", ModelAccent.Green),
    ModelOption("WaveGuard", "WaveGuard", "DTCWT 频域 · 模型适配器", ModelAccent.Amber),
    ModelOption("SepMark", "SepMark", "高低频分离 · 模型适配器", ModelAccent.Purple),
)

data class AttackOption(
    val id: String,
    val label: String,
    val category: String,
)

/** Canonical attack identifiers accepted by the backend's attack pipeline. */
val ATTACKS: List<AttackOption> = listOf(
    AttackOption("clean", "无攻击 · Clean", "基线"),
    AttackOption("jpeg50", "JPEG 压缩 Q=50", "压缩"),
    AttackOption("jpeg70", "JPEG 压缩 Q=70", "压缩"),
    AttackOption("jpeg90", "JPEG 压缩 Q=90", "压缩"),
    AttackOption("webp50", "WebP 压缩 Q=50", "压缩"),
    AttackOption("resize_0.5x", "缩放往返 0.5×", "几何"),
    AttackOption("crop_center_0.8", "中心裁剪 0.8×", "几何"),
    AttackOption("rotate_5", "旋转 5°", "几何"),
    AttackOption("gaussian_blur_5", "高斯模糊 5×5", "光度"),
    AttackOption("gaussian_noise_sigma_3", "高斯噪声 σ=3", "光度"),
    AttackOption("brightness_0.85", "亮度系数 0.85", "光度"),
    AttackOption("contrast_1.2", "对比度系数 1.2", "光度"),
    AttackOption("platform_wechat_v1", "微信传播仿真", "平台"),
    AttackOption("platform_douyin_v1", "抖音传播仿真", "平台"),
    AttackOption("deepfake_proxy_v1", "局部人脸编辑代理（非真实 Deepfake）", "编辑代理"),
)

val DEFAULT_MODEL: ModelOption = MODELS.first()        // LIDMark
val DEFAULT_ATTACK: AttackOption = ATTACKS.first()     // clean
