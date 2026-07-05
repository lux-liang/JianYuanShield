package com.vpsg.jianyuanshield.ui.pub.screens

import android.widget.Toast
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.RecordRow
import com.vpsg.jianyuanshield.ui.pub.SectionHeader
import com.vpsg.jianyuanshield.ui.pub.enterHero
import com.vpsg.jianyuanshield.ui.pub.enterStd
import com.vpsg.jianyuanshield.ui.pub.pressScale
import com.vpsg.jianyuanshield.ui.pub.stats
import com.vpsg.jianyuanshield.ui.pub.toPubRecord
import java.io.File
import kotlinx.coroutines.delay

@Composable
fun PubHomeScreen(
    vm: PubDetectViewModel,
    onUpload: () -> Unit,
    onOpenRecords: () -> Unit,
    onOpenLearn: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val history by vm.historyEntries.collectAsState()
    val (total, passed, flagged) = history.stats()
    val nowSec = remember(history) { System.currentTimeMillis() / 1000 }
    val recent = remember(history) { history.take(3).map { it.toPubRecord(nowSec) } }
    val userName by vm.userName.collectAsState()
    val avatarPath by vm.avatarPath.collectAsState()
    val context = LocalContext.current

    var play by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { play = true }

    var visibleSub by remember { mutableStateOf(false) }
    var visibleStats by remember { mutableStateOf(false) }
    var visibleQuick by remember { mutableStateOf(false) }
    var visibleRecord0 by remember { mutableStateOf(false) }
    var visibleRecord1 by remember { mutableStateOf(false) }
    var visibleRecord2 by remember { mutableStateOf(false) }
    var visibleBanner by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        delay(80);  visibleSub = true
        delay(80);  visibleStats = true
        delay(80);  visibleQuick = true
        delay(160); visibleRecord0 = true
        delay(60);  visibleRecord1 = true
        delay(60);  visibleRecord2 = true
        delay(80);  visibleBanner = true
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 78.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("你好,$userName", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                            Text("今天有什么图片想验证?", color = Color.White.copy(alpha = 0.78f), fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
                        }
                        Box(
                            Modifier.size(36.dp).clip(RoundedCornerShape(50)).background(Color.White.copy(alpha = 0.14f))
                                .pressScale(to = 0.9f) { Toast.makeText(context, "暂无新通知", Toast.LENGTH_SHORT).show() },
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(PubIcons.bell, "通知", tint = Color(0xFFEAF2FF), modifier = Modifier.size(18.dp))
                        }
                        Spacer(Modifier.width(10.dp))
                        Box(
                            Modifier.size(38.dp).clip(RoundedCornerShape(50))
                                .background(Brush.linearGradient(listOf(Color(0xFFFFB36B), Color(0xFFF0852E))))
                                .pressScale(to = 0.9f) { onSelectTab(PubTab.Me) },
                            contentAlignment = Alignment.Center,
                        ) {
                            if (avatarPath != null) {
                                AsyncImage(model = File(avatarPath!!), contentDescription = "我的", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                            } else {
                                Icon(PubIcons.person, null, tint = Color.White, modifier = Modifier.size(20.dp))
                            }
                        }
                    }

                    AnimatedVisibility(play, enter = enterHero(0)) {
                        Text(
                            "图片真伪,\n一鉴便知", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold,
                            lineHeight = 32.sp, modifier = Modifier.padding(top = 20.dp),
                        )
                    }

                    AnimatedVisibility(visibleSub, enter = enterHero(0)) {
                        Text(
                            "溯源水印 · 抗攻击鲁棒性 · 合规标识,真连服务器检测",
                            color = Color.White.copy(alpha = 0.85f), fontSize = 12.5.sp, modifier = Modifier.padding(top = 10.dp),
                        )
                    }

                    AnimatedVisibility(visibleStats, enter = enterHero(0)) {
                        Row(Modifier.fillMaxWidth().padding(top = 20.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            HeroStat(PubIcons.check, "$total", "累计鉴别", Color(0xFFBDF1FF), Color(0x387EE6FF), Modifier.weight(1f))
                            HeroStat(PubIcons.shieldCheck, "$passed", "通过核验", Color(0xFFBFF3D6), Color(0x3863E6A0), Modifier.weight(1f))
                            HeroStat(PubIcons.warning, "$flagged", "需留意", Color(0xFFFFC0B8), Color(0x38FFA096), Modifier.weight(1f))
                        }
                    }
                }

                Column(Modifier.offset(y = (-52).dp)) {
                    AnimatedVisibility(visibleQuick, enter = enterHero(0)) {
                        PubCard(
                            Modifier.padding(horizontal = 16.dp),
                            corner = 20.dp,
                            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 18.dp),
                        ) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceAround) {
                                QuickAction(PubIcons.camera, 0, "拍照鉴别", onUpload)
                                QuickAction(PubIcons.gallery, 1, "相册鉴别", onUpload)
                                QuickAction(PubIcons.shieldCheck, 2, "水印核验", onUpload)
                                QuickAction(PubIcons.clock, 3, "鉴别记录", onOpenRecords)
                            }
                        }
                    }

                    PrimaryCta("上传一张图,立即鉴别", Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp), icon = PubIcons.upload, onClick = onUpload)

                    SectionHeader("最近鉴别", action = "全部", onAction = onOpenRecords)

                    if (recent.isEmpty()) {
                        EmptyRecent(Modifier.padding(horizontal = 16.dp))
                    } else {
                        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                            val vis = listOf(visibleRecord0, visibleRecord1, visibleRecord2)
                            recent.forEachIndexed { index, record ->
                                AnimatedVisibility(vis.getOrElse(index) { visibleRecord2 }, enter = enterStd(0)) {
                                    RecordRow(record)
                                }
                            }
                        }
                    }

                    AnimatedVisibility(visibleBanner, enter = enterStd(0)) {
                        Row(
                            Modifier.padding(start = 16.dp, end = 16.dp, top = 22.dp).fillMaxWidth()
                                .clip(RoundedCornerShape(18.dp))
                                .background(Brush.linearGradient(listOf(Color(0xFFEAF1FE), Color(0xFFEFEBFF))))
                                .pressScale(to = 0.97f) { onOpenLearn() }
                                .padding(horizontal = 18.dp, vertical = 16.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            ClayIcon(PubIcons.learn, palette = 2, size = 40.dp, corner = 12.dp, iconSize = 20.dp)
                            Column(Modifier.weight(1f).padding(start = 14.dp)) {
                                Text("3 秒看懂:溯源水印怎么用?", color = Color(0xFF22306B), fontSize = 13.5.sp, fontWeight = FontWeight.Bold)
                                Text("学会这几招,转发前先验真", color = Color(0xFF6B76A3), fontSize = 11.5.sp, modifier = Modifier.padding(top = 4.dp))
                            }
                            Icon(PubIcons.chevronRight, null, tint = Color(0xFF8893C4), modifier = Modifier.size(20.dp))
                        }
                    }

                    Spacer(Modifier.height(20.dp))
                }
            }
            PubTabBar(PubTab.Home, onSelectTab)
        }
    }
}

@Composable
private fun EmptyRecent(modifier: Modifier = Modifier) {
    PubCard(modifier, corner = 18.dp, contentPadding = PaddingValues(vertical = 26.dp, horizontal = 18.dp)) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(PubIcons.history, null, tint = Pub.Ink3, modifier = Modifier.size(34.dp))
            Text("还没有鉴别记录", color = Pub.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp))
            Text("上传一张图试试,结果会自动存到这里", color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

@Composable
private fun HeroStat(
    icon: ImageVector,
    number: String,
    label: String,
    iconTint: Color,
    iconBg: Color,
    modifier: Modifier = Modifier,
) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Box(Modifier.size(30.dp).clip(RoundedCornerShape(9.dp)).background(iconBg), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = iconTint, modifier = Modifier.size(16.dp))
        }
        Column {
            Text(number, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold)
            Text(label, color = Color.White.copy(alpha = 0.72f), fontSize = 10.5.sp, modifier = Modifier.padding(top = 3.dp))
        }
    }
}

@Composable
private fun QuickAction(icon: ImageVector, palette: Int, label: String, onClick: () -> Unit) {
    Column(
        Modifier
            .clip(RoundedCornerShape(14.dp))
            .pressScale(to = 0.94f) { onClick() }
            .padding(horizontal = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ClayIcon(icon, palette = palette, size = 52.dp, corner = 17.dp)
        Text(label, color = Pub.Ink2, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
    }
}
