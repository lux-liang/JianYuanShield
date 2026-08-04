package com.vpsg.jianyuanshield.ui.pub.screens

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubSample

@Composable
fun PubArticleScreen(index: Int, onBack: () -> Unit) {
    val article = com.vpsg.jianyuanshield.ui.pub.PubSample.articles.getOrNull(index)
    val title = article?.title ?: "用图安全课堂"
    val category = article?.category ?: "科普"
    val meta = if (article != null) "${article.minutes} 分钟 · ${article.views}" else ""
    val body = articleBody(index)

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 44.dp)) {
                PubNavBar("用图安全课堂", onBack = onBack)
                Box(
                    Modifier.padding(top = 16.dp).clip(RoundedCornerShape(8.dp)).background(Color.White.copy(alpha = 0.18f))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) { Text(category, color = Color.White, fontSize = 10.5.sp, fontWeight = FontWeight.Bold) }
                Text(title, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, lineHeight = 30.sp, modifier = Modifier.padding(top = 12.dp))
                if (meta.isNotBlank()) {
                    Text(meta, color = Color.White.copy(alpha = 0.82f), fontSize = 11.5.sp, modifier = Modifier.padding(top = 8.dp))
                }
            }

            Column(Modifier.offset(y = (-18).dp)) {
                PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(18.dp)) {
                    body.forEachIndexed { i, para ->
                        if (i > 0) {
                            Box(Modifier.fillMaxWidth().padding(vertical = 14.dp).height(1.dp).background(Pub.Hair))
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Box(
                                Modifier.size(26.dp).clip(RoundedCornerShape(50)).background(paraBadge(i)),
                                contentAlignment = Alignment.Center,
                            ) { Text("${i + 1}", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.ExtraBold) }
                            Text(
                                para,
                                color = Pub.Ink2, fontSize = 13.5.sp, lineHeight = 22.sp,
                                modifier = Modifier.weight(1f).padding(top = 2.dp),
                            )
                        }
                    }
                }

                // 知识点提示条(蓝紫渐变),对齐网页
                Row(
                    Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 14.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(Brush.linearGradient(listOf(Color(0xFFEAF1FE), Color(0xFFEFEBFF))))
                        .border(1.dp, Color(0xFFE5E9FB), RoundedCornerShape(14.dp))
                        .padding(horizontal = 14.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(11.dp),
                ) {
                    Box(
                        Modifier.size(32.dp).clip(RoundedCornerShape(10.dp))
                            .background(Brush.linearGradient(listOf(Color(0xFF7E8DF0), Color(0xFF4E5BD0)))),
                        contentAlignment = Alignment.Center,
                    ) { Icon(PubIcons.info, null, tint = Color.White, modifier = Modifier.size(17.dp)) }
                    Column(Modifier.weight(1f)) {
                        Text("知识点", color = Color(0xFF22306B), fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
                        Text(articleTip(index), color = Color(0xFF6B76A3), fontSize = 11.5.sp, lineHeight = 16.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                }

                Row(
                    Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 14.dp)
                        .clip(RoundedCornerShape(14.dp)).background(Pub.OkB)
                        .padding(horizontal = 14.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(PubIcons.shieldCheck, null, tint = Pub.Ok, modifier = Modifier.size(18.dp))
                    Text("发布前可用「登记核验」保护内容；核验时必须同时提供该记录的 content_id。", color = Color(0xFF0E7A50), fontSize = 12.5.sp, lineHeight = 18.sp)
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

private fun paraBadge(i: Int): Brush = when (i % 3) {
    0 -> Brush.linearGradient(listOf(Color(0xFF5A92FF), Color(0xFF235FD8)))
    1 -> Brush.linearGradient(listOf(Color(0xFF9B7BF6), Color(0xFF5E3FD0)))
    else -> Brush.linearGradient(listOf(Color(0xFFFFB257), Color(0xFFEE7C20)))
}

private fun articleTip(index: Int): String = when (index) {
    0 -> "截图能改:金额、时间、对方名字几秒就能 P。到账以你自己账户记录为准。"
    1 -> "手指、耳朵、牙齿、发丝边缘和背景文字,是 AI 图最容易露馅的地方。"
    2 -> "光影、边缘、对称性是识破换脸/合成的三大突破口。"
    3 -> "「没读到水印」不等于有问题,但带且可恢复水印的,来源更可追溯。"
    else -> "若图片发布前已由鉴源盾保护，可核对来源水印；没有本体系水印时不能据此判断真假。"
}

private fun articleBody(index: Int): List<String> = when (index) {
    0 -> listOf(
        "收到「转账成功」截图,先别急着发货或确认。截图最容易被改:金额、时间、对方名字,改起来几秒钟。",
        "三招人工核查:一看到账短信/银行 App 里有没有这笔;二看截图里字体、对齐有没有不一致;三向发送方索取原始交易记录。",
        "记住:截图≠到账。真正到账以你自己账户的记录为准。",
    )
    1 -> listOf(
        "AI 画的人，乍看挺真,细节最容易露馅。重点看手指(数量、关节)、耳朵(左右不对称、形状怪)、牙齿、发丝边缘。",
        "再看背景:文字会变成乱码、栏杆/砖缝会错位、光影方向对不上。",
        "拿不准就核对原始发布渠道；只有发布前已登记的内容，才能用本系统 content_id 核验来源水印。",
    )
    2 -> listOf(
        "「明星同框」「名人合影」很多是换脸或拼接。最容易看出来的是光影:脸和身体的光照方向、冷暖不一致,脖子和下巴接缝处发虚。",
        "还可以看边缘:发际线、耳朵附近有没有模糊、错位。",
        "涉及名人、热点的图，转发前应核对权威原始来源；本系统不提供通用换脸检测。",
    )
    3 -> listOf(
        "正规平台和 AI 工具,常会在图里嵌入肉眼看不见的「来源水印」,相当于给图片盖了个看不见的章。",
        "鉴源盾先为新内容写入与登记记录绑定的来源消息，之后只能针对指定 content_id 做 decode-only 核验。",
        "「没匹配到登记消息」不等于图片有问题；匹配也只说明与本系统预登记记录一致，不代表自然人身份或图片真假。",
    )
    else -> listOf(
        "家里长辈最容易转发这几类:养生神药、内部消息、抽奖中奖、催泪故事配图、伪造的官方通知。",
        "共同点:配一张「证据图」让你深信不疑,而这张图往往是拼接或 AI 生成的。",
        "提醒长辈：鉴源盾核对的是本体系主动写入的来源水印；没有本体系水印时，应结合发布账号、原始链接等渠道继续核实。",
    )
}
