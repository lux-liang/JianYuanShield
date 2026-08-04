package com.vpsg.jianyuanshield.ui.screens.compliance

import android.net.Uri
import androidx.compose.foundation.background
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
import com.vpsg.jianyuanshield.core.formatNullableCount
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
import com.vpsg.jianyuanshield.ui.foundation.GradientButtonWide
import com.vpsg.jianyuanshield.ui.foundation.ThinProgress
import com.vpsg.jianyuanshield.ui.foundation.rememberCountUp
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkSecondary
import com.vpsg.jianyuanshield.ui.theme.NeonAmber
import com.vpsg.jianyuanshield.ui.theme.TintCard
import com.vpsg.jianyuanshield.ui.theme.NeonCoral
import com.vpsg.jianyuanshield.ui.theme.NeonMint

private val STEP_LABELS = listOf("请求样本", "能力检查")

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
                "正在检查盲检能力",
                total = uris.size.coerceAtLeast(1),
                steps = listOf("读取请求样本", "校验接口约束", "检查盲检适配器", "返回能力状态"),
            )
        }

        is UiState.Success -> ComplianceReport(s.data, onAgain = { restart() })

        is UiState.Error -> Column(Modifier.fillMaxSize()) {
            GradientTopBar(title = "盲检能力检查")
            Spacer(Modifier.height(24.dp))
            ErrorState(s.message, onRetry = { viewModel.run(uris, modelId) })
            Spacer(Modifier.height(8.dp))
            GradientButtonWide(text = "返回修改", onClick = { viewModel.reset() }, modifier = Modifier.padding(horizontal = 32.dp))
        }

        is UiState.Idle -> StepScaffold(
            title = "盲检能力检查",
            currentStep = step,
            totalSteps = 2,
            stepLabels = STEP_LABELS,
            primaryText = if (step < 2) "下一步" else "检查能力状态",
            primaryEnabled = step != 1 || uris.isNotEmpty(),
            onPrimary = { if (step < 2) step++ else viewModel.run(uris, modelId) },
            secondaryText = if (step > 1) "上一步" else null,
            onSecondary = if (step > 1) ({ step-- }) else null,
            onBack = if (step > 1) ({ step-- }) else null,
        ) {
            Spacer(Modifier.height(4.dp))
            when (step) {
                1 -> StepBlock("添加请求样本", "当前接口不会判定图片合规性；所选图片仅用于验证批量请求契约") {
                    MultiImagePickField(selected = uris, onPicked = { uris = it })
                    Spacer(Modifier.height(16.dp))
                    StandardCard()
                }
                2 -> StepBlock("选择请求模型", "模型标识会随请求发送；当前无模型提供既有图片盲检适配器") {
                    ModelSelector(MODELS, modelId, onSelect = { modelId = it.id })
                    Spacer(Modifier.height(16.dp))
                    CapabilityNoticeCard()
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

/** 展示当前后端能力边界，不把未实现项标成已启用。 */
@Composable
private fun StandardCard() {
    Column(
        Modifier.fillMaxWidth().background(TintCard, androidx.compose.foundation.shape.RoundedCornerShape(14.dp)).padding(14.dp),
    ) {
        Text("当前后端契约", style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        StandardRow("能力状态返回", available = true)
        StandardRow("既有图片盲水印检测", available = false)
        StandardRow("合规率统计", available = false)
        StandardRow("逐文件合规结论", available = false)
    }
}

@Composable
private fun StandardRow(name: String, available: Boolean) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(name, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, modifier = Modifier.weight(1f))
        StatusPill(if (available) "可返回" else "当前不可用", if (available) StatusTone.Success else StatusTone.Neutral)
    }
}

/** compliance-batch.v2 没有快速/完整模式参数，只展示真实能力状态。 */
@Composable
private fun CapabilityNoticeCard() {
    Column(
        Modifier.fillMaxWidth().background(TintCard, androidx.compose.foundation.shape.RoundedCornerShape(14.dp)).padding(14.dp),
    ) {
        Text("能力边界", style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            "compliance-batch.v2 当前返回 capability_unavailable，assessed=0，所有统计与判定字段均为 null。不得将返回结果解释为合规、不合规或无水印。",
            style = MaterialTheme.typography.bodyMedium,
            color = InkSecondary,
        )
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
    val assessmentAvailable = result.capabilityAvailable && result.claimValid && result.complianceRate != null
    val rate = result.complianceRate?.toFloat() ?: 0f
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
        GradientTopBar(title = "盲检能力状态", onBack = onAgain)
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SectionCard {
                if (!assessmentAvailable) {
                    SectionHeader("未执行合规判定", subtitle = "当前盲检能力不可用 · claim_valid=false")
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "当前模型仅支持嵌入后解码评估，未提供对既有图片的盲水印检测；本次未生成合规、不合规或无水印结论。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = NeonAmber,
                    )
                } else {
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
            }

            SectionCard {
                SectionHeader("能力状态")
                Spacer(Modifier.height(8.dp))
                KeyValueRow("运行模式", result.mode ?: "unknown", mono = true)
                KeyValueRow("能力", result.capability ?: "blind_watermark_detection", mono = true)
                KeyValueRow("已判定文件", result.assessed.toString())
                KeyValueRow("声明门禁", if (result.claimValid) "claim_valid=true" else "claim_valid=false")
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
                                    val bitAccuracy = item.bitAccuracy
                                    val sub = buildString {
                                        append(item.label ?: "")
                                        if (bitAccuracy != null) {
                                            if (isNotEmpty()) append(" · ")
                                            append("精度 ${formatPercent(bitAccuracy)}")
                                        }
                                    }
                                    if (sub.isNotBlank()) {
                                        Text(sub, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    }
                                }
                                Spacer(Modifier.width(8.dp))
                                StatusPill(statusWord(item.status), resultTone(item.status))
                            }
                            val bitAccuracy = item.bitAccuracy
                            if (bitAccuracy != null) {
                                Spacer(Modifier.height(8.dp))
                                ThinProgress(
                                    value = bitAccuracy.toFloat(),
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

            GradientButtonWide(text = "再次检查", onClick = onAgain)
            Spacer(Modifier.height(80.dp))
        }
    }
}

@Composable
private fun StatLine(color: Color, label: String, count: Int?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(color, CircleShape))
        Spacer(Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, modifier = Modifier.weight(1f))
        Text(formatNullableCount(count), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Ink)
    }
}

private fun statusWord(status: String): String = when (status) {
    "watermark_verified" -> "合规"
    "watermark_degraded" -> "降级"
    "no_watermark" -> "无水印"
    "assessment_unavailable" -> "未执行"
    "error" -> "错误"
    else -> status
}
