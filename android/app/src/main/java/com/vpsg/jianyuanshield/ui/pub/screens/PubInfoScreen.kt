package com.vpsg.jianyuanshield.ui.pub.screens

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.ui.pub.ClayIcon
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar

private data class InfoSection(
    val heading: String,
    val paragraphs: List<String> = emptyList(),
    val legend: List<Pair<Long, String>> = emptyList(),
)
private data class InfoContent(val title: String, val subtitle: String, val palette: Int, val sections: List<InfoSection>)

@Composable
fun PubInfoScreen(infoKey: String, onBack: () -> Unit) {
    val content = infoContent(infoKey)
    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 40.dp)) {
                PubNavBar(content.title, subtitle = content.subtitle, onBack = onBack)
            }
            Column(Modifier.offset(y = (-16).dp), verticalArrangement = Arrangement.spacedBy(13.dp)) {
                content.sections.forEach { sec ->
                    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(18.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(11.dp)) {
                            ClayIcon(PubIcons.shieldCheck, palette = content.palette, size = 32.dp, corner = 10.dp, iconSize = 17.dp)
                            Text(sec.heading, color = Pub.Ink, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                        }
                        sec.paragraphs.forEach { p ->
                            Text(p, color = Pub.Ink2, fontSize = 13.sp, lineHeight = 21.sp, modifier = Modifier.padding(top = 10.dp))
                        }
                        sec.legend.forEach { (argb, t) ->
                            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                                Box(Modifier.padding(top = 6.dp).size(9.dp).clip(RoundedCornerShape(50)).background(Color(argb)))
                                Text(t, color = Pub.Ink2, fontSize = 13.sp, lineHeight = 21.sp, modifier = Modifier.weight(1f))
                            }
                        }
                    }
                }
                Row(
                    Modifier.fillMaxWidth().padding(start = 22.dp, end = 22.dp, top = 8.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(PubIcons.shield, null, tint = Pub.Blue, modifier = Modifier.size(14.dp))
                    Text("技术支持 · 新疆大学 VPSG 实验室", color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.padding(start = 7.dp))
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

private fun infoContent(key: String): InfoContent = when (key) {
    "help" -> InfoContent(
        title = "帮助中心",
        subtitle = "怎么用?结果怎么看?都在这",
        palette = 1,
        sections = listOf(
            InfoSection("怎么鉴别一张图", listOf(
                "1. 在「鉴别」页点拍照或从相册选一张图。",
                "2. 确认是这张后点「开始鉴别」,图片会上传到鉴别服务器分析。",
                "3. 几秒后出结果:结论 + 各项指标;可保存成凭证或分享。",
            )),
            InfoSection("结果颜色怎么看", legend = listOf(
                0xFF13A06A to "绿色「通过核验」:成功恢复出可信的来源水印,来源可追溯。",
                0xFFE0901F to "琥珀「水印降级」:有水印残留但已明显降级,可能被压缩或二次处理。",
                0xFFE0463C to "红色「未能确认」:没恢复出可信水印,无法确认来源,转发请谨慎。",
            )),
            InfoSection("连不上服务器怎么办", listOf(
                "去「我的 → 服务器设置」填后端地址并点测试连接。",
                "连不上时 App 会自动用本地演示数据,并在结果页标注「离线演示」,不作为真实结论。",
            )),
        ),
    )
    "privacy" -> InfoContent(
        title = "隐私与数据",
        subtitle = "你的图片怎么被使用",
        palette = 2,
        sections = listOf(
            InfoSection("图片去哪了", listOf(
                "点「开始鉴别」后,所选图片会经压缩后上传到你配置的鉴别服务器,用于这一次检测。",
                "首次鉴别会弹窗征得你同意;之后不再询问。",
            )),
            InfoSection("会不会留存", listOf(
                "服务器为了生成可核验的报告与凭证,会保存本次的检测结果与图像工件。",
                "如果你不希望上传,可在「服务器设置」打开演示模式——全程用本地模拟数据,不联网。",
            )),
            InfoSection("凭证与指纹", listOf(
                "每次鉴别生成的凭证带 SHA-256 指纹与可扫码核验链接,用来证明结论未被篡改。",
            )),
        ),
    )
    else -> InfoContent(
        title = "关于鉴源盾",
        subtitle = "我们是谁、在做什么",
        palette = 0,
        sections = listOf(
            InfoSection("鉴源盾是什么", listOf(
                "一款面向普通人的图片来源核验工具:基于「主动取证水印」技术,帮你确认一张图的来源是否可追溯、是否被二次处理。",
            )),
            InfoSection("技术原理(大白话)", listOf(
                "我们在图片里嵌入肉眼看不见的来源水印,即使图片被压缩、裁剪甚至换脸,也能尝试把它恢复出来,从而判断来源是否可信。",
            )),
            InfoSection("版本与团队", listOf(
                "版本 V2.0.0。",
                "技术支持:新疆大学 VPSG 实验室。符合国家《人工智能生成合成内容标识办法》。",
            )),
        ),
    )
}
