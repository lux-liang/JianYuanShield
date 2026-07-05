package com.vpsg.jianyuanshield.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// ── Unified error envelope (docs/API_CONTRACT.md) ─────────────────────────────

@Serializable
data class ApiErrorEnvelope(
    val ok: Boolean = false,
    val error: ApiError? = null,
)

@Serializable
data class ApiError(
    val code: String? = null,
    val message: String? = null,
    val path: String? = null,
)

// ── GET /api/health ───────────────────────────────────────────────────────────

@Serializable
data class HealthResponse(
    val ok: Boolean = false,
    val mode: String? = null,
    val version: String? = null,
    @SerialName("uptime_seconds") val uptimeSeconds: Double? = null,
)

// ── GET /api/models/status → Map<modelName, ModelState> ───────────────────────

@Serializable
data class ModelState(
    val available: Boolean = false,
    val loaded: Boolean = false,
)

// ── GET /api/modules → List<ModuleInfo> ───────────────────────────────────────

@Serializable
data class ModuleInfo(
    val name: String? = null,
    val function: String? = null,
    @SerialName("model_status") val modelStatus: String? = null,
    @SerialName("defense_ready") val defenseReady: Boolean = false,
)

// ── POST /api/infer/single → infer-single.v1 ──────────────────────────────────

@Serializable
data class InferResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("task_id") val taskId: String = "",
    @SerialName("created_at") val createdAt: Long? = null,
    val mode: String? = null,
    val model: String? = null,
    val attack: String? = null,
    val metrics: JsonObject = JsonObject(emptyMap()),
    /** Relative URLs such as /artifacts/{task}/original.png */
    val artifacts: Map<String, String> = emptyMap(),
    @SerialName("artifacts_b64") val artifactsB64: Map<String, String> = emptyMap(),
    val evidence: Evidence = Evidence(),
    val compliance: Compliance = Compliance(),
)

@Serializable
data class Evidence(
    val sha256: Map<String, String?> = emptyMap(),
)

@Serializable
data class Compliance(
    @SerialName("watermark_detected") val watermarkDetected: Boolean = false,
    val regulation: String? = null,
    val verdict: String? = null,
)

// ── POST /api/compliance/batch → compliance-batch.v1 ──────────────────────────

@Serializable
data class ComplianceResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("generated_at") val generatedAt: Long? = null,
    val model: String? = null,
    val mode: String? = null,
    val total: Int = 0,
    val compliant: Int = 0,
    val degraded: Int = 0,
    @SerialName("no_watermark") val noWatermark: Int = 0,
    @SerialName("compliance_rate") val complianceRate: Double = 0.0,
    val regulation: String? = null,
    val results: List<ComplianceItem> = emptyList(),
)

@Serializable
data class ComplianceItem(
    val filename: String? = null,
    val status: String = "",
    val label: String? = null,
    @SerialName("bit_accuracy") val bitAccuracy: Double? = null,
    val error: String? = null,
)

// ── GET /api/evidence/audit → evidence-audit.v1 ───────────────────────────────

@Serializable
data class EvidenceAudit(
    @SerialName("schema_version") val schemaVersion: String? = null,
    val status: String? = null,
    @SerialName("ready_for_demo") val readyForDemo: Boolean = false,
    @SerialName("ready_for_claims") val readyForClaims: Boolean = false,
    @SerialName("benchmark_complete") val benchmarkComplete: Map<String, Boolean> = emptyMap(),
    val protocol: Protocol = Protocol(),
    val findings: List<Finding> = emptyList(),
    @SerialName("blocking_findings") val blockingFindings: List<Finding> = emptyList(),
    val signature: Signature = Signature(),
)

@Serializable
data class Protocol(
    val dataset: String? = null,
    val attacks: List<String> = emptyList(),
    @SerialName("known_limitations") val knownLimitations: List<String> = emptyList(),
)

@Serializable
data class Finding(
    val severity: String? = null,
    val code: String? = null,
    val message: String? = null,
)

@Serializable
data class Signature(
    val verified: Boolean? = null,
    val status: String? = null,
    // Backend (signing.verify_evidence_bundle) emits these exact keys; the old
    // files_covered/algorithm fields never existed and rendered as blank rows.
    @SerialName("signature_valid") val signatureValid: Boolean? = null,
    @SerialName("file_count") val fileCount: Int? = null,
)

// ── GET /api/benchmark/{model} → single benchmark (with normalized schema) ─────

@Serializable
data class SingleBenchmark(
    val method: String? = null,
    val mode: String? = null,
    @SerialName("checkpoint_type") val checkpointType: String? = null,
    @SerialName("data_type") val dataType: String? = null,
    val normalized: NormalizedBenchmark? = null,
    @SerialName("full_benchmark") val fullBenchmark: SingleBenchmark? = null,
    @SerialName("small_benchmark") val smallBenchmark: SingleBenchmark? = null,
) {
    /** Resolve the best available normalized payload (handles WaveGuard nesting). */
    fun resolved(): NormalizedBenchmark? =
        normalized ?: fullBenchmark?.resolved() ?: smallBenchmark?.resolved()
}

@Serializable
data class NormalizedBenchmark(
    @SerialName("schema_version") val schemaVersion: String? = null,
    val method: String? = null,
    val mode: String? = null,
    val status: String? = null,
    // Backend normalization runs these counts through numeric() → float(), so they
    // arrive as JSON floats (e.g. 13233.0). Declaring them Double? avoids a
    // JsonDecodingException that would otherwise drop the whole benchmark payload.
    @SerialName("num_images") val numImages: Double? = null,
    @SerialName("data_type") val dataType: String? = null,
    val attacks: List<AttackResult> = emptyList(),
)

@Serializable
data class AttackResult(
    val attack: String = "",
    val status: String? = null,
    val count: Double? = null,
    val metrics: JsonObject = JsonObject(emptyMap()),
)
