package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

/** Signature easing — fast attack, long luxurious settle (easeOutExpo-like). */
val LuxEase = CubicBezierEasing(0.16f, 1f, 0.3f, 1f)

/**
 * One-shot staggered entrance: each indexed element rises 28dp and fades in,
 * 80ms apart. Applied to cards so every screen "assembles" once on arrival.
 */
fun Modifier.entrance(index: Int = 0): Modifier = composed {
    val progress = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        delay(60L + 80L * index)
        progress.animateTo(1f, tween(560, easing = LuxEase))
    }
    graphicsLayer {
        alpha = progress.value
        translationY = (1f - progress.value) * 28.dp.toPx()
    }
}

/**
 * Apple-feel press: springy scale-down, no ripple (glass surfaces carry their
 * own light). Use for buttons, docks and tiles built on custom surfaces.
 */
fun Modifier.pressable(
    onClick: () -> Unit,
    enabled: Boolean = true,
    pressedScale: Float = 0.965f,
): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed && enabled) pressedScale else 1f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessMediumLow,
        ),
        label = "press-scale",
    )
    this
        .scale(scale)
        .clickable(
            interactionSource = interaction,
            indication = null,
            enabled = enabled,
            onClick = onClick,
        )
}

/**
 * Count-up driver: animates 0 → target once on first composition (and on any
 * later target change) with the signature easing. Read `.value` and format.
 */
@Composable
fun rememberCountUp(
    target: Float,
    durationMillis: Int = 1200,
): State<Float> {
    var started by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { started = true }
    return animateFloatAsState(
        targetValue = if (started) target else 0f,
        animationSpec = tween(durationMillis, easing = LuxEase),
        label = "count-up",
    )
}
