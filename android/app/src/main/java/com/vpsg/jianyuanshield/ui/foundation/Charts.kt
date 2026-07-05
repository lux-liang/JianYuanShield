package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.TextMid
import kotlinx.coroutines.delay

/**
 * Apple-fitness-style activity ring: rounded caps, sweep gradient, a soft glow
 * underlay, and a 1.2s ease-out sweep on first composition.
 */
@Composable
fun ActivityRing(
    progress: Float,
    modifier: Modifier = Modifier,
    size: Dp = 120.dp,
    strokeWidth: Dp = 12.dp,
    colors: List<Color>,
    trackColor: Color = Ink.copy(alpha = 0.08f),
    content: @Composable () -> Unit = {},
) {
    val target = progress.coerceIn(0f, 1f)
    val animated by rememberCountUp(target)
    val arcColor = colors.firstOrNull() ?: GovBlue   // 政务:单色实心弧,去彩虹渐变/glow

    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val sw = strokeWidth.toPx()
            val inset = sw
            val arcSize = Size(this.size.width - inset * 2, this.size.height - inset * 2)
            val topLeft = Offset(inset, inset)

            drawArc(
                color = trackColor,
                startAngle = 0f,
                sweepAngle = 360f,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(sw, cap = StrokeCap.Round),
            )
            if (animated > 0.005f) {
                rotate(-90f) {
                    drawArc(
                        color = arcColor,
                        startAngle = 0f,
                        sweepAngle = 360f * animated,
                        useCenter = false,
                        topLeft = topLeft,
                        size = arcSize,
                        style = Stroke(sw, cap = StrokeCap.Round),
                    )
                }
            }
        }
        content()
    }
}

data class BarEntry(
    val label: String,
    val value: Float,
    val valueText: String,
    val color: Color,
)

/**
 * Horizontal comparison bars: each bar grows in sequence (90ms stagger) with a
 * mono value label — the Screen-Time look, tuned for model benchmarks.
 */
@Composable
fun GroupedBars(
    entries: List<BarEntry>,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        entries.forEachIndexed { index, entry ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    entry.label,
                    style = MaterialTheme.typography.labelLarge,
                    color = TextMid,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.width(82.dp),
                )
                var started by remember { mutableStateOf(false) }
                LaunchedEffect(Unit) {
                    delay(150L + 90L * index)
                    started = true
                }
                val fraction by animateFloatAsState(
                    targetValue = if (started) entry.value.coerceIn(0f, 1f) else 0f,
                    animationSpec = tween(900, easing = LuxEase),
                    label = "bar-$index",
                )
                Box(
                    Modifier
                        .weight(1f)
                        .height(10.dp)
                        .clip(CircleShape)
                        .background(Ink.copy(alpha = 0.08f)),
                ) {
                    Box(
                        Modifier
                            .fillMaxHeight()
                            .fillMaxWidth(fraction)
                            .clip(CircleShape)
                            .background(entry.color),
                    )
                }
                Spacer(Modifier.width(10.dp))
                Text(
                    entry.valueText,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = entry.color,
                    textAlign = TextAlign.End,
                    maxLines = 1,
                    modifier = Modifier.width(64.dp),
                )
            }
        }
    }
}

/** Thin animated progress strip used under list rows. */
@Composable
fun ThinProgress(
    value: Float,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val fraction by rememberCountUp(value.coerceIn(0f, 1f), durationMillis = 900)
    Box(
        modifier
            .fillMaxWidth()
            .height(5.dp)
            .clip(CircleShape)
            .background(Ink.copy(alpha = 0.08f)),
    ) {
        Box(
            Modifier
                .fillMaxHeight()
                .fillMaxWidth(fraction)
                .clip(CircleShape)
                .background(color),
        )
    }
}
