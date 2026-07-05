package com.vpsg.jianyuanshield.data

import com.vpsg.jianyuanshield.data.remote.dto.AttackResult
import com.vpsg.jianyuanshield.data.remote.dto.Compliance
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceItem
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.Evidence
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.Finding
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelState
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.NormalizedBenchmark
import com.vpsg.jianyuanshield.data.remote.dto.Protocol
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

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

    val modelsStatus: Map<String, ModelState> = mapOf(
        "LIDMark" to ModelState(available = true, loaded = true),
        "KAD-Net" to ModelState(available = true, loaded = true),
        "WaveGuard" to ModelState(available = true, loaded = true),
        "SepMark" to ModelState(available = true, loaded = true),
    )

    val modules: List<ModuleInfo> = listOf(
        ModuleInfo("主动取证水印", "为原创图像嵌入 152bit 身份水印", "ready", true),
        ModuleInfo("攻击仿真链路", "JPEG/缩放/模糊/平台转码全链路仿真", "ready", true),
        ModuleInfo("溯源解码引擎", "Deepfake 换脸后仍可恢复来源身份", "ready", true),
        ModuleInfo("合规批量检测", "《AI 标识办法》隐式标识批量核验", "ready", true),
        ModuleInfo("证据链签名", "Ed25519 清单签名 · 司法级不可抵赖", "ready", true),
        ModuleInfo("基准评测", "LFW 全量基准 · 本地已就绪", "ready", true),
    )

    fun inferResult(localImageUri: String, model: String, attack: String) = InferResult(
        schemaVersion = "infer-single.v1",
        taskId = "JYD-20260614-2237",
        createdAt = 1_780_000_000,
        mode = "demo_simulation",
        model = model,
        attack = attack,
        metrics = buildJsonObject {
            put("bit_accuracy", 0.9847)
            put("source_id_acc", 0.9823)
            put("confidence", 0.9786)
            put("threshold", 0.82)
            put("psnr", 39.46)
            put("ssim", 0.9772)
            put("elapsed_ms", 1483)
            put("success", true)
        },
        // 演示不 echo 用户上传图:把它当"含水印/篡改/热力图"展示会显假(黑边/社媒截图、
        // 三图雷同)。演示下不提供任何 artifact → 水印对比与可视化卡自动隐藏,报告以
        // 结论+指标+哈希呈现(真实后端会回填真实对比图)。
        artifacts = emptyMap(),
        evidence = Evidence(
            sha256 = mapOf(
                "original" to "3f6a9c0d4e7b1a92c5f80d3e6a14b7c9d2e5f8a01b3c4d5e6f7089abcdef01234",
                "watermarked" to "b81e42aa17c9305e6f8d2b4a1907c3e5d6f8091a2b3c4d5e6f70819a2b3c4d5e6",
                "attacked" to "9d04c7f15e2b8a6307f1c93d4e5a6b7089c1d2e3f4a5b6c7d8e9f001122334455",
            ),
        ),
        compliance = Compliance(
            watermarkDetected = true,
            regulation = "《人工智能生成合成内容标识办法》第五条（隐式标识）",
            verdict = "compliant",
        ),
    )

    fun complianceResult(filenames: List<String>, model: String): ComplianceResult {
        val statuses = listOf(
            Triple("watermark_verified", "合规水印已验证", 0.9873),
            Triple("watermark_verified", "合规水印已验证", 0.9812),
            Triple("watermark_degraded", "水印降级（攻击后残留）", 0.8231),
            Triple("watermark_verified", "合规水印已验证", 0.9791),
            Triple("no_watermark", "未检测到合规隐式水印", 0.3124),
        )
        val results = filenames.mapIndexed { i, name ->
            val (status, label, acc) = statuses[i % statuses.size]
            ComplianceItem(
                filename = name,
                status = status,
                label = label,
                bitAccuracy = acc,
                error = null,
            )
        }
        val compliant = results.count { it.status == "watermark_verified" }
        val degraded = results.count { it.status == "watermark_degraded" }
        val noWm = results.count { it.status == "no_watermark" }
        return ComplianceResult(
            schemaVersion = "compliance-batch.v1",
            generatedAt = 1_780_000_000,
            model = model,
            mode = "demo_simulation",
            total = results.size,
            compliant = compliant,
            degraded = degraded,
            noWatermark = noWm,
            complianceRate = if (results.isEmpty()) 0.0 else compliant.toDouble() / results.size,
            regulation = "《人工智能生成合成内容标识办法》",
            results = results,
        )
    }

    val evidenceAudit = EvidenceAudit(
        schemaVersion = "evidence-audit.v1",
        status = "verified",
        readyForDemo = true,
        readyForClaims = true,
        benchmarkComplete = mapOf(
            "lidmark" to true,
            "hidden" to true,
            "sepmark" to true,
            "waveguard_full" to true,
        ),
        protocol = Protocol(
            dataset = "LFW 13,233 张",
            attacks = listOf(
                "clean", "jpeg_50", "jpeg_70", "jpeg_90", "webp_80",
                "resize", "crop", "rotate_5", "blur", "noise",
            ),
            knownLimitations = listOf(
                "演示模式：本页数据为本地模拟，仅用于界面预览，不构成评测证据。",
            ),
        ),
        findings = listOf(
            Finding(severity = "info", code = "本地演示环境", message = "当前为本地演示环境，检测结果仅用于流程预览。"),
        ),
        signature = Signature(
            verified = true,
            status = "verified",
            signatureValid = true,
            fileCount = 42,
        ),
    )

    val benchmarks: List<SingleBenchmark> = listOf(
        demoBenchmark("LIDMark", listOf(0.9986, 0.9963, 0.9911, 0.9874)),
        demoBenchmark("KAD-Net", listOf(0.9991, 0.9624, 0.9783, 0.9512)),
        demoBenchmark("WaveGuard", listOf(0.9990, 0.9421, 0.9755, 0.9618)),
        demoBenchmark("SepMark", listOf(0.9978, 0.9716, 0.9837, 0.9695)),
    )

    private fun demoBenchmark(method: String, acc: List<Double>) = SingleBenchmark(
        method = method,
        mode = "demo_simulation",
        dataType = "real_lfw_images",
        normalized = NormalizedBenchmark(
            schemaVersion = "benchmark.v1",
            method = method,
            mode = "demo_simulation",
            status = "complete",
            numImages = 512.0,
            dataType = "real_lfw_images",
            attacks = listOf("clean", "jpeg_50", "resize", "blur").mapIndexed { i, attack ->
                AttackResult(
                    attack = attack,
                    status = "complete",
                    count = 512.0,
                    metrics = buildJsonObject { put("bit_accuracy", acc[i]) },
                )
            },
        ),
    )
}
