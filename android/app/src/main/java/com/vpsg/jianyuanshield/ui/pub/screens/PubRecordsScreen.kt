package com.vpsg.jianyuanshield.ui.pub.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.pub.JysMotion
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubRecord
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.RecordRow
import com.vpsg.jianyuanshield.ui.pub.VerdictKind
import com.vpsg.jianyuanshield.ui.pub.grouped
import com.vpsg.jianyuanshield.ui.pub.verdictKindOf

@Composable
fun PubRecordsScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
) {
    val history by vm.historyEntries.collectAsState()
    val nowSec = remember(history) { System.currentTimeMillis() / 1000 }

    var selectedFilter by remember { mutableStateOf(0) }

    val total = history.size
    // 计数/筛选/分组按依赖 remember,避免切筛选或 chip 动画重组时反复全量遍历
    val counts = remember(history) {
        Triple(
            history.count { verdictKindOf(it.verdict) == VerdictKind.Real },
            history.count { verdictKindOf(it.verdict) == VerdictKind.Ai },
            history.count { verdictKindOf(it.verdict) == VerdictKind.Tampered },
        )
    }
    val (real, ai, tampered) = counts

    val filtered = remember(history, selectedFilter) {
        when (selectedFilter) {
            1 -> history.filter { verdictKindOf(it.verdict) == VerdictKind.Real }
            2 -> history.filter { verdictKindOf(it.verdict) == VerdictKind.Ai }
            3 -> history.filter { verdictKindOf(it.verdict) == VerdictKind.Tampered }
            else -> history
        }
    }
    val groups = remember(filtered, nowSec) { filtered.grouped(nowSec) }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            LazyColumn(Modifier.weight(1f)) {
                item {
                    PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 24.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            PubNavBar("链路评估记录", subtitle = "仅存档通过客户端声明门禁的结果", onBack = onBack, modifier = Modifier.weight(1f))
                            Column(horizontalAlignment = Alignment.End) {
                                Text("$total", color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.ExtraBold)
                                Text("累计核验", color = Color.White.copy(alpha = 0.75f), fontSize = 10.5.sp, modifier = Modifier.padding(top = 4.dp))
                            }
                        }
                    }
                }

                item {
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(9.dp),
                    ) {
                        FilterChip("全部", "$total", on = selectedFilter == 0, dot = null) { selectedFilter = 0 }
                        FilterChip("通过核验", "$real", on = selectedFilter == 1, dot = Pub.Ok) { selectedFilter = 1 }
                        FilterChip("水印降级", "$ai", on = selectedFilter == 2, dot = Pub.Warn) { selectedFilter = 2 }
                        FilterChip("验证未通过", "$tampered", on = selectedFilter == 3, dot = Pub.Hi) { selectedFilter = 3 }
                    }
                }

                if (filtered.isEmpty()) {
                    item { EmptyRecords() }
                } else {
                    if (groups.today.isNotEmpty()) {
                        item { GroupLabel("今天") }
                        items(groups.today) { RecordRow(it, Modifier.padding(start = 16.dp, end = 16.dp, top = 13.dp)) }
                    }
                    if (groups.week.isNotEmpty()) {
                        item { GroupLabel("本周") }
                        items(groups.week) { RecordRow(it, Modifier.padding(start = 16.dp, end = 16.dp, top = 13.dp)) }
                    }
                    if (groups.earlier.isNotEmpty()) {
                        item { GroupLabel("更早") }
                        items(groups.earlier) { RecordRow(it, Modifier.padding(start = 16.dp, end = 16.dp, top = 13.dp)) }
                    }
                }

                item { Spacer(Modifier.height(20.dp)) }
            }
            PubTabBar(PubTab.Records, onSelectTab)
        }
    }
}

@Composable
private fun EmptyRecords() {
    Column(
        Modifier.fillMaxWidth().padding(top = 70.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(PubIcons.history, null, tint = Pub.Ink3, modifier = Modifier.size(44.dp))
        Text("还没有链路评估记录", color = Pub.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 12.dp))
        Text("来源登记与核验请前往「登记核验」", color = Pub.Ink3, fontSize = 12.sp, modifier = Modifier.padding(top = 5.dp))
    }
}

@Composable
private fun GroupLabel(text: String) {
    Row(
        Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 22.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(text, color = Pub.Ink3, fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
        Box(Modifier.weight(1f).height(1.dp).background(Pub.Hair))
    }
}

@Composable
private fun FilterChip(label: String, count: String, on: Boolean, dot: Color?, onClick: () -> Unit) {
    val shape = RoundedCornerShape(11.dp)
    val labelColor by animateColorAsState(
        targetValue = if (on) Color.White else Pub.Ink2,
        animationSpec = tween(JysMotion.STATE),
        label = "filterChipLabel",
    )
    val countColor by animateColorAsState(
        targetValue = if (on) Color.White.copy(alpha = 0.82f) else Pub.Ink3,
        animationSpec = tween(JysMotion.STATE),
        label = "filterChipCount",
    )
    val scale by animateFloatAsState(
        targetValue = if (on) 1.04f else 1f,
        animationSpec = tween(JysMotion.STATE, easing = JysMotion.easeStd),
        label = "filterChipScale",
    )
    val base = if (on) {
        Modifier.clip(shape).background(Pub.ctaBrush())
    } else {
        Modifier.clip(shape).background(Pub.Card).border(1.dp, Pub.Hair, shape)
    }
    Row(
        base
            .scale(scale)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (dot != null) Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(dot))
        Text(label, color = labelColor, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
        Text(count, color = countColor, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
    }
}
