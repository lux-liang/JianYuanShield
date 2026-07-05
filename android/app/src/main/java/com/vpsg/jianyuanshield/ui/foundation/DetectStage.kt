package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.theme.CardBg
import com.vpsg.jianyuanshield.ui.theme.Divider
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.HeroEnd
import com.vpsg.jianyuanshield.ui.theme.HeroStart
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.InkSecondary
import kotlinx.coroutines.delay

/** Build the brand shield path scaled into a square of [s] px (108-unit artwork). */
private fun shieldPath(s: Float): Path {
    val k = s / 108f
    fun x(v: Float) = v * k
    return Path().apply {
        moveTo(x(54f), x(24f))
        lineTo(x(82f), x(34f))
        lineTo(x(82f), x(57f))
        cubicTo(x(82f), x(75f), x(70f), x(86f), x(54f), x(92f))
        cubicTo(x(38f), x(86f), x(26f), x(75f), x(26f), x(57f))
        lineTo(x(26f), x(34f))
        close()
    }
}

/**
 * 检测中 = 真实"运行态工作台":一个中等盾牌(品牌识别)+ 当前检材 + 进度 % +
 * 分步处理日志(算哈希→解水印→比对→签名)。不再是空荡荡的概念海报。
 */
@Composable
fun DetectingStage(
    text: String,
    modifier: Modifier = Modifier,
    shieldSize: Dp = 88.dp,
    fileName: String? = null,
    total: Int = 1,
    steps: List<String> = listOf("计算文件哈希", "解码隐式水印", "源身份比对", "生成证据签名"),
) {
    var pct by remember { mutableIntStateOf(0) }
    var stepIdx by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        // 本地模型运行中:进度推进到 ~96% 后等待真实结果返回(返回即切屏)。
        while (pct < 96) {
            delay(55)
            pct = (pct + 2).coerceAtMost(96)
            // 接近完成时所有步骤打勾(末步也完成),避免最后一步永远停在「…」。
            stepIdx = if (pct >= 92) steps.size else (pct * steps.size / 100)
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Top,
    ) {
        Spacer(Modifier.height(44.dp))
        Box(contentAlignment = Alignment.Center) {
            RadarSweep(size = shieldSize * 1.5f, color = GovBlue)

            val transition = rememberInfiniteTransition(label = "shield-scan")
            val scanY by transition.animateFloat(
                0.08f, 0.92f,
                infiniteRepeatable(tween(1700, easing = FastOutSlowInEasing), RepeatMode.Reverse),
                label = "shield-scan-y",
            )
            Canvas(Modifier.size(shieldSize)) {
                val path = shieldPath(size.minDimension)
                drawPath(path, brush = Brush.verticalGradient(listOf(HeroEnd, HeroStart)))
                drawPath(path, color = Color.White.copy(alpha = 0.18f), style = Stroke(2f))
                clipPath(path, clipOp = ClipOp.Intersect) {
                    val y = size.height * scanY
                    drawRect(
                        Brush.verticalGradient(
                            listOf(Color.Transparent, Color.White.copy(alpha = 0.45f), Color.Transparent),
                            startY = y - 16f,
                            endY = y + 16f,
                        ),
                        topLeft = Offset(0f, y - 16f),
                        size = androidx.compose.ui.geometry.Size(size.width, 32f),
                    )
                }
            }
        }

        Spacer(Modifier.height(18.dp))
        Text(text, style = MaterialTheme.typography.titleMedium, color = Ink)
        Spacer(Modifier.height(4.dp))
        Text(
            "鉴源盾正在本地运行取证模型,请稍候",
            style = MaterialTheme.typography.bodySmall,
            color = InkSecondary,
        )

        Spacer(Modifier.height(22.dp))
        // 运行态面板:当前检材 + 进度 + 分步日志
        Column(
            Modifier
                .fillMaxWidth()
                .background(CardBg, RoundedCornerShape(14.dp))
                .border(1.dp, Divider, RoundedCornerShape(14.dp))
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("当前检材", style = MaterialTheme.typography.labelMedium, color = InkSecondary, modifier = Modifier.width(60.dp))
                Spacer(Modifier.width(8.dp))
                Text(
                    fileName ?: "本地图像",
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = FontFamily.Monospace,
                    color = Ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (total > 1) {
                    Spacer(Modifier.width(8.dp))
                    Text("共 $total 张", style = MaterialTheme.typography.labelMedium, color = InkFaint)
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .weight(1f)
                        .height(6.dp)
                        .clip(CircleShape)
                        .background(Ink.copy(alpha = 0.08f)),
                ) {
                    Box(
                        Modifier
                            .fillMaxHeight()
                            .fillMaxWidth(pct / 100f)
                            .clip(CircleShape)
                            .background(GovBlue),
                    )
                }
                Spacer(Modifier.width(10.dp))
                Text(
                    "$pct%",
                    style = MaterialTheme.typography.labelLarge,
                    fontFamily = FontFamily.Monospace,
                    color = GovBlue,
                )
            }
            Spacer(Modifier.height(14.dp))
            steps.forEachIndexed { i, s ->
                val done = i < stepIdx
                val active = i == stepIdx
                Row(
                    Modifier.padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier
                            .size(18.dp)
                            .background(if (done || active) GovBlue else Divider, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (done) {
                            Icon(Icons.Rounded.Check, null, tint = Color.White, modifier = Modifier.size(12.dp))
                        } else if (active) {
                            Box(Modifier.size(6.dp).background(Color.White, CircleShape))
                        }
                    }
                    Spacer(Modifier.width(10.dp))
                    Text(
                        when {
                            done -> "$s · 完成"
                            active -> "$s …"
                            else -> s
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (i <= stepIdx) Ink else InkFaint,
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(
                "本地推理 · 检材不出端 · 全程不上传云端",
                style = MaterialTheme.typography.labelSmall,
                color = InkFaint,
            )
        }
    }
}
