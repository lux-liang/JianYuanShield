package com.vpsg.jianyuanshield.ui.screens.settings

import androidx.compose.animation.Crossfade
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.RestartAlt
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.BuildConfig
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.SecondaryButton
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.ServiceStatusRow
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.foundation.GradientButton
import com.vpsg.jianyuanshield.ui.theme.Divider
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue
import com.vpsg.jianyuanshield.ui.theme.TextMid

@Composable
fun SettingsScreen(
    onOpenAbout: () -> Unit,
    viewModel: SettingsViewModel = viewModel(factory = SettingsViewModel.Factory),
) {
    val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
    val ping by viewModel.ping.collectAsStateWithLifecycle()
    val demoMode by viewModel.demoMode.collectAsStateWithLifecycle()
    var text by rememberSaveable { mutableStateOf("") }

    LaunchedEffect(baseUrl) {
        if (text.isEmpty()) text = baseUrl
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        GradientTopBar(title = "设置", subtitle = "服务节点与演示环境")

        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SectionCard {
                SectionHeader("服务节点", subtitle = "连接成功仅表示节点可达；实际能力以后端声明门禁为准")
                Spacer(Modifier.height(14.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    singleLine = true,
                    label = { Text("服务节点 URL") },
                    placeholder = {
                        Text(if (BuildConfig.DEBUG) "http://10.0.2.2:8026" else "https://api.example.com")
                    },
                    leadingIcon = { Icon(Icons.Rounded.Dns, contentDescription = null) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = ElectricBlue,
                        unfocusedBorderColor = Divider,
                        focusedLabelColor = ElectricBlue,
                        unfocusedLabelColor = TextMid,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    if (BuildConfig.DEBUG) {
                        "Debug 仅允许 10.0.2.2 模拟器宿主地址使用明文 HTTP；其他节点请使用 HTTPS。"
                    } else {
                        "正式包禁止明文 HTTP；请配置已授权的 HTTPS 服务节点。"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = com.vpsg.jianyuanshield.ui.theme.InkFaint,
                )

                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    GradientButton(
                        text = "保存并检测",
                        onClick = { viewModel.saveAndTest(text.trim()) },
                        enabled = text.isNotBlank(),
                        loading = ping is UiState.Loading,
                        modifier = Modifier.weight(1f),
                    )
                    SecondaryButton(
                        text = "恢复默认",
                        icon = Icons.Rounded.RestartAlt,
                        onClick = {
                            text = viewModel.defaultBaseUrl
                            viewModel.resetToDefault()
                        },
                    )
                }

                Spacer(Modifier.height(12.dp))
                ConnectionStatus(ping)
            }

            SectionCard {
                SectionHeader(
                    "演示环境",
                    subtitle = if (demoMode) "已显式启用 · 模拟结果不可发布或生成凭证" else "已关闭 · 服务失败会明确报错，不自动回退模拟数据",
                    trailing = {
                        Switch(checked = demoMode, onCheckedChange = viewModel::setDemoMode)
                    },
                )
            }

            SectionCard {
                SectionHeader("能力提示", subtitle = "节点连通不等于盲检、合规或证据能力已就绪")
                Spacer(Modifier.height(6.dp))
                ServiceStatusRow("本地流程演示", demoMode)
                ServiceStatusRow("既有图片盲检", false)
                ServiceStatusRow("正式证据签名", false)
                ServiceStatusRow("可发布声明", false)
            }

            SectionCard(contentPadding = PaddingValues(0.dp)) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(onClick = onOpenAbout)
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Rounded.Info, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(12.dp))
                    Text(
                        "关于应用",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f),
                    )
                    Icon(
                        Icons.Rounded.ChevronRight,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(96.dp))
        }
    }
}

@Composable
private fun ConnectionStatus(ping: UiState<*>) {
    Crossfade(targetState = ping, label = "ping-state") { p ->
        when (p) {
            is UiState.Idle -> Text(
                "保存后将自动测试连通性",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            is UiState.Loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Text("正在测试连接…", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            is UiState.Success -> StatusPill("连接成功", StatusTone.Success)
            is UiState.Error -> Text(
                p.message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}
