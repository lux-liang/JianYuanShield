package com.vpsg.jianyuanshield.ui.screens.evidence

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.ui.components.ErrorState
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.KeyValueRow
import com.vpsg.jianyuanshield.ui.components.LoadingState
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone

/**
 * Evaluation protocol & benchmark completeness — split out of the evidence-chain
 * screen so each view serves a single purpose (forensic integrity vs. eval report).
 */
@Composable
fun EvalReportScreen(
    onBack: () -> Unit,
    viewModel: EvidenceViewModel = viewModel(factory = EvidenceViewModel.Factory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        GradientTopBar(
            title = "评测协议与完整性",
            subtitle = "数据集 · 篡改场景集合 · 基准完整性",
            onBack = onBack,
        )

        Column(
            modifier = Modifier
                .padding(16.dp)
                .animateContentSize(),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            when (val s = state) {
                is UiState.Loading -> SectionCard { LoadingState("正在加载评测报告…") }
                is UiState.Error -> SectionCard { ErrorState(s.message, onRetry = viewModel::load) }
                is UiState.Success -> ReportContent(s.data)
                is UiState.Idle -> SectionCard { LoadingState("正在加载评测报告…") }
            }
        }
    }
}

@Composable
private fun ReportContent(audit: EvidenceAudit) {
    if (audit.benchmarkComplete.isNotEmpty()) {
        SectionCard {
            SectionHeader("评测完整性", subtitle = "各模型基准是否齐备")
            Spacer(Modifier.height(8.dp))
            audit.benchmarkComplete.forEach { (key, complete) ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 6.dp),
                ) {
                    Text(
                        benchmarkLabel(key),
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                    StatusPill(
                        if (complete) "完整" else "缺失",
                        if (complete) StatusTone.Success else StatusTone.Danger,
                    )
                }
            }
        }
    }

    SectionCard {
        SectionHeader("评测协议")
        Spacer(Modifier.height(8.dp))
        audit.protocol.dataset?.let { KeyValueRow("数据集", it) }
        if (audit.protocol.attacks.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text("篡改场景集合", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(6.dp))
            AttackChips(audit.protocol.attacks)
        }
        if (audit.protocol.knownLimitations.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Text("已知局限", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            audit.protocol.knownLimitations.forEach { limit ->
                Row(Modifier.padding(vertical = 3.dp)) {
                    Text("•  ", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        limit,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AttackChips(attacks: List<String>) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        attacks.forEach { StatusPill(it, StatusTone.Neutral) }
    }
}

private fun benchmarkLabel(key: String): String = when (key) {
    "hidden" -> "HiDDeN / MEA"
    "sepmark" -> "SepMark"
    "waveguard_full" -> "WaveGuard"
    "lidmark" -> "LIDMark"
    else -> key
}
