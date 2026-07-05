package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue
import com.vpsg.jianyuanshield.ui.theme.NeonCyan
import com.vpsg.jianyuanshield.ui.theme.NeonMint
import com.vpsg.jianyuanshield.ui.theme.TextMid
import kotlinx.coroutines.delay

/**
 * Rotating radar sweep with expanding ripples — the "active defense" motif
 * behind the home shield. Quiet, continuous, never louder than the content.
 */
@Composable
fun RadarSweep(
    modifier: Modifier = Modifier,
    size: Dp = 76.dp,
    color: Color = ElectricBlue,
) {
    val transition = rememberInfiniteTransition(label = "radar")
    val angle by transition.animateFloat(
        0f, 360f,
        infiniteRepeatable(tween(5200, easing = LinearEasing)),
        label = "radar-angle",
    )
    val ripple1 by transition.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(3000, easing = FastOutSlowInEasing)),
        label = "radar-r1",
    )
    val ripple2 by transition.animateFloat(
        0f, 1f,
        infiniteRepeatable(
            tween(3000, easing = FastOutSlowInEasing),
            initialStartOffset = StartOffset(1500),
        ),
        label = "radar-r2",
    )

    Canvas(modifier.size(size)) {
        val maxR = this.size.minDimension / 2f
        val center = Offset(this.size.width / 2f, this.size.height / 2f)
        // Static reference circles
        listOf(0.55f, 0.8f, 1f).forEach { f ->
            drawCircle(Color.White.copy(alpha = 0.06f), radius = maxR * f, center = center, style = Stroke(1.dp.toPx()))
        }
        // Ripples
        listOf(ripple1, ripple2).forEach { r ->
            if (r > 0.02f) {
                drawCircle(
                    color.copy(alpha = (1f - r) * 0.30f),
                    radius = maxR * r,
                    center = center,
                    style = Stroke(1.5.dp.toPx()),
                )
            }
        }
        // Sweep wedge + leading line
        rotate(angle, pivot = center) {
            drawArc(
                color = color.copy(alpha = 0.10f),
                startAngle = -110f,
                sweepAngle = 40f,
                useCenter = true,
                topLeft = Offset(center.x - maxR, center.y - maxR),
                size = Size(maxR * 2, maxR * 2),
            )
            drawLine(
                brush = Brush.linearGradient(
                    listOf(Color.Transparent, color.copy(alpha = 0.75f)),
                    start = center,
                    end = Offset(center.x, center.y - maxR),
                ),
                start = center,
                end = Offset(center.x, center.y - maxR),
                strokeWidth = 2.dp.toPx(),
            )
        }
    }
}

/** Stroke-traced checkmark — the success moment, drawn rather than stamped. */
@Composable
fun AnimatedCheckmark(
    modifier: Modifier = Modifier,
    size: Dp = 26.dp,
    color: Color = NeonMint,
    strokeWidth: Dp = 3.dp,
) {
    val progress = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        delay(220)
        progress.animateTo(1f, tween(650, easing = LuxEase))
    }
    Canvas(modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val path = Path().apply {
            moveTo(w * 0.16f, h * 0.55f)
            lineTo(w * 0.42f, h * 0.78f)
            lineTo(w * 0.85f, h * 0.25f)
        }
        val measure = PathMeasure()
        measure.setPath(path, false)
        val partial = Path()
        measure.getSegment(0f, measure.length * progress.value, partial, true)
        drawPath(
            partial,
            color = color,
            style = Stroke(strokeWidth.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
    }
}

/** Premium loader: expanding pulse rings around a glowing core dot. */
@Composable
fun PulseLoader(
    modifier: Modifier = Modifier,
    color: Color = ElectricBlue,
    text: String? = null,
) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        val transition = rememberInfiniteTransition(label = "pulse")
        val p1 by transition.animateFloat(
            0f, 1f, infiniteRepeatable(tween(1600, easing = FastOutSlowInEasing)), label = "p1",
        )
        val p2 by transition.animateFloat(
            0f, 1f,
            infiniteRepeatable(tween(1600, easing = FastOutSlowInEasing), initialStartOffset = StartOffset(800)),
            label = "p2",
        )
        Canvas(Modifier.size(54.dp)) {
            val center = Offset(size.width / 2f, size.height / 2f)
            val maxR = size.minDimension / 2f
            listOf(p1, p2).forEach { p ->
                if (p > 0.02f) {
                    drawCircle(
                        color.copy(alpha = (1f - p) * 0.35f),
                        radius = maxR * (0.3f + 0.7f * p),
                        center = center,
                        style = Stroke(2.dp.toPx()),
                    )
                }
            }
            drawCircle(
                Brush.radialGradient(listOf(color, color.copy(alpha = 0f)), center = center, radius = maxR * 0.45f),
                radius = maxR * 0.45f,
                center = center,
            )
            drawCircle(Color.White.copy(alpha = 0.9f), radius = 3.dp.toPx(), center = center)
        }
        if (text != null) {
            Spacer(Modifier.height(12.dp))
            Text(text, style = MaterialTheme.typography.bodyMedium, color = TextMid)
        }
    }
}

/** Slowly flowing dashed gradient border — the upload drop-zone affordance. */
fun Modifier.marchingAnts(
    cornerRadius: Dp = 18.dp,
    colorA: Color = ElectricBlue,
    colorB: Color = NeonCyan,
): Modifier = composed {
    val transition = rememberInfiniteTransition(label = "ants")
    val phase by transition.animateFloat(
        0f, -52f,
        infiniteRepeatable(tween(1600, easing = LinearEasing)),
        label = "ants-phase",
    )
    drawWithContent {
        drawContent()
        drawRoundRect(
            brush = Brush.linearGradient(listOf(colorA.copy(alpha = 0.8f), colorB.copy(alpha = 0.8f))),
            cornerRadius = CornerRadius(cornerRadius.toPx()),
            style = Stroke(
                width = 1.5.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(18f, 14f), phase),
            ),
        )
    }
}

/** Animated shimmer brush for skeleton placeholders. */
@Composable
fun shimmerBrush(): Brush {
    val transition = rememberInfiniteTransition(label = "shimmer")
    val x by transition.animateFloat(
        0f, 1200f,
        infiniteRepeatable(tween(1300, easing = LinearEasing)),
        label = "shimmer-x",
    )
    return Brush.linearGradient(
        listOf(
            Color.White.copy(alpha = 0.05f),
            Color.White.copy(alpha = 0.13f),
            Color.White.copy(alpha = 0.05f),
        ),
        start = Offset(x - 400f, 0f),
        end = Offset(x, 220f),
    )
}

/** Skeleton block with the shimmer wash. */
@Composable
fun SkeletonBox(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(12.dp),
) {
    Box(modifier.clip(shape).background(shimmerBrush()))
}
