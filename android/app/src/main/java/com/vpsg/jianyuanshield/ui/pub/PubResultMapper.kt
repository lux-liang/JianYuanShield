package com.vpsg.jianyuanshield.ui.pub

import com.vpsg.jianyuanshield.core.absoluteArtifactUrl
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/**
 * 把后端 [InferResult] 映射为公众版结果视图 [PubResultUi]。
 *
 * 后端 `/api/infer/single` 做的是"主动取证水印":给图嵌入水印 → 施加攻击 → 尝试恢复,
 * 据此得到 bit 准确率 / 鲁棒性 / 图像质量(PSNR/SSIM)/ 合规判定。这里如实呈现这些真实
 * 字段,不编造"AI 生成 / 换脸"等后端未计算的结论。结论颜色:
 * 绿(通过核验)/ 琥珀(水印降级)/ 红(无法确认)。
 */

private fun JsonObject.numOrNull(key: String): Double? =
    (this[key] as? JsonPrimitive)?.doubleOrNull

private fun JsonObject.boolOrNull(key: String): Boolean? =
    (this[key] as? JsonPrimitive)?.booleanOrNull

private fun pct(v: Double?): Int = ((v ?: 0.0).coerceIn(0.0, 1.0) * 100).roundToInt()

private fun fmtTime(epochSeconds: Long?): String {
    val millis = (epochSeconds ?: 0L) * 1000L
    if (millis <= 0L) return "—"
    return SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date(millis))
}

fun InferResult.toPubResultUi(
    baseUrl: String,
    fileName: String,
    localUri: String?,
    offline: Boolean,
): PubResultUi {
    val m = metrics
    val bitAcc = m.numOrNull("bit_accuracy")
        ?: m.numOrNull("bit_accuracy_c")
        ?: m.numOrNull("bit_accuracy_detector")
    val srcAcc = m.numOrNull("source_id_acc")
    val conf = m.numOrNull("confidence") ?: bitAcc ?: srcAcc ?: 0.0
    val psnr = m.numOrNull("psnr")
    val ssim = m.numOrNull("ssim")
    val elapsedMs = m.numOrNull("elapsed_ms")
    val success = (m.boolOrNull("success") ?: compliance.watermarkDetected)
    val verdictStr = compliance.verdict   // compliant / degraded / null
    val isClean = attack.isNullOrBlank() || attack == "clean"

    // ── 结论 ───────────────────────────────────────────────────────────────────
    val verdict: VerdictKind
    val palette: HeroPalette
    val title: String
    val badge: String
    val desc: String
    val headlineLabel: String
    val headlinePercent: Int
    when {
        verdictStr == "compliant" || (success && verdictStr != "degraded") -> {
            verdict = VerdictKind.Real
            palette = Pub.heroGreen
            title = "通过来源核验"
            badge = "可放心"
            headlineLabel = "可信度"
            headlinePercent = pct(conf)
            desc = if (isClean)
                "成功恢复出可信的来源水印,这张图片来源可追溯、未见异常。"
            else
                "在「${attackLabel(attack)}」处理后仍能恢复来源水印,鲁棒性良好、来源可追溯。"
        }
        verdictStr == "degraded" -> {
            verdict = VerdictKind.Ai
            palette = Pub.heroAmber
            title = "水印已降级"
            badge = "需留意"
            headlineLabel = "水印完整度"
            headlinePercent = pct(conf)
            desc = "检测到来源水印的残留,但已明显降级,图片可能经过压缩或二次处理。"
        }
        else -> {
            verdict = VerdictKind.Tampered
            palette = Pub.heroRed
            title = "未能确认来源"
            badge = "无法确认"
            headlineLabel = "水印完整度"
            headlinePercent = pct(conf)
            desc = "未能从这张图片恢复出可信的来源水印,无法确认它的来源,转发请谨慎。"
        }
    }

    // ── 工件图 ───────────────────────────────────────────────────────────────────
    fun art(key: String): String? = artifacts[key]?.let { absoluteArtifactUrl(baseUrl, it) }
    val previewUrl = art("original") ?: localUri
    val heatmapUrl = art("heatmap") ?: art("diff")
    val annotation = if (heatmapUrl != null) "已生成水印残差热力图,高亮区域为差异最大处" else null

    // ── 分项(结果页 2×2)──────────────────────────────────────────────────────────
    val itemWatermark = PubResultItem(
        icon = PubIcons.shieldCheck,
        tone = if (success) PubTone.Ok else PubTone.Mut,
        label = "溯源水印",
        value = if (success) "已检出" else "未检出",
        sub = bitAcc?.let { "bit 准确率 ${pct(it)}%" } ?: "来源标记核验",
    )
    val itemRobust = PubResultItem(
        icon = PubIcons.bolt,
        tone = when {
            isClean -> PubTone.Mut
            success -> PubTone.Ok
            else -> PubTone.Warn
        },
        label = "抗攻击鲁棒性",
        value = if (isClean) "未施加" else if (success) "通过" else "未通过",
        sub = if (isClean) "基线 · 无攻击" else attackLabel(attack),
    )
    val itemQuality = PubResultItem(
        icon = PubIcons.image,
        tone = if ((psnr ?: 0.0) >= 35.0) PubTone.Ok else PubTone.Mut,
        label = "图像质量",
        value = psnr?.let { "${oneDecimal(it)} dB" } ?: "—",
        sub = ssim?.let { "SSIM ${twoDecimal(it)}" } ?: "PSNR / SSIM",
    )
    val itemCompliance = PubResultItem(
        icon = PubIcons.verified,
        tone = if (verdictStr == "compliant") PubTone.Ok else PubTone.Mut,
        label = "合规标识",
        value = when (verdictStr) {
            "compliant" -> "合规"
            "degraded" -> "降级"
            else -> "待确认"
        },
        sub = "《AI 标识办法》",
    )
    val items = listOf(itemWatermark, itemRobust, itemQuality, itemCompliance)

    // ── 报告块 ───────────────────────────────────────────────────────────────────
    val blocks = buildList {
        add(
            PubAnalysisBlock(
                icon = PubIcons.shieldCheck,
                tone = if (success) PubTone.Ok else PubTone.Warn,
                label = "溯源水印强度",
                chip = if (success) "清晰" else "微弱",
                barFraction = (bitAcc ?: conf).toFloat().coerceIn(0f, 1f),
                barNumber = "${pct(bitAcc ?: conf)}%",
                whyLabel = "我们看到了这些",
                bullets = buildList {
                    add("从图片里恢复水印比特的准确率为 ${pct(bitAcc ?: conf)}%,越高说明来源标记越完整。")
                    srcAcc?.let { add("身份溯源准确率 ${pct(it)}%,可定位到原始来源身份。") }
                    add(if (success) "判定为成功恢复来源水印。" else "未达到成功阈值,水印可能已被破坏。")
                },
            ),
        )
        add(
            PubAnalysisBlock(
                icon = PubIcons.bolt,
                tone = when {
                    isClean -> PubTone.Mut
                    success -> PubTone.Ok
                    else -> PubTone.Warn
                },
                label = "抗攻击鲁棒性",
                chip = if (isClean) "基线" else if (success) "通过" else "未通过",
                barFraction = if (isClean) 0f else if (success) 0.92f else 0.3f,
                barNumber = if (isClean) "—" else if (success) "强" else "弱",
                whyLabel = "这一项怎么测",
                bullets = if (isClean)
                    listOf("本次未施加攻击(Clean 基线),仅做原始嵌入与恢复。")
                else
                    listOf(
                        "模拟了「${attackLabel(attack)}」对图片的破坏。",
                        if (success) "破坏后仍能恢复出来源水印,说明抗攻击能力良好。"
                        else "破坏后水印恢复失败,说明该攻击对水印影响较大。",
                    ),
            ),
        )
        add(
            PubAnalysisBlock(
                icon = PubIcons.image,
                tone = if ((psnr ?: 0.0) >= 35.0) PubTone.Ok else PubTone.Mut,
                label = "图像质量",
                chip = psnr?.let { "${oneDecimal(it)} dB" } ?: "—",
                barFraction = ((psnr ?: 0.0) / 50.0).toFloat().coerceIn(0f, 1f),
                barNumber = ssim?.let { twoDecimal(it) } ?: "—",
                whyLabel = "这说明什么",
                bullets = buildList {
                    psnr?.let { add("PSNR ${oneDecimal(it)} dB,数值越高说明嵌入水印后画质损失越小。") }
                    ssim?.let { add("SSIM ${twoDecimal(it)},接近 1 表示与原图几乎一致。") }
                    if (psnr == null && ssim == null) add("本次未返回画质指标。")
                },
            ),
        )
        add(
            PubAnalysisBlock(
                icon = PubIcons.verified,
                tone = if (verdictStr == "compliant") PubTone.Ok else PubTone.Mut,
                label = "合规标识",
                chip = when (verdictStr) {
                    "compliant" -> "合规"; "degraded" -> "降级"; else -> "待确认"
                },
                barFraction = if (verdictStr == "compliant") 1f else if (verdictStr == "degraded") 0.5f else 0f,
                barNumber = when (verdictStr) {
                    "compliant" -> "合规"; "degraded" -> "降级"; else -> "—"
                },
                whyLabel = "依据是什么",
                bullets = listOf(
                    compliance.regulation ?: "《人工智能生成合成内容标识办法》",
                    when (verdictStr) {
                        "compliant" -> "已携带可识别的合规隐式标识。"
                        "degraded" -> "标识可识别但已降级,建议核实来源。"
                        else -> "未检出合规隐式标识。"
                    },
                ),
            ),
        )
    }

    val summaryText = buildString {
        append("本次由「")
        append(model ?: "鉴源盾")
        append("」对图片做主动取证水印检测。")
        append(
            when (verdict) {
                VerdictKind.Real -> "成功恢复出来源水印,来源可追溯,各项指标正常。"
                VerdictKind.Ai -> "水印可识别但已降级,图片可能经过压缩或二次处理,建议核实来源。"
                VerdictKind.Tampered -> "未能恢复出可信水印,无法确认来源,作为证据或转发前请再核实。"
            },
        )
    }

    val engine = if (mode == "real_checkpoint") "$model · 真实模型" else "$model · 演示模拟"
    val nature = when {
        offline -> "离线演示(未连服务器)"
        mode == "real_checkpoint" -> "实时检测 · 真实模型"
        else -> "实时检测 · 演示模拟"
    }
    val metaInfo = buildList {
        add("鉴别时间" to fmtTime(createdAt))
        elapsedMs?.let { add("检测用时" to "${oneDecimal(it / 1000.0)} 秒") }
        add("检测引擎" to engine)
        add("攻击场景" to (if (isClean) "无攻击 · Clean" else attackLabel(attack)))
        add("结果性质" to nature)
    }

    val sha = evidence.sha256.entries
        .filter { !it.value.isNullOrBlank() }
        .map { it.key to (it.value ?: "") }

    return PubResultUi(
        verdict = verdict,
        heroPalette = palette,
        headlinePercent = headlinePercent,
        headlineLabel = headlineLabel,
        title = title,
        badge = badge,
        desc = desc,
        previewUrl = previewUrl,
        heatmapUrl = heatmapUrl,
        annotation = annotation,
        items = items,
        analysisBlocks = blocks,
        summaryText = summaryText,
        metaInfo = metaInfo,
        certName = fileName,
        certNumber = "JY-${taskId.ifBlank { "------" }}",
        certTime = fmtTime(createdAt),
        certItems = "溯源水印 · 抗攻击鲁棒性 · 图像质量 · 合规标识",
        certBadge = title,
        certDesc = desc,
        sha256 = sha,
        model = model ?: "",
        attack = attack ?: "clean",
        mode = mode ?: "",
        offline = offline,
        taskId = taskId,
    )
}

private fun oneDecimal(v: Double): String = String.format(Locale.US, "%.1f", v)
private fun twoDecimal(v: Double): String = String.format(Locale.US, "%.2f", v)

/** 攻击 id → 大白话(对应 domain.ATTACKS,避免引依赖这里就地内置常用项)。 */
private fun attackLabel(id: String?): String = when (id) {
    null, "", "clean" -> "无攻击 · Clean"
    "jpeg_50" -> "JPEG 压缩 Q=50"
    "jpeg_70" -> "JPEG 压缩 Q=70"
    "jpeg_90" -> "JPEG 压缩 Q=90"
    "webp_80" -> "WebP 压缩 Q=80"
    "resize" -> "缩放往返"
    "crop" -> "中心裁剪"
    "rotate_5" -> "旋转 5°"
    "blur" -> "高斯模糊"
    "noise" -> "高斯噪声"
    "brightness" -> "亮度扰动"
    "contrast" -> "对比度扰动"
    "platform_wechat_v1" -> "微信传播仿真"
    "platform_douyin_v1" -> "抖音传播仿真"
    "deepfake_proxy_v1" -> "Deepfake 换脸代理"
    else -> id
}
