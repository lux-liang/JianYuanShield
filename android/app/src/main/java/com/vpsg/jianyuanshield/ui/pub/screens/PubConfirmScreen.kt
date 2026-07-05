package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.SecondaryButton
import com.vpsg.jianyuanshield.ui.pub.SectionHeader
import com.vpsg.jianyuanshield.ui.pub.enterStd
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.runtime.collectAsState

@Composable
fun PubConfirmScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onStart: () -> Unit,
    onRepick: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val image by vm.image.collectAsState()
    val fileName by vm.fileName.collectAsState()
    val fileMeta by vm.fileMeta.collectAsState()
    val consent by vm.uploadConsent.collectAsState()
    val scope = rememberCoroutineScope()
    var showConsent by remember { mutableStateOf(false) }

    // 统一入场触发
    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }

    // P0-⑥ 预览图 alpha/scale 动画
    val photoAlpha by animateFloatAsState(
        targetValue = if (play) 1f else 0f,
        animationSpec = tween(380, easing = JysMotion.easeStd),
        label = "photoAlpha",
    )
    val photoScale by animateFloatAsState(
        targetValue = if (play) 1f else 0.93f,
        animationSpec = tween(380, easing = JysMotion.easeOut),
        label = "photoScale",
    )

    // P1-⑦ WillRow / 文件信息 / 角标错时入场
    var visibleFileInfo by remember { mutableStateOf(false) }
    var visibleWill0 by remember { mutableStateOf(false) }
    var visibleWill1 by remember { mutableStateOf(false) }
    var visibleWill2 by remember { mutableStateOf(false) }
    var visibleWill3 by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        delay(200); visibleFileInfo = true
        delay(80);  visibleWill0 = true
        delay(60);  visibleWill1 = true
        delay(60);  visibleWill2 = true
        delay(60);  visibleWill3 = true
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 60.dp)) {
                    PubNavBar("确认图片", subtitle = "看清楚是这张,就开始鉴别", onBack = onBack)
                }

                Column(Modifier.offset(y = (-48).dp)) {
                    // P0-⑥ 预览框: graphicsLayer alpha 0→1 + scale 0.93→1
                    Box(
                        Modifier
                            .padding(horizontal = 16.dp)
                            .fillMaxWidth()
                            .height(236.dp)
                            .graphicsLayer {
                                alpha = photoAlpha
                                scaleX = photoScale
                                scaleY = photoScale
                            }
                            .clip(RoundedCornerShape(20.dp))
                            .background(Brush.linearGradient(listOf(Color(0xFFEEF2FA), Color(0xFFE2E8F4)))),
                    ) {
                        // 真实选中图(无则占位风景图)
                        if (image != null) {
                            AsyncImage(
                                model = image,
                                contentDescription = "已选图片",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            FauxPhoto(Modifier.fillMaxSize())
                        }
                        // 文件名 caption
                        Row(
                            Modifier.align(Alignment.BottomStart).padding(12.dp)
                                .clip(RoundedCornerShape(10.dp)).background(Color(0x990F1A2E))
                                .padding(horizontal = 11.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(7.dp),
                        ) {
                            Icon(PubIcons.image, null, tint = Color.White, modifier = Modifier.size(13.dp))
                            Text(fileName, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                        }
                        // 已选好
                        Row(
                            Modifier.align(Alignment.BottomEnd).padding(12.dp)
                                .clip(RoundedCornerShape(10.dp)).background(Pub.Ok)
                                .padding(horizontal = 11.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Icon(PubIcons.check, null, tint = Color.White, modifier = Modifier.size(13.dp))
                            Text("已选好", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                    }

                    // P1-⑦ 文件信息错时入场(真实尺寸/大小)
                    AnimatedVisibility(visibleFileInfo, enter = enterStd(0)) {
                        Row(
                            Modifier.fillMaxWidth().padding(top = 13.dp),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                fileMeta.ifBlank { "读取中…" },
                                color = Pub.Ink2, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }

                    SectionHeader("这一次会帮你检测", contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 11.dp))

                    // P1-⑦ WillRow 错时入场(对齐后端真实能力)
                    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                        AnimatedVisibility(visibleWill0, enter = enterStd(0)) {
                            WillRow(PubIcons.shieldCheck, 1, "有没有溯源水印", "读出图片里隐藏的来源标记", divider = true)
                        }
                        AnimatedVisibility(visibleWill1, enter = enterStd(0)) {
                            WillRow(PubIcons.bolt, 2, "抗攻击鲁棒不鲁棒", "压缩/裁剪/换脸后水印还在不在", divider = true)
                        }
                        AnimatedVisibility(visibleWill2, enter = enterStd(0)) {
                            WillRow(PubIcons.image, 3, "画质有没有损失", "嵌入水印后的 PSNR / SSIM", divider = true)
                        }
                        AnimatedVisibility(visibleWill3, enter = enterStd(0)) {
                            WillRow(PubIcons.verified, 0, "合不合规", "是否携带《AI 标识办法》隐式标识", divider = false)
                        }
                    }

                    PrivacyTip(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp))

                    PrimaryCta("开始鉴别", Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp), icon = PubIcons.search) {
                        if (consent) onStart() else showConsent = true
                    }
                    SecondaryButton(
                        "重新选择图片",
                        Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp).fillMaxWidth(),
                        icon = PubIcons.refresh, onClick = onRepick,
                    )

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }

        if (showConsent) {
            ConsentDialog(
                onAgree = {
                    showConsent = false
                    scope.launch { vm.grantConsent() }
                    onStart()
                },
                onDismiss = { showConsent = false },
            )
        }
    }
}

@Composable
private fun ConsentDialog(onAgree: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("上传提示", fontWeight = FontWeight.Bold, color = Pub.Ink) },
        text = {
            Text(
                "这张图片会上传到鉴别服务器用于本次检测,继续即表示你同意。\n之后不再询问;可在「我的 → 服务器设置」改回演示模式(不上传)。",
                fontSize = 13.sp, lineHeight = 20.sp, color = Pub.Ink2,
            )
        },
        confirmButton = { TextButton(onClick = onAgree) { Text("同意并开始", color = Pub.Blue, fontWeight = FontWeight.Bold) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消", color = Pub.Ink3) } },
    )
}

@Composable
private fun WillRow(icon: ImageVector, palette: Int, title: String, desc: String, divider: Boolean) {
    Column {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            ClayIcon(icon, palette = palette, size = 34.dp, corner = 11.dp, iconSize = 18.dp)
            Column(Modifier.weight(1f)) {
                Text(title, color = Pub.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                Text(desc, color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 2.dp))
            }
            Icon(PubIcons.check, null, tint = Pub.Ok, modifier = Modifier.size(20.dp))
        }
        if (divider) Box(Modifier.fillMaxWidth().height(1.dp).background(Pub.Hair))
    }
}

/** 占位"风景照"缩略图(对应 .pv-photo),仅在未选图时显示。 */
@Composable
fun FauxPhoto(modifier: Modifier = Modifier) {
    Box(
        modifier.background(
            Brush.verticalGradient(
                0.0f to Color(0xFFBCD2EE),
                0.40f to Color(0xFFC8D2E8),
                0.58f to Color(0xFFD6CFE0),
                0.581f to Color(0xFFC6B39C),
                1.0f to Color(0xFFB29C82),
            ),
        ),
    ) {
        // 太阳
        Box(
            Modifier.align(Alignment.TopEnd).padding(top = 30.dp, end = 54.dp).size(54.dp)
                .background(
                    Brush.radialGradient(
                        0.0f to Color(0xFFFFF4D6),
                        0.58f to Color(0xFFFFDF9C),
                        1.0f to Color(0x00FFDF9C),
                    ),
                ),
        )
        // 远山(两层)
        Box(
            Modifier.align(Alignment.BottomStart).fillMaxWidth(0.8f).fillMaxHeight(0.46f)
                .clip(RoundedCornerShape(topStart = 120.dp, topEnd = 120.dp))
                .background(Brush.verticalGradient(listOf(Color(0xFFA6B793), Color(0xFF849472)))),
        )
        Box(
            Modifier.align(Alignment.BottomEnd).fillMaxWidth(0.74f).fillMaxHeight(0.36f)
                .clip(RoundedCornerShape(topStart = 120.dp, topEnd = 120.dp))
                .background(Brush.verticalGradient(listOf(Color(0xFFBFA982), Color(0xFF9C8862)))),
        )
        // 压暗
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color(0x0DFFFFFF), Color(0x1F0F1A2E)))))
    }
}
