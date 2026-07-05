package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.animateIntAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.PubAnalysisBlock
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubResultUi
import com.vpsg.jianyuanshield.ui.pub.PubTone
import com.vpsg.jianyuanshield.ui.pub.VerdictKind
import com.vpsg.jianyuanshield.ui.pub.enterReveal
import com.vpsg.jianyuanshield.ui.pub.enterStd
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.RingProgress
import com.vpsg.jianyuanshield.ui.pub.SectionHeader

@Composable
fun PubReportScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onSaveCertificate: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val state by vm.state.collectAsState()
    val ui = (state as? UiState.Success)?.data
    if (ui == null) {
        Box(Modifier.fillMaxSize().background(Pub.Bg)) {
            Column(Modifier.fillMaxSize()) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 28.dp)) {
                    PubNavBar("完整分析", onBack = onBack)
                }
                Spacer(Modifier.weight(1f))
                PubTabBar(PubTab.Detect, onSelectTab)
            }
        }
        return
    }
    ReportContent(ui, onBack, onSaveCertificate, onSelectTab)
}

@Composable
private fun ReportContent(
    ui: PubResultUi,
    onBack: () -> Unit,
    onSaveCertificate: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }
    val tone = ui.verdict.toReportTone()
    val pct by animateIntAsState(
        targetValue = if (play) ui.headlinePercent else 0,
        animationSpec = tween(1000, easing = FastOutSlowInEasing),
        label = "pct",
    )
    val ringFrac by animateFloatAsState(
        targetValue = if (play) ui.headlinePercent.toFloat() else 0f,
        animationSpec = tween(JysMotion.RING, easing = JysMotion.easeStd),
        label = "ringFrac",
    )
    var visibleConclusion by remember { mutableStateOf(false) }
    val blockCount = ui.analysisBlocks.size
    val visibleBlocks = remember(blockCount) { Array(blockCount) { mutableStateOf(false) } }
    LaunchedEffect(Unit) {
        delay(80L)
        visibleConclusion = true
        visibleBlocks.forEachIndexed { index, st ->
            delay(if (index == 0) 200L else 150L)
            st.value = true
        }
    }
    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 60.dp)) {
                    PubNavBar("完整分析", subtitle = "${ui.certName} · 逐项依据说明", onBack = onBack)
                }

                Column(Modifier.offset(y = (-46).dp)) {
                    AnimatedVisibility(visibleConclusion, enter = enterReveal()) {
                        Row(
                            Modifier.padding(horizontal = 16.dp).fillMaxWidth()
                                .clip(RoundedCornerShape(20.dp))
                                .background(toneSoftBg(tone))
                                .border(1.dp, toneSoftBorder(tone), RoundedCornerShape(20.dp))
                                .padding(18.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp),
                        ) {
                            RingProgress(percent = ringFrac, progressColor = toneText(tone), diameter = 78.dp, trackColor = toneText(tone).copy(alpha = 0.18f), strokeWidth = 7.dp) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text("$pct%", color = toneText(tone), fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                                    Text(ui.headlineLabel, color = toneText(tone), fontSize = 9.5.sp, fontWeight = FontWeight.SemiBold)
                                }
                            }
                            Column {
                                Text(ui.title, color = toneDeep(tone), fontSize = 18.sp, fontWeight = FontWeight.ExtraBold)
                                Text(ui.desc, color = toneDeep(tone), fontSize = 12.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 7.dp))
                            }
                        }
                    }

                    SectionHeader("每一项是怎么判断的")
                    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                        ui.analysisBlocks.forEachIndexed { i, block ->
                            AnimatedVisibility(visibleBlocks.getOrNull(i)?.value ?: true, enter = enterStd(0)) {
                                AnalysisBlock(block, play = play, index = i)
                            }
                        }
                    }

                    // 综合判断说明
                    Column(
                        Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp).fillMaxWidth()
                            .clip(RoundedCornerShape(18.dp))
                            .background(Brush.linearGradient(listOf(Color(0xFFEAF1FE), Color(0xFFEFEBFF))))
                            .border(1.dp, Color(0xFFE5E9FB), RoundedCornerShape(18.dp))
                            .padding(horizontal = 18.dp, vertical = 16.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(PubIcons.help, null, tint = Pub.Blue, modifier = Modifier.size(17.dp))
                            Text("我们怎么给出这个结论", color = Pub.Ink, fontSize = 13.5.sp, fontWeight = FontWeight.Bold)
                        }
                        Text(
                            ui.summaryText,
                            color = Pub.Ink2, fontSize = 12.5.sp, lineHeight = 20.sp, modifier = Modifier.padding(top = 9.dp),
                        )
                    }

                    SectionHeader("这次鉴别的信息")
                    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                        ui.metaInfo.forEachIndexed { i, (k, v) ->
                            InfoKv(metaIcon(i), k, v, divider = i < ui.metaInfo.lastIndex)
                        }
                    }

                    // 证据指纹(真实 sha256)
                    if (ui.sha256.isNotEmpty()) {
                        SectionHeader("证据指纹 · SHA-256")
                        PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
                            ui.sha256.forEachIndexed { i, (k, v) ->
                                Column(Modifier.padding(top = if (i == 0) 0.dp else 10.dp)) {
                                    Text(k, color = Pub.Ink2, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                    Text(
                                        if (v.length > 24) "${v.take(12)}…${v.takeLast(12)}" else v,
                                        color = Pub.Ink3, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp),
                                    )
                                }
                            }
                        }
                    }

                    PrimaryCta("保存这份凭证", Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp), icon = PubIcons.save, onClick = onSaveCertificate)

                    Row(Modifier.padding(start = 22.dp, end = 22.dp, top = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(PubIcons.info, null, tint = Pub.Ink3, modifier = Modifier.size(14.dp).padding(top = 1.dp))
                        Text(
                            "结论由溯源水印模型分析得出,仅帮你做参考判断,不作为法律或司法鉴定依据。",
                            color = Pub.Ink3, fontSize = 11.sp, lineHeight = 17.sp,
                        )
                    }

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

private fun metaIcon(i: Int): ImageVector = listOf(
    PubIcons.clock, PubIcons.bolt, PubIcons.shield, PubIcons.verified, PubIcons.help,
)[i % 5]

// ── tones ─────────────────────────────────────────────────────────────────────
private enum class Tone { Warn, Ok, Hi, Mut }

private fun VerdictKind.toReportTone(): Tone = when (this) {
    VerdictKind.Real -> Tone.Ok
    VerdictKind.Ai -> Tone.Warn
    VerdictKind.Tampered -> Tone.Hi
}

private fun PubTone.toReportTone(): Tone = when (this) {
    PubTone.Warn -> Tone.Warn
    PubTone.Ok -> Tone.Ok
    PubTone.Mut -> Tone.Mut
}

private fun toneText(tone: Tone): Color = when (tone) {
    Tone.Warn -> Pub.Warn; Tone.Ok -> Pub.Ok; Tone.Hi -> Pub.Hi; Tone.Mut -> Pub.Ink3
}

private fun toneDeep(tone: Tone): Color = when (tone) {
    Tone.Warn -> Pub.WarnD; Tone.Ok -> Color(0xFF0E7A50); Tone.Hi -> Color(0xFFB3261E); Tone.Mut -> Pub.Ink2
}

private fun toneSoftBg(tone: Tone): Color = when (tone) {
    Tone.Warn -> Pub.WarnB; Tone.Ok -> Pub.OkB; Tone.Hi -> Pub.HiB; Tone.Mut -> Color(0xFFEEF1F8)
}

private fun toneSoftBorder(tone: Tone): Color = when (tone) {
    Tone.Warn -> Color(0xFFF4E2BE); Tone.Ok -> Color(0xFFD4EEE2); Tone.Hi -> Color(0xFFF2C7C4); Tone.Mut -> Pub.Hair
}

private fun toneChipBg(tone: Tone): Color = when (tone) {
    Tone.Warn -> Pub.WarnB; Tone.Ok -> Pub.OkB; Tone.Hi -> Pub.HiB; Tone.Mut -> Color(0xFFEEF1F8)
}

private fun toneIconBrush(tone: Tone): Brush = when (tone) {
    Tone.Warn -> Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20)))
    Tone.Ok -> Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A)))
    Tone.Hi -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
    Tone.Mut -> Brush.linearGradient(listOf(Color(0xFFA7B2CC), Color(0xFF7C89A8)))
}

private fun toneBarBrush(tone: Tone): Brush = when (tone) {
    Tone.Warn -> Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20)))
    Tone.Ok -> Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A)))
    Tone.Hi -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
    Tone.Mut -> Brush.linearGradient(listOf(Color(0xFFB6C0D6), Color(0xFF8C98B4)))
}

@Composable
private fun AnalysisBlock(block: PubAnalysisBlock, play: Boolean, index: Int) {
    val tone = block.tone.toReportTone()
    val barDelay = 200 + index * 150
    val w by animateFloatAsState(
        targetValue = if (play) block.barFraction.coerceIn(0f, 1f) else 0f,
        animationSpec = tween(700, delayMillis = barDelay, easing = JysMotion.easeStd),
        label = "barWidth_$index",
    )
    PubCard(contentPadding = PaddingValues(horizontal = 17.dp, vertical = 16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(11.dp)) {
            Box(Modifier.size(36.dp).clip(RoundedCornerShape(11.dp)).background(toneIconBrush(tone)), contentAlignment = Alignment.Center) {
                Icon(block.icon, null, tint = Color.White, modifier = Modifier.size(19.dp))
            }
            Text(block.label, color = Pub.Ink, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Box(Modifier.clip(RoundedCornerShape(9.dp)).background(toneChipBg(tone)).padding(horizontal = 10.dp, vertical = 4.dp)) {
                Text(block.chip, color = toneText(tone), fontSize = 11.5.sp, fontWeight = FontWeight.Bold)
            }
        }
        Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.weight(1f).height(8.dp).clip(RoundedCornerShape(5.dp)).background(Color(0xFFEEF1F8))) {
                // 宽度变化走渲染层 scaleX(不触发逐帧 measure/layout)
                Box(
                    Modifier.fillMaxSize()
                        .graphicsLayer { scaleX = w; transformOrigin = TransformOrigin(0f, 0.5f) }
                        .clip(RoundedCornerShape(5.dp)).background(toneBarBrush(tone)),
                )
            }
            Text(block.barNumber, color = toneText(tone), fontSize = 13.sp, fontWeight = FontWeight.ExtraBold)
        }
        Box(Modifier.fillMaxWidth().padding(top = 13.dp).height(1.dp).background(Pub.Hair))
        Row(Modifier.padding(top = 13.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(PubIcons.search, null, tint = Pub.Blue, modifier = Modifier.size(14.dp))
            Text(block.whyLabel, color = Pub.Ink2, fontSize = 11.5.sp, fontWeight = FontWeight.Bold)
        }
        block.bullets.forEach { Bullet(it) }
    }
}

@Composable
private fun Bullet(text: String) {
    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.padding(top = 7.dp).size(5.dp).clip(RoundedCornerShape(50)).background(Color(0xFFC2CCE0)))
        Text(text, color = Pub.Ink2, fontSize = 12.5.sp, lineHeight = 19.sp)
    }
}

@Composable
private fun InfoKv(icon: ImageVector, key: String, value: String, divider: Boolean) {
    Column {
        Row(Modifier.fillMaxWidth().padding(vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = Pub.Ink3, modifier = Modifier.size(15.dp))
            Text(key, color = Pub.Ink2, fontSize = 13.sp, modifier = Modifier.padding(start = 7.dp).weight(1f))
            Text(value, color = Pub.Ink, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
        }
        if (divider) Box(Modifier.fillMaxWidth().height(1.dp).background(Pub.Hair))
    }
}
