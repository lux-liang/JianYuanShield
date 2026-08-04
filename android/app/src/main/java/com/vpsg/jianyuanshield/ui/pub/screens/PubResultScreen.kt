package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.animateIntAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
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
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.vpsg.jianyuanshield.core.ShareUtils
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubResultItem
import com.vpsg.jianyuanshield.ui.pub.PubResultUi
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.PubTone
import com.vpsg.jianyuanshield.ui.pub.RingProgress
import com.vpsg.jianyuanshield.ui.pub.ResultProvenanceBanner
import com.vpsg.jianyuanshield.ui.pub.SecondaryButton
import com.vpsg.jianyuanshield.ui.pub.enterStd
import kotlinx.coroutines.delay

@Composable
fun PubResultScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onSaveCertificate: () -> Unit,
    onOpenReport: () -> Unit,
    onRetry: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val state by vm.state.collectAsState()
    when (val s = state) {
        is UiState.Success -> ResultContent(s.data, onBack, onSaveCertificate, onOpenReport, onRetry, onSelectTab)
        is UiState.Error -> ResultError(s.message, onBack, onRetry, onSelectTab)
        else -> ResultLoading(onBack, onSelectTab)
    }
}

@Composable
private fun ResultContent(
    ui: PubResultUi,
    onBack: () -> Unit,
    onSaveCertificate: () -> Unit,
    onOpenReport: () -> Unit,
    onRetry: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val context = LocalContext.current
    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }

    val ringFrac by animateFloatAsState(
        targetValue = if (play) ui.headlinePercent.toFloat() else 0f,
        animationSpec = tween(JysMotion.RING, easing = JysMotion.easeStd),
        label = "ringFrac",
    )
    val pct by animateIntAsState(
        targetValue = if (play) ui.headlinePercent else 0,
        animationSpec = tween(JysMotion.RING, easing = JysMotion.easeStd),
        label = "pct",
    )

    var overlayVisible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { delay(400); overlayVisible = true }

    var row0Visible by remember { mutableStateOf(false) }
    var row1Visible by remember { mutableStateOf(false) }
    var adviceVisible by remember { mutableStateOf(false) }
    var actionsVisible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(300); row0Visible = true
        delay(150); row1Visible = true
        delay(150); adviceVisible = true
        delay(150); actionsVisible = true
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(
                    palette = ui.heroPalette,
                    contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 60.dp),
                ) {
                    PubNavBar("保护链路评估结果", subtitle = "${ui.certName} · 刚刚完成", onBack = onBack)
                    Row(
                        Modifier.fillMaxWidth().padding(top = 18.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(18.dp),
                    ) {
                        RingProgress(percent = ringFrac, progressColor = Color.White, diameter = 96.dp) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("$pct%", color = Color.White, fontSize = 27.sp, fontWeight = FontWeight.ExtraBold)
                                Text(ui.headlineLabel, color = Color.White.copy(alpha = 0.85f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                            }
                        }
                        Column {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(ui.title, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                                Box(
                                    Modifier.clip(RoundedCornerShape(8.dp)).background(Color.White.copy(alpha = 0.2f))
                                        .border(1.dp, Color.White.copy(alpha = 0.32f), RoundedCornerShape(8.dp))
                                        .padding(horizontal = 9.dp, vertical = 3.dp),
                                ) { Text(ui.badge, color = Color.White, fontSize = 11.5.sp, fontWeight = FontWeight.Bold) }
                            }
                            Text(
                                ui.desc,
                                color = Color.White.copy(alpha = 0.9f), fontSize = 12.5.sp, lineHeight = 18.sp,
                                modifier = Modifier.padding(top = 9.dp),
                            )
                        }
                    }
                }

                Column(Modifier.offset(y = (-46).dp)) {
                    ResultProvenanceBanner(
                        ui,
                        Modifier.padding(start = 16.dp, end = 16.dp, bottom = 10.dp),
                    )

                    // 预览 + 真实热力图叠层
                    Box(
                        Modifier.padding(horizontal = 16.dp).fillMaxWidth().height(208.dp)
                            .shadow(18.dp, RoundedCornerShape(18.dp), clip = false, spotColor = Color(0x6B142D6E), ambientColor = Color(0x6B142D6E))
                            .clip(RoundedCornerShape(18.dp))
                            .background(Brush.linearGradient(listOf(Color(0xFFDFE6F2), Color(0xFFC5CFE2), Color(0xFFAEB9D2))))
                            .border(1.dp, Pub.Hair, RoundedCornerShape(18.dp)),
                    ) {
                        if (ui.previewUrl != null) {
                            AsyncImage(
                                model = ui.previewUrl,
                                contentDescription = "链路评估图片",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            Icon(PubIcons.image, null, tint = Color(0xFF9AA6C2), modifier = Modifier.align(Alignment.Center).size(46.dp))
                        }
                        // 真实残差热力图(服务器返回),揭示式淡入叠加
                        if (ui.heatmapUrl != null) {
                        this@Column.AnimatedVisibility(
                                visible = overlayVisible,
                                enter = fadeIn(tween(420)),
                                modifier = Modifier.fillMaxSize(),
                            ) {
                                AsyncImage(
                                    model = ui.heatmapUrl,
                                    contentDescription = "残差热力图",
                                    contentScale = ContentScale.Crop,
                                    alpha = 0.55f,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            }
                        }
                        if (ui.annotation != null) {
                            Row(
                                Modifier.align(Alignment.BottomStart).padding(12.dp).clip(RoundedCornerShape(10.dp))
                                    .background(Color(0x9E0F1A2E)).padding(horizontal = 11.dp, vertical = 5.dp),
                                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp),
                            ) {
                                Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(Pub.Cyan))
                                Text(ui.annotation, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                            }
                        }
                    }

                    // 分项结果 2×2(真实指标)
                    val items = ui.items
                    AnimatedVisibility(visible = row0Visible, enter = enterStd()) {
                        Row(
                            Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            items.getOrNull(0)?.let { ResultItemCard(it, Modifier.weight(1f)) }
                            items.getOrNull(1)?.let { ResultItemCard(it, Modifier.weight(1f)) }
                        }
                    }
                    AnimatedVisibility(visible = row1Visible, enter = enterStd()) {
                        Row(
                            Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            items.getOrNull(2)?.let { ResultItemCard(it, Modifier.weight(1f)) }
                            items.getOrNull(3)?.let { ResultItemCard(it, Modifier.weight(1f)) }
                        }
                    }

                    // 结论建议(随结论着色)
                    AnimatedVisibility(visible = adviceVisible, enter = enterStd()) {
                        val tone = verdictTone(ui)
                        Row(
                            Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp).fillMaxWidth()
                                .clip(RoundedCornerShape(16.dp)).background(toneSoftBg(tone))
                                .border(1.dp, toneSoftBorder(tone), RoundedCornerShape(16.dp))
                                .padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(13.dp),
                        ) {
                            ToneTile(tone, verdictIcon(ui), 38.dp, 11.dp, 20.dp)
                            Text(ui.desc, color = toneDeep(tone), fontSize = 13.5.sp, fontWeight = FontWeight.Bold, lineHeight = 19.sp)
                        }
                    }

                    AnimatedVisibility(visible = actionsVisible, enter = enterStd()) {
                        Column {
                            if (ui.canIssueCertificate) {
                                PrimaryCta(
                                    "生成来源核验凭证",
                                    Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp),
                                    icon = PubIcons.save,
                                    onClick = onSaveCertificate,
                                )
                            } else {
                                CertificateUnavailableNotice(
                                    Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp),
                                )
                            }
                            Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                SecondaryButton("分享结果", Modifier.weight(1f), icon = PubIcons.share) {
                                    ShareUtils.shareText(
                                        context,
                                        "【鉴源盾】${ui.evidenceStatusLabel}\n${ui.evidenceStatusDetail}\n" +
                                            "水印验证结果:${ui.title} · ${ui.headlineLabel} ${ui.headlinePercent}%\n" +
                                            "图片:${ui.certName}\n任务编号 ${ui.taskId}",
                                    )
                                }
                                SecondaryButton("再验一张", Modifier.weight(1f), icon = PubIcons.refresh, onClick = onRetry)
                            }

                            PubCard(
                                Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp),
                                corner = 16.dp,
                                contentPadding = PaddingValues(16.dp),
                                onClick = onOpenReport,
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(13.dp)) {
                                    Box(
                                        Modifier.size(38.dp).clip(RoundedCornerShape(11.dp))
                                            .background(Brush.linearGradient(listOf(Color(0xFF5A92FF), Color(0xFF235FD8)))),
                                        contentAlignment = Alignment.Center,
                                    ) { Icon(PubIcons.doc, null, tint = Color.White, modifier = Modifier.size(19.dp)) }
                                    Column(Modifier.weight(1f)) {
                                        Text("查看完整分析", color = Pub.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                                        Text("逐项依据 · 指标 · 证据指纹", color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 3.dp))
                                    }
                                    Icon(PubIcons.chevronRight, null, tint = Color(0xFF8893C4), modifier = Modifier.size(20.dp))
                                }
                            }

                            Spacer(Modifier.height(20.dp))
                        }
                    }
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun ResultLoading(onBack: () -> Unit, onSelectTab: (PubTab) -> Unit) {
    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 28.dp)) {
                PubNavBar("保护链路评估结果", onBack = onBack)
            }
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Pub.Blue, strokeWidth = 3.dp)
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun ResultError(message: String, onBack: () -> Unit, onRetry: () -> Unit, onSelectTab: (PubTab) -> Unit) {
    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            PubHero(
                palette = Pub.heroRed,
                contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 40.dp),
            ) {
                PubNavBar("保护链路评估失败", subtitle = "未生成任何模拟成功结果", onBack = onBack)
            }
            Column(Modifier.weight(1f).padding(16.dp)) {
                PubCard(contentPadding = PaddingValues(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        ToneTile(ItemTone.Warn, PubIcons.warning, 38.dp, 11.dp, 20.dp)
                        Text(message, color = Pub.Ink2, fontSize = 13.sp, lineHeight = 19.sp)
                    }
                }
                PrimaryCta("重新评估", Modifier.padding(top = 16.dp), icon = PubIcons.refresh, onClick = onRetry)
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun CertificateUnavailableNotice(modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Pub.WarnB)
            .border(1.dp, Color(0xFFF4E2BE), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(PubIcons.warning, null, tint = Pub.Warn, modifier = Modifier.size(18.dp))
        Column {
            Text("来源核验凭证不可用", color = Pub.WarnD, fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
            Text(
                "模拟结果或 claim_valid=false 的结果不能生成、保存或分享凭证。",
                color = Pub.WarnD2, fontSize = 11.sp, lineHeight = 16.sp, modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

// ── tones ─────────────────────────────────────────────────────────────────────
private enum class ItemTone { Warn, Ok, Hi, Mut }

private fun PubTone.toItemTone(): ItemTone = when (this) {
    PubTone.Warn -> ItemTone.Warn
    PubTone.Ok -> ItemTone.Ok
    PubTone.Mut -> ItemTone.Mut
}

private fun verdictTone(ui: PubResultUi): ItemTone = when (ui.verdict) {
    com.vpsg.jianyuanshield.ui.pub.VerdictKind.Real -> ItemTone.Ok
    com.vpsg.jianyuanshield.ui.pub.VerdictKind.Ai -> ItemTone.Warn
    com.vpsg.jianyuanshield.ui.pub.VerdictKind.Tampered -> ItemTone.Hi
}

private fun verdictIcon(ui: PubResultUi): ImageVector = when (ui.verdict) {
    com.vpsg.jianyuanshield.ui.pub.VerdictKind.Real -> PubIcons.shieldCheck
    else -> PubIcons.warning
}

private fun toneTextColor(tone: ItemTone): Color = when (tone) {
    ItemTone.Warn -> Pub.Warn
    ItemTone.Ok -> Pub.Ok
    ItemTone.Hi -> Pub.Hi
    ItemTone.Mut -> Pub.Ink3
}

private fun toneDeep(tone: ItemTone): Color = when (tone) {
    ItemTone.Warn -> Pub.WarnD
    ItemTone.Ok -> Color(0xFF0E7A50)
    ItemTone.Hi -> Color(0xFFB3261E)
    ItemTone.Mut -> Pub.Ink2
}

private fun toneSoftBg(tone: ItemTone): Color = when (tone) {
    ItemTone.Warn -> Pub.WarnB
    ItemTone.Ok -> Pub.OkB
    ItemTone.Hi -> Pub.HiB
    ItemTone.Mut -> Color(0xFFEEF1F8)
}

private fun toneSoftBorder(tone: ItemTone): Color = when (tone) {
    ItemTone.Warn -> Color(0xFFF4E2BE)
    ItemTone.Ok -> Color(0xFFD4EEE2)
    ItemTone.Hi -> Color(0xFFF2C7C4)
    ItemTone.Mut -> Pub.Hair
}

private fun toneBrush(tone: ItemTone): Brush = when (tone) {
    ItemTone.Warn -> Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20)))
    ItemTone.Ok -> Brush.linearGradient(listOf(Color(0xFF52C98E), Color(0xFF1C9C6A)))
    ItemTone.Hi -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
    ItemTone.Mut -> Brush.linearGradient(listOf(Color(0xFFA7B2CC), Color(0xFF7C89A8)))
}

@Composable
private fun ToneTile(tone: ItemTone, icon: ImageVector, size: Dp, corner: Dp, iconSize: Dp) {
    Box(Modifier.size(size).clip(RoundedCornerShape(corner)).background(toneBrush(tone)), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = Color.White, modifier = Modifier.size(iconSize))
    }
}

@Composable
private fun ResultItemCard(item: PubResultItem, modifier: Modifier = Modifier) {
    val tone = item.tone.toItemTone()
    PubCard(modifier, corner = 16.dp, contentPadding = PaddingValues(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 13.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            ToneTile(tone, item.icon, 32.dp, 10.dp, 17.dp)
            Text(item.label, color = Pub.Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
        Text(item.value, color = toneTextColor(tone), fontSize = 21.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(top = 11.dp))
        Text(item.sub, color = Pub.Ink3, fontSize = 11.sp, modifier = Modifier.padding(top = 3.dp))
    }
}
