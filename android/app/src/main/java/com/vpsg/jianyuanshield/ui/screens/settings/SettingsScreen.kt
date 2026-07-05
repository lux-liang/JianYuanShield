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
                SectionHeader("可信服务节点", subtitle = "连接后可启用完整取证、合规核验与证据签名能力")
                Spacer(Modifier.height(14.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    singleLine = true,
                    label = { Text("服务节点 URL") },
                    placeholder = { Text("http://10.0.2.2:8026") },
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
                    "本地调试环境可使用 10.0.2.2,真机预览请填写同一局域网服务地址。",
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
                    subtitle = if (demoMode) "已启用 · 使用本地模拟数据预览完整流程" else "未连接服务节点时使用本地模拟数据预览完整流程",
                    trailing = {
                        Switch(checked = demoMode, onCheckedChange = viewModel::setDemoMode)
                    },
                )
            }

            SectionCard {
                SectionHeader("模型服务", subtitle = if (demoMode) "本地演示 · 全部就绪" else "连接节点后启用")
                Spacer(Modifier.height(6.dp))
                ServiceStatusRow("溯源模型", demoMode)
                ServiceStatusRow("合规模型", demoMode)
                ServiceStatusRow("证据签名", demoMode)
                ServiceStatusRow("报告生成", demoMode)
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

