package com.vpsg.jianyuanshield.ui.pub.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.core.CaptureUtils
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.ConnProbe
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.SectionHeader
import com.vpsg.jianyuanshield.ui.pub.dashedRoundedBorder
import com.vpsg.jianyuanshield.ui.pub.enterHero
import com.vpsg.jianyuanshield.ui.pub.enterStd
import com.vpsg.jianyuanshield.ui.pub.pressScale
import kotlinx.coroutines.delay

@Composable
fun PubUploadScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onPicked: () -> Unit,
    onOpenServer: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val context = LocalContext.current

    // 真实选图:系统相册
    val galleryLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            vm.setImage(uri)
            onPicked()
        }
    }
    // 真实拍照:交给系统相机,输出到 FileProvider
    var cameraUri by remember { mutableStateOf<Uri?>(null) }
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok: Boolean ->
        val u = cameraUri
        if (ok && u != null) {
            vm.setImage(u)
            onPicked()
        }
    }
    fun launchCamera() {
        val u = CaptureUtils.newImageUri(context)
        cameraUri = u
        cameraLauncher.launch(u)
    }

    // 连接探测
    val probe by vm.probe.collectAsState()
    LaunchedEffect(Unit) { vm.probeConnection() }

    // 统一入场触发
    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }

    // P1-⑤ FeatureRow stagger 错时
    var visibleFeature0 by remember { mutableStateOf(false) }
    var visibleFeature1 by remember { mutableStateOf(false) }
    var visibleFeature2 by remember { mutableStateOf(false) }
    var visibleFeature3 by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        delay(200); visibleFeature0 = true
        delay(60);  visibleFeature1 = true
        delay(60);  visibleFeature2 = true
        delay(60);  visibleFeature3 = true
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 64.dp)) {
                    PubNavBar("主动水印链路评估", subtitle = "为本次评估新嵌入水印，再运行攻击与恢复", onBack = onBack)
                    ConnPill(probe, Modifier.padding(top = 14.dp), onClick = onOpenServer)
                }

                Column(Modifier.offset(y = (-52).dp)) {
                    // P0-④ 上传卡入场
                    AnimatedVisibility(play, enter = enterHero(0)) {
                        PubCard(
                            Modifier.padding(horizontal = 16.dp),
                            corner = 20.dp,
                            contentPadding = PaddingValues(18.dp),
                        ) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(13.dp)) {
                                UploadOption(PubIcons.camera, 0, "拍照", Modifier.weight(1f)) { launchCamera() }
                                UploadOption(PubIcons.gallery, 1, "从相册选择", Modifier.weight(1f)) { galleryLauncher.launch("image/*") }
                            }
                            Row(
                                Modifier.fillMaxWidth().padding(top = 14.dp),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(PubIcons.info, null, tint = Pub.Ink3, modifier = Modifier.size(14.dp))
                                Text("支持 ", color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(start = 7.dp))
                                Text("JPG / PNG / WEBP", color = Pub.Ink2, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold)
                                Text(" 格式", color = Pub.Ink3, fontSize = 11.5.sp)
                            }
                        }
                    }

                    SectionHeader("本次会验证什么")

                    // P1-⑤ FeatureRow stagger
                    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                        AnimatedVisibility(visibleFeature0, enter = enterStd(0)) {
                            FeatureRow(PubIcons.shieldCheck, 0, "本次水印恢复", "仅恢复本流程新嵌入的消息")
                        }
                        AnimatedVisibility(visibleFeature1, enter = enterStd(0)) {
                            FeatureRow(PubIcons.bolt, 2, "抗攻击鲁棒性", "验证压缩、裁剪等处理后的恢复能力")
                        }
                        AnimatedVisibility(visibleFeature2, enter = enterStd(0)) {
                            FeatureRow(PubIcons.image, 3, "图像质量评估", "嵌入水印后画质有没有损失")
                        }
                        AnimatedVisibility(visibleFeature3, enter = enterStd(0)) {
                            FeatureRow(PubIcons.verified, 1, "合规标识评估", "评估本流程嵌入的隐式标识")
                        }
                    }

                    PrivacyTip(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp))

                    PrimaryCta("选择图片,开始保护链路评估", Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp), icon = PubIcons.upload) {
                        galleryLauncher.launch("image/*")
                    }

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

/** 顶部连接状态小药丸:点按进入服务器设置。 */
@Composable
private fun ConnPill(probe: ConnProbe, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val dot: Color
    val text: String
    when (probe) {
        is ConnProbe.Idle, is ConnProbe.Checking -> {
            dot = Color(0xFFBFD4FF); text = "正在检查服务器连接…"
        }
        is ConnProbe.Ok -> {
            dot = Color(0xFF7BE5B0)
            text = when (probe.mode) {
                "local_demo" -> "本地演示已显式开启 · 未测试服务器"
                "real_checkpoint" -> if (probe.provenanceReadyModels.isEmpty()) {
                    "已连接服务器 · 无来源就绪模型"
                } else {
                    "已连接服务器 · 来源就绪 ${probe.provenanceReadyModels.joinToString()}"
                }
                else -> "已连接服务器 · 服务器仅返回流程模拟"
            }
        }
        is ConnProbe.Fail -> {
            dot = Color(0xFFFFB4A8); text = "未连接服务器 · 点此设置（不会自动生成模拟结果）"
        }
    }
    Row(
        modifier.clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.14f))
            .border(1.dp, Color.White.copy(alpha = 0.22f), RoundedCornerShape(20.dp))
            .pressScale(to = 0.97f, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.size(7.dp).clip(RoundedCornerShape(50)).background(dot))
        Text(text, color = Color.White.copy(alpha = 0.92f), fontSize = 11.5.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun UploadOption(icon: ImageVector, palette: Int, label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    // P0-④ 裸 clickable 换 pressScale(0.94f)
    Column(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(Brush.verticalGradient(listOf(Color(0xFFF7FAFF), Color(0xFFEFF4FE))))
            .dashedRoundedBorder(Color(0xFFC9D6F0), cornerRadius = 16.dp)
            .pressScale(to = 0.94f) { onClick() }
            .padding(top = 22.dp, bottom = 18.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        ClayIcon(icon, palette = palette, size = 54.dp, corner = 17.dp, iconSize = 26.dp)
        Text(label, color = Pub.Ink, fontSize = 14.5.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun FeatureRow(icon: ImageVector, palette: Int, title: String, desc: String) {
    PubCard(corner = 16.dp, contentPadding = PaddingValues(horizontal = 15.dp, vertical = 13.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(13.dp)) {
            ClayIcon(icon, palette = palette, size = 38.dp, corner = 12.dp, iconSize = 20.dp)
            Column(Modifier.weight(1f)) {
                Text(title, color = Pub.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                Text(desc, color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 3.dp))
            }
        }
    }
}

/** 绿底隐私提示(上传 / 确认页复用)。真连后端时图片会上传到评估服务器。 */
@Composable
fun PrivacyTip(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        modifier.fillMaxWidth().clip(shape)
            .background(Pub.OkB)
            .border(1.dp, Color(0xFFD4EEE2), shape)
            .padding(horizontal = 16.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        Icon(PubIcons.shieldCheck, null, tint = Pub.Ok, modifier = Modifier.size(22.dp))
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append("图片仅用于本次主动水印验证") }
                append(",会上传到所配置服务器运行嵌入、攻击与恢复流程；结果不等同于通用真假鉴定。")
            },
            color = Color(0xFF0E7A50), fontSize = 12.sp, lineHeight = 18.sp,
        )
    }
}
