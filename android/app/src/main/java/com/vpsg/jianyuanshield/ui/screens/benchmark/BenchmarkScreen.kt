package com.vpsg.jianyuanshield.ui.screens.benchmark

import androidx.compose.animation.animateContentSize
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.core.formatPercent
import com.vpsg.jianyuanshield.core.toMetricRows
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import com.vpsg.jianyuanshield.ui.components.ErrorState
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.LoadingState
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.foundation.BarEntry
import com.vpsg.jianyuanshield.ui.foundation.GroupedBars
import com.vpsg.jianyuanshield.ui.foundation.ThinProgress
import com.vpsg.jianyuanshield.ui.foundation.entrance
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue
import com.vpsg.jianyuanshield.ui.theme.GovBlueAux
import com.vpsg.jianyuanshield.ui.theme.GovBlueDeep
import com.vpsg.jianyuanshield.ui.theme.GovBlueSoft
import com.vpsg.jianyuanshield.ui.theme.TextMid
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BenchmarkScreen(
    onBack: () -> Unit,
    viewModel: BenchmarkViewModel = viewModel(factory = BenchmarkViewModel.Factory),
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
                title = "基准评测",
                subtitle = "LFW 全量基准 · 真实 checkpoint",
                onBack = onBack,
            )

            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .animateContentSize(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                when (val s = state) {
                    is UiState.Loading, is UiState.Idle ->
                        SectionCard { LoadingState("正在加载评测数据…") }
                    is UiState.Error ->
                        SectionCard { ErrorState(s.message, onRetry = viewModel::load) }
                    is UiState.Success -> {
                        CompareCard(s.data, Modifier.entrance(0))
                        s.data.forEachIndexed { index, bench ->
                            BenchmarkCard(bench, Modifier.entrance(index + 1))
                        }
                    }
                }

                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

/** Cross-model comparison: clean-baseline accuracy bars, Screen-Time style. */
@Composable
private fun CompareCard(benches: List<SingleBenchmark>, modifier: Modifier = Modifier) {
    val entries = benches.mapNotNull { bench ->
        val nb = bench.resolved()
        val method = nb?.method ?: bench.method ?: return@mapNotNull null
        val clean = nb?.attacks?.firstOrNull { it.attack.equals("clean", ignoreCase = true) }
            ?: nb?.attacks?.firstOrNull()
            ?: return@mapNotNull null
        val ratio = accuracyRatio(clean.metrics) ?: return@mapNotNull null
        BarEntry(
            label = method,
            value = ratio.toFloat(),
            valueText = formatPercent(ratio),
            color = modelColor(method),
        )
    }
    if (entries.size < 2) return

    SectionCard(modifier) {
        SectionHeader("模型横评", subtitle = "Clean 基线 · 解码精度对比")
        Spacer(Modifier.height(16.dp))
        GroupedBars(entries)
    }
}

@Composable
private fun BenchmarkCard(bench: SingleBenchmark, modifier: Modifier = Modifier) {
    val nb = bench.resolved()
    val method = nb?.method ?: bench.method ?: "模型"
    val mode = nb?.mode ?: bench.mode
    val real = mode == "real_checkpoint"
    val accent = modelColor(method)

    SectionCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(method, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.ExtraBold)
                val sub = buildString {
                    append(nb?.dataType ?: bench.dataType ?: "—")
                    nb?.numImages?.let { append(" · ${it.toLong()} 张") }
                }
                Text(sub, style = MaterialTheme.typography.bodyMedium, color = TextMid)
            }
            Spacer(Modifier.width(8.dp))
            StatusPill(
                if (real) "真实模型" else "演示",
                if (real) StatusTone.Success else StatusTone.Neutral,
            )
        }

        val attacks = nb?.attacks.orEmpty()
        if (attacks.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            attacks.forEach { attack ->
                val headline = attack.metrics.toMetricRows().firstOrNull()
                val ratio = accuracyRatio(attack.metrics)
                Column(Modifier.padding(vertical = 9.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            attackLabel(attack.attack),
                            style = MaterialTheme.typography.bodyLarge,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            headline?.value ?: "—",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                            fontFamily = FontFamily.Monospace,
                            color = accent,
                        )
                    }
                    if (ratio != null) {
                        Spacer(Modifier.height(6.dp))
                        ThinProgress(value = ratio.toFloat(), color = accent)
                    }
                }
            }
            val headlineLabel = attacks.firstOrNull()?.metrics?.toMetricRows()?.firstOrNull()?.label
            if (headlineLabel != null) {
                Text(
                    "指标：$headlineLabel",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextMid,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        } else {
            Spacer(Modifier.height(8.dp))
            Text(
                "暂无逐场景指标",
                style = MaterialTheme.typography.bodyMedium,
                color = TextMid,
            )
        }
    }
}

/** First accuracy-like metric in 0..1, used for bars and row progress. */
private fun accuracyRatio(metrics: JsonObject): Double? =
    metrics.entries.firstNotNullOfOrNull { (key, element) ->
        val value = (element as? JsonPrimitive)?.doubleOrNull ?: return@firstNotNullOfOrNull null
        if (key.lowercase().contains("acc") && value in 0.0..1.0) value else null
    }

private fun modelColor(method: String): Color {
    val m = method.lowercase()
    return when {
        m.contains("lid") -> GovBlueDeep
        m.contains("kad") -> ElectricBlue
        m.contains("wave") -> GovBlueAux
        m.contains("sep") -> GovBlueSoft
        else -> ElectricBlue
    }
}

private fun attackLabel(raw: String): String = when (raw.lowercase()) {
    "clean" -> "无篡改 Clean"
    else -> raw.replace('_', ' ').replaceFirstChar { it.uppercase() }
}
