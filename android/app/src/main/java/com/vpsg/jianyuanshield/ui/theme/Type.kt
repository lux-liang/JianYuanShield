package com.vpsg.jianyuanshield.ui.theme

import android.content.Context
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Optional brand typeface loaded from assets at runtime — drop font files into
 * `app/src/main/assets/fonts/` and they are picked up automatically:
 *   brand_regular.otf · brand_medium.otf · brand_bold.otf · brand_black.otf
 * (e.g. Source Han Sans / Noto Sans SC weights). Missing files → system font.
 */
fun loadBrandFontFamily(context: Context): FontFamily? = runCatching {
    val assets = context.assets
    FontFamily(
        Font("fonts/brand_regular.otf", assets, FontWeight.Normal, FontStyle.Normal),
        Font("fonts/brand_medium.otf", assets, FontWeight.Medium, FontStyle.Normal),
        Font("fonts/brand_bold.otf", assets, FontWeight.Bold, FontStyle.Normal),
        Font("fonts/brand_black.otf", assets, FontWeight.Black, FontStyle.Normal),
    )
}.getOrNull()

@Composable
fun rememberBrandFontFamily(): FontFamily? {
    val context = LocalContext.current
    return remember { loadBrandFontFamily(context) }
}

/**
 * Dramatic, Apple-leaning scale: heavy display numerals, tight large titles,
 * comfortable body. Built against an optional brand family.
 */
fun buildAppTypography(brand: FontFamily?): Typography {
    val f = brand ?: FontFamily.Default
    return Typography(
        // 政务克制字阶:去满屏 Black/ExtraBold,拉开 页面>模块>内容>辅助>状态 五级层级。
        displayLarge = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Bold,
            fontSize = 34.sp, lineHeight = 40.sp, letterSpacing = (-0.5).sp,
        ),
        displayMedium = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Bold,
            fontSize = 28.sp, lineHeight = 34.sp, letterSpacing = (-0.5).sp,
        ),
        displaySmall = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Bold,
            fontSize = 24.sp, lineHeight = 30.sp, letterSpacing = (-0.25).sp,
        ),
        headlineLarge = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Bold,
            fontSize = 22.sp, lineHeight = 28.sp, letterSpacing = (-0.25).sp,
        ),
        headlineMedium = TextStyle(
            fontFamily = f, fontWeight = FontWeight.SemiBold,
            fontSize = 19.sp, lineHeight = 25.sp,
        ),
        headlineSmall = TextStyle(
            fontFamily = f, fontWeight = FontWeight.SemiBold,
            fontSize = 17.sp, lineHeight = 23.sp,
        ),
        titleLarge = TextStyle(
            fontFamily = f, fontWeight = FontWeight.SemiBold,
            fontSize = 16.sp, lineHeight = 22.sp,
        ),
        titleMedium = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Medium,
            fontSize = 15.sp, lineHeight = 21.sp,
        ),
        titleSmall = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Medium,
            fontSize = 14.sp, lineHeight = 20.sp,
        ),
        bodyLarge = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Normal,
            fontSize = 15.sp, lineHeight = 22.sp,
        ),
        bodyMedium = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Normal,
            fontSize = 14.sp, lineHeight = 20.sp,
        ),
        bodySmall = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Normal,
            fontSize = 12.sp, lineHeight = 17.sp,
        ),
        labelLarge = TextStyle(
            fontFamily = f, fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp, lineHeight = 18.sp,
        ),
        labelMedium = TextStyle(
            fontFamily = f, fontWeight = FontWeight.SemiBold,
            fontSize = 12.sp, lineHeight = 16.sp,
        ),
        labelSmall = TextStyle(
            fontFamily = f, fontWeight = FontWeight.Medium,
            fontSize = 11.sp, lineHeight = 14.sp,
        ),
    )
}

/** Default typography (system font); the theme swaps in the brand family when present. */
val AppTypography = buildAppTypography(null)
