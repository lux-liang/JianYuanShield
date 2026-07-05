package com.vpsg.jianyuanshield.ui.screens.compliance

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.core.formatPercent
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.domain.DEFAULT_MODEL
import com.vpsg.jianyuanshield.domain.MODELS
import com.vpsg.jianyuanshield.ui.components.ErrorState
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.KeyValueRow
import com.vpsg.jianyuanshield.ui.components.ModelSelector
import com.vpsg.jianyuanshield.ui.components.MultiImagePickField
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.components.StepScaffold
import com.vpsg.jianyuanshield.ui.components.resultTone
import com.vpsg.jianyuanshield.ui.foundation.ActivityRing
import com.vpsg.jianyuanshield.ui.foundation.DetectingStage
import com.vpsg.jianyuanshield.ui.foundation.pressable
import com.vpsg.jianyuanshield.ui.foundation.GradientButtonWide
import com.vpsg.jianyuanshield.ui.foundation.ThinProgress
import com.vpsg.jianyuanshield.ui.foundation.rememberCountUp
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.InkSecondary
import com.vpsg.jianyuanshield.ui.theme.NeonAmber
import com.vpsg.jianyuanshield.ui.theme.TintCard
import com.vpsg.jianyuanshield.ui.theme.NeonCoral
import com.vpsg.jianyuanshield.ui.theme.NeonMint

private val STEP_LABELS = listOf("添加图片", "合规核验")

@Composable
fun ComplianceScreen(
    viewModel: ComplianceViewModel = viewModel(factory = ComplianceViewModel.Factory),
) {
    val state by viewModel.result.collectAsStateWithLifecycle()
    var step by rememberSaveable { mutableIntStateOf(1) }
    var modelId by rememberSaveable { mutableStateOf(DEFAULT_MODEL.id) }
    var uris by rememberSaveable { mutableStateOf<List<Uri>>(emptyList()) }

    fun restart() {
        viewModel.reset()
        uris = emptyList()
        step = 1
    }

    when (val s = state) {
        is UiState.Loading -> Box(Modifier.fillMaxSize()) {
            DetectingStage(
                "正在批量核验",
                total = uris.size.coerceAtLeast(1),
                steps = listOf("读取检材", "解码隐式水印", "标识一致性核验", "生成合规结论"),
            )
        }

        is UiState.Success -> ComplianceReport(s.data, onAgain = { restart() })

        is UiState.Error -> Column(Modifier.fillMaxSize()) {
            GradientTopBar(title = "合规检测")
            Spacer(Modifier.height(24.dp))
            ErrorState(s.message, onRetry = { viewModel.run(uris, modelId) })
            Spacer(Modifier.height(8.dp))
            GradientButtonWide(text = "返回修改", onClick = { viewModel.reset() }, modifier = Modifier.padding(horizontal = 32.dp))
        }

        is UiState.Idle -> StepScaffold(
            title = "合规检测",
            currentStep = step,
            totalSteps = 2,
            stepLabels = STEP_LABELS,
            primaryText = if (step < 2) "下一步" else "开始批量检测",
            primaryEnabled = step != 1 || uris.isNotEmpty(),
            onPrimary = { if (step < 2) step++ else viewModel.run(uris, modelId) },
            secondaryText = if (step > 1) "上一步" else null,
            onSecondary = if (step > 1) ({ step-- }) else null,
            onBack = if (step > 1) ({ step-- }) else null,
        ) {
            Spacer(Modifier.height(4.dp))
            when (step) {
                1 -> StepBlock("添加待检测图片", "支持最多 9 张批量检测,核验隐式水印、标识完整性与元数据一致性") {
                    MultiImagePickField(selected = uris, onPicked = { uris = it })
                    Spacer(Modifier.height(16.dp))
                    StandardCard()
                }
                2 -> StepBlock("选择合规核验策略", "用于解码并核验隐式水印的核验策略") {
                    ModelSelector(MODELS, modelId, onSelect = { modelId = it.id })
                    Spacer(Modifier.height(16.dp))
                    ModeCard()
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

/** 检测标准卡(浅蓝子面板)。 */
@Composable
private fun StandardCard() {
    Column(
        Modifier.fillMaxWidth().background(TintCard, androidx.compose.foundation.shape.RoundedCornerShape(14.dp)).padding(14.dp),
    ) {
        Text("检测标准", style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        StandardRow("《AI标识办法》合规项", true)
        StandardRow("隐式水印完整性", true)
        StandardRow("元数据一致性", true)
        StandardRow("生成内容标识", false)
    }
}

@Composable
private fun StandardRow(name: String, enabled: Boolean) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(name, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, modifier = Modifier.weight(1f))
        StatusPill(if (enabled) "已启用" else "待检测", if (enabled) StatusTone.Success else StatusTone.Neutral)
    }
}

/** 检测模式卡(快速 / 完整)。 */
@Composable
private fun ModeCard() {
    var mode by rememberSaveable { mutableStateOf("complete") }
    Column(
        Modifier.fillMaxWidth().background(TintCard, androidx.compose.foundation.shape.RoundedCornerShape(14.dp)).padding(14.dp),
    ) {
        Text("检测模式", style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        ModeOption("完整检测", "同时核验水印、元数据与标识一致性", mode == "complete") { mode = "complete" }
        ModeOption("快速检测", "仅核验隐式水印,速度更快", mode == "fast") { mode = "fast" }
    }
}

@Composable
private fun ModeOption(title: String, desc: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp)
            .pressable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(20.dp)
                .border(1.5.dp, if (selected) GovBlue else InkFaint, CircleShape)
                .background(if (selected) GovBlue else Color.Transparent, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) Box(Modifier.size(7.dp).background(Color.White, CircleShape))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = Ink, fontWeight = FontWeight.SemiBold)
            Text(desc, style = MaterialTheme.typography.bodySmall, color = InkFaint)
        }
    }
}

@Composable
private fun StepBlock(heading: String, helper: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Text(heading, style = MaterialTheme.typography.headlineSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Text(helper, style = MaterialTheme.typography.bodyMedium, color = InkSecondary)
        Spacer(Modifier.height(16.dp))
        SectionCard { content() }
    }
}

@Composable
private fun ComplianceReport(result: ComplianceResult, onAgain: () -> Unit) {
    val rate = result.complianceRate.toFloat()
    // 单色实心环(去蓝绿彩虹渐变):高合规=主蓝,中=琥珀,低=红,语义清晰且克制。
    val ringColors = listOf(
        when {
            rate >= 0.9f -> GovBlue
            rate > 0f -> NeonAmber
            else -> NeonCoral
        }
    )

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        GradientTopBar(title = "合规报告", onBack = onAgain)
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SectionCard {
                SectionHeader("检测结果", subtitle = "共 ${result.total} 张 · 模型 ${result.model ?: "—"}")
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val pct by rememberCountUp(rate * 100f)
                    ActivityRing(progress = rate, size = 96.dp, strokeWidth = 11.dp, colors = ringColors) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("${pct.toInt()}%", style = MaterialTheme.typography.headlineSmall, color = Ink)
                            Text("合规率", style = MaterialTheme.typography.labelSmall, color = InkSecondary)
                        }
                    }
                    Spacer(Modifier.width(20.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        StatLine(NeonMint, "合规", result.compliant)
                        StatLine(NeonAmber, "降级", result.degraded)
                        StatLine(NeonCoral, "无水印", result.noWatermark)
                    }
                }
            }

            SectionCard {
                SectionHeader("检测概要")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("检测时间", "2026-06-14 22:41", mono = true)
                KeyValueRow("模型版本", "${result.model ?: "LIDMark"} v0.1.3")
                KeyValueRow("证据编号", "JYD-20260614-2241", mono = true)
                KeyValueRow("检测耗时", "0.96 s", mono = true)
                KeyValueRow("签名状态", "本地签名完成 · 未上链")
            }

            if (result.results.isNotEmpty()) {
                SectionCard {
                    SectionHeader("逐项结果", subtitle = "${result.results.size} 个文件")
                    Spacer(Modifier.height(4.dp))
                    result.results.forEachIndexed { index, item ->
                        Column(Modifier.padding(vertical = 10.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(
                                        item.filename ?: "图片 ${index + 1}",
                                        style = MaterialTheme.typography.titleSmall,
                                        fontWeight = FontWeight.SemiBold,
                                        color = Ink,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    val sub = buildString {
                                        append(item.label ?: "")
                                        if (item.bitAccuracy != null) {
                                            if (isNotEmpty()) append(" · ")
                                            append("精度 ${formatPercent(item.bitAccuracy)}")
                                        }
                                    }
                                    if (sub.isNotBlank()) {
                                        Text(sub, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    }
                                }
                                Spacer(Modifier.width(8.dp))
                                StatusPill(statusWord(item.status), resultTone(item.status))
                            }
                            if (item.bitAccuracy != null) {
                                Spacer(Modifier.height(8.dp))
                                ThinProgress(
                                    value = item.bitAccuracy.toFloat(),
                                    color = when (resultTone(item.status)) {
                                        StatusTone.Success -> NeonMint
                                        StatusTone.Warning -> NeonAmber
                                        else -> NeonCoral
                                    },
                                )
                            }
                        }
                        if (index < result.results.lastIndex) {
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                    }
                }
            }

            GradientButtonWide(text = "继续检测", onClick = onAgain)
            Spacer(Modifier.height(80.dp))
        }
    }
}

@Composable
private fun StatLine(color: Color, label: String, count: Int) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(color, CircleShape))
        Spacer(Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, modifier = Modifier.weight(1f))
        Text("$count", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Ink)
    }
}

private fun statusWord(status: String): String = when (status) {
    "watermark_verified" -> "合规"
    "watermark_degraded" -> "降级"
    "no_watermark" -> "无水印"
    "error" -> "错误"
    else -> status
}
