package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.vpsg.jianyuanshield.data.UiState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.enterHero

private enum class StepState { Done, Doing, Wait }

@Composable
fun PubDetectingScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onDone: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val image by vm.image.collectAsState()
    val fileName by vm.fileName.collectAsState()

    // P0-①: Animatable 驱动进度——先走到 70%,等真实结果返回再补满
    val prog = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        // 进入即触发真实推理(幂等);失败会在 VM 内回退本地演示数据
        if (vm.state.value is UiState.Idle) vm.run()
        prog.animateTo(0.7f, tween(1400, easing = JysMotion.easeStd))
        // 等待真实终态(成功或错误)
        snapshotFlow { vm.state.value }.first { it is UiState.Success || it is UiState.Error }
        prog.animateTo(1f, tween(500, easing = JysMotion.easeStd))
        delay(300)
        onDone()
    }

    // P1-③: hero entrance for the preview block
    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }

    val p = prog.value

    // P0-②: derive each step's state from progress
    val step1 = if (p < 0.25f) StepState.Doing else StepState.Done
    val step2 = when {
        p < 0.25f -> StepState.Wait
        p < 0.55f -> StepState.Doing
        else -> StepState.Done
    }
    val step3 = when {
        p < 0.55f -> StepState.Wait
        p < 1f -> StepState.Doing
        else -> StepState.Done
    }
    val step4 = if (p < 1f) StepState.Wait else StepState.Done

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 56.dp)) {
                    PubNavBar("正在鉴别…", subtitle = "已上传到鉴别服务器,正在分析", onBack = onBack)
                }

                Column(Modifier.offset(y = (-44).dp)) {
                    // P1-③: wrap preview with AnimatedVisibility + enterHero
                    AnimatedVisibility(visible = play, enter = enterHero()) {
                        BoxWithConstraints(
                            Modifier.padding(horizontal = 16.dp).fillMaxWidth().aspectRatio(4f / 3f)
                                .clip(RoundedCornerShape(20.dp))
                                .background(Brush.linearGradient(listOf(Color(0xFF1A2D55), Color(0xFF1E2F5C)))),
                        ) {
                            val maxH = maxHeight
                            // 真实图片预览(无则占位)
                            if (image != null) {
                                AsyncImage(
                                    model = image,
                                    contentDescription = "正在鉴别的图片",
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            } else {
                                Column(
                                    Modifier.align(Alignment.Center),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(10.dp),
                                ) {
                                    Icon(PubIcons.image, null, tint = Color(0x99FFFFFF), modifier = Modifier.size(40.dp))
                                    Text(fileName, color = Color(0xCCFFFFFF), fontSize = 12.sp)
                                }
                            }
                            // 取景角标
                            CornerFrame()
                            // 扫描线:单向自上而下循环(对齐网页 scanmove),底沿一道青色亮边
                            val transition = rememberInfiniteTransition(label = "scan")
                            val t by transition.animateFloat(
                                initialValue = 0f, targetValue = 1f,
                                animationSpec = infiniteRepeatable(
                                    tween(2400, easing = LinearEasing),
                                    RepeatMode.Restart,
                                ),
                                label = "scanY",
                            )
                            val lineH = 78.dp
                            Box(
                                Modifier.fillMaxWidth().height(lineH)
                                    // 走渲染层(translationY),不再每帧重排,消除扫描线卡顿。
                                    .graphicsLayer { translationY = ((maxH + lineH) * t - lineH).toPx() }
                                    .background(
                                        Brush.verticalGradient(
                                            0.0f to Color(0x002E66E6),
                                            0.55f to Color(0x1A2E66E6),
                                            0.88f to Color(0x4D2E66E6),
                                            1.0f to Color(0xD978E0FF),
                                        ),
                                    ),
                            ) {
                                // 底沿亮线
                                Box(
                                    Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(2.dp)
                                        .background(
                                            Brush.horizontalGradient(
                                                listOf(Color(0x007CE0FF), Color(0xFF7CE0FF), Color(0x007CE0FF)),
                                            ),
                                        ),
                                )
                            }
                        }
                    }

                    // 进度
                    Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp)) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
                            Text("正在分析水印与鲁棒性", color = Pub.Ink, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f))
                            Text("${(p * 100).toInt()}%", color = Pub.Blue, fontSize = 30.sp, fontWeight = FontWeight.ExtraBold)
                        }
                        Box(
                            Modifier.fillMaxWidth().padding(top = 11.dp).height(9.dp)
                                .clip(RoundedCornerShape(6.dp)).background(Color(0xFFE6EBF6)),
                        ) {
                            // 进度宽度走渲染层 scaleX(每帧只重绘,不触发 measure/layout)
                            Box(
                                Modifier.fillMaxSize()
                                    .graphicsLayer { scaleX = p; transformOrigin = TransformOrigin(0f, 0.5f) }
                                    .clip(RoundedCornerShape(6.dp)).background(Pub.ctaBrush()),
                            )
                        }
                    }

                    // 分步清单 — 状态由 prog.value 推导
                    PubCard(Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                        StepRow(step1, "读取并上传图像", stepSub(step1), divider = true)
                        StepRow(step2, "模型恢复来源水印", stepSub(step2), divider = true)
                        StepRow(step3, "评估鲁棒性与画质", stepSub(step3), divider = true)
                        StepRow(step4, "综合判定结论", stepSub(step4), divider = false)
                    }

                    // 安心提示
                    Row(
                        Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, top = 18.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(PubIcons.shieldCheck, null, tint = Pub.Ok, modifier = Modifier.size(16.dp))
                        Text("正在上传并分析,请稍候", color = Pub.Ink2, fontSize = 12.5.sp, modifier = Modifier.padding(start = 8.dp))
                    }

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

private fun stepSub(state: StepState): String = when (state) {
    StepState.Done -> "已完成"
    StepState.Doing -> "进行中…"
    StepState.Wait -> "等待中"
}

@Composable
private fun CornerFrame() {
    val c = Color(0x8C2E66E6)
    Box(Modifier.fillMaxSize().padding(12.dp)) {
        CornerMark(Modifier.align(Alignment.TopStart), top = true, start = true, color = c)
        CornerMark(Modifier.align(Alignment.TopEnd), top = true, start = false, color = c)
        CornerMark(Modifier.align(Alignment.BottomStart), top = false, start = true, color = c)
        CornerMark(Modifier.align(Alignment.BottomEnd), top = false, start = false, color = c)
    }
}

@Composable
private fun CornerMark(modifier: Modifier, top: Boolean, start: Boolean, color: Color) {
    Box(modifier.size(20.dp)) {
        // 横边
        Box(
            Modifier.align(if (top) Alignment.TopStart else Alignment.BottomStart)
                .fillMaxWidth().height(2.dp).background(color),
        )
        // 竖边
        Box(
            Modifier.align(if (start) Alignment.TopStart else Alignment.TopEnd)
                .width(2.dp).fillMaxHeight().background(color),
        )
    }
}

@Composable
private fun StepRow(state: StepState, title: String, sub: String, divider: Boolean) {
    Column {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            StepDot(state)
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    color = if (state == StepState.Wait) Pub.Ink3 else Pub.Ink,
                    fontSize = 14.5.sp,
                    fontWeight = if (state == StepState.Wait) FontWeight.Medium else FontWeight.SemiBold,
                )
                Text(
                    sub,
                    color = when (state) { StepState.Done -> Pub.Ok; StepState.Doing -> Pub.Blue; StepState.Wait -> Pub.Ink3 },
                    fontSize = 11.5.sp, modifier = Modifier.padding(top = 3.dp),
                )
            }
        }
        if (divider) Box(Modifier.fillMaxWidth().height(1.dp).background(Pub.Hair))
    }
}

@Composable
private fun StepDot(state: StepState) {
    when (state) {
        StepState.Done -> AnimatedVisibility(
            visible = true,
            enter = scaleIn(
                androidx.compose.animation.core.spring(
                    dampingRatio = 0.55f,
                    stiffness = androidx.compose.animation.core.Spring.StiffnessMedium,
                ),
                initialScale = 0.5f,
            ),
        ) {
            Box(
                Modifier.size(30.dp).clip(RoundedCornerShape(50)).background(Pub.OkB),
                contentAlignment = Alignment.Center,
            ) { Icon(PubIcons.check, null, tint = Pub.Ok, modifier = Modifier.size(16.dp)) }
        }
        StepState.Doing -> Box(
            Modifier.size(30.dp).clip(RoundedCornerShape(50))
                .background(Brush.linearGradient(listOf(Color(0xFF5A92FF), Color(0xFF235FD8)))),
            contentAlignment = Alignment.Center,
        ) { CircularProgressIndicator(modifier = Modifier.size(16.dp), color = Color.White, strokeWidth = 2.4.dp) }
        StepState.Wait -> Box(
            Modifier.size(30.dp).clip(RoundedCornerShape(50)).background(Color(0xFFEEF1F8)),
            contentAlignment = Alignment.Center,
        ) { Icon(PubIcons.search, null, tint = Pub.Ink3, modifier = Modifier.size(16.dp)) }
    }
}
