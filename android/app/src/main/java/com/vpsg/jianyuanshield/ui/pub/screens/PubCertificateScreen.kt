package com.vpsg.jianyuanshield.ui.pub.screens

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.vpsg.jianyuanshield.core.MediaStoreSaver
import com.vpsg.jianyuanshield.core.ShareUtils
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.ui.pub.DashedHLine
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCertImage
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.QrBox
import com.vpsg.jianyuanshield.ui.pub.SecondaryButton
import com.vpsg.jianyuanshield.ui.pub.VerdictKind
import com.vpsg.jianyuanshield.ui.pub.enterReveal
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun PubCertificateScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val state by vm.state.collectAsState()
    val ui = (state as? UiState.Success)?.data
    if (ui == null || !ui.canIssueCertificate) {
        CertificateBlockedScreen(ui?.evidenceStatusDetail, onBack, onSelectTab)
        return
    }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // 平台证据签名状态(best-effort)
    var sigLabel by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(ui.taskId) {
        sigLabel = vm.evidenceSignatureLabel()
    }

    val qrContent = vm.reportUrl(ui.taskId)

    fun doSave() {
        val u = ui
        scope.launch {
            val ok = withContext(Dispatchers.IO) {
                val bmp = PubCertImage.render(u, qrContent)
                MediaStoreSaver.saveToGallery(context, bmp, "鉴源盾来源核验凭证_${u.taskId}.png")
            }
            Toast.makeText(context, if (ok) "已保存到相册" else "保存失败", Toast.LENGTH_SHORT).show()
        }
    }
    val writePerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) doSave() else Toast.makeText(context, "未授予存储权限,无法保存", Toast.LENGTH_SHORT).show()
    }
    fun onSaveClick() {
        val ok = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        if (ok) doSave() else writePerm.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
    }
    fun onShareClick() {
        val u = ui
        scope.launch {
            val bmp = withContext(Dispatchers.IO) { PubCertImage.render(u, qrContent) }
            ShareUtils.shareImage(context, bmp, "cert_${u.taskId}.png", "【鉴源盾】来源核验凭证:${u.title}")
        }
    }

    var visible by remember { mutableStateOf(false) }
    var chipVisible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        visible = true
        kotlinx.coroutines.delay(250)
        chipVisible = true
    }
    // 入场只用 graphicsLayer 平移(只重绘,不触发逐帧 relayout / 下方内容抖动);静态 -50dp 留给布局压住 hero
    val cardEnter by animateFloatAsState(
        targetValue = if (visible) 0f else 80f,
        animationSpec = tween(durationMillis = 420, easing = JysMotion.easeStd),
        label = "certCardEnter",
    )

    val (chipBg, chipFg) = when (ui.verdict) {
        VerdictKind.Real -> Pub.OkB to Pub.Ok
        VerdictKind.Tampered -> Pub.HiB to Pub.Hi
        else -> Pub.WarnB to Pub.Warn
    }
    val headBrush = when (ui.verdict) {
        VerdictKind.Real -> Brush.linearGradient(listOf(Color(0xFF45C98C), Color(0xFF18A56E)))
        VerdictKind.Tampered -> Brush.linearGradient(listOf(Color(0xFFEE7C72), Color(0xFFD63E34)))
        else -> Brush.linearGradient(listOf(Color(0xFFF2B65A), Color(0xFFDE8C1C)))
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 64.dp)) {
                    PubNavBar("来源核验凭证", subtitle = "登记盲检 · claim_valid=true", onBack = onBack)
                }

                Column(
                    Modifier
                        .offset(y = (-50).dp)
                        .graphicsLayer { translationY = cardEnter.dp.toPx() },
                ) {
                    val cardShape = RoundedCornerShape(22.dp)
                    Column(
                        Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(cardShape)
                            .background(Pub.Card).border(1.dp, Pub.Hair, cardShape),
                    ) {
                        Column(
                            Modifier.fillMaxWidth()
                                .background(Brush.linearGradient(listOf(Color(0xFF3A6FEC), Color(0xFF2A57CE), Color(0xFF23399E))))
                                .padding(start = 18.dp, end = 18.dp, top = 17.dp, bottom = 16.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Box(
                                    Modifier.size(34.dp).clip(RoundedCornerShape(10.dp))
                                        .background(Color.White.copy(alpha = 0.16f))
                                        .border(1.dp, Color.White.copy(alpha = 0.28f), RoundedCornerShape(10.dp)),
                                    contentAlignment = Alignment.Center,
                                ) { Icon(PubIcons.shieldCheck, null, tint = Color.White, modifier = Modifier.size(19.dp)) }
                                Column {
                                    Text("鉴源盾 · 来源核验凭证", color = Color.White, fontSize = 14.5.sp, fontWeight = FontWeight.ExtraBold)
                                    Text("WATERMARK VERIFICATION RECORD", color = Color.White.copy(alpha = 0.82f), fontSize = 10.5.sp)
                                }
                            }
                            Row(Modifier.padding(top = 13.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                Icon(PubIcons.qr, null, tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(13.dp))
                                Text("编号 ${ui.certNumber}", color = Color.White.copy(alpha = 0.9f), fontSize = 11.5.sp)
                            }
                        }

                        Column(Modifier.padding(18.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                Box(
                                    Modifier.size(58.dp).clip(RoundedCornerShape(14.dp)).background(headBrush),
                                    contentAlignment = Alignment.Center,
                                ) { Icon(PubIcons.image, null, tint = Color.White, modifier = Modifier.size(26.dp)) }
                                Column(Modifier.weight(1f)) {
                                    AnimatedVisibility(chipVisible, enter = enterReveal(delayMillis = 0)) {
                                        Row(
                                            Modifier.clip(RoundedCornerShape(9.dp)).background(chipBg).padding(horizontal = 11.dp, vertical = 5.dp),
                                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(chipFg))
                                            Text(ui.certBadge, color = chipFg, fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
                                        }
                                    }
                                    Text(ui.certDesc, color = Pub.Ink2, fontSize = 12.5.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 8.dp))
                                }
                            }

                            DashedHLine(Modifier.padding(top = 16.dp))
                            Column(Modifier.padding(top = 6.dp)) {
                                CertKv("图片名称", ui.certName)
                                CertKv("核验时间", ui.certTime)
                                CertKv("核验项目", ui.certItems)
                                CertKv("核验引擎", "鉴源盾 · ${ui.model}")
                            }

                            DashedHLine(Modifier.padding(top = 6.dp))
                            Row(Modifier.padding(top = 16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(15.dp)) {
                                QrBox(content = qrContent)
                                Column {
                                    Text("扫码核对原始报告", color = Pub.Ink, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                                    Text("扫码可核对本次主动水印验证记录;SHA-256 指纹一致表示报告未被改动。", color = Pub.Ink3, fontSize = 11.5.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 5.dp))
                                }
                            }

                            // 真实 SHA-256 指纹
                            ui.sha256.firstOrNull()?.let { (k, v) ->
                                DashedHLine(Modifier.padding(top = 14.dp))
                                Column(Modifier.padding(top = 12.dp)) {
                                    Text("证据指纹 · SHA-256($k)", color = Pub.Ink2, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold)
                                    Text(
                                        if (v.length > 28) "${v.take(16)}…${v.takeLast(12)}" else v,
                                        color = Pub.Ink3, fontSize = 11.sp, modifier = Modifier.padding(top = 3.dp),
                                    )
                                }
                            }

                            DashedHLine(Modifier.padding(top = 15.dp))
                            Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Icon(PubIcons.shield, null, tint = Pub.Blue, modifier = Modifier.size(15.dp))
                                Text("技术支持 · 新疆大学 VPSG 实验室 · 本凭证为技术核验记录，非司法鉴定", color = Pub.Ink3, fontSize = 11.sp, lineHeight = 16.sp)
                            }
                        }
                    }

                    // 平台 Ed25519 签名状态(真实)
                    if (sigLabel != null) {
                        Row(
                            Modifier.padding(start = 22.dp, end = 22.dp, top = 14.dp),
                            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(PubIcons.verified, null, tint = Pub.Ok, modifier = Modifier.size(15.dp))
                            Text(sigLabel!!, color = Pub.Ok, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold)
                        }
                    }

                    Row(Modifier.padding(start = 22.dp, end = 22.dp, top = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(PubIcons.info, null, tint = Pub.Ok, modifier = Modifier.size(15.dp).padding(top = 1.dp))
                        Text(
                            "仅 registered_blind_verification、真实 checkpoint 且 claim_valid=true 的结果可生成本凭证；扫码可核对报告指纹。",
                            color = Pub.Ink2, fontSize = 11.5.sp, lineHeight = 18.sp,
                        )
                    }

                    PrimaryCta("保存到相册", Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp), icon = PubIcons.download) { onSaveClick() }
                    SecondaryButton(
                        "分享凭证",
                        Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp).fillMaxWidth(),
                        icon = PubIcons.share,
                    ) { onShareClick() }

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun CertificateBlockedScreen(
    detail: String?,
    onBack: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 40.dp)) {
                PubNavBar("凭证不可用", subtitle = "结果未通过发布门禁", onBack = onBack)
            }
            Column(Modifier.weight(1f).padding(16.dp)) {
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(Pub.WarnB)
                        .border(1.dp, Color(0xFFF4E2BE), RoundedCornerShape(18.dp))
                        .padding(18.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(PubIcons.warning, null, tint = Pub.Warn, modifier = Modifier.size(21.dp))
                        Text("已阻止生成来源核验凭证", color = Pub.WarnD, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    }
                    Text(
                        detail ?: "只有 registered_blind_verification、真实 checkpoint 且 claim_valid=true 时才能生成、保存或分享凭证。",
                        color = Pub.WarnD2,
                        fontSize = 12.5.sp,
                        lineHeight = 19.sp,
                        modifier = Modifier.padding(top = 10.dp),
                    )
                }
                PrimaryCta("返回结果", Modifier.padding(top = 16.dp), icon = PubIcons.back, onClick = onBack)
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun CertKv(key: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(key, color = Pub.Ink3, fontSize = 12.5.sp, modifier = Modifier.weight(1f))
        Text(value, color = Pub.Ink, fontSize = 13.sp)
    }
}
