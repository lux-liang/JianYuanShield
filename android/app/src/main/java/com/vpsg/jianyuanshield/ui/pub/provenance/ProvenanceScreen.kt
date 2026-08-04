package com.vpsg.jianyuanshield.ui.pub.provenance

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.core.CreatorKeyIdentity
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.ui.pub.PrimaryCta
import com.vpsg.jianyuanshield.ui.pub.Pub
import com.vpsg.jianyuanshield.ui.pub.PubCard
import com.vpsg.jianyuanshield.ui.pub.PubHero
import com.vpsg.jianyuanshield.ui.pub.PubIcons
import com.vpsg.jianyuanshield.ui.pub.PubNavBar
import com.vpsg.jianyuanshield.ui.pub.PubTab
import com.vpsg.jianyuanshield.ui.pub.PubTabBar
import com.vpsg.jianyuanshield.ui.pub.SecondaryButton
import com.vpsg.jianyuanshield.ui.pub.SectionHeader

private enum class LifecycleMode { Protect, Verify, Revoke }

@Composable
fun ProvenanceScreen(
    onBack: () -> Unit,
    onOpenServer: () -> Unit,
    onSelectTab: (PubTab) -> Unit,
    vm: ProvenanceViewModel = viewModel(factory = ProvenanceViewModel.Factory),
) {
    val models by vm.models.collectAsState()
    val selectedModel by vm.selectedModel.collectAsState()
    val protect by vm.protect.collectAsState()
    val verify by vm.verify.collectAsState()
    val exportMessage by vm.exportMessage.collectAsState()
    val creatorIdentity by vm.creatorIdentity.collectAsState()
    val revocation by vm.revocation.collectAsState()
    var mode by rememberSaveable { mutableStateOf(LifecycleMode.Protect) }
    var protectUri by remember { mutableStateOf<Uri?>(null) }
    var verifyUri by remember { mutableStateOf<Uri?>(null) }
    var credentialUri by remember { mutableStateOf<Uri?>(null) }
    var creatorRef by rememberSaveable { mutableStateOf("") }
    var contentId by rememberSaveable { mutableStateOf("") }
    var revocationReason by rememberSaveable { mutableStateOf("creator_request") }

    val protectPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) {
        if (it != null) protectUri = it
    }
    val verifyPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) {
        if (it != null) verifyUri = it
    }
    val credentialPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {
        if (it != null) credentialUri = it
    }
    val exportPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("image/png")) {
        if (it != null) vm.exportProtected(it)
    }
    val credentialExportPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) {
        if (it != null) vm.exportSourceCredential(it)
    }

    Box(Modifier.fillMaxSize().background(Pub.Bg)) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                PubHero(contentPadding = PaddingValues(start = 22.dp, end = 22.dp, top = 14.dp, bottom = 28.dp)) {
                    PubNavBar(ProvenanceCopy.SCREEN_TITLE, subtitle = ProvenanceCopy.SCOPE, onBack = onBack)
                    Text(
                        ProvenanceCopy.LIMIT,
                        color = Color.White.copy(alpha = 0.78f),
                        fontSize = 11.5.sp,
                        modifier = Modifier.padding(top = 12.dp),
                    )
                }

                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    ModeButton("保护与登记", mode == LifecycleMode.Protect, Modifier.weight(1f)) {
                        mode = LifecycleMode.Protect
                    }
                    ModeButton("登记后核验", mode == LifecycleMode.Verify, Modifier.weight(1f)) {
                        mode = LifecycleMode.Verify
                    }
                    ModeButton("签名撤销", mode == LifecycleMode.Revoke, Modifier.weight(1f)) {
                        mode = LifecycleMode.Revoke
                    }
                }

                when (mode) {
                    LifecycleMode.Protect -> ProtectPane(
                        models = models,
                        creatorIdentity = creatorIdentity,
                        selectedModel = selectedModel,
                        creatorRef = creatorRef,
                        onCreatorRefChange = { creatorRef = it.take(128) },
                        imageUri = protectUri,
                        state = protect,
                        onSelectModel = vm::selectModel,
                        onRefreshModels = vm::refreshModels,
                        onPick = { protectPicker.launch("image/*") },
                        onProtect = { protectUri?.let { vm.protect(it, creatorRef) } },
                        onVerifyGenerated = {
                            val session = (protect as? UiState.Success)?.data
                            if (session != null) {
                                contentId = session.result.contentId
                                verifyUri = session.protectedUri
                                mode = LifecycleMode.Verify
                                vm.verifyGeneratedProtection()
                            }
                        },
                        onExport = {
                            val session = (protect as? UiState.Success)?.data
                            if (session != null) {
                                exportPicker.launch("jianyuanshield_${session.result.contentId}.png")
                            }
                        },
                        onExportCredential = {
                            val session = (protect as? UiState.Success)?.data
                            if (session != null) {
                                credentialExportPicker.launch("${session.result.contentId}.jys-credential.json")
                            }
                        },
                        exportMessage = exportMessage,
                        onOpenServer = onOpenServer,
                    )
                    LifecycleMode.Verify -> VerifyPane(
                        imageUri = verifyUri,
                        credentialUri = credentialUri,
                        contentId = contentId,
                        onContentIdChange = { contentId = it.trim().lowercase().take(32) },
                        state = verify,
                        onPick = { verifyPicker.launch("image/*") },
                        onPickCredential = { credentialPicker.launch(arrayOf("application/json", "text/plain")) },
                        onVerify = {
                            val image = verifyUri
                            if (image != null) {
                                if (credentialUri != null) vm.verifyWithSourceCredential(image, credentialUri!!)
                                else vm.verify(image, contentId)
                            }
                        },
                    )
                    LifecycleMode.Revoke -> RevokePane(
                        contentId = contentId,
                        onContentIdChange = { contentId = it.trim().lowercase().take(32) },
                        reasonCode = revocationReason,
                        onReasonChange = { revocationReason = it },
                        creatorIdentity = creatorIdentity,
                        state = revocation,
                        onRevoke = { vm.revoke(contentId, revocationReason) },
                    )
                }
                Spacer(Modifier.height(24.dp))
            }
            PubTabBar(PubTab.Detect, onSelectTab)
        }
    }
}

@Composable
private fun ProtectPane(
    models: UiState<ModelsStatusResponse>,
    creatorIdentity: UiState<CreatorKeyIdentity>,
    selectedModel: String?,
    creatorRef: String,
    onCreatorRefChange: (String) -> Unit,
    imageUri: Uri?,
    state: UiState<ProtectedSession>,
    onSelectModel: (String) -> Unit,
    onRefreshModels: () -> Unit,
    onPick: () -> Unit,
    onProtect: () -> Unit,
    onVerifyGenerated: () -> Unit,
    onExport: () -> Unit,
    onExportCredential: () -> Unit,
    exportMessage: String?,
    onOpenServer: () -> Unit,
) {
    SectionHeader("1 · 设备创作者持钥证明")
    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
        when (creatorIdentity) {
            UiState.Loading -> LinearProgressIndicator(Modifier.fillMaxWidth())
            is UiState.Error -> BoundaryError(creatorIdentity.message)
            is UiState.Success -> {
                Text("Ed25519 私钥由 Android Keystore 包装保护", color = Pub.Ok, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    "密钥指纹 ${creatorIdentity.data.fingerprintSha256.take(12)}…${creatorIdentity.data.fingerprintSha256.takeLast(6)}",
                    color = Pub.Ink2,
                    fontSize = 11.5.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Text("证明设备持有该私钥，不声明自然人实名身份。卸载应用前应先处理仍需撤销的登记记录。", color = Pub.Ink3, fontSize = 11.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 7.dp))
            }
            UiState.Idle -> Unit
        }
    }

    SectionHeader("2 · provenance_ready 模型")
    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
        when (models) {
            UiState.Loading -> LinearProgressIndicator(Modifier.fillMaxWidth())
            is UiState.Error -> {
                BoundaryError(models.message)
                Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SecondaryButton("重试", Modifier.weight(1f), PubIcons.refresh, onRefreshModels)
                    SecondaryButton("配置节点 / Token", Modifier.weight(1f), PubIcons.lock, onOpenServer)
                }
            }
            is UiState.Success -> {
                val ready = models.data.readyModels
                if (ready.isEmpty()) {
                    BoundaryError("当前没有同时通过注册、校准、签名信任门禁的模型。")
                    SecondaryButton(
                        "刷新模型状态",
                        Modifier.fillMaxWidth().padding(top = 10.dp),
                        PubIcons.refresh,
                        onRefreshModels,
                    )
                } else {
                    Text("仅列出 provenance_ready=true", color = Pub.Ink3, fontSize = 11.5.sp)
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        ready.keys.forEach { model ->
                            FilterChip(
                                selected = selectedModel == model,
                                onClick = { onSelectModel(model) },
                                label = { Text(model) },
                            )
                        }
                    }
                    val status = selectedModel?.let { ready[it] }
                    Text(
                        "registered=${status?.registered == true} · calibrated=${status?.calibrated == true} · trusted=${status?.trusted == true}",
                        color = Pub.Ink2,
                        fontSize = 11.5.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
            UiState.Idle -> Unit
        }
    }

    SectionHeader("3 · 新内容与应用侧引用")
    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
        SecondaryButton(
            if (imageUri == null) "选择要保护的新图片" else "已选择图片 · 重新选择",
            Modifier.fillMaxWidth(),
            PubIcons.gallery,
            onPick,
        )
        OutlinedTextField(
            value = creatorRef,
            onValueChange = onCreatorRefChange,
            label = { Text("creator_ref（应用侧主体引用）") },
            supportingText = { Text("不是自然人身份认证；会随登记记录持久化。") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            colors = provenanceFieldColors(),
        )
        PrimaryCta(
            ProvenanceCopy.PROTECT_ACTION,
            Modifier.padding(top = 14.dp),
            PubIcons.shieldCheck,
            brush = if (imageUri != null && selectedModel != null && isValidCreatorRef(creatorRef.trim()) && creatorIdentity is UiState.Success) {
                Pub.ctaBrush()
            } else {
                Brush.linearGradient(listOf(Pub.Ink3, Pub.Ink3))
            },
        ) {
            if (imageUri != null && selectedModel != null && isValidCreatorRef(creatorRef.trim()) && creatorIdentity is UiState.Success) onProtect()
        }
    }

    when (state) {
        UiState.Loading -> LoadingCard("正在嵌入水印、写入登记记录并绑定 checkpoint…")
        is UiState.Error -> ResultError(state.message)
        is UiState.Success -> {
            PresentationCard(state.data.result.toPresentation())
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                SecondaryButton("导出受保护 PNG", Modifier.weight(1f), PubIcons.download, onExport)
                SecondaryButton("导出签名来源凭证", Modifier.weight(1f), PubIcons.doc, onExportCredential)
            }
            PrimaryCta(
                "用签名来源凭证执行登记核验",
                Modifier.padding(horizontal = 16.dp),
                PubIcons.verified,
                onClick = onVerifyGenerated,
            )
            exportMessage?.let {
                Text(it, color = Pub.Ok, fontSize = 11.5.sp, modifier = Modifier.padding(horizontal = 20.dp))
            }
        }
        UiState.Idle -> Unit
    }
}

@Composable
private fun RevokePane(
    contentId: String,
    onContentIdChange: (String) -> Unit,
    reasonCode: String,
    onReasonChange: (String) -> Unit,
    creatorIdentity: UiState<CreatorKeyIdentity>,
    state: UiState<com.vpsg.jianyuanshield.data.remote.dto.RevocationResult>,
    onRevoke: () -> Unit,
) {
    SectionHeader("创作者签名撤销")
    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
        Text(
            "服务端签发一次性撤销意图，本机用登记时同一 Ed25519 私钥签名；私钥不会上传。",
            color = Pub.Ink2,
            fontSize = 12.sp,
            lineHeight = 18.sp,
        )
        OutlinedTextField(
            value = contentId,
            onValueChange = onContentIdChange,
            label = { Text("content_id") },
            singleLine = true,
            textStyle = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace),
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            colors = provenanceFieldColors(),
        )
        Text("撤销原因", color = Pub.Ink2, fontSize = 12.sp, modifier = Modifier.padding(top = 13.dp))
        Column(Modifier.padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            listOf(
                "creator_request" to "创作者主动撤销",
                "key_compromise" to "创作者密钥可能泄露",
                "mislabeling" to "登记标签错误",
                "policy_violation" to "违反发布策略",
            ).forEach { (code, label) ->
                FilterChip(
                    selected = reasonCode == code,
                    onClick = { onReasonChange(code) },
                    label = { Text(label) },
                )
            }
        }
        PrimaryCta(
            "签署并撤销登记记录",
            Modifier.padding(top = 12.dp),
            PubIcons.block,
            brush = if (isValidContentId(contentId) && creatorIdentity is UiState.Success) {
                Brush.linearGradient(listOf(Pub.Hi, Color(0xFFC93131)))
            } else {
                Brush.linearGradient(listOf(Pub.Ink3, Pub.Ink3))
            },
        ) {
            if (isValidContentId(contentId) && creatorIdentity is UiState.Success) onRevoke()
        }
    }
    Text(
        "撤销不可恢复。完成后该记录及其来源凭证必须显示 revoked=true，后续核验 claim_valid=false。",
        color = Pub.Hi,
        fontSize = 11.5.sp,
        lineHeight = 17.sp,
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
    )
    when (state) {
        UiState.Loading -> LoadingCard("正在获取一次性撤销意图并用设备创作者密钥签名…")
        is UiState.Error -> ResultError(state.message)
        is UiState.Success -> PresentationCard(state.data.toPresentation())
        UiState.Idle -> Unit
    }
}

@Composable
private fun VerifyPane(
    imageUri: Uri?,
    credentialUri: Uri?,
    contentId: String,
    onContentIdChange: (String) -> Unit,
    state: UiState<com.vpsg.jianyuanshield.data.remote.dto.VerifyResult>,
    onPick: () -> Unit,
    onPickCredential: () -> Unit,
    onVerify: () -> Unit,
) {
    SectionHeader("指定预登记记录")
    PubCard(Modifier.padding(horizontal = 16.dp), contentPadding = PaddingValues(16.dp)) {
        SecondaryButton(
            if (imageUri == null) "选择待核验图片" else "已选择图片 · 重新选择",
            Modifier.fillMaxWidth(),
            PubIcons.gallery,
            onPick,
        )
        SecondaryButton(
            if (credentialUri == null) "可选：导入签名来源凭证" else "已导入来源凭证 · 重新选择",
            Modifier.fillMaxWidth().padding(top = 10.dp),
            PubIcons.doc,
            onPickCredential,
        )
        OutlinedTextField(
            value = contentId,
            onValueChange = onContentIdChange,
            label = { Text("content_id") },
            supportingText = { Text("未导入来源凭证时必填；导入后由签名 sidecar 定位记录。") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
            textStyle = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace),
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            colors = provenanceFieldColors(),
        )
        PrimaryCta(
            ProvenanceCopy.VERIFY_ACTION,
            Modifier.padding(top = 14.dp),
            PubIcons.verified,
            brush = if (imageUri != null && (credentialUri != null || isValidContentId(contentId))) {
                Pub.ctaBrush()
            } else {
                Brush.linearGradient(listOf(Pub.Ink3, Pub.Ink3))
            },
        ) {
            if (imageUri != null && (credentialUri != null || isValidContentId(contentId))) onVerify()
        }
    }
    Text(
        "核验只回答“图片中的恢复消息是否匹配指定登记记录”。它不判断任意图片真假，也不证明图片未经编辑。",
        color = Pub.Ink3,
        fontSize = 11.5.sp,
        lineHeight = 17.sp,
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
    )
    when (state) {
        UiState.Loading -> LoadingCard("正在执行 decode-only 登记核验…")
        is UiState.Error -> ResultError(state.message)
        is UiState.Success -> PresentationCard(state.data.toPresentation())
        UiState.Idle -> Unit
    }
}

@Composable
private fun ModeButton(text: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    SecondaryButton(
        text = text,
        modifier = modifier.background(if (selected) Pub.Blue.copy(alpha = 0.08f) else Color.Transparent),
        icon = if (selected) PubIcons.checkCircle else null,
        onClick = onClick,
    )
}

@Composable
private fun PresentationCard(presentation: ProvenancePresentation) {
    val color = if (presentation.publishable) Pub.Ok else Pub.Warn
    val background = if (presentation.publishable) Pub.OkB else Pub.WarnB
    PubCard(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), contentPadding = PaddingValues(16.dp)) {
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(13.dp)).background(background).padding(13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(if (presentation.publishable) PubIcons.verified else PubIcons.warning, null, tint = color, modifier = Modifier.size(22.dp))
            Column(Modifier.weight(1f)) {
                Text(presentation.headline, color = color, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                Text(presentation.detail, color = Pub.Ink2, fontSize = 11.5.sp, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
        Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            presentation.rows.forEach { (key, value) ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(key, color = Pub.Ink3, fontSize = 11.5.sp, modifier = Modifier.weight(0.48f))
                    SelectionContainer(Modifier.weight(0.52f)) {
                        Text(
                            value,
                            color = Pub.Ink,
                            fontSize = 11.5.sp,
                            fontFamily = if (key.contains("id") || key.contains("checkpoint") || key.contains("指纹")) FontFamily.Monospace else FontFamily.Default,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LoadingCard(text: String) {
    PubCard(Modifier.padding(16.dp), contentPadding = PaddingValues(16.dp)) {
        LinearProgressIndicator(Modifier.fillMaxWidth())
        Text(text, color = Pub.Ink2, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
    }
}

@Composable
private fun ResultError(message: String) {
    PubCard(Modifier.padding(16.dp), contentPadding = PaddingValues(16.dp)) { BoundaryError(message) }
}

@Composable
private fun BoundaryError(message: String) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Pub.HiB)
            .border(1.dp, Pub.Hi.copy(alpha = 0.25f), RoundedCornerShape(12.dp)).padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(PubIcons.warning, null, tint = Pub.Hi, modifier = Modifier.size(19.dp))
        Text(message, color = Pub.Hi, fontSize = 12.sp, lineHeight = 17.sp, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun provenanceFieldColors() = TextFieldDefaults.colors(
    focusedContainerColor = Color.White,
    unfocusedContainerColor = Color.White,
    focusedIndicatorColor = Pub.Blue,
    unfocusedIndicatorColor = Pub.Hair,
    cursorColor = Pub.Blue,
    focusedTextColor = Pub.Ink,
    unfocusedTextColor = Pub.Ink,
)
