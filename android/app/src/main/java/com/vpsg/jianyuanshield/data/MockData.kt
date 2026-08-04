package com.vpsg.jianyuanshield.data

import com.vpsg.jianyuanshield.data.remote.dto.Compliance
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceItem
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.Evidence
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.Finding
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelState
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.Protocol
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import kotlinx.serialization.json.buildJsonObject

/**
 * Local demo dataset: lets every screen render fully without a reachable
 * backend (UI preview / 演示模式). All payloads are tagged demo_simulation so
 * the UI keeps showing the「演示」pill — never passed off as real evidence.
 */
object MockData {

    val health = HealthResponse(
        ok = true,
        mode = "demo_simulation",
        version = "1.0.0",
        uptimeSeconds = 3600.0,
    )

    val modelsStatus = ModelsStatusResponse(
        schemaVersion = "model-provenance-status.v1",
        preferredModel = null,
        lidMark = ModelState(available = false, loaded = false),
        kadNet = ModelState(available = false, loaded = false),
        waveGuard = ModelState(available = false, loaded = false),
        sepMark = ModelState(available = false, loaded = false),
    )

    val modules: List<ModuleInfo> = listOf(
        ModuleInfo("主动取证水印", "仅预览保护流程，不执行 checkpoint", "demo_simulation", false),
        ModuleInfo("攻击仿真链路", "仅预览交互流程", "demo_simulation", false),
        ModuleInfo("溯源解码引擎", "本地演示不执行盲解码", "unavailable", false),
        ModuleInfo("合规批量检测", "盲检能力不可用，不生成合规率", "unavailable", false),
        ModuleInfo("完整性签名", "本地演示不生成签名", "not_signed", false),
        ModuleInfo("基准评测", "无本地证据 artifact", "review_required", false),
    )

    fun inferResult(localImageUri: String, model: String, attack: String) = InferResult(
        schemaVersion = "infer-single.v1",
        taskId = "DEMO-NOT-EVIDENCE",
        createdAt = null,
        mode = "demo_simulation",
        resultProvenance = "deterministic_ui_simulation",
        claimValid = false,
        model = model,
        attack = attack,
        metrics = buildJsonObject {},
        // 演示不 echo 用户上传图:把它当"含水印/篡改/热力图"展示会显假(黑边/社媒截图、
        // 三图雷同)。演示下不提供 artifact 或证据指纹；真实后端才回填可核验工件。
        artifacts = emptyMap(),
        // Mock output is deliberately not dressed up with evidence fingerprints.
        evidence = Evidence(),
        compliance = Compliance(
            watermarkDetected = null,
            regulation = "《人工智能生成合成内容标识办法》第五条（隐式标识）",
            verdict = "not_assessed",
        ),
        warnings = listOf(
            "本地模拟数据仅用于预览主动水印流程，不构成来源、合规或科研结论。",
        ),
    )

    fun complianceResult(filenames: List<String>, model: String): ComplianceResult {
        val results = filenames.map { name ->
            ComplianceItem(
                filename = name,
                status = "assessment_unavailable",
                label = "未执行：演示模式没有盲检能力",
                bitAccuracy = null,
                error = null,
            )
        }
        return ComplianceResult(
            schemaVersion = "compliance-batch.v2",
            generatedAt = null,
            model = model,
            mode = "capability_unavailable",
            claimValid = false,
            capabilityAvailable = false,
            capability = "blind_watermark_detection",
            reason = "local demo does not execute a blind detector",
            warning = "未生成合规、不合规或无水印结论。",
            total = results.size,
            assessed = 0,
            compliant = null,
            degraded = null,
            noWatermark = null,
            complianceRate = null,
            regulation = "《人工智能生成合成内容标识办法》",
            results = results,
        )
    }

    val evidenceAudit = EvidenceAudit(
        schemaVersion = "evidence-audit.v1",
        status = "review_required",
        readyForDemo = true,
        readyForClaims = false,
        benchmarkComplete = mapOf(
            "lidmark" to false,
            "hidden" to false,
            "sepmark" to false,
            "waveguard_full" to false,
        ),
        protocol = Protocol(
            dataset = null,
            attacks = emptyList(),
            knownLimitations = listOf(
                "演示模式：本页数据为本地模拟，仅用于界面预览，不构成评测证据。",
            ),
        ),
        findings = listOf(
            Finding(severity = "info", code = "本地演示环境", message = "当前为本地演示环境，检测结果仅用于流程预览。"),
        ),
        signature = Signature(
            verified = false,
            status = "simulation_not_signed",
            signatureValid = false,
            fileCount = 0,
        ),
    )

    val benchmarks: List<SingleBenchmark> = emptyList()
}
