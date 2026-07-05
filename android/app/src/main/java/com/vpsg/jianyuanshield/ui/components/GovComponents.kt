package com.vpsg.jianyuanshield.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.Badge
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.foundation.GradientButton
import com.vpsg.jianyuanshield.ui.foundation.glass
import com.vpsg.jianyuanshield.ui.foundation.pressable
import com.vpsg.jianyuanshield.ui.foundation.shieldOutlinePath
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.GovBlueAux
import com.vpsg.jianyuanshield.ui.theme.GovBlueDeep
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkBody
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.ShadowSoft
import com.vpsg.jianyuanshield.ui.theme.TintCard

/**
 * Faint security texture for the deep-blue hero: a low-opacity data grid plus a
 * large shield watermark on the right. Calm, never neon. Clip the container.
 */
fun Modifier.heroTexture(): Modifier = composed {
    drawBehind {
        val step = 26.dp.toPx()
        val line = Color.White.copy(alpha = 0.05f)
        var x = 0f
        while (x < size.width) {
            drawLine(line, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1f)
            x += step
        }
        var y = 0f
        while (y < size.height) {
            drawLine(line, Offset(0f, y), Offset(size.width, y), strokeWidth = 1f)
            y += step
        }
        // Shield watermark, large, faint, right side
        val s = size.height * 1.5f
        translate(left = size.width - s * 0.62f, top = -s * 0.18f) {
            drawPath(shieldOutlinePath(s), color = Color.White.copy(alpha = 0.06f))
            drawPath(shieldOutlinePath(s), color = Color.White.copy(alpha = 0.08f), style = Stroke(2f))
        }
    }
}

/**
 * 可信取证卡 — the home visual anchor: a digital-ID-style dark card carrying
 * forensic identity, device, signature algorithm, chain status, today's tasks,
 * plus two actions. Has real thickness (gradient + shield emblem).
 */
@Composable
fun TrustedEvidenceCard(
    identity: String,
    deviceId: String,
    algorithm: String,
    chainStatus: String,
    todayTasks: Int,
    onNewTask: () -> Unit,
    onOpenChain: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(16.dp)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Brush.linearGradient(listOf(GovBlueDeep, Color(0xFF143E70))))
            .heroTexture()
            .padding(18.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(40.dp).background(Color.White.copy(alpha = 0.14f), RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.Badge, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("可信取证卡", style = MaterialTheme.typography.titleMedium, color = Color.White, fontWeight = FontWeight.Bold)
                Text("数字证据身份凭证", style = MaterialTheme.typography.labelMedium, color = Color.White.copy(alpha = 0.7f))
            }
            Box(
                Modifier.size(34.dp).background(Color.White.copy(alpha = 0.12f), CircleShape).pressable(onClick = onOpenChain),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.ContentCopy, contentDescription = "复制", tint = Color.White.copy(alpha = 0.9f), modifier = Modifier.size(16.dp))
            }
        }
        Spacer(Modifier.height(16.dp))
        CardKv("取证身份", identity)
        CardKv("设备编号", deviceId, mono = true)
        CardKv("签名算法", algorithm, mono = true)
        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("证据链状态", style = MaterialTheme.typography.bodyMedium, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.weight(1f))
            Box(
                Modifier.background(Color.White.copy(alpha = 0.16f), CircleShape).padding(horizontal = 10.dp, vertical = 4.dp),
            ) {
                Text(chainStatus, style = MaterialTheme.typography.labelMedium, color = Color.White, fontWeight = FontWeight.SemiBold)
            }
        }
        CardKv("今日取证任务", "$todayTasks")
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            GradientButton(text = "新建取证", onClick = onNewTask, modifier = Modifier.weight(1f))
            Box(
                Modifier.weight(1f).height(52.dp)
                    .background(Color.White.copy(alpha = 0.14f), RoundedCornerShape(12.dp))
                    .border(1.dp, Color.White.copy(alpha = 0.25f), RoundedCornerShape(12.dp))
                    .pressable(onClick = onOpenChain),
                contentAlignment = Alignment.Center,
            ) {
                Text("查看证据链", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
            }
        }
    }
}

@Composable
private fun CardKv(k: String, v: String, mono: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        Text(k, style = MaterialTheme.typography.bodyMedium, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.weight(1f))
        Text(
            v,
            style = MaterialTheme.typography.bodyLarge,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
            fontFamily = if (mono) FontFamily.Monospace else null,
        )
    }
}

/** Core-service entry: tinted line icon + title + one-line description + chevron. */
@Composable
fun ServiceEntry(
    icon: ImageVector,
    title: String,
    desc: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .glass(RoundedCornerShape(14.dp))
            .pressable(onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(42.dp)
                .shadow(2.dp, RoundedCornerShape(12.dp), ambientColor = ShadowSoft, spotColor = ShadowSoft)
                .background(accent.copy(alpha = 0.14f), RoundedCornerShape(12.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.SemiBold)
            Text(desc, style = MaterialTheme.typography.bodySmall, color = InkFaint, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, contentDescription = null, tint = InkFaint, modifier = Modifier.size(20.dp))
    }
}

/** 最近取证任务卡 — file, task id, time + status pills. */
@Composable
fun TaskCard(
    taskId: String,
    fileName: String,
    time: String,
    pills: List<Pair<String, StatusTone>>,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth().padding(vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(38.dp)
                    .shadow(2.dp, RoundedCornerShape(10.dp), ambientColor = ShadowSoft, spotColor = ShadowSoft)
                    .background(TintCard, RoundedCornerShape(10.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.Badge, contentDescription = null, tint = GovBlue, modifier = Modifier.size(18.dp))
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(fileName, style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("$taskId · $time", style = MaterialTheme.typography.labelMedium, color = InkFaint, fontFamily = FontFamily.Monospace)
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            pills.forEach { (t, tone) -> StatusPill(t, tone) }
        }
    }
}

/** 证据时间线:蓝点 + 竖线连接,克制。events = (时间, 事件)。 */
@Composable
fun EvidenceTimeline(events: List<Pair<String, String>>, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        events.forEachIndexed { i, (time, label) ->
            Row {
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(16.dp)) {
                    Box(Modifier.size(10.dp).background(GovBlue, CircleShape))
                    if (i < events.lastIndex) {
                        Box(Modifier.width(2.dp).height(36.dp).background(GovBlue.copy(alpha = 0.25f)))
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.padding(bottom = if (i < events.lastIndex) 8.dp else 0.dp)) {
                    Text(label, style = MaterialTheme.typography.bodyLarge, color = Ink, fontWeight = FontWeight.SemiBold)
                    Text(time, style = MaterialTheme.typography.labelMedium, color = InkFaint, fontFamily = FontFamily.Monospace)
                }
            }
        }
    }
}

/** 服务状态行:名称 + 就绪标签。 */
@Composable
fun ServiceStatusRow(name: String, ready: Boolean) {
    Row(Modifier.fillMaxWidth().padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(7.dp).background(if (ready) com.vpsg.jianyuanshield.ui.theme.SuccessGreen else InkFaint, CircleShape))
        Spacer(Modifier.width(10.dp))
        Text(name, style = MaterialTheme.typography.bodyLarge, color = InkBody, modifier = Modifier.weight(1f))
        StatusPill(if (ready) "可用" else "未就绪", if (ready) StatusTone.Success else StatusTone.Neutral)
    }
}
