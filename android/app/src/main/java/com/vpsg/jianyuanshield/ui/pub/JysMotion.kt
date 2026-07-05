package com.vpsg.jianyuanshield.ui.pub

import androidx.compose.animation.EnterTransition
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.scale

/**
 * 鉴源盾 · 公众版统一动效规范(JysMotion)。
 *
 * 原则:清透、克制、顺滑 —— **不要回弹过冲(果冻感)**,**入场幅度要小**(避免和页面转场叠加
 * 显得又忙又顿)。全站只用这里的时长 / 缓动 / 入场 / 按压封装。
 */
object JysMotion {
    // 标准时长(ms)
    const val PRESS = 120
    const val COLOR = 200
    const val STATE = 220
    const val ENTER = 280
    const val HERO = 300
    const val FILL = 900          // 进度 / 圆环 / 可信度条揭示
    const val RING = 1000         // 结果 / 报告圆环(略慢、更有仪式感)

    // 缓动
    val easeStd: Easing = FastOutSlowInEasing
    val easeOut: Easing = CubicBezierEasing(0.17f, 0.84f, 0.44f, 1f)   // EaseOutCubic 近似,无过冲
    val easeSine: Easing = CubicBezierEasing(0.45f, 0f, 0.55f, 1f)     // ease-in-out-sine,给 infinite 漂浮/呼吸
}

/**
 * 标准入场:淡入为主 + 小幅上移(封顶 64px,避免大元素滑动过长)。easeOut 收尾、无过冲。
 */
fun enterStd(delayMillis: Int = 0): EnterTransition =
    fadeIn(tween(JysMotion.ENTER, delayMillis, JysMotion.easeStd)) +
        slideInVertically(tween(JysMotion.ENTER, delayMillis, JysMotion.easeOut)) { (it / 6).coerceAtMost(64) }

/** Hero/卡片入场:略大一点的上移(封顶 88px),但仍克制。 */
fun enterHero(delayMillis: Int = 0): EnterTransition =
    fadeIn(tween(JysMotion.HERO, delayMillis, JysMotion.easeStd)) +
        slideInVertically(tween(JysMotion.HERO, delayMillis, JysMotion.easeOut)) { (it / 5).coerceAtMost(88) }

/**
 * 揭示型强调(圆环/警告 chip/凭证/头像):**精致**的轻放大 + 淡入。
 * 去掉了原来的弹簧回弹(dampingRatio=0.5 的过冲),改用 easeOut tween,从 0.96 放大到 1,
 * 不再有"果冻/玩具"感。
 */
fun enterReveal(delayMillis: Int = 0): EnterTransition =
    scaleIn(tween(JysMotion.ENTER, delayMillis, JysMotion.easeOut), initialScale = 0.96f) +
        fadeIn(tween(JysMotion.ENTER, delayMillis, JysMotion.easeStd))

/**
 * 统一按压反馈:按下时轻微缩小([to]),用**临界阻尼**弹簧(dampingRatio=1f,不回弹),
 * 响应干脆;保留 Material 涟漪。替换裸 `clickable { ... }`。
 */
fun Modifier.pressScale(
    to: Float = 0.97f,
    enabled: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    val src = remember { MutableInteractionSource() }
    val pressed by src.collectIsPressedAsState()
    val s by animateFloatAsState(
        targetValue = if (pressed) to else 1f,
        animationSpec = spring(dampingRatio = 1f, stiffness = 900f),
        label = "pressScale",
    )
    this
        .scale(s)
        .clickable(interactionSource = src, indication = LocalIndication.current, enabled = enabled) { onClick() }
}
