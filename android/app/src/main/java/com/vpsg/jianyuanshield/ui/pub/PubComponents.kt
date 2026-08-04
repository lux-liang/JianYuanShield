package com.vpsg.jianyuanshield.ui.pub

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.AutoFixHigh
import androidx.compose.material.icons.outlined.Block
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ChevronLeft
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Face
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.FileUpload
import androidx.compose.material.icons.outlined.GppGood
import androidx.compose.material.icons.outlined.HelpOutline
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.PriorityHigh
import androidx.compose.material.icons.outlined.QrCode2
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.SaveAlt
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material.icons.outlined.Smartphone
import androidx.compose.material.icons.outlined.Verified
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material.icons.outlined.Waves
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.hypot

/**
 * 鉴源盾 · 公众版共享 Compose 组件库(对应 HTML 打样 mockups/app.css 的组件)。
 *
 * 每个公众版界面都只依赖本文件 + [Pub]([PubTheme]) + [PubModels] 暴露的 API,
 * 不要在界面里自创同名组件。所有颜色/渐变取自 [Pub]。
 */

// ─────────────────────────────────────────────────────────────────────────────
// 图标集中表(全部用 Material Outlined,放进立体瓦片即获得厚度,不当扁平主视觉)
// ─────────────────────────────────────────────────────────────────────────────
object PubIcons {
    val ai = Icons.Outlined.AutoAwesome
    val faceSwap = Icons.Outlined.Face
    val tamper = Icons.Outlined.AutoFixHigh
    val watermark = Icons.Outlined.Waves
    val shield = Icons.Outlined.Shield
    val shieldCheck = Icons.Outlined.GppGood
    val camera = Icons.Outlined.PhotoCamera
    val gallery = Icons.Outlined.PhotoLibrary
    val history = Icons.Outlined.History
    val clock = Icons.Outlined.Schedule
    val person = Icons.Outlined.Person
    val home = Icons.Outlined.Home
    val search = Icons.Outlined.Search
    val bell = Icons.Outlined.NotificationsNone
    val back = Icons.Outlined.ChevronLeft
    val chevronRight = Icons.Outlined.ChevronRight
    val check = Icons.Outlined.Check
    val checkCircle = Icons.Outlined.CheckCircle
    val warning = Icons.Outlined.Warning
    val close = Icons.Outlined.Close
    val bolt = Icons.Outlined.Bolt
    val upload = Icons.Outlined.FileUpload
    val download = Icons.Outlined.FileDownload
    val save = Icons.Outlined.SaveAlt
    val share = Icons.Outlined.Share
    val refresh = Icons.Outlined.Refresh
    val qr = Icons.Outlined.QrCode2
    val qrScan = Icons.Outlined.QrCodeScanner
    val lock = Icons.Outlined.Lock
    val help = Icons.Outlined.HelpOutline
    val info = Icons.Outlined.Info
    val verified = Icons.Outlined.Verified
    val edit = Icons.Outlined.Edit
    val eye = Icons.Outlined.Visibility
    val doc = Icons.Outlined.Description
    val learn = Icons.Outlined.MenuBook
    val image = Icons.Outlined.Image
    val priorityHigh = Icons.Outlined.PriorityHigh
    val phone = Icons.Outlined.Smartphone
    val cloud = Icons.Outlined.Cloud
    val block = Icons.Outlined.Block
}

// ─────────────────────────────────────────────────────────────────────────────
// 语义色辅助
// ─────────────────────────────────────────────────────────────────────────────
fun verdictTint(kind: VerdictKind): Color = when (kind) {
    VerdictKind.Real -> Pub.Ok
    VerdictKind.Ai -> Pub.Warn
    VerdictKind.Tampered -> Pub.Hi
}

fun verdictContainer(kind: VerdictKind): Color = when (kind) {
    VerdictKind.Real -> Pub.OkB
    VerdictKind.Ai -> Pub.WarnB
    VerdictKind.Tampered -> Pub.HiB
}

private fun verdictCornerIcon(kind: VerdictKind): ImageVector = when (kind) {
    VerdictKind.Real -> PubIcons.check
    VerdictKind.Ai -> PubIcons.priorityHigh
    VerdictKind.Tampered -> PubIcons.close
}

/** 虚线圆角描边(上传选项卡)。 */
fun Modifier.dashedRoundedBorder(
    color: Color,
    cornerRadius: Dp,
    strokeWidth: Dp = 1.5.dp,
    on: Dp = 5.dp,
    off: Dp = 4.dp,
): Modifier = this.drawBehind {
    val stroke = Stroke(
        width = strokeWidth.toPx(),
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(on.toPx(), off.toPx())),
    )
    val half = strokeWidth.toPx() / 2f
    drawRoundRect(
        color = color,
        topLeft = Offset(half, half),
        size = Size(size.width - strokeWidth.toPx(), size.height - strokeWidth.toPx()),
        cornerRadius = CornerRadius(cornerRadius.toPx()),
        style = stroke,
    )
}

/** 一条横向虚线分隔(凭证卡)。 */
@Composable
fun DashedHLine(modifier: Modifier = Modifier, color: Color = Color(0xFFE0E6F2)) {
    Canvas(modifier.fillMaxWidth().height(1.dp)) {
        drawLine(
            color = color,
            start = Offset(0f, 0f),
            end = Offset(size.width, 0f),
            strokeWidth = size.height,
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx())),
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 立体盾(品牌核心):侧壁 + 面 + 高光 + 字形,纯 Canvas 绘制
// ─────────────────────────────────────────────────────────────────────────────
enum class ShieldGlyph { Magnifier, Check, None }

/** 盾牌轮廓路径,在 120×150 单位空间(乘以 [s])并整体下移 [dy] 像素。 */
private fun shieldPath(s: Float, dy: Float): Path = Path().apply {
    moveTo(60 * s, 7 * s + dy)
    lineTo(100 * s, 21 * s + dy)
    cubicTo(102 * s, 22 * s + dy, 103 * s, 23.5f * s + dy, 103 * s, 26.5f * s + dy)
    lineTo(103 * s, 65 * s + dy)
    cubicTo(103 * s, 95 * s + dy, 84 * s, 117 * s + dy, 60 * s, 127 * s + dy)
    cubicTo(36 * s, 117 * s + dy, 17 * s, 95 * s + dy, 17 * s, 65 * s + dy)
    lineTo(17 * s, 26.5f * s + dy)
    cubicTo(17 * s, 23.5f * s + dy, 18 * s, 22 * s + dy, 20 * s, 21 * s + dy)
    close()
}

@Composable
fun ShieldArt(
    modifier: Modifier = Modifier,
    width: Dp = 120.dp,
    glyph: ShieldGlyph = ShieldGlyph.Magnifier,
) {
    val height = width * (150f / 120f)
    Canvas(modifier.size(width, height)) {
        val s = size.width / 120f
        val glyphBrush = Brush.linearGradient(listOf(Color.White, Color(0xFFDCE8FF)))

        // 接触阴影
        drawOval(
            color = Color(0xFF23489E).copy(alpha = 0.30f),
            topLeft = Offset((60 - 42) * s, (142 - 8.5f) * s),
            size = Size(84 * s, 17 * s),
        )
        // 侧壁(下移 11)
        drawPath(
            shieldPath(s, 11 * s),
            brush = Brush.linearGradient(
                listOf(Pub.ShieldSideTop, Pub.ShieldSideBot),
                start = Offset(0f, 18 * s), end = Offset(0f, 138 * s),
            ),
        )
        // 正面
        val face = shieldPath(s, 0f)
        drawPath(
            face,
            brush = Brush.linearGradient(
                listOf(Pub.ShieldFaceTop, Pub.ShieldFaceMid, Pub.ShieldFaceBot),
                start = Offset(24 * s, 0f), end = Offset(84 * s, 150 * s),
            ),
        )
        // 边缘高光描边
        drawPath(
            face,
            brush = Brush.linearGradient(
                listOf(Color(0xFFE2EEFF), Color(0xFF3E66D6).copy(alpha = 0.25f)),
                start = Offset(0f, 7 * s), end = Offset(0f, 127 * s),
            ),
            style = Stroke(width = 1.8f * s),
        )
        // 面内的高光与暗部(裁剪到盾面)
        clipPath(face) {
            // 顶部大高光
            drawOval(
                brush = Brush.radialGradient(
                    0.0f to Color.White.copy(alpha = 0.85f),
                    0.5f to Color.White.copy(alpha = 0.14f),
                    1.0f to Color.Transparent,
                    center = Offset(40 * s, 16 * s),
                    radius = 48 * s,
                ),
                topLeft = Offset((46 - 42) * s, (25 - 21) * s),
                size = Size(84 * s, 42 * s),
            )
            // 斜向反光带
            val diag = Path().apply {
                moveTo(-12 * s, 72 * s); lineTo(60 * s, 16 * s)
                lineTo(82 * s, 27 * s); lineTo(4 * s, 96 * s); close()
            }
            drawPath(diag, Color.White.copy(alpha = 0.10f))
            // 底部内阴影
            drawOval(
                color = Color(0xFF143178).copy(alpha = 0.42f),
                topLeft = Offset((60 - 48) * s, (122 - 28) * s),
                size = Size(96 * s, 56 * s),
            )
            // 左侧描边弧
            val arc = Path().apply {
                moveTo(19 * s, 27 * s); lineTo(19 * s, 64 * s)
                cubicTo(19 * s, 92 * s, 35 * s, 112 * s, 58 * s, 122 * s)
            }
            drawPath(arc, Color(0xFFD6E7FF).copy(alpha = 0.6f), style = Stroke(width = 2.8f * s, cap = StrokeCap.Round))
        }
        // 字形
        when (glyph) {
            ShieldGlyph.Magnifier -> {
                val cy = 60 * s
                drawCircle(Color(0xFF7CA8F5).copy(alpha = 0.18f), radius = 16 * s, center = Offset(55 * s, cy))
                drawCircle(
                    brush = glyphBrush, radius = 16 * s, center = Offset(55 * s, cy),
                    style = Stroke(width = 6 * s),
                )
                drawLine(
                    brush = glyphBrush,
                    start = Offset(67 * s, 72 * s), end = Offset(81 * s, 86 * s),
                    strokeWidth = 9 * s, cap = StrokeCap.Round,
                )
            }
            ShieldGlyph.Check -> {
                val check = Path().apply {
                    moveTo(44 * s, 61 * s); lineTo(55 * s, 72 * s); lineTo(78 * s, 47 * s)
                }
                drawPath(check, brush = glyphBrush, style = Stroke(width = 8 * s, cap = StrokeCap.Round))
            }
            ShieldGlyph.None -> {}
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 立体瓦片图标(claymorphism):侧壁 + 渐变面 + 顶部光泽,绝不扁平/果冻
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun ClayTile(
    faceBrush: Brush,
    edge: Color,
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    corner: Dp = 16.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    val shape = RoundedCornerShape(corner)
    // 原版"清透"立体:柔和彩色投影 + 顶部半身光泽,不做硬底面侧壁(避免玩具/廉价感)。
    Box(
        modifier.size(size)
            .shadow(8.dp, shape, clip = false, ambientColor = edge.copy(alpha = 0.5f), spotColor = edge.copy(alpha = 0.6f))
            .clip(shape)
            .background(faceBrush),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.fillMaxSize().background(
                Brush.verticalGradient(
                    0.0f to Color.White.copy(alpha = 0.34f),
                    0.45f to Color.Transparent,
                ),
            ),
        )
        content()
    }
}

@Composable
fun ClayIcon(
    icon: ImageVector,
    palette: Int,
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    corner: Dp = 16.dp,
    iconSize: Dp = 24.dp,
    contentDescription: String? = null,
) {
    ClayTile(
        faceBrush = Pub.tileBrush(palette),
        edge = Pub.tileEdge(palette),
        modifier = modifier,
        size = size,
        corner = corner,
    ) {
        Icon(icon, contentDescription, tint = Color.White, modifier = Modifier.size(iconSize))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 蓝渐变 HERO 头部 + 内页标题栏
// ─────────────────────────────────────────────────────────────────────────────
/** 画出 hero 的多层网格渐变:底色线性 + 右上 + 左下两处彩色光晕 + 细点阵。 */
private fun DrawScope.drawHeroMesh(palette: HeroPalette) {
    // 底色线性(≈158deg:自右上到左下)
    drawRect(
        brush = Brush.linearGradient(
            palette.base,
            start = Offset(size.width, 0f),
            end = Offset(0f, size.height),
        ),
    )
    // 右上青色光晕
    drawRect(
        brush = Brush.radialGradient(
            0.0f to palette.glowTopRight,
            0.5f to Color.Transparent,
            center = Offset(size.width * 0.92f, size.height * 0.02f),
            radius = size.width * 0.98f,
        ),
    )
    // 左下紫色光晕
    drawRect(
        brush = Brush.radialGradient(
            0.0f to palette.glowBottomLeft,
            0.55f to Color.Transparent,
            center = Offset(size.width * 0.06f, size.height * 1.06f),
            radius = size.width * 0.98f,
        ),
    )
    // 细点阵(右上角浓、向下淡出)
    val step = 18.dp.toPx()
    val r = 0.9.dp.toPx()
    var y = 0f
    while (y < size.height) {
        var x = 0f
        while (x < size.width) {
            val d = hypot(x - size.width * 0.8f, y) / size.width
            val a = (0.16f * (1f - d / 0.95f)).coerceIn(0f, 0.16f)
            if (a > 0.012f) drawCircle(Color.White.copy(alpha = a), radius = r, center = Offset(x, y))
            x += step
        }
        y += step
    }
}

@Composable
fun PubHero(
    modifier: Modifier = Modifier,
    palette: HeroPalette = Pub.heroBlue,
    bottomRadius: Dp = 30.dp,
    contentPadding: PaddingValues = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 22.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(bottomStart = bottomRadius, bottomEnd = bottomRadius)
    Box(modifier.fillMaxWidth().clip(shape)) {
        Canvas(Modifier.matchParentSize()) { drawHeroMesh(palette) }
        Column(
            Modifier.fillMaxWidth().statusBarsPadding().padding(contentPadding),
            content = content,
        )
    }
}

@Composable
fun PubNavBar(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            Box(
                Modifier.size(36.dp).clip(RoundedCornerShape(50))
                    .background(Color.White.copy(alpha = 0.14f))
                    .border(1.dp, Color.White.copy(alpha = 0.22f), RoundedCornerShape(50))
                    .pressScale(to = 0.9f, onClick = onBack),
                contentAlignment = Alignment.Center,
            ) {
                Icon(PubIcons.back, "返回", tint = Color(0xFFEAF2FF), modifier = Modifier.size(22.dp))
            }
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            if (subtitle != null) {
                Text(subtitle, color = Color.White.copy(alpha = 0.78f), fontSize = 11.5.sp, modifier = Modifier.padding(top = 3.dp))
            }
        }
        trailing()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 按钮
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun PrimaryCta(
    text: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    brush: Brush = Pub.ctaBrush(),
    height: Dp = 54.dp,
    contentColor: Color = Color.White,
    iconLeading: Boolean = true,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(16.dp)
    Box(
        modifier.fillMaxWidth().height(height)
            .shadow(18.dp, shape, clip = false, spotColor = Pub.Blue.copy(alpha = 0.6f))
            .clip(shape).background(brush).pressScale(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            if (icon != null && iconLeading) Icon(icon, null, tint = contentColor, modifier = Modifier.size(20.dp))
            Text(text, color = contentColor, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            if (icon != null && !iconLeading) Icon(icon, null, tint = contentColor, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
fun SecondaryButton(
    text: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier.height(50.dp).clip(shape).background(Pub.Card)
            .border(1.dp, Pub.Hair, shape).pressScale(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            Modifier.padding(horizontal = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (icon != null) Icon(icon, null, tint = Pub.Blue, modifier = Modifier.size(18.dp))
            Text(text, color = Pub.Blue, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

/**
 * Result provenance/release-gate banner shared by result and report screens.
 * Invalid or simulated data remains visually explicit even when the user scrolls past the hero copy.
 */
@Composable
fun ResultProvenanceBanner(
    ui: PubResultUi,
    modifier: Modifier = Modifier,
) {
    val publishable = ui.canIssueCertificate
    val bg = if (publishable) Pub.OkB else Pub.WarnB
    val border = if (publishable) Color(0xFFD4EEE2) else Color(0xFFF0D5A5)
    val fg = if (publishable) Pub.Ok else Pub.WarnD
    val detail = if (publishable) Color(0xFF397A60) else Pub.WarnD2
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(bg)
            .border(1.dp, border, RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(
            if (publishable) PubIcons.verified else PubIcons.warning,
            contentDescription = null,
            tint = fg,
            modifier = Modifier.size(19.dp),
        )
        Column(Modifier.weight(1f)) {
            Text(ui.evidenceStatusLabel, color = fg, fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
            Text(
                ui.evidenceStatusDetail,
                color = detail,
                fontSize = 11.sp,
                lineHeight = 16.sp,
                modifier = Modifier.padding(top = 3.dp),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 卡片 / 区块标题
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun PubCard(
    modifier: Modifier = Modifier,
    corner: Dp = 18.dp,
    contentPadding: PaddingValues = PaddingValues(0.dp),
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(corner)
    val base = modifier
        .shadow(14.dp, shape, clip = false, ambientColor = Pub.ShadowCard, spotColor = Pub.ShadowCard)
        .clip(shape).background(Pub.Card).border(1.dp, Pub.Hair, shape)
    Box(if (onClick != null) base.pressScale(to = 0.985f, onClick = onClick) else base) {
        Column(Modifier.padding(contentPadding), content = content)
    }
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    action: String? = null,
    onAction: (() -> Unit)? = null,
    contentPadding: PaddingValues = PaddingValues(start = 22.dp, end = 22.dp, top = 26.dp, bottom = 13.dp),
) {
    Row(
        modifier.fillMaxWidth().padding(contentPadding),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, color = Pub.Ink, fontSize = 17.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        if (action != null) {
            if (onAction != null) {
                Box(Modifier.pressScale(to = 0.95f) { onAction() }) {
                    Text(action, color = Pub.Blue, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
                }
            } else {
                Text(action, color = Pub.Ink3, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 结论 chip / pill
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun VerdictChip(kind: VerdictKind, modifier: Modifier = Modifier, text: String = kind.label()) {
    val tint = verdictTint(kind)
    Row(
        modifier.clip(RoundedCornerShape(9.dp)).background(verdictContainer(kind))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(Modifier.size(5.dp).clip(RoundedCornerShape(50)).background(tint))
        Text(text, color = tint, fontSize = 11.5.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun Pill(
    text: String,
    modifier: Modifier = Modifier,
    dotColor: Color = Pub.Ok,
) {
    Row(
        modifier.clip(RoundedCornerShape(9.dp)).background(Pub.Bg)
            .border(1.dp, Pub.Hair, RoundedCornerShape(9.dp))
            .padding(horizontal = 11.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(dotColor))
        Text(text, color = Pub.Ink2, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 记录行(缩略图 + 信息 + 结论)
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun RecordRow(
    record: PubRecord,
    modifier: Modifier = Modifier,
    onClick: () -> Unit = {},
) {
    val shape = RoundedCornerShape(18.dp)
    Row(
        modifier.fillMaxWidth()
            .shadow(14.dp, shape, clip = false, ambientColor = Pub.ShadowCard, spotColor = Pub.ShadowCard)
            .clip(shape).background(Pub.Card).border(1.dp, Pub.Hair, shape)
            .pressScale(to = 0.975f, onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // 缩略图 + 角标
        Box(Modifier.size(56.dp).clip(RoundedCornerShape(14.dp)).background(Pub.thumbBrush(record.kind))) {
            Icon(
                PubIcons.image, null, tint = Color.White,
                modifier = Modifier.align(Alignment.Center).size(24.dp),
            )
            Box(
                Modifier.align(Alignment.BottomEnd).size(21.dp)
                    .clip(RoundedCornerShape(topStart = 13.dp, bottomEnd = 12.dp))
                    .background(Color.White.copy(alpha = 0.92f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(verdictCornerIcon(record.kind), null, tint = verdictTint(record.kind), modifier = Modifier.size(13.dp))
            }
        }
        // 信息
        Column(Modifier.weight(1f)) {
            Text(
                record.name, color = Pub.Ink, fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Text(record.meta, color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 4.dp))
            // 进度条
            Box(Modifier.fillMaxWidth().padding(top = 9.dp).height(5.dp).clip(RoundedCornerShape(3.dp)).background(Color(0xFFEEF1F8))) {
                Box(
                    Modifier.fillMaxWidth(record.percent / 100f).height(5.dp)
                        .clip(RoundedCornerShape(3.dp)).background(Pub.thumbBrush(record.kind)),
                )
            }
        }
        // 结论
        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            VerdictChip(record.kind)
            Text(record.kind.percentLabel(record.percent), color = Pub.Ink3, fontSize = 11.sp)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 圆环进度(结果页)
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun RingProgress(
    percent: Float,
    progressColor: Color,
    modifier: Modifier = Modifier,
    diameter: Dp = 96.dp,
    trackColor: Color = Color.White.copy(alpha = 0.22f),
    strokeWidth: Dp = 9.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    Box(modifier.size(diameter), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val sw = strokeWidth.toPx()
            val arcSize = Size(size.width - sw, size.height - sw)
            val topLeft = Offset(sw / 2f, sw / 2f)
            drawArc(trackColor, -90f, 360f, false, topLeft = topLeft, size = arcSize, style = Stroke(sw, cap = StrokeCap.Round))
            drawArc(
                progressColor, -90f, 360f * percent / 100f, false,
                topLeft = topLeft, size = arcSize, style = Stroke(sw, cap = StrokeCap.Round),
            )
        }
        content()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 仿真二维码(凭证 / 引导页)
// ─────────────────────────────────────────────────────────────────────────────
@Composable
fun QrBox(
    modifier: Modifier = Modifier,
    boxSize: Dp = 84.dp,
    padding: Dp = 7.dp,
    content: String? = null,
) {
    val shape = RoundedCornerShape(12.dp)
    // 有内容则生成真实可扫二维码,否则退回占位图案。
    val matrix = content?.let { com.vpsg.jianyuanshield.core.QrEncoder.encode(it, 256) }
    Box(
        modifier.size(boxSize)
            .shadow(8.dp, shape, clip = false, spotColor = Pub.ShadowCard)
            .clip(shape).background(Color.White).border(1.dp, Pub.Hair, shape)
            .padding(padding),
    ) {
        Canvas(Modifier.fillMaxSize()) { if (matrix != null) drawQrMatrix(matrix) else drawFauxQr() }
    }
}

private fun DrawScope.drawQrMatrix(matrix: com.google.zxing.common.BitMatrix) {
    val n = matrix.width
    if (n <= 0) return
    val cell = size.minDimension / n
    val ink = Color(0xFF0F1A2E)
    for (y in 0 until n) {
        for (x in 0 until n) {
            if (matrix.get(x, y)) drawRect(ink, topLeft = Offset(x * cell, y * cell), size = Size(cell, cell))
        }
    }
}

private fun DrawScope.drawFauxQr() {
    val n = 25
    val cell = size.minDimension / n
    val ink = Color(0xFF0F1A2E)
    fun cellRect(r: Int, c: Int) {
        drawRect(ink, topLeft = Offset(c * cell, r * cell), size = Size(cell, cell))
    }
    fun finder(r0: Int, c0: Int) {
        for (r in 0 until 7) for (c in 0 until 7) cellRect(r0 + r, c0 + c)
        for (r in 1 until 6) for (c in 1 until 6) drawRect(
            Color.White, topLeft = Offset((c0 + c) * cell, (r0 + r) * cell), size = Size(cell, cell),
        )
        for (r in 2 until 5) for (c in 2 until 5) cellRect(r0 + r, c0 + c)
    }
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0)
    fun inFinder(r: Int, c: Int): Boolean =
        (r < 8 && c < 8) || (r < 8 && c >= n - 8) || (r >= n - 8 && c < 8)
    for (r in 0 until n) for (c in 0 until n) {
        if (!inFinder(r, c) && (r * c + r * 3 + c * 7) % 5 == 0) cellRect(r, c)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 底部 Tab
// ─────────────────────────────────────────────────────────────────────────────
enum class PubTab { Home, Detect, Records, Me }

@Composable
fun PubTabBar(
    selected: PubTab,
    onSelect: (PubTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth().background(Color.White.copy(alpha = 0.96f))) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Pub.Hair))
        Row(
            Modifier.fillMaxWidth().navigationBarsPadding().padding(top = 11.dp, bottom = 12.dp),
            horizontalArrangement = Arrangement.SpaceAround,
        ) {
            PubTabItem(PubIcons.home, "首页", selected == PubTab.Home) { onSelect(PubTab.Home) }
            PubTabItem(PubIcons.shieldCheck, "登记核验", selected == PubTab.Detect) { onSelect(PubTab.Detect) }
            PubTabItem(PubIcons.clock, "记录", selected == PubTab.Records) { onSelect(PubTab.Records) }
            PubTabItem(PubIcons.person, "我的", selected == PubTab.Me) { onSelect(PubTab.Me) }
        }
    }
}

@Composable
private fun PubTabItem(icon: ImageVector, label: String, on: Boolean, onClick: () -> Unit) {
    val tint by animateColorAsState(if (on) Pub.Blue else Pub.Ink3, tween(JysMotion.STATE), label = "tabTint")
    val iconScale by animateFloatAsState(
        targetValue = if (on) 1.12f else 1f,
        animationSpec = spring(dampingRatio = 0.55f, stiffness = 380f),
        label = "tabScale",
    )
    Column(
        Modifier.clip(RoundedCornerShape(12.dp)).pressScale(to = 0.92f, onClick = onClick).padding(horizontal = 14.dp, vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Icon(icon, label, tint = tint, modifier = Modifier.size(22.dp).scale(iconScale))
        Text(label, color = tint, fontSize = 10.5.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Medium)
    }
}
