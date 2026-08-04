package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.pub.ClayTile
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.LearnArticle
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubSample
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar

private val articleIcons = listOf(PubIcons.doc, PubIcons.ai, PubIcons.faceSwap, PubIcons.shieldCheck, PubIcons.warning)

@Composable
fun PubLearnScreen(
    onBack: () -> Unit,
    onOpenArticle: (Int) -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    // P0-③a: CategoryChip 选中状态
    var selectedCat by remember { mutableStateOf(0) }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 24.dp)) {
                    PubNavBar("用图安全课堂", onBack = onBack)
                    Text("认识合成图片风险", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(top = 20.dp))
                    Row(Modifier.padding(top = 13.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(PubIcons.shieldCheck, null, tint = Color(0xFFBDF1FF), modifier = Modifier.size(15.dp))
                        Text("了解 AI 图、假截图与换脸照的常见人工核查线索", color = Color.White.copy(alpha = 0.85f), fontSize = 12.sp)
                    }
                }

                // P0-③a + P0-④: 分类 chips，带选中状态与动画
                val catLabels = listOf("全部", "AI 生成", "换脸", "防骗", "隐藏水印")
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(9.dp),
                ) {
                    catLabels.forEachIndexed { idx, label ->
                        CategoryChip(
                            label = label,
                            on = selectedCat == idx,
                            onClick = { selectedCat = idx },
                        )
                    }
                }

                // 头条
                Column(
                    Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp).fillMaxWidth().height(134.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(Brush.linearGradient(listOf(Color(0xFF3A6FEC), Color(0xFF2742B0)))),
                ) {
                    Box(Modifier.fillMaxSize()) {
                        // 右上紫色光晕 + 左下青色光晕(对齐网页 .fbg 的两层 radial)
                        Box(
                            Modifier.size(190.dp).align(Alignment.TopEnd).offset(x = 50.dp, y = (-60).dp)
                                .background(Brush.radialGradient(listOf(Color(0x998A77F4), Color.Transparent))),
                        )
                        Box(
                            Modifier.size(170.dp).align(Alignment.BottomStart).offset(x = (-50).dp, y = 60.dp)
                                .background(Brush.radialGradient(listOf(Color(0x802EC6E0), Color.Transparent))),
                        )
                        Box(
                            Modifier.align(Alignment.TopStart).padding(start = 16.dp, top = 15.dp)
                                .clip(RoundedCornerShape(8.dp)).background(Color.White.copy(alpha = 0.18f))
                                .border(1.dp, Color.White.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
                                .padding(horizontal = 10.dp, vertical = 4.dp),
                        ) { Text("本周必看", color = Color.White, fontSize = 10.5.sp, fontWeight = FontWeight.Bold) }
                        Icon(
                            PubIcons.faceSwap, null, tint = Color.White.copy(alpha = 0.2f),
                            modifier = Modifier.align(Alignment.CenterEnd).padding(end = 14.dp).size(96.dp),
                        )
                        Column(Modifier.align(Alignment.BottomStart).padding(start = 16.dp, end = 16.dp, bottom = 14.dp)) {
                            Text("3 秒看懂 AI 换脸的破绽", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold)
                            Row(Modifier.padding(top = 9.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                FeatMeta(PubIcons.clock, "2 分钟")
                                FeatMeta(PubIcons.eye, "1.2 万人看过")
                            }
                        }
                    }
                }

                // P0-③b: 文章列表，ArticleRow 传 onClick
                Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                    PubSample.articles.forEachIndexed { i, a ->
                        ArticleRow(a, articleIcons[i % articleIcons.size], onClick = { onOpenArticle(i) })
                    }
                }

                Text(
                    "风险图片先核对原始发布渠道 · 本系统仅核验预登记来源凭证",
                    color = Pub.Ink3, fontSize = 11.5.sp, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(top = 20.dp),
                )

                Spacer(Modifier.height(20.dp))
            }
            PubTabBar(PubTab.Home, onSelectTab)
        }
    }
}

private fun articleFace(palette: Int): Brush = when (palette) {
    0 -> Brush.linearGradient(listOf(Color(0xFF5A92FF), Color(0xFF235FD8)))
    1 -> Brush.linearGradient(listOf(Color(0xFF2FD0C0), Color(0xFF0E9E94)))
    2 -> Brush.linearGradient(listOf(Color(0xFF9B7BF6), Color(0xFF5E3FD0)))
    3 -> Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20)))
    else -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
}

private fun articleEdge(palette: Int): Color = when (palette) {
    0 -> Color(0xFF1E48B2); 1 -> Color(0xFF0A726A); 2 -> Color(0xFF4124A8); 3 -> Color(0xFFBE5A11); else -> Color(0xFFA32A22)
}

// P0-③b: onClick 参数，整卡可点
@Composable
private fun ArticleRow(a: LearnArticle, icon: ImageVector, onClick: () -> Unit) {
    PubCard(contentPadding = PaddingValues(14.dp), onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            ClayTile(faceBrush = articleFace(a.palette), edge = articleEdge(a.palette), size = 60.dp, corner = 15.dp) {
                Icon(icon, null, tint = Color.White, modifier = Modifier.size(26.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(a.category, color = Pub.Blue, fontSize = 10.5.sp, fontWeight = FontWeight.Bold)
                Text(a.title, color = Pub.Ink, fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold, lineHeight = 20.sp, modifier = Modifier.padding(top = 4.dp))
                Row(Modifier.padding(top = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("${a.minutes} 分钟", color = Pub.Ink3, fontSize = 11.sp)
                    Text("·", color = Pub.Ink3, fontSize = 11.sp)
                    Text(a.views, color = Pub.Ink3, fontSize = 11.sp)
                }
            }
            Icon(PubIcons.chevronRight, null, tint = Color(0xFFC0C9DC), modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
private fun FeatMeta(icon: ImageVector, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Icon(icon, null, tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(13.dp))
        Text(text, color = Color.White.copy(alpha = 0.8f), fontSize = 11.sp)
    }
}

// P0-④: CategoryChip 带 scale + 文字色动画
@Composable
private fun CategoryChip(label: String, on: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(11.dp)

    // P0-④: scale 用 spring，弹感轻柔
    val chipScale by animateFloatAsState(
        targetValue = if (on) 1.05f else 1f,
        animationSpec = spring(dampingRatio = 0.5f, stiffness = 380f),
        label = "catChipScale",
    )
    // P0-④: 文字色动画
    val labelColor by animateColorAsState(
        targetValue = if (on) Color.White else Pub.Ink2,
        animationSpec = tween(JysMotion.STATE),
        label = "catChipLabel",
    )

    val base = if (on) Modifier.clip(shape).background(Pub.ctaBrush())
    else Modifier.clip(shape).background(Pub.Card).border(1.dp, Pub.Hair, shape)

    Box(
        base
            .scale(chipScale)
            .clickable(onClick = onClick)
            .padding(horizontal = 15.dp, vertical = 8.dp),
    ) {
        Text(label, color = labelColor, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
    }
}
