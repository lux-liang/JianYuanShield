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
    ModelOption("LIDMark", "LIDMark", "152bit 关键点溯源 · Deepfake 穿透", ModelAccent.Blue),
    ModelOption("KAD-Net", "KAD-Net", "KAN+SE 非线性 · 全场景 100%", ModelAccent.Green),
    ModelOption("WaveGuard", "WaveGuard", "DTCWT 频域 · 抗平台压缩", ModelAccent.Amber),
    ModelOption("SepMark", "SepMark", "高低频分离 · RF 解码器增强", ModelAccent.Purple),
)

data class AttackOption(
    val id: String,
    val label: String,
    val category: String,
)

/** Canonical attack identifiers accepted by the backend's attack pipeline. */
val ATTACKS: List<AttackOption> = listOf(
    AttackOption("clean", "无攻击 · Clean", "基线"),
    AttackOption("jpeg_50", "JPEG 压缩 Q=50", "压缩"),
    AttackOption("jpeg_70", "JPEG 压缩 Q=70", "压缩"),
    AttackOption("jpeg_90", "JPEG 压缩 Q=90", "压缩"),
    AttackOption("webp_80", "WebP 压缩 Q=80", "压缩"),
    AttackOption("resize", "缩放往返 0.5×", "几何"),
    AttackOption("crop", "中心裁剪 0.8×", "几何"),
    AttackOption("rotate_5", "旋转 5°", "几何"),
    AttackOption("blur", "高斯模糊", "光度"),
    AttackOption("noise", "高斯噪声", "光度"),
    AttackOption("brightness", "亮度扰动", "光度"),
    AttackOption("contrast", "对比度扰动", "光度"),
    AttackOption("platform_wechat_v1", "微信传播仿真", "平台"),
    AttackOption("platform_douyin_v1", "抖音传播仿真", "平台"),
    AttackOption("deepfake_proxy_v1", "Deepfake 换脸代理", "深度伪造"),
)

val DEFAULT_MODEL: ModelOption = MODELS.first()        // LIDMark
val DEFAULT_ATTACK: AttackOption = ATTACKS.first()     // clean
