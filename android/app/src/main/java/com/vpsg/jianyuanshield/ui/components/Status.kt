package com.vpsg.jianyuanshield.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.vpsg.jianyuanshield.ui.theme.brandColors

/** Semantic tone shared across status pills, banners and chips. */
enum class StatusTone { Success, Warning, Danger, Info, Neutral }

data class ToneColors(
    val accent: Color,
    val container: Color,
    val onContainer: Color,
)

@Composable
fun StatusTone.colors(): ToneColors {
    val brand = brandColors
    return when (this) {
        StatusTone.Success -> ToneColors(brand.success, brand.successContainer, brand.onSuccessContainer)
        StatusTone.Warning -> ToneColors(brand.warning, brand.warningContainer, brand.onWarningContainer)
        StatusTone.Danger -> ToneColors(brand.danger, brand.dangerContainer, brand.onDangerContainer)
        StatusTone.Info -> ToneColors(brand.info, brand.infoContainer, brand.onInfoContainer)
        StatusTone.Neutral -> ToneColors(
            accent = MaterialTheme.colorScheme.outline,
            container = MaterialTheme.colorScheme.surfaceVariant,
            onContainer = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Map a backend severity string to a tone. */
fun severityTone(severity: String?): StatusTone = when (severity?.lowercase()) {
    "info" -> StatusTone.Info
    "warning" -> StatusTone.Warning
    "error", "critical" -> StatusTone.Danger
    else -> StatusTone.Neutral
}

/** Map a compliance/result status string to a tone. */
fun resultTone(status: String?): StatusTone = when (status?.lowercase()) {
    "watermark_verified", "compliant", "verified", "complete" -> StatusTone.Success
    "watermark_degraded", "degraded", "review_required", "partial" -> StatusTone.Warning
    "no_watermark", "error", "failed" -> StatusTone.Danger
    else -> StatusTone.Neutral
}
