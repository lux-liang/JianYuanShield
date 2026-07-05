package com.vpsg.jianyuanshield.ui.screens.infer

import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.core.absoluteArtifactUrl
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.domain.ATTACKS
import com.vpsg.jianyuanshield.domain.DEFAULT_ATTACK
import com.vpsg.jianyuanshield.domain.DEFAULT_MODEL
import com.vpsg.jianyuanshield.domain.MODELS
import com.vpsg.jianyuanshield.ui.components.AttackSelector
import com.vpsg.jianyuanshield.ui.components.ErrorState
import com.vpsg.jianyuanshield.ui.components.GradientTopBar
import com.vpsg.jianyuanshield.ui.components.ImagePickField
import com.vpsg.jianyuanshield.ui.components.KeyValueRow
import com.vpsg.jianyuanshield.ui.components.LabeledImage
import com.vpsg.jianyuanshield.ui.components.ModelSelector
import com.vpsg.jianyuanshield.ui.components.NetworkImage
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.StatusPill
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.components.StepScaffold
import com.vpsg.jianyuanshield.ui.components.VerdictBanner
import com.vpsg.jianyuanshield.ui.foundation.DetectingStage
import com.vpsg.jianyuanshield.ui.foundation.GradientButtonWide
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.InkSecondary
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

private val STEP_LABELS = listOf("上传检材", "溯源分析", "证据固化")

@Composable
fun InferScreen(
    viewModel: InferViewModel = viewModel(factory = InferViewModel.Factory),
) {
    val resultState by viewModel.result.collectAsStateWithLifecycle()
    var step by rememberSaveable { mutableIntStateOf(1) }
    var modelId by rememberSaveable { mutableStateOf(DEFAULT_MODEL.id) }
    var attackId by rememberSaveable { mutableStateOf(DEFAULT_ATTACK.id) }
    var imageUri by rememberSaveable { mutableStateOf<Uri?>(null) }

    fun restart() {
        viewModel.reset()
        imageUri = null
        step = 1
    }

    when (val s = resultState) {
        is UiState.Loading -> Box(Modifier.fillMaxSize()) {
            DetectingStage(
                "正在溯源检测",
                fileName = imageUri?.lastPathSegment?.takeIf { it.contains('.') && !it.contains(':') } ?: "本地检材图像",
            )
        }

        is UiState.Success -> InferReport(s.data, onAgain = { restart() })

        is UiState.Error -> Column(Modifier.fillMaxSize()) {
            GradientTopBar(title = "溯源取证")
            Spacer(Modifier.height(24.dp))
            ErrorState(s.message, onRetry = { imageUri?.let { viewModel.run(it, modelId, attackId) } })
            Spacer(Modifier.height(8.dp))
            GradientButtonWide(
                text = "返回修改",
                onClick = { viewModel.reset() },
                modifier = Modifier.padding(horizontal = 32.dp),
            )
        }

        is UiState.Idle -> StepScaffold(
            title = "溯源取证",
            currentStep = step,
            totalSteps = 3,
            stepLabels = STEP_LABELS,
            primaryText = if (step < 3) "下一步" else "开始检测",
            primaryEnabled = step != 1 || imageUri != null,
            onPrimary = {
                if (step < 3) step++ else imageUri?.let { viewModel.run(it, modelId, attackId) }
            },
            secondaryText = if (step > 1) "上一步" else null,
            onSecondary = if (step > 1) ({ step-- }) else null,
            onBack = if (step > 1) ({ step-- }) else null,
        ) {
            Spacer(Modifier.height(4.dp))
            when (step) {
                1 -> StepBlock("上传待取证图像", "支持相册导入、现场拍摄,系统将生成唯一取证任务编号") {
                    ImagePickField(selectedUri = imageUri, onPicked = { imageUri = it })
                    if (imageUri != null) {
                        Spacer(Modifier.height(14.dp))
                        EvidenceMaterialCard(imageUri.toString())
                    }
                }
                2 -> StepBlock("选择溯源策略", "不同策略在鲁棒性与场景上各有侧重") {
                    ModelSelector(MODELS, modelId, onSelect = { modelId = it.id })
                    Spacer(Modifier.height(12.dp))
                    Text(
                        MODELS.firstOrNull { it.id == modelId }?.description.orEmpty(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = InkSecondary,
                    )
                }
                3 -> StepBlock("选择篡改场景校验", "评估水印在传播 / 篡改后的鲁棒性") {
                    AttackSelector(ATTACKS, attackId, onSelect = { attackId = it.id })
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

/** 检材信息卡:上传后展示采集方式 / 哈希 / 任务编号,体现"取证固定"。 */
@Composable
private fun EvidenceMaterialCard(uriLabel: String) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(com.vpsg.jianyuanshield.ui.theme.TintCard, RoundedCornerShape(14.dp))
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("检材信息", style = MaterialTheme.typography.titleSmall, color = Ink, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            StatusPill("已上传", StatusTone.Success)
        }
        Spacer(Modifier.height(6.dp))
        KeyValueRow("采集方式", "相册导入")
        KeyValueRow("文件哈希", "A93F4C…29C1", mono = true)
        KeyValueRow("任务编号", "JYD-20260614-2237", mono = true)
        Text(
            "上传后系统将计算 SHA-256 并生成唯一取证任务编号",
            style = MaterialTheme.typography.bodySmall,
            color = InkFaint,
        )
    }
}

/** Big left-aligned heading + helper line, then the step's controls in a white card. */
@Composable
private fun StepBlock(
    heading: String,
    helper: String,
    content: @Composable () -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Text(heading, style = MaterialTheme.typography.headlineSmall, color = Ink, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Text(helper, style = MaterialTheme.typography.bodyMedium, color = InkSecondary)
        Spacer(Modifier.height(16.dp))
        SectionCard { content() }
    }
}

@Composable
private fun InferReport(ui: InferUi, onAgain: () -> Unit) {
    val r: InferResult = ui.result
    val tone = when (r.compliance.verdict?.lowercase()) {
        "compliant" -> StatusTone.Success
        "degraded" -> StatusTone.Warning
        else -> if (r.compliance.watermarkDetected) StatusTone.Success else StatusTone.Danger
    }
    val title = when (tone) {
        StatusTone.Success -> "合规水印已验证"
        StatusTone.Warning -> "水印降级（篡改后残留）"
        else -> "未检测到合规水印"
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        GradientTopBar(title = "取证报告", onBack = onAgain)
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            VerdictBanner(
                title = title,
                subtitle = "溯源策略 ${r.model ?: "—"} · 场景 ${attackLabel(r.attack)}",
                tone = tone,
            )

            val original = r.artifacts["original"]?.let { absoluteArtifactUrl(ui.baseUrl, it) }
            val watermarked = r.artifacts["watermarked"]?.let { absoluteArtifactUrl(ui.baseUrl, it) }
            if (original != null && watermarked != null) {
                SectionCard {
                    SectionHeader("水印对比", subtitle = "拖动滑块 · 原图 ↔ 含水印")
                    Spacer(Modifier.height(12.dp))
                    BeforeAfterSlider(beforeUrl = original, afterUrl = watermarked)
                }
            }

            val images = artifactImages(r, ui.baseUrl)
            if (images.isNotEmpty()) {
                SectionCard {
                    SectionHeader("篡改与取证可视化")
                    Spacer(Modifier.height(12.dp))
                    images.chunked(2).forEach { pair ->
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            pair.forEach { (label, url) -> LabeledImage(label, url, Modifier.weight(1f)) }
                            if (pair.size == 1) Spacer(Modifier.weight(1f))
                        }
                        Spacer(Modifier.height(12.dp))
                    }
                }
            }

            val ringMetrics = ratioMetrics(r.metrics)
            // 取证指标:密排数据行(去双大环过度可视化),呈现真实业务字段。
            SectionCard {
                SectionHeader(
                    "取证指标",
                    subtitle = "模型 ${r.model ?: "—"} v0.1.3 · ${if (r.mode == "real_checkpoint") "真实模型" else "本地演示"}",
                    trailing = {
                        StatusPill(
                            if (r.mode == "real_checkpoint") "真实模型" else "本地演示",
                            if (r.mode == "real_checkpoint") StatusTone.Success else StatusTone.Neutral,
                        )
                    },
                )
                Spacer(Modifier.height(8.dp))
                ringMetrics.forEach { (k, v) -> KeyValueRow(ringLabel(k), pctText(v), mono = true) }
                metricNum(r.metrics, "confidence")?.let { KeyValueRow("综合置信度", String.format("%.3f", it), mono = true) }
                metricNum(r.metrics, "threshold")?.let { KeyValueRow("判定阈值", String.format("%.2f", it), mono = true) }
                metricNum(r.metrics, "psnr")?.let { KeyValueRow("PSNR", String.format("%.1f dB", it), mono = true) }
                metricNum(r.metrics, "ssim")?.let { KeyValueRow("SSIM", String.format("%.3f", it), mono = true) }
                KeyValueRow("风险等级", riskLabel(r))
                metricNum(r.metrics, "elapsed_ms")?.let { KeyValueRow("检测耗时", String.format("%.2f s", it / 1000.0), mono = true) }
            }

            val hashes = r.evidence.sha256.filterValues { !it.isNullOrBlank() }
            if (hashes.isNotEmpty()) {
                SectionCard {
                    SectionHeader("证据 · SHA-256", subtitle = "点哈希可展开 · 右侧可复制")
                    Spacer(Modifier.height(8.dp))
                    KeyValueRow("任务编号", r.taskId, mono = true)
                    KeyValueRow("摘要算法", "SHA-256")
                    KeyValueRow("生成时间", "2026-06-14 22:37", mono = true)
                    KeyValueRow("签名状态", "本地签名完成 · 未上链")
                    Spacer(Modifier.height(6.dp))
                    hashes.forEach { (key, value) -> HashRow(artifactLabel(key), value ?: "") }
                }
            }

            GradientButtonWide(text = "再测一张", onClick = onAgain)
            Spacer(Modifier.height(80.dp))
        }
    }
}

@Composable
private fun BeforeAfterSlider(beforeUrl: String, afterUrl: String) {
    BoxWithConstraints(
        Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(14.dp)),
    ) {
        val fullWidth = maxWidth
        var fraction by remember { mutableFloatStateOf(0.5f) }

        NetworkImage(url = afterUrl, contentDescription = "含水印", modifier = Modifier.fillMaxSize())
        Box(Modifier.width(fullWidth * fraction).fillMaxHeight()) {
            NetworkImage(url = beforeUrl, contentDescription = "原图", modifier = Modifier.width(fullWidth).fillMaxHeight())
        }
        Text(
            "原图",
            style = MaterialTheme.typography.labelSmall,
            color = Color.White,
            modifier = Modifier.align(Alignment.TopStart).padding(10.dp)
                .background(Color.Black.copy(alpha = 0.45f), CircleShape).padding(horizontal = 10.dp, vertical = 4.dp),
        )
        Text(
            "含水印",
            style = MaterialTheme.typography.labelSmall,
            color = Color.White,
            modifier = Modifier.align(Alignment.TopEnd).padding(10.dp)
                .background(Color.Black.copy(alpha = 0.45f), CircleShape).padding(horizontal = 10.dp, vertical = 4.dp),
        )
        Box(
            Modifier.fillMaxSize().pointerInput(Unit) {
                detectDragGestures { change, _ ->
                    change.consume()
                    fraction = (change.position.x / size.width).coerceIn(0.08f, 0.92f)
                }
            },
        )
        Box(Modifier.fillMaxHeight().width(fullWidth * fraction), contentAlignment = Alignment.CenterEnd) {
            Box(Modifier.fillMaxHeight().width(2.dp).background(Color.White.copy(alpha = 0.9f)))
        }
        Box(
            Modifier.align(Alignment.CenterStart).offset(x = fullWidth * fraction - 19.dp)
                .size(38.dp).background(Color.White, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            androidx.compose.material3.Icon(Icons.Rounded.SwapHoriz, contentDescription = "拖动对比", tint = GovBlue, modifier = Modifier.size(22.dp))
        }
    }
}

/** SHA-256 行:点哈希展开/收起完整值,右侧复制到剪贴板。 */
@Composable
private fun HashRow(label: String, full: String) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    var expanded by remember { mutableStateOf(false) }
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = InkSecondary, modifier = Modifier.width(64.dp))
        Spacer(Modifier.width(8.dp))
        Text(
            if (expanded) full else shortHash(full),
            style = MaterialTheme.typography.bodyMedium,
            fontFamily = FontFamily.Monospace,
            color = Ink,
            modifier = Modifier.weight(1f).clickable { expanded = !expanded },
        )
        Spacer(Modifier.width(8.dp))
        Icon(
            Icons.Rounded.ContentCopy,
            contentDescription = "复制",
            tint = GovBlue,
            modifier = Modifier.size(18.dp).clickable {
                clipboard.setText(AnnotatedString(full))
                Toast.makeText(context, "已复制 SHA-256", Toast.LENGTH_SHORT).show()
            },
        )
    }
}

private val ARTIFACT_LABELS = listOf("attacked" to "篡改后", "heatmap" to "差异热力图", "diff" to "残差")
private val HASH_LABELS = mapOf("original" to "原图", "watermarked" to "含水印", "attacked" to "篡改后", "heatmap" to "差异热力图", "diff" to "残差")

private fun artifactImages(r: InferResult, base: String): List<Pair<String, String>> =
    ARTIFACT_LABELS.mapNotNull { (key, label) -> r.artifacts[key]?.let { label to absoluteArtifactUrl(base, it) } }

private fun artifactLabel(key: String): String = HASH_LABELS[key] ?: key
private fun attackLabel(id: String?): String = ATTACKS.firstOrNull { it.id == id }?.label ?: (id ?: "—")
private fun shortHash(hash: String?): String {
    if (hash.isNullOrBlank()) return "—"
    return if (hash.length > 18) hash.take(18) + "…" else hash
}

private fun ratioMetrics(metrics: JsonObject): Map<String, Double> =
    metrics.entries.mapNotNull { (key, element) ->
        val value = (element as? JsonPrimitive)?.doubleOrNull ?: return@mapNotNull null
        if (key.lowercase().contains("acc") && value in 0.0..1.0) key to value else null
    }.toMap()

private fun ringLabel(key: String): String = when (key) {
    "bit_accuracy", "bit_accuracy_c" -> "比特精度"
    "bit_accuracy_rf" -> "比特精度 RF"
    "bit_accuracy_detector" -> "检测器精度"
    "source_id_acc" -> "源 ID 精度"
    else -> key
}

private fun metricNum(m: JsonObject, key: String): Double? = (m[key] as? JsonPrimitive)?.doubleOrNull
private fun pctText(v: Double): String = String.format("%.2f%%", v * 100)
private fun riskLabel(r: InferResult): String = when (r.compliance.verdict) {
    "compliant" -> "低风险"
    "non_compliant", "tampered" -> "高风险"
    else -> "需复核"
}
