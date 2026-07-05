package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Matrix
import androidx.compose.ui.graphics.asComposePath
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.graphics.shapes.CornerRounding
import androidx.graphics.shapes.Morph
import androidx.graphics.shapes.RoundedPolygon
import androidx.graphics.shapes.circle
import androidx.graphics.shapes.star
import androidx.compose.ui.unit.dp
import androidx.graphics.shapes.toPath
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue

/**
 * M3-Expressive shape morph: an eight-petal scalloped star breathing into a
 * circle while rotating slowly. Used as the living halo behind the home
 * shield — official androidx.graphics:graphics-shapes, no custom math.
 */
@Composable
fun MorphingHalo(
    modifier: Modifier = Modifier,
    color: Color = ElectricBlue,
) {
    val morph = remember {
        val scallop = RoundedPolygon.star(
            numVerticesPerRadius = 8,
            radius = 1f,
            innerRadius = 0.82f,
            rounding = CornerRounding(0.32f),
        ).normalized()
        val circle = RoundedPolygon.circle(numVertices = 8).normalized()
        Morph(scallop, circle)
    }

    val transition = rememberInfiniteTransition(label = "halo")
    val progress by transition.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(3800, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "halo-morph",
    )
    val spin by transition.animateFloat(
        0f, 360f,
        infiniteRepeatable(tween(26_000, easing = LinearEasing)),
        label = "halo-spin",
    )

    Canvas(modifier) {
        // normalized() puts the shape in the unit box [0,1] — scale to canvas.
        val path = morph.toPath(progress).asComposePath()
        path.transform(
            Matrix().apply { scale(x = size.width, y = size.height) },
        )
        rotate(spin) {
            drawPath(
                path,
                brush = Brush.radialGradient(
                    listOf(color.copy(alpha = 0.16f), color.copy(alpha = 0.02f)),
                ),
            )
            drawPath(
                path,
                color = color.copy(alpha = 0.45f),
                style = Stroke(width = 1.5.dp.toPx()),
            )
        }
    }
}
