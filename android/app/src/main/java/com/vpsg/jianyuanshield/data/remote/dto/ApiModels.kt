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

// ── GET /api/models/status → model-provenance-status.v1 ─────────────────────

@Serializable
data class ModelState(
    val available: Boolean = false,
    val loaded: Boolean = false,
    @SerialName("checkpoint_sha256") val checkpointSha256: String? = null,
    val registered: Boolean = false,
    val calibrated: Boolean = false,
    val trusted: Boolean = false,
    @SerialName("provenance_ready") val provenanceReady: Boolean = false,
    @SerialName("verification_threshold") val verificationThreshold: Double? = null,
    @SerialName("reason_codes") val reasonCodes: List<String> = emptyList(),
)

/**
 * The response is an object with protocol metadata plus four model-named keys;
 * decoding it as `Map<String, ModelState>` loses the metadata and fails the
 * whole response. Keep the fixed API names explicit and expose one fail-closed
 * selection helper to every caller.
 */
@Serializable
data class ModelsStatusResponse(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("preferred_model") val preferredModel: String? = null,
    @SerialName("LIDMark") val lidMark: ModelState? = null,
    @SerialName("KAD-Net") val kadNet: ModelState? = null,
    @SerialName("SepMark") val sepMark: ModelState? = null,
    @SerialName("WaveGuard") val waveGuard: ModelState? = null,
) {
    val models: Map<String, ModelState>
        get() = buildMap {
            lidMark?.let { put("LIDMark", it) }
            kadNet?.let { put("KAD-Net", it) }
            sepMark?.let { put("SepMark", it) }
            waveGuard?.let { put("WaveGuard", it) }
        }

    val readyModels: Map<String, ModelState>
        get() = models.filterValues { it.provenanceReady }

    /** The backend preference is accepted only if its current gate is ready. */
    fun safePreferredModel(): String? =
        preferredModel?.takeIf { readyModels.containsKey(it) }
            ?: readyModels.keys.firstOrNull()
}

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
    @SerialName("result_provenance") val resultProvenance: String? = null,
    /**
     * Backend release gate. Missing/legacy values deliberately decode as false:
     * an unproven response must never become a publishable client-side claim.
     */
    @SerialName("claim_valid") val claimValid: Boolean = false,
    val model: String? = null,
    val attack: String? = null,
    val metrics: JsonObject = JsonObject(emptyMap()),
    /** Relative URLs such as /artifacts/{task}/original.png */
    val artifacts: Map<String, String> = emptyMap(),
    @SerialName("artifacts_b64") val artifactsB64: Map<String, String> = emptyMap(),
    val evidence: Evidence = Evidence(),
    val compliance: Compliance = Compliance(),
    val warnings: List<String> = emptyList(),
)

@Serializable
data class Evidence(
    val sha256: Map<String, String?> = emptyMap(),
)

@Serializable
data class Compliance(
    /** Simulation responses intentionally return null because no assessment ran. */
    @SerialName("watermark_detected") val watermarkDetected: Boolean? = null,
    @SerialName("assessment_status") val assessmentStatus: String? = null,
    val regulation: String? = null,
    val verdict: String? = null,
    val reason: String? = null,
)

// ── Registered provenance protect / verify lifecycle ─────────────────────────

@Serializable
data class PayloadSignature(
    val status: String? = null,
    val signed: Boolean = false,
    val algorithm: String? = null,
    @SerialName("signature_base64") val signatureBase64: String? = null,
    @SerialName("public_key_fingerprint_sha256") val publicKeyFingerprintSha256: String? = null,
)

@Serializable
data class ProtectedImage(
    val url: String? = null,
    @SerialName("png_base64") val pngBase64: String? = null,
)

@Serializable
data class ProvenancePrivacy(
    @SerialName("original_persisted") val originalPersisted: Boolean = false,
    @SerialName("creator_ref_persisted") val creatorRefPersisted: Boolean = false,
    @SerialName("creator_public_key_persisted") val creatorPublicKeyPersisted: Boolean = false,
)

@Serializable
data class CreatorChallenge(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("challenge_id") val challengeId: String = "",
    @SerialName("creator_ref") val creatorRef: String = "",
    @SerialName("creator_key_fingerprint_sha256") val creatorKeyFingerprintSha256: String? = null,
    @SerialName("owner_scope") val ownerScope: String? = null,
    val model: String = "",
    @SerialName("image_sha256") val imageSha256: String? = null,
    @SerialName("expires_at") val expiresAt: Long? = null,
    @SerialName("signing_message_base64") val signingMessageBase64: String? = null,
    @SerialName("server_signature_trusted") val serverSignatureTrusted: Boolean = false,
)

@Serializable
data class SourceCredentialRef(
    @SerialName("schema_version") val schemaVersion: String? = null,
    val url: String? = null,
    val sha256: String? = null,
    @SerialName("json_base64") val jsonBase64: String? = null,
    @SerialName("signature_trusted") val signatureTrusted: Boolean = false,
)

@Serializable
data class ProtectResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("content_id") val contentId: String = "",
    @SerialName("creator_ref") val creatorRef: String = "",
    val model: String = "",
    @SerialName("created_at") val createdAt: Long? = null,
    @SerialName("original_sha256") val originalSha256: String? = null,
    @SerialName("protected_sha256") val protectedSha256: String? = null,
    @SerialName("checkpoint_sha256") val checkpointSha256: String? = null,
    @SerialName("checkpoint_registered") val checkpointRegistered: Boolean = false,
    @SerialName("checkpoint_calibrated") val checkpointCalibrated: Boolean = false,
    @SerialName("verification_threshold") val verificationThreshold: Double? = null,
    @SerialName("evidence_signature") val evidenceSignature: PayloadSignature = PayloadSignature(),
    @SerialName("claim_valid") val claimValid: Boolean = false,
    @SerialName("evidence_status") val evidenceStatus: String? = null,
    val mode: String? = null,
    @SerialName("result_provenance") val resultProvenance: String? = null,
    @SerialName("creator_identity_verified") val creatorIdentityVerified: Boolean = false,
    @SerialName("owner_scope") val ownerScope: String? = null,
    @SerialName("creator_identity") val creatorIdentity: JsonObject = JsonObject(emptyMap()),
    @SerialName("source_credential") val sourceCredential: SourceCredentialRef = SourceCredentialRef(),
    @SerialName("protected_image") val protectedImage: ProtectedImage = ProtectedImage(),
    val privacy: ProvenancePrivacy = ProvenancePrivacy(),
)

@Serializable
data class VerifyResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("event_id") val eventId: String = "",
    @SerialName("content_id") val contentId: String = "",
    @SerialName("creator_ref") val creatorRef: String = "",
    val model: String = "",
    @SerialName("created_at") val createdAt: Long? = null,
    @SerialName("observed_sha256") val observedSha256: String? = null,
    @SerialName("exact_protected_file_match") val exactProtectedFileMatch: Boolean = false,
    @SerialName("bit_accuracy") val bitAccuracy: Double? = null,
    @SerialName("verification_threshold") val verificationThreshold: Double? = null,
    val verified: Boolean = false,
    @SerialName("checkpoint_sha256") val checkpointSha256: String? = null,
    @SerialName("runtime_checkpoint_sha256") val runtimeCheckpointSha256: String? = null,
    @SerialName("checkpoint_registered") val checkpointRegistered: Boolean = false,
    @SerialName("checkpoint_calibrated") val checkpointCalibrated: Boolean = false,
    @SerialName("parent_record_claim_valid") val parentRecordClaimValid: Boolean = false,
    @SerialName("parent_record_revoked") val parentRecordRevoked: Boolean = false,
    @SerialName("creator_key_fingerprint_sha256") val creatorKeyFingerprintSha256: String? = null,
    @SerialName("owner_scope") val ownerScope: String? = null,
    @SerialName("source_locator") val sourceLocator: String? = null,
    @SerialName("evidence_signature") val evidenceSignature: PayloadSignature = PayloadSignature(),
    @SerialName("claim_valid") val claimValid: Boolean = false,
    @SerialName("evidence_status") val evidenceStatus: String? = null,
    val mode: String? = null,
    @SerialName("result_provenance") val resultProvenance: String? = null,
)

@Serializable
data class RevocationIntent(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("intent_id") val intentId: String = "",
    @SerialName("content_id") val contentId: String = "",
    @SerialName("reason_code") val reasonCode: String = "",
    @SerialName("creator_key_fingerprint_sha256") val creatorKeyFingerprintSha256: String? = null,
    @SerialName("expires_at") val expiresAt: Long? = null,
    @SerialName("signing_message_base64") val signingMessageBase64: String? = null,
    @SerialName("server_signature_trusted") val serverSignatureTrusted: Boolean = false,
)

@Serializable
data class RevocationResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("revocation_id") val revocationId: String = "",
    @SerialName("content_id") val contentId: String = "",
    @SerialName("reason_code") val reasonCode: String = "",
    @SerialName("revoked_at") val revokedAt: Long? = null,
    @SerialName("creator_key_fingerprint_sha256") val creatorKeyFingerprintSha256: String? = null,
    @SerialName("evidence_signature") val evidenceSignature: PayloadSignature = PayloadSignature(),
    val revoked: Boolean = false,
    @SerialName("claim_valid") val claimValid: Boolean = false,
    @SerialName("source_credential_sha256") val sourceCredentialSha256: String? = null,
)

// ── POST /api/compliance/batch → compliance-batch.v2 ──────────────────────────

@Serializable
data class ComplianceResult(
    @SerialName("schema_version") val schemaVersion: String? = null,
    @SerialName("generated_at") val generatedAt: Long? = null,
    val model: String? = null,
    val mode: String? = null,
    @SerialName("claim_valid") val claimValid: Boolean = false,
    @SerialName("capability_available") val capabilityAvailable: Boolean = false,
    val capability: String? = null,
    val reason: String? = null,
    val warning: String? = null,
    val total: Int = 0,
    val assessed: Int = 0,
    val compliant: Int? = null,
    val degraded: Int? = null,
    @SerialName("no_watermark") val noWatermark: Int? = null,
    @SerialName("compliance_rate") val complianceRate: Double? = null,
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
