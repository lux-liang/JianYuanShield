package com.vpsg.jianyuanshield.ui.pub

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/**
 * 鉴源盾 · 公众版设计系统(R7)颜色与渐变 token。
 *
 * 这一套对应 HTML 打样 mockups/app.css 里的公众版 R7 规范(白底 + 多档蓝 + 立体盾),
 * 独立于旧的政务取证 [com.vpsg.jianyuanshield.ui.theme.Color] 调色板,互不影响。
 * 全部为纯 Kotlin 顶层常量 / 函数,任何 Composable 均可直接引用。
 */
object Pub {
    // 页面 / 表面
    val Bg = Color(0xFFF2F5FB)
    val Card = Color(0xFFFFFFFF)
    val Hair = Color(0xFFEBEFF7)

    // 文本
    val Ink = Color(0xFF0F1A2E)
    val Ink2 = Color(0xFF4E5D77)
    val Ink3 = Color(0xFF97A2B8)

    // 蓝阶
    val Blue = Color(0xFF2E66E6)
    val Indigo = Color(0xFF3D3AC2)
    val Cyan = Color(0xFF1FA6C8)

    // 语义色 + 浅底
    val Ok = Color(0xFF13A06A)
    val OkB = Color(0xFFE7F6EF)
    val Warn = Color(0xFFE0901F)
    val WarnB = Color(0xFFFCF2DE)
    val WarnD = Color(0xFF8A5A12)
    val WarnD2 = Color(0xFFA06E1E)
    val Hi = Color(0xFFE0463C)
    val HiB = Color(0xFFFCEAE8)

    // 立体图标(claymorphism)四色:亮→深,以及更深的"侧壁"边色
    val C1a = Color(0xFF6BA0FF); val C1b = Color(0xFF2C5FE0); val C1edge = Color(0xFF1E48B2)
    val C2a = Color(0xFF3CDAC9); val C2b = Color(0xFF0E9E94); val C2edge = Color(0xFF0A726A)
    val C3a = Color(0xFFA98BF8); val C3b = Color(0xFF5E3FD0); val C3edge = Color(0xFF4124A8)
    val C4a = Color(0xFFFFBE63); val C4b = Color(0xFFEE7C20); val C4edge = Color(0xFFBE5A11)

    // 立体盾:面 / 侧壁 / 高光
    val ShieldFaceTop = Color(0xFF9CC6FF)
    val ShieldFaceMid = Color(0xFF4476ED)
    val ShieldFaceBot = Color(0xFF2A55C8)
    val ShieldSideTop = Color(0xFF2A53BE)
    val ShieldSideBot = Color(0xFF102C82)

    // 阴影
    val ShadowSoft = Color(0x14142D6E)
    val ShadowCard = Color(0x1F142D6E)

    // ── 渐变 ──────────────────────────────────────────────────────────
    /** 首页/内页浅色页里的蓝渐变 hero(对应 .hero)。 */
    fun heroBrush() = Brush.linearGradient(
        colors = listOf(Color(0xFF4C8BF7), Color(0xFF2A60DA), Color(0xFF1B3FAD)),
        start = Offset(0f, 0f),
        end = Offset(0f, Float.POSITIVE_INFINITY),
    )

    /** 结果页琥珀 hero(疑似 AI)。 */
    fun heroAmberBrush() = Brush.linearGradient(
        colors = listOf(Color(0xFFF0A93F), Color(0xFFE0901F), Color(0xFFB86A12)),
        start = Offset(0f, 0f),
        end = Offset(0f, Float.POSITIVE_INFINITY),
    )

    /** 引导页深蓝渐变满屏底。 */
    fun onboardBrush() = Brush.linearGradient(
        colors = listOf(Color(0xFF2C63E0), Color(0xFF1E47B8), Color(0xFF143289)),
        start = Offset(0f, 0f),
        end = Offset(0f, Float.POSITIVE_INFINITY),
    )

    /** 主按钮渐变。 */
    fun ctaBrush() = Brush.linearGradient(listOf(Color(0xFF2E66E6), Color(0xFF3F3AC8)))

    /** 立体图标四色面渐变。 */
    fun tileBrush(index: Int): Brush = when (index % 4) {
        0 -> Brush.linearGradient(listOf(C1a, C1b))
        1 -> Brush.linearGradient(listOf(C2a, C2b))
        2 -> Brush.linearGradient(listOf(C3a, C3b))
        else -> Brush.linearGradient(listOf(C4a, C4b))
    }

    fun tileEdge(index: Int): Color = when (index % 4) {
        0 -> C1edge; 1 -> C2edge; 2 -> C3edge; else -> C4edge
    }

    /** 缩略图按结论上色(真实/疑似AI/已篡改)。 */
    fun thumbBrush(kind: VerdictKind): Brush = when (kind) {
        VerdictKind.Real -> Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A)))
        VerdictKind.Ai -> Brush.linearGradient(listOf(Color(0xFFF2B65A), Color(0xFFDE8C1C)))
        VerdictKind.Tampered -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
    }

    // ── HERO 多层网格渐变(对应 app.css .hero 的 多 radial + linear 叠加)──────
    /** 首页/内页蓝色 hero:主蓝线性 + 右上青色光晕 + 左下紫色光晕。 */
    val heroBlue = HeroPalette(
        base = listOf(Color(0xFF4C8BF7), Color(0xFF2A60DA), Color(0xFF1B3FAD)),
        glowTopRight = Color(0xFF66E0FF),
        glowBottomLeft = Color(0xFF5B4DE0),
    )

    /** 结果页琥珀 hero(疑似 AI)。 */
    val heroAmber = HeroPalette(
        base = listOf(Color(0xFFF0A93F), Color(0xFFE0901F), Color(0xFFB86A12)),
        glowTopRight = Color(0xFFFFD98A),
        glowBottomLeft = Color(0xFFE08A2B),
    )

    /** 结果页绿色 hero(通过核验 / 可信)。 */
    val heroGreen = HeroPalette(
        base = listOf(Color(0xFF45C98C), Color(0xFF18A56E), Color(0xFF0E7A50)),
        glowTopRight = Color(0xFFB8F4D6),
        glowBottomLeft = Color(0xFF15B07A),
    )

    /** 结果页红色 hero(无法确认 / 异常)。 */
    val heroRed = HeroPalette(
        base = listOf(Color(0xFFEE7C72), Color(0xFFD63E34), Color(0xFFAE2A22)),
        glowTopRight = Color(0xFFFFC9C2),
        glowBottomLeft = Color(0xFFD6453A),
    )

    /** 引导页深蓝 hero 的三处光晕(对应 onboarding.html .lt1)。 */
    val onboardGlowTop = Color(0xFF5E97FF)
    val onboardGlowPurple = Color(0xFF7E5BEC)
    val onboardGlowCyan = Color(0xFF25C4DE)
}

/** 一组 hero 网格渐变配色:底色线性 + 两处角落彩色光晕。 */
data class HeroPalette(
    val base: List<Color>,
    val glowTopRight: Color,
    val glowBottomLeft: Color,
)

/** 结论类别,驱动语义配色。 */
enum class VerdictKind { Real, Ai, Tampered }
