package com.vpsg.jianyuanshield.ui.screens.evidence

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Assessment
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.Finding
import com.vpsg.jianyuanshield.ui.components.ErrorState
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.KeyValueRow
import com.vpsg.jianyuanshield.ui.components.LoadingState
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.EvidenceTimeline
import com.vpsg.jianyuanshield.ui.components.SecondaryButton
import com.vpsg.jianyuanshield.ui.foundation.GradientButtonWide
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.components.VerdictBanner
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.components.resultTone
import com.vpsg.jianyuanshield.ui.components.severityTone

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EvidenceScreen(
    onOpenReport: () -> Unit,
    viewModel: EvidenceViewModel = viewModel(factory = EvidenceViewModel.Factory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val refreshing by viewModel.refreshing.collectAsStateWithLifecycle()

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = viewModel::refresh,
        modifier = Modifier.fillMaxSize(),
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
        ) {
            GradientTopBar(
                title = "证据链",
                subtitle = "Ed25519 签名 · 证据完整性核验",
            )

            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .animateContentSize(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                when (val s = state) {
                    is UiState.Loading -> SectionCard { LoadingState("正在核验证据链…") }
                    is UiState.Error -> SectionCard { ErrorState(s.message, onRetry = viewModel::load) }
                    is UiState.Success -> EvidenceContent(s.data, onOpenReport)
                    is UiState.Idle -> SectionCard { LoadingState("正在核验证据链…") }
                }
                Spacer(Modifier.height(96.dp))
            }
        }
    }
}

@Composable
private fun EvidenceContent(audit: EvidenceAudit, onOpenReport: () -> Unit) {
    val signed = audit.signature.verified == true
    val clipboard = androidx.compose.ui.platform.LocalClipboardManager.current
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val evidenceNo = "JYD-20260614-2237"
    val copyNo: () -> Unit = {
        clipboard.setText(androidx.compose.ui.text.AnnotatedString(evidenceNo))
        android.widget.Toast.makeText(ctx, "已复制证据编号 $evidenceNo", android.widget.Toast.LENGTH_SHORT).show()
    }

    // 证据编号(顶部,带复制)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("证据编号", style = MaterialTheme.typography.labelMedium, color = InkFaint)
                Text(
                    evidenceNo,
                    style = MaterialTheme.typography.titleMedium,
                    color = Ink,
                    fontWeight = FontWeight.Bold,
                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                )
            }
            androidx.compose.material3.Icon(
                Icons.Rounded.ContentCopy,
                contentDescription = "复制证据编号",
                tint = GovBlue,
                modifier = Modifier
                    .clickable(onClick = copyNo)
                    .padding(4.dp),
            )
        }
    }

    // 头部裁决(一次,醒目)
    VerdictBanner(
        title = if (signed) "证据签名已验证" else "签名待核验",
        subtitle = if (signed) "Ed25519 · SHA-256 · 时间戳已固化" else (audit.signature.status ?: "未生成签名"),
        tone = if (signed) StatusTone.Success else StatusTone.Warning,
    )

    // 核验结论
    SectionCard {
        SectionHeader("核验结论", subtitle = "审计就绪状态与签名完整性")
        Spacer(Modifier.height(12.dp))
        PillRow("审计状态", audit.statusLabel(), resultTone(audit.status))
        PillRow("就绪自检", yesNo(audit.readyForDemo), boolTone(audit.readyForDemo))
        PillRow("结论就绪", yesNo(audit.readyForClaims), boolTone(audit.readyForClaims))
        audit.signature.signatureValid?.let {
            PillRow("密码学校验", if (it) "通过" else "未通过", if (it) StatusTone.Success else StatusTone.Warning)
        }
        audit.signature.fileCount?.let { KeyValueRow("覆盖文件", "$it 个") }
    }

    // 证据摘要(本地演示数据)
    SectionCard {
        SectionHeader("证据摘要")
        Spacer(Modifier.height(8.dp))
        KeyValueRow("原始文件", "IMG_20260614_2237.jpg")
        KeyValueRow("文件哈希", "a93f4c…29c1", mono = true)
        KeyValueRow("取证时间", "2026-06-14 22:37", mono = true)
        KeyValueRow("取证设备", "JYD-2026-0042", mono = true)
        KeyValueRow("溯源策略", "LIDMark-v0.1")
    }

    // 证据时间线
    SectionCard {
        SectionHeader("证据时间线")
        Spacer(Modifier.height(12.dp))
        EvidenceTimeline(
            listOf(
                "22:37" to "上传检材",
                "22:37" to "计算文件哈希",
                "22:38" to "完成水印溯源",
                "22:38" to "生成证据签名",
                "22:39" to "证据链归档",
            ),
        )
    }

    if (audit.findings.isNotEmpty()) {
        SectionCard {
            SectionHeader("审计发现", subtitle = "${audit.findings.size} 条")
            Spacer(Modifier.height(8.dp))
            audit.findings.forEach { FindingRow(it) }
        }
    }

    // 底部操作区:导出报告(主)/ 复制证据编号(副)
    GradientButtonWide(text = "导出报告", icon = Icons.Rounded.Download, onClick = onOpenReport)
    SecondaryButton(
        text = "复制证据编号",
        icon = Icons.Rounded.ContentCopy,
        onClick = copyNo,
        modifier = Modifier.fillMaxWidth(),
    )
    SecondaryButton(
        text = "查看评测协议与完整性",
        icon = Icons.Rounded.Assessment,
        onClick = onOpenReport,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun PillRow(label: String, pill: String, tone: StatusTone) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        StatusPill(pill, tone)
    }
}

@Composable
private fun FindingRow(finding: Finding) {
    Column(Modifier.padding(vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusPill(severityWord(finding.severity), severityTone(finding.severity))
            Spacer(Modifier.width(8.dp))
            Text(
                finding.code ?: "",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (!finding.message.isNullOrBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(
                finding.message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

internal fun EvidenceAudit.statusLabel(): String = when (status) {
    "verified" -> "已核验"
    "review_required" -> "待复核"
    else -> status ?: "未知"
}

internal fun yesNo(value: Boolean) = if (value) "是" else "否"
internal fun boolTone(value: Boolean) = if (value) StatusTone.Success else StatusTone.Warning

private fun severityWord(severity: String?): String = when (severity?.lowercase()) {
    "info" -> "提示"
    "warning" -> "警告"
    "error", "critical" -> "严重"
    else -> severity ?: "—"
}
