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
    localDemo: Boolean,
): PubResultUi {
    val m = metrics
    val bitAcc = m.numOrNull("bit_accuracy_tracer")
        ?: m.numOrNull("bit_accuracy_c")
        ?: m.numOrNull("bit_accuracy")
        ?: m.numOrNull("bit_accuracy_detector")
    val srcAcc = m.numOrNull("source_id_acc")
    val conf = m.numOrNull("confidence") ?: bitAcc ?: srcAcc ?: 0.0
    val psnr = m.numOrNull("psnr")
    val ssim = m.numOrNull("ssim")
    val elapsedMs = m.numOrNull("elapsed_ms")
    val success = m.boolOrNull("success") ?: compliance.watermarkDetected ?: false
    val verdictStr = compliance.verdict   // compliant / degraded / null
    val isClean = attack.isNullOrBlank() || attack == "clean"
    val resultMode = mode.orEmpty()
    val trustState = evaluateResultTrust(
        claimValid = claimValid,
        mode = resultMode,
        localDemo = localDemo,
        resultProvenance = resultProvenance,
    )
    val isSimulation = trustState.isSimulation
    val canPublish = trustState.canIssueCertificate

    // ── 结论 ───────────────────────────────────────────────────────────────────
    val verdict: VerdictKind
    val palette: HeroPalette
    val title: String
    val badge: String
    val desc: String
    val headlineLabel: String
    val headlinePercent: Int
    when {
        !canPublish -> {
            verdict = VerdictKind.Ai
            palette = Pub.heroAmber
            title = "主动水印流程演示"
            badge = "不可发布"
            headlineLabel = "模拟指标"
            headlinePercent = pct(conf)
            desc = when {
                localDemo -> "当前为你显式开启的本地演示，仅预览嵌入、攻击与恢复流程，不构成来源或合规结论。"
                isSimulation -> "服务器未使用真实 checkpoint，本次输出仅供流程演示，不构成来源或合规结论。"
                else -> "本次输出未通过 claim_valid 声明门禁，不得作为来源、合规或科研结论。"
            }
        }
        verdictStr == "compliant" || (success && verdictStr != "degraded") -> {
            verdict = VerdictKind.Real
            palette = Pub.heroGreen
            title = "主动水印验证通过"
            badge = "可核验"
            headlineLabel = "恢复置信度"
            headlinePercent = pct(conf)
            desc = if (isClean)
                "本次流程新嵌入的来源水印已成功恢复，证明该水印保护链路可用。"
            else
                "本次流程新嵌入的来源水印在「${attackLabel(attack)}」处理后仍能恢复，鲁棒性验证通过。"
        }
        verdictStr == "degraded" -> {
            verdict = VerdictKind.Ai
            palette = Pub.heroAmber
            title = "水印已降级"
            badge = "需留意"
            headlineLabel = "水印完整度"
            headlinePercent = pct(conf)
            desc = "本次流程新嵌入的来源水印在处理后仍有残留，但恢复质量已明显降级。"
        }
        else -> {
            verdict = VerdictKind.Tampered
            palette = Pub.heroRed
            title = "主动水印验证未通过"
            badge = "未通过"
            headlineLabel = "水印完整度"
            headlinePercent = pct(conf)
            desc = "未能恢复本次流程新嵌入的来源水印，说明当前攻击场景下保护链路未通过。"
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
        tone = if (!canPublish) PubTone.Warn else if (success) PubTone.Ok else PubTone.Mut,
        label = "溯源水印",
        value = if (!canPublish) "流程演示" else if (success) "已检出" else "未检出",
        sub = if (!canPublish) "模拟值 · 不可作结论" else bitAcc?.let { "bit 准确率 ${pct(it)}%" } ?: "来源标记核验",
    )
    val itemRobust = PubResultItem(
        icon = PubIcons.bolt,
        tone = when {
            !canPublish -> PubTone.Warn
            isClean -> PubTone.Mut
            success -> PubTone.Ok
            else -> PubTone.Warn
        },
        label = "抗攻击鲁棒性",
        value = if (!canPublish) "模拟评估" else if (isClean) "未施加" else if (success) "通过" else "未通过",
        sub = if (!canPublish) "不可发布" else if (isClean) "基线 · 无攻击" else attackLabel(attack),
    )
    val itemQuality = PubResultItem(
        icon = PubIcons.image,
        tone = if (!canPublish) PubTone.Warn else if ((psnr ?: 0.0) >= 35.0) PubTone.Ok else PubTone.Mut,
        label = "图像质量",
        value = psnr?.let { "${oneDecimal(it)} dB" } ?: "—",
        sub = if (!canPublish) "模拟指标 · 不可发布" else ssim?.let { "SSIM ${twoDecimal(it)}" } ?: "PSNR / SSIM",
    )
    val itemCompliance = PubResultItem(
        icon = PubIcons.verified,
        tone = if (canPublish && verdictStr == "compliant") PubTone.Ok else PubTone.Mut,
        label = "本流程标识",
        value = if (!canPublish) "未评估" else when (verdictStr) {
            "compliant" -> "合规"
            "degraded" -> "降级"
            else -> "待确认"
        },
        sub = if (canPublish) "《AI 标识办法》" else "claim_valid=false",
    )
    val items = listOf(itemWatermark, itemRobust, itemQuality, itemCompliance)

    // ── 报告块 ───────────────────────────────────────────────────────────────────
    val blocks = buildList {
        add(
            PubAnalysisBlock(
                icon = PubIcons.shieldCheck,
                tone = if (!canPublish) PubTone.Warn else if (success) PubTone.Ok else PubTone.Warn,
                label = "溯源水印强度",
                chip = if (!canPublish) "模拟值" else if (success) "清晰" else "微弱",
                barFraction = (bitAcc ?: conf).toFloat().coerceIn(0f, 1f),
                barNumber = "${pct(bitAcc ?: conf)}%",
                whyLabel = "我们看到了这些",
                bullets = buildList {
                    if (!canPublish) add("以下数值来自流程模拟，不能用于来源或合规判断。")
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
                    !canPublish -> PubTone.Warn
                    isClean -> PubTone.Mut
                    success -> PubTone.Ok
                    else -> PubTone.Warn
                },
                label = "抗攻击鲁棒性",
                chip = if (!canPublish) "模拟值" else if (isClean) "基线" else if (success) "通过" else "未通过",
                barFraction = if (isClean) 0f else if (success) 0.92f else 0.3f,
                barNumber = if (isClean) "—" else if (success) "强" else "弱",
                whyLabel = "这一项怎么测",
                bullets = if (!canPublish)
                    listOf(
                        "本项仅演示攻击处理后的水印恢复流程，不构成鲁棒性结论。",
                        "模拟场景：${if (isClean) "无攻击 · Clean" else attackLabel(attack)}。",
                    )
                else if (isClean)
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
                tone = if (!canPublish) PubTone.Warn else if ((psnr ?: 0.0) >= 35.0) PubTone.Ok else PubTone.Mut,
                label = "图像质量",
                chip = if (!canPublish) "模拟值" else psnr?.let { "${oneDecimal(it)} dB" } ?: "—",
                barFraction = ((psnr ?: 0.0) / 50.0).toFloat().coerceIn(0f, 1f),
                barNumber = ssim?.let { twoDecimal(it) } ?: "—",
                whyLabel = "这说明什么",
                bullets = buildList {
                    if (!canPublish) add("以下画质数值仅用于界面流程预览。")
                    psnr?.let { add("PSNR ${oneDecimal(it)} dB,数值越高说明嵌入水印后画质损失越小。") }
                    ssim?.let { add("SSIM ${twoDecimal(it)},接近 1 表示与原图几乎一致。") }
                    if (psnr == null && ssim == null) add("本次未返回画质指标。")
                },
            ),
        )
        add(
            PubAnalysisBlock(
                icon = PubIcons.verified,
                tone = if (canPublish && verdictStr == "compliant") PubTone.Ok else PubTone.Mut,
                label = "合规标识",
                chip = if (!canPublish) "未评估" else when (verdictStr) {
                    "compliant" -> "合规"; "degraded" -> "降级"; else -> "待确认"
                },
                barFraction = if (!canPublish) 0f else if (verdictStr == "compliant") 1f else if (verdictStr == "degraded") 0.5f else 0f,
                barNumber = if (!canPublish) "—" else when (verdictStr) {
                    "compliant" -> "合规"; "degraded" -> "降级"; else -> "—"
                },
                whyLabel = "依据是什么",
                bullets = if (!canPublish) listOf(
                    "claim_valid=false，本次没有形成可发布的合规结论。",
                    "模拟输出不得解释为已合规或不合规。",
                ) else listOf(
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

    val summaryText = if (!canPublish) {
        "本页仅展示主动取证水印的嵌入、攻击与恢复流程。模拟指标未通过声明门禁，不用于判断上传图片真假，不构成来源、合规、科研或司法结论。"
    } else buildString {
        append("本次由「")
        append(model ?: "鉴源盾")
        append("」对图片运行主动取证水印嵌入—攻击—恢复验证。")
        append(
            when (verdict) {
                VerdictKind.Real -> "本次新嵌入的来源水印恢复成功，保护链路验证通过。"
                VerdictKind.Ai -> "本次新嵌入的水印在攻击处理后恢复质量下降。"
                VerdictKind.Tampered -> "本次新嵌入的水印未能恢复，当前保护链路验证未通过。"
            },
        )
    }

    val engine = if (resultMode == "real_checkpoint") "$model · 真实模型" else "$model · 演示模拟"
    val nature = when {
        canPublish -> "真实 checkpoint · 可核验"
        localDemo -> "本地流程演示 · 不可发布"
        isSimulation -> "服务器流程模拟 · 不可发布"
        else -> "声明门禁未通过 · 不可发布"
    }
    val metaInfo = buildList {
        add("核验时间" to fmtTime(createdAt))
        elapsedMs?.let { add("核验用时" to "${oneDecimal(it / 1000.0)} 秒") }
        add("核验引擎" to engine)
        add("攻击场景" to (if (isClean) "无攻击 · Clean" else attackLabel(attack)))
        add("结果性质" to nature)
        add("声明门禁" to if (claimValid) "claim_valid=true" else "claim_valid=false")
    }

    val sha = if (canPublish) {
        evidence.sha256.entries
            .filter { !it.value.isNullOrBlank() }
            .map { it.key to (it.value ?: "") }
    } else {
        emptyList()
    }

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
        certItems = "主动水印 · 抗攻击鲁棒性 · 图像质量 · 本流程标识",
        certBadge = title,
        certDesc = desc,
        sha256 = sha,
        model = model ?: "",
        attack = attack ?: "clean",
        mode = resultMode,
        resultProvenance = resultProvenance.orEmpty(),
        claimValid = claimValid,
        localDemo = localDemo,
        taskId = taskId,
    )
}

private fun oneDecimal(v: Double): String = String.format(Locale.US, "%.1f", v)
private fun twoDecimal(v: Double): String = String.format(Locale.US, "%.2f", v)

/** 攻击 id → 大白话(对应 domain.ATTACKS,避免引依赖这里就地内置常用项)。 */
private fun attackLabel(id: String?): String = when (id) {
    null, "", "clean" -> "无攻击 · Clean"
    "jpeg50" -> "JPEG 压缩 Q=50"
    "jpeg70" -> "JPEG 压缩 Q=70"
    "jpeg90" -> "JPEG 压缩 Q=90"
    "webp50" -> "WebP 压缩 Q=50"
    "resize_0.5x" -> "缩放往返 0.5×"
    "crop_center_0.8" -> "中心裁剪 0.8×"
    "rotate_5" -> "旋转 5°"
    "gaussian_blur_5" -> "高斯模糊 5×5"
    "gaussian_noise_sigma_3" -> "高斯噪声 σ=3"
    "brightness_0.85" -> "亮度系数 0.85"
    "contrast_1.2" -> "对比度系数 1.2"
    "platform_wechat_v1" -> "微信传播仿真"
    "platform_douyin_v1" -> "抖音传播仿真"
    "deepfake_proxy_v1" -> "局部人脸编辑代理（非真实 Deepfake）"
    else -> id
}
