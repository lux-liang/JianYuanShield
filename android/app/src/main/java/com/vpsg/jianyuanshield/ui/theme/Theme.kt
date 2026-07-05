package com.vpsg.jianyuanshield.ui.theme

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/** Extra brand colors not covered by the Material color scheme. */
data class BrandColors(
    val success: Color,
    val successContainer: Color,
    val onSuccessContainer: Color,
    val warning: Color,
    val warningContainer: Color,
    val onWarningContainer: Color,
    val danger: Color,
    val dangerContainer: Color,
    val onDangerContainer: Color,
    val info: Color,
    val infoContainer: Color,
    val onInfoContainer: Color,
    val heroGradient: List<Color>,
    val accentBlue: Color,
    val accentGreen: Color,
    val accentAmber: Color,
    val accentPurple: Color,
)

private val GovBrandColors = BrandColors(
    success = SuccessGreen,
    successContainer = SuccessContainer,
    onSuccessContainer = OnSuccessContainer,
    warning = WarningAmber,
    warningContainer = WarningContainer,
    onWarningContainer = OnWarningContainer,
    danger = DangerRed,
    dangerContainer = DangerContainer,
    onDangerContainer = OnDangerContainer,
    info = InfoBlue,
    infoContainer = InfoContainer,
    onInfoContainer = OnInfoContainer,
    heroGradient = listOf(HeroStart, HeroMid, HeroEnd),
    accentBlue = AccentBlue,
    accentGreen = AccentGreen,
    accentAmber = AccentAmber,
    accentPurple = AccentPurple,
)

val LocalBrandColors = staticCompositionLocalOf { GovBrandColors }

private val GovColors = lightColorScheme(
    primary = GovBlue,
    onPrimary = Color.White,
    primaryContainer = GovBlueTint,
    onPrimaryContainer = OnInfoContainer,
    secondary = GovBlue,
    onSecondary = Color.White,
    secondaryContainer = GovBlueTint,
    onSecondaryContainer = OnInfoContainer,
    tertiary = RedAccent,
    onTertiary = Color.White,
    background = PageBg,
    onBackground = Ink,
    surface = CardBg,
    onSurface = Ink,
    surfaceVariant = LightSurfaceVariant,
    onSurfaceVariant = InkSecondary,
    surfaceContainer = LightSurfaceContainer,
    surfaceContainerHigh = Color(0xFFEFF1F6),
    outline = LightOutline,
    outlineVariant = Divider,
    error = DangerRed,
    onError = Color.White,
    errorContainer = DangerContainer,
    onErrorContainer = OnDangerContainer,
)

/** Convenience accessor for brand colors from any composable. */
val brandColors: BrandColors
    @Composable get() = LocalBrandColors.current

/** Hero gradient brush (home banner). */
val heroBrush: Brush
    @Composable get() = Brush.linearGradient(LocalBrandColors.current.heroGradient)

/**
 * GovTrust is a calm, light-first 政务 design language: light gray canvas, white
 * cards, navy primary. Status bar stays light with dark icons everywhere.
 */
@Composable
fun JianYuanShieldTheme(
    content: @Composable () -> Unit,
) {
    val brandFont = rememberBrandFontFamily()
    val typography = remember(brandFont) { buildAppTypography(brandFont) }

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = PageBg.toArgb()
            window.navigationBarColor = CardBg.toArgb()
            val insets = WindowCompat.getInsetsController(window, view)
            insets.isAppearanceLightStatusBars = true   // dark icons on light bar
            insets.isAppearanceLightNavigationBars = true
        }
    }

    CompositionLocalProvider(LocalBrandColors provides GovBrandColors) {
        MaterialTheme(
            colorScheme = GovColors,
            typography = typography,
            content = content,
        )
    }
}
