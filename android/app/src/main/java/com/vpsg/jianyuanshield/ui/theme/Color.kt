package com.vpsg.jianyuanshield.ui.theme

import androidx.compose.ui.graphics.Color

// ═══ 鉴源盾 · 政务取证设计规范(严格按构想 token)══════════════════════════

// 页面 / 表面
val PageBg = Color(0xFFF4F6FA)        // 浅灰蓝底,非纯白
val CardBg = Color(0xFFFFFFFF)
val TintCard = Color(0xFFEEF4FF)      // 浅蓝卡片
val Divider = Color(0xFFDCE1EA)       // 统一 hairline(更清晰的卡片边界)

// 主蓝阶
val GovBlueDeep = Color(0xFF0B3A8D)   // 政务深蓝(Hero / 重按钮)
val GovBlue = Color(0xFF234E86)       // 主蓝:更深更灰,去"亮蓝AI模板"感
val GovBlueAux = Color(0xFF4A6A97)    // 辅助蓝:偏灰
val GovBlueSoft = Color(0xFF6F9BE0)   // 浅蓝(图表第四档区分,仍属蓝阶)
val GovBluePressed = Color(0xFF0B3A8D)
val GovBlueTint = TintCard

// Hero 渐变(深蓝顶部)
val HeroStart = Color(0xFF0B3460)
val HeroMid = Color(0xFF143E70)
val HeroEnd = Color(0xFF235184)

// 文本
val Ink = Color(0xFF111827)           // 标题黑
val InkBody = Color(0xFF374151)       // 正文深灰(可读)
val InkSecondary = InkBody            // 兼容别名(正文深灰)
val InkFaint = Color(0xFF8A8F99)      // 辅助灰(弱说明)

// 语义色 + 浅底(政务降饱和:去马卡龙糖果感,只作小圆点/弱底,不抢主蓝)
val SuccessGreen = Color(0xFF1F8A5F)  // 深一档的克制绿
val SuccessContainer = Color(0xFFEAF3EE)
val OnSuccessContainer = Color(0xFF0C3D27)
val WarningAmber = Color(0xFFB7791F)  // 去高明度黄,转沉稳琥珀
val WarningContainer = Color(0xFFF6EFE2)
val OnWarningContainer = Color(0xFF4A3500)
val DangerRed = Color(0xFFC0392B)     // 收敛的政务红
val DangerContainer = Color(0xFFF6E7E5)
val OnDangerContainer = Color(0xFF4A0F0B)
val InfoBlue = GovBlue
val InfoContainer = GovBlueTint
val OnInfoContainer = GovBlueDeep
val RedAccent = DangerRed

// 中性状态(未就绪/次要)——可见的描边灰,不再近乎隐形
val NeutralDot = Color(0xFF9AA1AE)
val PillBg = Color(0xFFF3F5F9)        // 统一克制 pill 底(中性极浅)
val PillBorder = Divider              // 收口到单一 hairline,避免两套灰

// 灰阴影 token(暖灰,制造纸感厚度;非透明蓝)
val ShadowSoft = Color(0x14101828)    // 图标块 / 小控件
val ShadowCard = Color(0x1F101828)    // 卡片
val ShadowStrong = Color(0x2B101828)  // 浮起 / 主按钮

// ── 兼容别名(保留旧 token 名,统一指向新规范,避免改动面过大)──────────────
val ElectricBlue = GovBlue
val NeonCyan = GovBlueAux
val NeonMint = SuccessGreen
val NeonAmber = WarningAmber
val NeonCoral = DangerRed
val NeonViolet = GovBlueAux            // 重定向:消灭唯一出圈的紫,统一回蓝阶
val TextHi = Ink
val TextMid = InkBody                 // 正文用更深的灰,修正"过浅看不清"
val Space0 = PageBg
val Space1 = Color(0xFFEAEEF6)
val Space2 = CardBg
val GlowBlue = GovBlue
val GlowCyan = GovBlueAux
val GlowViolet = NeonViolet

// 品牌蓝(legacy)
val BrandBlue = GovBlue
val BrandBlueDark = GovBlueDeep
val BrandBlueDeep = GovBlueDeep
val BrandBlueLight = GovBlueAux

// 模型 / 图表强调色(克制、政务)
val AccentBlue = GovBlue
val AccentGreen = SuccessGreen
val AccentAmber = WarningAmber
val AccentPurple = GovBlueAux           // 重定向回蓝阶

// 浅色中性(给 MaterialTheme)
val LightBackground = PageBg
val LightSurface = CardBg
val LightSurfaceVariant = Color(0xFFEFF2F8)
val LightSurfaceContainer = Color(0xFFF7F8FC)
val LightOutline = Color(0xFFD3D7E0)
val LightOutlineVariant = Divider
val LightOnSurface = Ink
val LightOnSurfaceVariant = InkBody

// 暗色中性(占位,App 为浅色优先)
val DarkBackground = Color(0xFF0E1116)
val DarkSurface = Color(0xFF161A21)
val DarkSurfaceVariant = Color(0xFF272C36)
val DarkOutline = Color(0xFF3A404C)
val DarkOnSurface = Color(0xFFE3E6EC)
val DarkOnSurfaceVariant = Color(0xFFB4BAC6)
