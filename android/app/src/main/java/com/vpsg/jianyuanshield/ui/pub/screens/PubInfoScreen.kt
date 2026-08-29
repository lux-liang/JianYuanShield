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
            InfoSection("怎么使用登记来源凭证", listOf(
                "1. 在「登记核验」页选择新内容，填写应用侧主体引用。",
                "2. 只选择 provenance_ready 模型完成保护登记，并保存受保护 PNG 与 content_id。",
                "3. 核验时同时提交图片和 content_id；只有 registered_blind_verification 且 claim_valid=true 才形成可发布技术记录。",
            )),
            InfoSection("结果颜色怎么看", legend = listOf(
                0xFF13A06A to "绿色：预登记消息匹配，且 checkpoint 与签名声明门禁通过。",
                0xFFE0901F to "琥珀：消息匹配但声明门禁未通过，只能作为 operational 记录。",
                0xFFE0463C to "红色：未匹配指定 content_id 的预登记消息。",
            )),
            InfoSection("连不上服务器怎么办", listOf(
                "去「我的 → 服务器设置」填后端地址并点测试连接。",
                "连接失败会明确报错，App 不会自动生成模拟成功结果；如需预览流程，请自行显式开启演示模式。",
            )),
        ),
    )
    "privacy" -> InfoContent(
        title = "隐私与数据",
        subtitle = "你的图片怎么被使用",
        palette = 2,
        sections = listOf(
            InfoSection("图片去哪了", listOf(
                "点「保护并登记」或「核验预登记凭证」后，所选图片以原始字节上传到你配置的服务器。",
                "首次上传会弹窗征得你同意；之后不再询问。",
            )),
            InfoSection("会不会留存", listOf(
                "保护接口不持久化原始上传图，但会保存 creator_ref、登记元数据和受保护 PNG；自建节点应单独核对其保留策略。",
                "如果你不希望上传，可显式开启本地演示模式；模拟数据不联网，也不形成可发布结论或凭证。",
            )),
            InfoSection("凭证与指纹", listOf(
                "正式凭证还必须是 registered_blind_verification 且 claim_valid=true；SHA-256 只用于核对工件完整性，不是图片真伪鉴定。",
            )),
        ),
    )
    else -> InfoContent(
        title = "关于鉴源盾",
        subtitle = "我们是谁、在做什么",
        palette = 0,
        sections = listOf(
            InfoSection("鉴源盾是什么", listOf(
                "本 Android 端已接入跨请求保护登记与 decode-only 核验生命周期，并对模型来源、checkpoint、校准与签名状态做 fail-closed 展示。",
            )),
            InfoSection("技术原理(大白话)", listOf(
                "系统为新内容嵌入与 content_id 绑定的来源消息；后续只核验指定登记记录。它不是任意图片真假、AI 生成或换脸分类器。",
            )),
            InfoSection("版本与团队", listOf(
                "版本 V1.0.0。",
                "技术支持：新疆大学 VPSG 实验室。本工具提供技术验证记录，不替代监管认定或司法鉴定。",
            )),
        ),
    )
}
