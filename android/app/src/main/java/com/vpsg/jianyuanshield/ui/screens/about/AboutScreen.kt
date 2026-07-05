package com.vpsg.jianyuanshield.ui.screens.about

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.BuildConfig
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.KeyValueRow
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader

@Composable
fun AboutScreen(onBack: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        GradientTopBar(title = "关于", subtitle = "应用信息 · 合规依据", onBack = onBack)

        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SectionCard {
                SectionHeader("应用信息")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("应用", "鉴源盾 JianYuanShield")
                KeyValueRow("版本", "v${BuildConfig.VERSION_NAME}")
                KeyValueRow("实验室", "新疆大学 VPSG")
                KeyValueRow("合规", "《人工智能生成合成内容标识办法》")
            }

            SectionCard {
                SectionHeader("五端统一")
                Spacer(Modifier.height(8.dp))
                Text(
                    "Android 客户端与 Web / iOS / 小程序 / 鸿蒙五端共用同一可信服务后台，" +
                        "保证溯源与取证结果在各端一致。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            SectionCard {
                SectionHeader("合规与资质")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("合规依据", "《AI 标识办法》")
                KeyValueRow("证据签名", "Ed25519")
                KeyValueRow("数据处理", "本地推理 · 检材不出端")
                KeyValueRow("备案号", "新ICP备2026XXXXXX号", mono = true)
            }

            SectionCard {
                SectionHeader("技术规格")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("溯源模型", "LIDMark 等 4 种")
                KeyValueRow("哈希算法", "SHA-256", mono = true)
                KeyValueRow("基准数据集", "LFW 13,233 张")
                KeyValueRow("最低系统", "Android 8.0+")
            }

            SectionCard {
                SectionHeader("支持与反馈")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("主管实验室", "新疆大学 VPSG")
                KeyValueRow("更新日志", "v1.0.0 · 2026-06")
                Spacer(Modifier.height(6.dp))
                Text(
                    "演示模式下使用本地模拟数据预览完整流程，不构成正式取证结论。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
