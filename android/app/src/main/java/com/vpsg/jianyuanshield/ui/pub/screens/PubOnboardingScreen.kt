package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.ClayTile
import com.vpsg.jianyuanshield.ui.pub.DashedHLine
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.Pill
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.QrBox
import com.vpsg.jianyuanshield.ui.pub.ShieldArt
import com.vpsg.jianyuanshield.ui.pub.ShieldGlyph
import com.vpsg.jianyuanshield.ui.pub.enterStd
import com.vpsg.jianyuanshield.ui.pub.pressScale
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val whiteBrush = Brush.linearGradient(listOf(Color.White, Color.White))

@Composable
fun PubOnboardingScreen(onFinish: () -> Unit) {
    val pager = rememberPagerState(pageCount = { 4 })
    val scope = rememberCoroutineScope()
    fun goNext(from: Int) { scope.launch { pager.animateScrollToPage(from + 1) } }

    Box(Modifier.fillMaxSize().background(Pub.onboardBrush())) {
        Canvas(Modifier.fillMaxSize()) { drawOnboardAtmosphere() }

        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize()) { page ->
            when (page) {
                0 -> SlideHero(
                    glyph = ShieldGlyph.Magnifier,
                    title = "这张图,是真是假?",
                    body = "假图越来越真,眼睛已经看不出来了。\n鉴源盾,帮你一键看穿。",
                    withChips = true,
                    currentPage = pager.currentPage,
                    ctaText = "下一步",
                    ctaIcon = PubIcons.chevronRight,
                    onCta = { goNext(0) },
                )
                1 -> SlideCaps(currentPage = pager.currentPage, onCta = { goNext(1) })
                2 -> SlidePrivacy(currentPage = pager.currentPage, onCta = { goNext(2) })
                else -> SlideHero(
                    glyph = ShieldGlyph.Check,
                    title = "准备好了,开始鉴别吧",
                    body = "从现在起,真假你自己说了算。",
                    withChips = false,
                    withBadges = true,
                    currentPage = pager.currentPage,
                    ctaText = "立即开始鉴别",
                    ctaIcon = PubIcons.search,
                    ctaIconLeading = true,
                    onCta = onFinish,
                )
            }
        }

        if (pager.currentPage < 3) {
            Box(
                Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(top = 8.dp, end = 16.dp)
                    .clip(RoundedCornerShape(22.dp)).background(Color.White.copy(alpha = 0.15f))
                    .border(1.dp, Color.White.copy(alpha = 0.26f), RoundedCornerShape(22.dp))
                    .pressScale(to = 0.94f) { onFinish() }
                    .padding(horizontal = 17.dp, vertical = 10.dp),
            ) { Text("跳过", color = Color.White.copy(alpha = 0.92f), fontSize = 13.sp, fontWeight = FontWeight.Medium) }
        }
    }
}

// ── 幻灯 1 / 4:盾牌主视觉 ──────────────────────────────────────────────────
@Composable
private fun SlideHero(
    glyph: ShieldGlyph,
    title: String,
    body: String,
    withChips: Boolean,
    currentPage: Int,
    ctaText: String,
    ctaIcon: ImageVector,
    onCta: () -> Unit,
    withBadges: Boolean = false,
    ctaIconLeading: Boolean = false,
) {
    // P1: stagger入场状态
    var chip0Visible by remember(currentPage) { mutableStateOf(false) }
    var chip1Visible by remember(currentPage) { mutableStateOf(false) }
    var badge0Visible by remember(currentPage) { mutableStateOf(false) }
    var badge1Visible by remember(currentPage) { mutableStateOf(false) }
    var badge2Visible by remember(currentPage) { mutableStateOf(false) }
    var badge3Visible by remember(currentPage) { mutableStateOf(false) }

    LaunchedEffect(currentPage) {
        if (withChips) {
            delay(200L)
            chip0Visible = true
            delay(70L)
            chip1Visible = true
        }
        if (withBadges) {
            delay(200L)
            badge0Visible = true
            delay(60L)
            badge1Visible = true
            delay(60L)
            badge2Visible = true
            delay(60L)
            badge3Visible = true
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        // 舞台
        Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
            // 光晕
            Box(
                Modifier.size(300.dp).clip(RoundedCornerShape(50)).background(
                    Brush.radialGradient(
                        0.0f to Color(0xAE6296FF),
                        0.40f to Color(0x4D78C8FF),
                        0.68f to Color(0x0078C8FF),
                    ),
                ),
            )
            Box(Modifier.size(300.dp).clip(RoundedCornerShape(50)).border(1.5.dp, Color(0x33BEDAFF), RoundedCornerShape(50)))
            Box(Modifier.size(230.dp).clip(RoundedCornerShape(50)).border(1.5.dp, Color(0x57BEDAFF), RoundedCornerShape(50)))
            val floatT = rememberInfiniteTransition(label = "shieldFloat")
            val dy by floatT.animateFloat(
                initialValue = -6f, targetValue = 6f,
                // P0-②: 替换 FastOutSlowInEasing 为 JysMotion.easeSine 消除极值二次抖动
                animationSpec = infiniteRepeatable(tween(2750, easing = JysMotion.easeSine), RepeatMode.Reverse),
                label = "dy",
            )
            ShieldArt(modifier = Modifier.graphicsLayer { translationY = dy.dp.toPx() }, width = if (glyph == ShieldGlyph.Magnifier) 184.dp else 170.dp, glyph = glyph)

            if (withChips) {
                this@Column.AnimatedVisibility(
                    visible = chip0Visible,
                    enter = enterStd(),
                    modifier = Modifier.align(Alignment.TopEnd).padding(top = 70.dp, end = 14.dp),
                ) {
                    FloatingChip(
                        PubIcons.ai, Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20))),
                        "疑似 AI 生成", "可能性 88%",
                    )
                }
                this@Column.AnimatedVisibility(
                    visible = chip1Visible,
                    enter = enterStd(),
                    modifier = Modifier.align(Alignment.BottomStart).padding(bottom = 70.dp, start = 12.dp),
                ) {
                    FloatingChip(
                        PubIcons.check, Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A))),
                        "真伪一眼看穿", "3 秒出结论",
                    )
                }
            }

            if (withBadges) {
                Row(
                    Modifier.align(Alignment.BottomCenter).padding(bottom = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    AnimatedVisibility(visible = badge0Visible, enter = enterStd()) { Badge(PubIcons.ai, 0, "AI 生成") }
                    AnimatedVisibility(visible = badge1Visible, enter = enterStd()) { Badge(PubIcons.faceSwap, 1, "换脸") }
                    AnimatedVisibility(visible = badge2Visible, enter = enterStd()) { Badge(PubIcons.tamper, 2, "P 图") }
                    AnimatedVisibility(visible = badge3Visible, enter = enterStd()) { Badge(PubIcons.watermark, 3, "水印") }
                }
            }
        }

        // 文案
        Column(Modifier.fillMaxWidth().padding(horizontal = 34.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, color = Color.White, fontSize = 31.sp, fontWeight = FontWeight.Black, textAlign = TextAlign.Center, lineHeight = 40.sp)
            Text(body, color = Color(0xFFE4EEFF).copy(alpha = 0.85f), fontSize = 13.5.sp, textAlign = TextAlign.Center, lineHeight = 23.sp, modifier = Modifier.padding(top = 14.dp))
        }

        SlideFoot(currentPage, ctaText, ctaIcon, ctaIconLeading, onCta)
    }
}

// ── 幻灯 2:四种能力 ────────────────────────────────────────────────────────
@Composable
private fun SlideCaps(currentPage: Int, onCta: () -> Unit) {
    // P1: 四张能力卡错时入场
    var card0Visible by remember(currentPage) { mutableStateOf(false) }
    var card1Visible by remember(currentPage) { mutableStateOf(false) }
    var card2Visible by remember(currentPage) { mutableStateOf(false) }
    var card3Visible by remember(currentPage) { mutableStateOf(false) }

    LaunchedEffect(currentPage) {
        delay(200L)
        card0Visible = true
        delay(80L)
        card1Visible = true
        delay(80L)
        card2Visible = true
        delay(80L)
        card3Visible = true
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Column(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.Center) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 34.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("拍一下,一秒看穿真假", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Black, textAlign = TextAlign.Center, lineHeight = 38.sp)
                Text("不管是群里转发的,还是新闻截图,\n一传给它,马上看出真假。", color = Color(0xFFE4EEFF).copy(alpha = 0.84f), fontSize = 13.sp, textAlign = TextAlign.Center, lineHeight = 22.sp, modifier = Modifier.padding(top = 13.dp))
            }
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 30.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    AnimatedVisibility(visible = card0Visible, enter = enterStd(), modifier = Modifier.weight(1f)) {
                        CapCard(PubIcons.ai, 0, "AI 画的图", "整张图都是 AI 画出来的", Modifier.fillMaxWidth())
                    }
                    AnimatedVisibility(visible = card1Visible, enter = enterStd(), modifier = Modifier.weight(1f)) {
                        CapCard(PubIcons.faceSwap, 1, "换脸冒充", "把别人的脸贴上去", Modifier.fillMaxWidth())
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    AnimatedVisibility(visible = card2Visible, enter = enterStd(), modifier = Modifier.weight(1f)) {
                        CapCard(PubIcons.tamper, 2, "P 图动手脚", "截图被涂改、拼接", Modifier.fillMaxWidth())
                    }
                    AnimatedVisibility(visible = card3Visible, enter = enterStd(), modifier = Modifier.weight(1f)) {
                        CapCard(PubIcons.watermark, 3, "删改水印", "来源标记被抹掉", Modifier.fillMaxWidth())
                    }
                }
            }
        }
        SlideFoot(currentPage, "下一步", PubIcons.chevronRight, false, onCta)
    }
}

// ── 幻灯 3:隐私 + 凭证 ─────────────────────────────────────────────────────
@Composable
private fun SlidePrivacy(currentPage: Int, onCta: () -> Unit) {
    // P1: 两张白卡错时入场
    var card0Visible by remember(currentPage) { mutableStateOf(false) }
    var card1Visible by remember(currentPage) { mutableStateOf(false) }

    LaunchedEffect(currentPage) {
        delay(200L)
        card0Visible = true
        delay(80L)
        card1Visible = true
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Column(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.Center) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 34.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("上传只为这次鉴别", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Black, textAlign = TextAlign.Center, lineHeight = 38.sp)
                Text("图片仅用于这次鉴别,会安全上传分析;\n每次还出一张凭证,家人扫一下就知真假。", color = Color(0xFFE4EEFF).copy(alpha = 0.84f), fontSize = 13.sp, textAlign = TextAlign.Center, lineHeight = 22.sp, modifier = Modifier.padding(top = 13.dp))
            }
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 30.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                // 隐私卡
                AnimatedVisibility(visible = card0Visible, enter = enterStd()) {
                    WhiteCard {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                            ClayIcon(PubIcons.phone, palette = 0, size = 56.dp, corner = 18.dp, iconSize = 27.dp)
                            Box(Modifier.width(56.dp).padding(horizontal = 10.dp), contentAlignment = Alignment.Center) {
                                DashedHLine(color = Color(0xFFC4D0E8))
                                Box(
                                    Modifier.size(30.dp).clip(RoundedCornerShape(50)).background(Color.White)
                                        .border(1.6.dp, Pub.Blue, RoundedCornerShape(50)),
                                    contentAlignment = Alignment.Center,
                                ) { Icon(PubIcons.lock, null, tint = Pub.Blue, modifier = Modifier.size(16.dp)) }
                            }
                            ClayTile(
                                faceBrush = Brush.linearGradient(listOf(Color(0xFFD7DEEC), Color(0xFFB2BFD4))),
                                edge = Color(0xFF9DAAC2), size = 56.dp, corner = 18.dp,
                            ) { Icon(PubIcons.cloud, null, tint = Color(0xFF8390AC), modifier = Modifier.size(27.dp)) }
                        }
                        PrivacyCaption(Modifier.padding(top = 15.dp))
                    }
                }
                // 凭证卡
                AnimatedVisibility(visible = card1Visible, enter = enterStd()) {
                    WhiteCard {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                            Box(
                                Modifier.size(32.dp).clip(RoundedCornerShape(10.dp))
                                    .background(Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A)))),
                                contentAlignment = Alignment.Center,
                            ) { Icon(PubIcons.shieldCheck, null, tint = Color.White, modifier = Modifier.size(18.dp)) }
                            Text("鉴别完成", color = Pub.Ok, fontSize = 14.5.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f))
                            Text("2026-06-15 14:32", color = Pub.Ink3, fontSize = 11.sp)
                        }
                        Row(Modifier.padding(top = 15.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Pill("已出真伪结论")
                                Pill("圈出有问题的地方")
                                Pill("带防伪编号")
                            }
                            QrBox(boxSize = 62.dp, padding = 5.dp)
                        }
                        Text(
                            "每次生成专属凭证,扫码就能核验真假",
                            color = Pub.Ink2, fontSize = 12.5.sp, textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                        )
                    }
                }
            }
        }
        SlideFoot(currentPage, "下一步", PubIcons.chevronRight, false, onCta)
    }
}

// ── 复用件 ─────────────────────────────────────────────────────────────────

// P0-①: currentPage 替换静态 active,dots 用动画宽度和颜色
@Composable
private fun SlideFoot(currentPage: Int, ctaText: String, ctaIcon: ImageVector, iconLeading: Boolean, onCta: () -> Unit) {
    Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(start = 30.dp, end = 30.dp, top = 24.dp, bottom = 32.dp)) {
        Row(Modifier.fillMaxWidth().padding(bottom = 20.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            for (i in 0 until 4) {
                val w by animateDpAsState(
                    targetValue = if (i == currentPage) 20.dp else 7.dp,
                    animationSpec = spring(stiffness = 300f),
                    label = "dotW$i",
                )
                val c by animateColorAsState(
                    targetValue = if (i == currentPage) Color.White else Color.White.copy(alpha = 0.4f),
                    animationSpec = tween(JysMotion.STATE),
                    label = "dotC$i",
                )
                Box(
                    Modifier.padding(horizontal = 4.dp).height(7.dp)
                        .width(w)
                        .clip(RoundedCornerShape(5.dp))
                        .background(c),
                )
            }
        }
        PrimaryCta(
            ctaText, icon = ctaIcon, brush = whiteBrush, height = 56.dp, contentColor = Pub.Blue,
            iconLeading = iconLeading, onClick = onCta,
        )
    }
}

@Composable
private fun FloatingChip(icon: ImageVector, iconBrush: Brush, title: String, sub: String, modifier: Modifier = Modifier) {
    Row(
        modifier.clip(RoundedCornerShape(15.dp)).background(Color.White.copy(alpha = 0.85f))
            .border(1.dp, Color.White, RoundedCornerShape(15.dp))
            .padding(horizontal = 13.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Box(Modifier.size(34.dp).clip(RoundedCornerShape(10.dp)).background(iconBrush), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = Color.White, modifier = Modifier.size(18.dp))
        }
        Column {
            Text(title, color = Pub.Ink, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            Text(sub, color = Pub.Ink3, fontSize = 10.sp, modifier = Modifier.padding(top = 2.dp))
        }
    }
}

@Composable
private fun Badge(icon: ImageVector, palette: Int, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ClayIcon(icon, palette = palette, size = 56.dp, corner = 17.dp, iconSize = 21.dp)
        Text(label, color = Color(0xFFE4EEFF).copy(alpha = 0.9f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun CapCard(icon: ImageVector, palette: Int, title: String, desc: String, modifier: Modifier = Modifier) {
    Column(
        modifier.clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.92f))
            .border(1.dp, Color.White, RoundedCornerShape(20.dp))
            .padding(start = 17.dp, end = 17.dp, top = 20.dp, bottom = 17.dp),
    ) {
        ClayIcon(icon, palette = palette, size = 60.dp, corner = 19.dp, iconSize = 25.dp)
        Text(title, color = Pub.Ink, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 14.dp))
        Text(desc, color = Pub.Ink2, fontSize = 11.5.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 5.dp))
    }
}

@Composable
private fun WhiteCard(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.92f))
            .border(1.dp, Color.White, RoundedCornerShape(20.dp)).padding(18.dp),
        content = content,
    )
}

@Composable
private fun PrivacyCaption(modifier: Modifier = Modifier) {
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = Pub.Ink)) { append("图片仅用于本次鉴别") }
            append(",安全上传、不作他用")
        },
        color = Pub.Ink2, fontSize = 12.5.sp, textAlign = TextAlign.Center,
        modifier = modifier.fillMaxWidth(),
    )
}

private fun DrawScope.drawOnboardAtmosphere() {
    // 三处主光晕(对应 onboarding.html .lt1:顶部蓝、右上紫、底部青)
    val glows = listOf(
        Triple(Offset(size.width * 0.50f, -size.height * 0.04f), Pub.onboardGlowTop.copy(alpha = 0.55f), size.width * 0.78f),
        Triple(Offset(size.width * 0.88f, size.height * 0.14f), Pub.onboardGlowPurple.copy(alpha = 0.45f), size.width * 0.62f),
        Triple(Offset(size.width * 0.50f, size.height * 1.10f), Pub.onboardGlowCyan.copy(alpha = 0.5f), size.width * 0.9f),
    )
    glows.forEach { (c, color, r) ->
        drawCircle(Brush.radialGradient(listOf(color, Color.Transparent), center = c, radius = r), radius = r, center = c)
    }
    // 角落补光,丰富层次
    drawCircle(
        Brush.radialGradient(listOf(Pub.onboardGlowTop.copy(alpha = 0.3f), Color.Transparent), center = Offset(size.width * 0.12f, size.height * 0.86f), radius = size.width * 0.5f),
        radius = size.width * 0.5f, center = Offset(size.width * 0.12f, size.height * 0.86f),
    )
    // 细点阵(顶部浓)
    val step = 22.dp.toPx()
    var y = 0f
    while (y < size.height) {
        var x = 0f
        while (x < size.width) {
            val a = (0.18f * (1f - y / (size.height * 0.7f))).coerceIn(0f, 0.18f)
            if (a > 0.012f) drawCircle(Color.White.copy(alpha = a), radius = 1.dp.toPx(), center = Offset(x, y))
            x += step
        }
        y += step
    }
}
