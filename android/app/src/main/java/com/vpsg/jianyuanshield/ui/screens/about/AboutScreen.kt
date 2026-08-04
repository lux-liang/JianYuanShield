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
        GradientTopBar(title = "关于", subtitle = "应用信息 · 能力边界", onBack = onBack)

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
                KeyValueRow("法规参考", "《人工智能生成合成内容标识办法》")
            }

            SectionCard {
                SectionHeader("五端统一")
                Spacer(Modifier.height(8.dp))
                Text(
                    "Android 客户端与 Web / iOS / 小程序 / 鸿蒙端按同一 REST 契约访问后端；" +
                        "实际能力和可发布性以后端状态及声明门禁为准。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            SectionCard {
                SectionHeader("能力与依据")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("法规参考", "《人工智能生成合成内容标识办法》")
                KeyValueRow("证据状态", "以 /api/claims 与签名 artifact 为准")
                KeyValueRow("数据处理", "图片上传至所配置服务；衍生产物按服务端 TTL 管理")
            }

            SectionCard {
                SectionHeader("技术规格")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("溯源模型", "LIDMark 等 4 种")
                KeyValueRow("哈希算法", "SHA-256", mono = true)
                KeyValueRow("评测状态", "以 /api/claims 与签名 artifact 为准")
                KeyValueRow("最低系统", "Android 8.0+")
            }

            SectionCard {
                SectionHeader("支持与反馈")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("主管实验室", "新疆大学 VPSG")
                KeyValueRow("当前版本", "v${BuildConfig.VERSION_NAME}")
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
