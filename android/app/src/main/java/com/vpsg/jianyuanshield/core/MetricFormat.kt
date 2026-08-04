package com.vpsg.jianyuanshield.core

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import java.util.Locale
import kotlin.math.abs

/** Human-friendly Chinese labels for common metric keys. */
private val METRIC_LABELS: Map<String, String> = mapOf(
    "psnr" to "PSNR",
    "ssim" to "SSIM",
    "ber" to "误码率 BER",
    "id_ber" to "ID 误码率",
    "bit_accuracy" to "比特精度",
    "bit_accuracy_c" to "比特精度",
    "bit_accuracy_rf" to "比特精度 (RF)",
    "bit_accuracy_detector" to "检测器精度",
    "source_id_acc" to "源 ID 精度",
    "landmark_error" to "关键点误差",
    "landmark_aed" to "关键点平均误差",
    "attack_success" to "攻击成功",
    "success" to "水印验证通过",
)

data class MetricRow(val label: String, val value: String)

/** Preserve the semantic difference between a real zero and an unavailable count. */
fun formatNullableCount(value: Int?): String = value?.toString() ?: "—"

/** Render a metrics [JsonObject] into a stable, display-ready list of rows. */
fun JsonObject.toMetricRows(): List<MetricRow> = entries
    .sortedBy { displayOrder(it.key) }
    .map { (key, element) ->
        MetricRow(
            label = METRIC_LABELS[key] ?: key,
            value = formatValue(key, element as? JsonPrimitive),
        )
    }

private fun displayOrder(key: String): Int = when (key) {
    "bit_accuracy", "bit_accuracy_c", "bit_accuracy_rf", "source_id_acc" -> 0
    "psnr" -> 1
    "ssim" -> 2
    "ber", "id_ber" -> 3
    else -> 10
}

private fun formatValue(key: String, primitive: JsonPrimitive?): String {
    if (primitive == null) return "—"

    primitive.booleanOrNull?.let { return if (it) "是" else "否" }

    val number = primitive.doubleOrNull
    if (number != null) {
        val k = key.lowercase()
        val looksLikeRatio = (k.contains("acc") || k.contains("rate") || k == "ber" || k == "id_ber") &&
            abs(number) <= 1.0
        return if (looksLikeRatio) {
            formatPercent(number)
        } else {
            formatNumber(number)
        }
    }

    return primitive.content
}

fun formatPercent(value: Double): String {
    val pct = value * 100.0
    return String.format(Locale.US, "%.2f%%", pct)
}

fun formatNumber(value: Double): String {
    return if (value == value.toLong().toDouble()) {
        value.toLong().toString()
    } else {
        String.format(Locale.US, "%.4f", value).trimEnd('0').trimEnd('.')
    }
}
