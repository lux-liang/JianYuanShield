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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vpsg.jianyuanshield.BuildConfig
import com.vpsg.jianyuanshield.ui.pub.ConnProbe
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubDetectViewModel
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.SecondaryButton
import com.vpsg.jianyuanshield.ui.pub.SectionHeader
import kotlinx.coroutines.launch

@Composable
fun PubServerScreen(
    vm: PubDetectViewModel,
    onBack: () -> Unit,
) {
    val savedUrl by vm.baseUrl.collectAsState()
    val demoMode by vm.demoMode.collectAsState()
    val bigFont by vm.bigFont.collectAsState()
    val tokenConfigured by vm.apiTokenConfigured.collectAsState()
    val scope = rememberCoroutineScope()

    var urlText by remember(savedUrl) { mutableStateOf(savedUrl) }
    var probe by remember { mutableStateOf<ConnProbe>(ConnProbe.Idle) }
    var savedHint by remember { mutableStateOf(false) }
    var tokenText by remember { mutableStateOf("") }
    var tokenHint by remember { mutableStateOf(false) }
    var tokenError by remember { mutableStateOf<String?>(null) }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 30.dp)) {
                PubNavBar("服务器设置", subtitle = "连通状态不等于结论可发布", onBack = onBack)
            }

            Column(Modifier.offset(y = (-14).dp)) {
                SectionHeader("后端服务器地址")
                PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
                    OutlinedTextField(
                        value = urlText,
                        onValueChange = { urlText = it; savedHint = false },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        placeholder = {
                            Text(
                                if (BuildConfig.DEBUG) "http://10.0.2.2:8026" else "https://api.example.com",
                                color = Pub.Ink3,
                                fontSize = 14.sp,
                            )
                        },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        colors = TextFieldDefaults.colors(
                            focusedContainerColor = Color.White,
                            unfocusedContainerColor = Color.White,
                            focusedIndicatorColor = Pub.Blue,
                            unfocusedIndicatorColor = Pub.Hair,
                            cursorColor = Pub.Blue,
                            focusedTextColor = Pub.Ink,
                            unfocusedTextColor = Pub.Ink,
                        ),
                    )
                    Text(
                        if (BuildConfig.DEBUG) {
                            "Debug 仅放行 10.0.2.2 模拟器宿主的明文 HTTP；其他地址须使用 HTTPS。"
                        } else {
                            "正式包只允许 HTTPS；默认 .invalid 地址会安全地连接失败，请填写已授权节点。"
                        },
                        color = Pub.Ink3, fontSize = 11.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 10.dp),
                    )
                    // 连接结果
                    ConnResult(probe, Modifier.padding(top = 12.dp))

                    Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        SecondaryButton("测试连接", Modifier.weight(1f), icon = PubIcons.bolt) {
                            scope.launch {
                                probe = ConnProbe.Checking
                                probe = try {
                                    vm.saveBaseUrl(urlText)
                                    vm.testConnection()
                                } catch (error: Throwable) {
                                    ConnProbe.Fail(error.message ?: "服务节点地址无效")
                                }
                            }
                        }
                        SecondaryButton(if (savedHint) "已保存 ✓" else "保存地址", Modifier.weight(1f), icon = PubIcons.save) {
                            scope.launch {
                                try {
                                    vm.saveBaseUrl(urlText)
                                    savedHint = true
                                } catch (error: Throwable) {
                                    savedHint = false
                                    probe = ConnProbe.Fail(error.message ?: "服务节点地址无效")
                                }
                            }
                        }
                    }
                }

                SectionHeader("短期 API Token")
                PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
                    Text(
                        if (tokenConfigured) "当前已配置运行时 Token（值不回显）" else "当前未配置 Token",
                        color = if (tokenConfigured) Pub.Ok else Pub.Warn,
                        fontSize = 12.5.sp,
                        fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
                    )
                    OutlinedTextField(
                        value = tokenText,
                        onValueChange = {
                            tokenText = it.take(512)
                            tokenHint = false
                            tokenError = null
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                        singleLine = true,
                        label = { Text("部署方签发的短期 Token") },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        colors = TextFieldDefaults.colors(
                            focusedContainerColor = Color.White,
                            unfocusedContainerColor = Color.White,
                            focusedIndicatorColor = Pub.Blue,
                            unfocusedIndicatorColor = Pub.Hair,
                            cursorColor = Pub.Blue,
                            focusedTextColor = Pub.Ink,
                            unfocusedTextColor = Pub.Ink,
                        ),
                    )
                    Text(
                        "Token 仅在运行时注入 X-API-Key，不写入 URL、日志或安装包，也不参与系统备份。",
                        color = Pub.Ink3,
                        fontSize = 11.sp,
                        lineHeight = 17.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    tokenError?.let {
                        Text(it, color = Pub.Hi, fontSize = 11.5.sp, modifier = Modifier.padding(top = 6.dp))
                    }
                    Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        SecondaryButton(
                            if (tokenHint) "已保存 ✓" else "保存 Token",
                            Modifier.weight(1f),
                            PubIcons.lock,
                        ) {
                            if (tokenText.isNotBlank()) {
                                scope.launch {
                                    try {
                                        vm.saveApiToken(tokenText)
                                        tokenText = ""
                                        tokenHint = true
                                    } catch (error: Throwable) {
                                        tokenError = error.message ?: "API Token 格式无效"
                                    }
                                }
                            }
                        }
                        SecondaryButton("清除 Token", Modifier.weight(1f), PubIcons.close) {
                            scope.launch {
                                vm.saveApiToken("")
                                tokenText = ""
                                tokenHint = false
                            }
                        }
                    }
                }

                SectionHeader("演示模式")
                PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 6.dp)) {
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text("使用本地演示数据", color = Pub.Ink, fontSize = 14.5.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                            Text(
                                "只有你显式打开后才使用本地模拟数据；仅供界面预览，不形成结论、历史或凭证。关闭则真连后端，失败会明确报错。",
                                color = Pub.Ink3, fontSize = 11.5.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 3.dp, end = 8.dp),
                            )
                        }
                        Switch(
                            checked = demoMode,
                            onCheckedChange = { scope.launch { vm.setDemoMode(it) } },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = Color.White,
                                checkedTrackColor = Pub.Blue,
                                uncheckedThumbColor = Color.White,
                                uncheckedTrackColor = Pub.Ink3,
                            ),
                        )
                    }
                }

                SectionHeader("适老化")
                PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 6.dp)) {
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text("大字模式", color = Pub.Ink, fontSize = 14.5.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                            Text(
                                "整体字号放大一档,长辈看得更清楚。",
                                color = Pub.Ink3, fontSize = 11.5.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 3.dp, end = 8.dp),
                            )
                        }
                        Switch(
                            checked = bigFont,
                            onCheckedChange = { scope.launch { vm.setBigFont(it) } },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = Color.White,
                                checkedTrackColor = Pub.Blue,
                                uncheckedThumbColor = Color.White,
                                uncheckedTrackColor = Pub.Ink3,
                            ),
                        )
                    }
                }

                // 当前生效地址
                Row(
                    Modifier.fillMaxWidth().padding(start = 22.dp, end = 22.dp, top = 16.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(PubIcons.cloud, null, tint = Pub.Ink3, modifier = Modifier.size(14.dp))
                    Text("当前生效:$savedUrl", color = Pub.Ink3, fontSize = 11.5.sp)
                }

                PrimaryCta("完成", Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp), icon = PubIcons.check, onClick = onBack)

                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
private fun ConnResult(probe: ConnProbe, modifier: Modifier = Modifier) {
    val (bg, fg, icon, text) = when (probe) {
        is ConnProbe.Idle -> return
        is ConnProbe.Checking -> Quad(Color(0xFFEAF1FE), Pub.Blue, PubIcons.bolt, "正在连接…")
        is ConnProbe.Ok -> Quad(
            Pub.OkB, Pub.Ok, PubIcons.checkCircle,
            when (probe.mode) {
                "local_demo" -> "本地演示已显式开启 · 未测试服务器"
                "real_checkpoint" -> "连接成功 · 真实模型"
                else -> "连接成功 · 服务器仅返回流程模拟"
            } + if (probe.mode == "local_demo") "" else buildString {
                probe.version?.let { append(" · v$it") }
                if (probe.provenanceReadyModels.isNotEmpty()) {
                    append(" · 来源就绪 ")
                    append(probe.provenanceReadyModels.joinToString())
                } else {
                    append(" · 无来源就绪模型")
                }
            },
        )
        is ConnProbe.Fail -> Quad(Pub.HiB, Pub.Hi, PubIcons.warning, probe.message)
    }
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(bg)
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Icon(icon, null, tint = fg, modifier = Modifier.size(18.dp))
        Text(text, color = fg, fontSize = 12.5.sp, lineHeight = 18.sp)
    }
}

private data class Quad(
    val bg: Color,
    val fg: Color,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
    val text: String,
)
