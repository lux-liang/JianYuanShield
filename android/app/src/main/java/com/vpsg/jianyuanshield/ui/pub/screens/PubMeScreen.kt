package com.vpsg.jianyuanshield.ui.pub.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldDefaults
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.ClayTile
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.enterHero
import com.vpsg.jianyuanshield.ui.pub.enterStd
import com.vpsg.jianyuanshield.ui.pub.pressScale
import com.vpsg.jianyuanshield.ui.pub.stats
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

@Composable
fun PubMeScreen(
    vm: PubDetectViewModel,
    onOpenRecords: () -> Unit,
    onOpenServer: () -> Unit,
    onOpenInfo: (String) -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val history by vm.historyEntries.collectAsState()
    val (total, passed, flagged) = history.stats()
    val userName by vm.userName.collectAsState()
    val avatarPath by vm.avatarPath.collectAsState()
    val scope = rememberCoroutineScope()
    var showEdit by remember { mutableStateOf(false) }

    var visibleHero by remember { mutableStateOf(false) }
    var visibleStats by remember { mutableStateOf(false) }
    var visibleMenu by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        visibleHero = true
        delay(150)
        visibleStats = true
        delay(100)
        visibleMenu = true
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 22.dp)) {
                    Text("我的", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)

                    AnimatedVisibility(visibleHero, enter = enterHero()) {
                        Row(Modifier.fillMaxWidth().padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(15.dp)) {
                            Avatar(avatarPath, 62.dp, 26)
                            Column(Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Text(userName, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, maxLines = 1)
                                    Box(
                                        Modifier.clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.16f))
                                            .border(1.dp, Color.White.copy(alpha = 0.26f), RoundedCornerShape(20.dp))
                                            .padding(horizontal = 9.dp, vertical = 3.dp),
                                    ) { Text("守护者", color = Color(0xFFEAF2FF), fontSize = 10.5.sp, fontWeight = FontWeight.SemiBold) }
                                }
                                Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Icon(PubIcons.shieldCheck, null, tint = Color.White.copy(alpha = 0.85f), modifier = Modifier.size(14.dp))
                                    Text("已保存 $total 条链路评估 · $passed 条通过门禁", color = Color.White.copy(alpha = 0.85f), fontSize = 12.5.sp)
                                }
                            }
                            Box(
                                Modifier.size(34.dp).clip(RoundedCornerShape(50)).background(Color.White.copy(alpha = 0.14f))
                                    .border(1.dp, Color.White.copy(alpha = 0.22f), RoundedCornerShape(50))
                                    .pressScale(to = 0.9f) { showEdit = true },
                                contentAlignment = Alignment.Center,
                            ) { Icon(PubIcons.edit, "编辑资料", tint = Color(0xFFEAF2FF), modifier = Modifier.size(17.dp)) }
                        }
                    }

                    AnimatedVisibility(visibleStats, enter = enterStd(delayMillis = 0)) {
                        Row(Modifier.fillMaxWidth().padding(top = 20.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            MeStat(PubIcons.check, total, "链路评估", Color(0xFFBDF1FF), Color(0x387EE6FF), Modifier.weight(1f), play = visibleStats)
                            MeStat(PubIcons.shieldCheck, passed, "通过核验", Color(0xFFBFF3D6), Color(0x3863E6A0), Modifier.weight(1f), play = visibleStats)
                            MeStat(PubIcons.warning, flagged, "需留意", Color(0xFFFFC0B8), Color(0x38FFA096), Modifier.weight(1f), play = visibleStats)
                        }
                    }
                }

                AnimatedVisibility(visibleMenu, enter = enterStd(delayMillis = 0)) {
                    PubCard(Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                        MenuRow(palette = 0, icon = PubIcons.shieldCheck, title = "声明门禁记录", sub = "仅保存通过客户端门禁的链路评估", tag = if (total > 0) "$total 条" else null, divider = true, onClick = onOpenRecords)
                        MenuRow(palette = 1, icon = PubIcons.clock, title = "评估记录", sub = "查看已保存的主动水印链路结果", divider = true, onClick = onOpenRecords)
                        MenuRow(palette = 2, icon = PubIcons.cloud, title = "服务器设置", sub = "配置地址、测试连接、演示/大字模式", divider = true, onClick = onOpenServer)
                        MenuRow(palette = 3, icon = PubIcons.lock, title = "隐私与数据", sub = "图片如何上传与使用", divider = true, onClick = { onOpenInfo("privacy") })
                        MenuRow(palette = 0, icon = PubIcons.help, title = "帮助中心", sub = "怎么用?结果怎么看?", divider = true, onClick = { onOpenInfo("help") })
                        MenuRow(indigo = true, icon = PubIcons.info, title = "关于鉴源盾", sub = "版本 V1.0.0 · 我们是谁", divider = false, onClick = { onOpenInfo("about") })
                    }
                }

                Row(
                    Modifier.fillMaxWidth().padding(start = 22.dp, end = 22.dp, top = 24.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(PubIcons.shield, null, tint = Pub.Blue, modifier = Modifier.size(15.dp))
                    Text("技术支持 · 新疆大学 VPSG 实验室 · 技术记录不替代监管或司法认定", color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(start = 7.dp))
                }

                Spacer(Modifier.height(20.dp))
            }
            PubTabBar(PubTab.Me, onSelectTab)
        }

        if (showEdit) {
            EditProfileDialog(
                currentName = userName,
                avatarPath = avatarPath,
                onPickAvatar = { uri -> scope.launch { vm.setAvatar(uri) } },
                onSave = { name -> scope.launch { vm.setUserName(name) }; showEdit = false },
                onDismiss = { showEdit = false },
            )
        }
    }
}

@Composable
private fun EditProfileDialog(
    currentName: String,
    avatarPath: String?,
    onPickAvatar: (Uri) -> Unit,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var nameInput by remember { mutableStateOf(currentName) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) onPickAvatar(uri)
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑资料", fontWeight = FontWeight.Bold, color = Pub.Ink) },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    Avatar(avatarPath, 56.dp, 22)
                    TextButton(onClick = { gallery.launch("image/*") }) {
                        Text("更换头像", color = Pub.Blue, fontWeight = FontWeight.SemiBold)
                    }
                }
                OutlinedTextField(
                    value = nameInput,
                    onValueChange = { nameInput = it },
                    singleLine = true,
                    label = { Text("昵称") },
                    modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.White,
                        unfocusedContainerColor = Color.White,
                        focusedIndicatorColor = Pub.Blue,
                        unfocusedIndicatorColor = Pub.Hair,
                        cursorColor = Pub.Blue,
                        focusedLabelColor = Pub.Blue,
                        focusedTextColor = Pub.Ink,
                        unfocusedTextColor = Pub.Ink,
                    ),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(nameInput.ifBlank { "鉴源盾用户" }) }) {
                Text("保存", color = Pub.Blue, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消", color = Pub.Ink3) } },
    )
}

@Composable
private fun Avatar(path: String?, size: Dp, textSp: Int) {
    Box(
        Modifier.size(size).clip(RoundedCornerShape(50))
            .background(Brush.linearGradient(listOf(Color(0xFFFFB36B), Color(0xFFF0852E)))),
        contentAlignment = Alignment.Center,
    ) {
        if (path != null) {
            AsyncImage(
                model = File(path),
                contentDescription = "头像",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Text("盾", color = Color.White, fontSize = textSp.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun MeStat(
    icon: ImageVector,
    numberTarget: Int,
    label: String,
    iconTint: Color,
    iconBg: Color,
    modifier: Modifier = Modifier,
    play: Boolean = false,
) {
    val animatedNumber by animateIntAsState(
        targetValue = if (play) numberTarget else 0,
        animationSpec = tween(durationMillis = JysMotion.FILL, easing = JysMotion.easeOut),
        label = "meStatNumber",
    )
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Box(Modifier.size(30.dp).clip(RoundedCornerShape(9.dp)).background(iconBg), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = iconTint, modifier = Modifier.size(16.dp))
        }
        Column {
            Text(
                text = if (animatedNumber >= 1000) "${animatedNumber / 1000},${String.format("%03d", animatedNumber % 1000)}" else "$animatedNumber",
                color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold,
            )
            Text(label, color = Color.White.copy(alpha = 0.72f), fontSize = 10.5.sp, modifier = Modifier.padding(top = 3.dp))
        }
    }
}

@Composable
private fun MenuRow(
    icon: ImageVector,
    title: String,
    sub: String,
    divider: Boolean,
    palette: Int = 0,
    indigo: Boolean = false,
    tag: String? = null,
    onClick: () -> Unit,
) {
    Column {
        Row(
            Modifier
                .fillMaxWidth()
                .pressScale(to = 0.97f) { onClick() }
                .padding(vertical = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (indigo) {
                ClayTile(
                    faceBrush = Brush.linearGradient(listOf(Color(0xFF7E8DF0), Color(0xFF4E5BD0))),
                    edge = Color(0xFF3C46A8), size = 38.dp, corner = 12.dp,
                ) { Icon(icon, null, tint = Color.White, modifier = Modifier.size(20.dp)) }
            } else {
                ClayIcon(icon, palette = palette, size = 38.dp, corner = 12.dp, iconSize = 20.dp)
            }
            Column(Modifier.weight(1f)) {
                Text(title, color = Pub.Ink, fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold)
                Text(sub, color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 3.dp))
            }
            if (tag != null) {
                Box(Modifier.clip(RoundedCornerShape(8.dp)).background(Pub.OkB).padding(horizontal = 9.dp, vertical = 3.dp)) {
                    Text(tag, color = Pub.Ok, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.size(8.dp))
            }
            Icon(PubIcons.chevronRight, null, tint = Pub.Ink3, modifier = Modifier.size(20.dp))
        }
        if (divider) Box(Modifier.fillMaxWidth().height(1.dp).background(Pub.Hair))
    }
}
