package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import com.vpsg.jianyuanshield.ui.theme.PageBg

/**
 * GovTrust page canvas: a calm, near-flat cool-gray background with a barely
 * perceptible cooler tint at the very top. No glow, no orbs — the dignity comes
 * from whitespace and white cards floating on this neutral field.
 */
@Composable
fun AuroraBackground(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        drawRect(
            Brush.verticalGradient(
                0f to Color(0xFFEFF2F8),
                0.25f to PageBg,
                1f to PageBg,
            ),
        )
    }
}
