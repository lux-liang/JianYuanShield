package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.size
import com.vpsg.jianyuanshield.ui.theme.GovBlue

/** Brand shield path scaled into a square of [s] px (108-unit artwork). Reusable. */
fun shieldOutlinePath(s: Float): Path {
    val k = s / 108f
    fun x(v: Float) = v * k
    return Path().apply {
        moveTo(x(54f), x(24f))
        lineTo(x(82f), x(34f))
        lineTo(x(82f), x(57f))
        cubicTo(x(82f), x(75f), x(70f), x(86f), x(54f), x(92f))
        cubicTo(x(38f), x(86f), x(26f), x(75f), x(26f), x(57f))
        lineTo(x(26f), x(34f))
        close()
    }
}

/**
 * Calm flat empty-state artwork (asset-free): a soft document card with text
 * lines and a small verification badge — the dignified "暂无内容" motif used by
 * e-gov apps, drawn in muted brand tints. No bright color.
 */
@Composable
fun GovEmptyArt(modifier: Modifier = Modifier, size: Dp = 128.dp) {
    Canvas(modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val tint = GovBlue.copy(alpha = 0.10f)
        val line = GovBlue.copy(alpha = 0.16f)
        val edge = GovBlue.copy(alpha = 0.22f)

        // Soft ground shadow
        drawOval(
            color = Color(0x0F1A3A7A),
            topLeft = Offset(w * 0.16f, h * 0.86f),
            size = Size(w * 0.68f, h * 0.10f),
        )
        // Document card
        val docTL = Offset(w * 0.22f, h * 0.14f)
        val docSize = Size(w * 0.50f, h * 0.66f)
        val r = CornerRadius(w * 0.045f, w * 0.045f)
        drawRoundRect(color = tint, topLeft = docTL, size = docSize, cornerRadius = r)
        drawRoundRect(color = edge, topLeft = docTL, size = docSize, cornerRadius = r, style = Stroke(w * 0.012f))
        // Text lines
        repeat(3) { i ->
            val ly = docTL.y + docSize.height * (0.22f + i * 0.20f)
            drawRoundRect(
                color = line,
                topLeft = Offset(docTL.x + docSize.width * 0.14f, ly),
                size = Size(docSize.width * (if (i == 2) 0.42f else 0.72f), h * 0.045f),
                cornerRadius = CornerRadius(h * 0.03f),
            )
        }
        // Verification badge (shield + check), bottom-right overlap
        val badge = w * 0.34f
        val bx = w * 0.58f
        val by = h * 0.48f
        val shield = shieldOutlinePath(badge).apply { translate(Offset(bx, by)) }
        drawPath(shield, color = GovBlue)
        // Check inside the badge
        drawPath(
            Path().apply {
                moveTo(bx + badge * 0.32f, by + badge * 0.50f)
                lineTo(bx + badge * 0.45f, by + badge * 0.62f)
                lineTo(bx + badge * 0.70f, by + badge * 0.34f)
            },
            color = Color.White,
            style = Stroke(width = badge * 0.07f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
    }
}
