package com.vpsg.jianyuanshield.ui.pub.provenance

import com.vpsg.jianyuanshield.data.remote.dto.PayloadSignature
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
import java.util.Locale

/** Copy is centralized so boundary wording can be unit-tested. */
object ProvenanceCopy {
    const val SCREEN_TITLE = "登记来源凭证"
    const val SCOPE = "仅保护新内容、核验本系统预登记来源凭证并执行持钥撤销"
    const val PROTECT_ACTION = "保护并登记"
    const val VERIFY_ACTION = "核验预登记凭证"
    const val LIMIT = "本功能不是任意图片真假、AI 生成或换脸检测器"
}

data class ProvenancePresentation(
    val publishable: Boolean,
    val headline: String,
    val detail: String,
    val rows: List<Pair<String, String>>,
)

fun ProtectResult.hasPublishableProtectionClaim(): Boolean =
    schemaVersion == "provenance-record.v2" &&
        claimValid &&
        mode == "real_checkpoint" &&
        resultProvenance == "registered_protection_record" &&
        evidenceStatus == "signed_checkpoint_bound" &&
        checkpointRegistered &&
        checkpointCalibrated &&
        creatorIdentityVerified &&
        sourceCredential.signatureTrusted &&
        evidenceSignature.isSignedEd25519()

fun VerifyResult.hasPublishableVerificationClaim(): Boolean =
    schemaVersion == "provenance-verification.v1" &&
        claimValid &&
        verified &&
        mode == "real_checkpoint" &&
        resultProvenance == "registered_blind_verification" &&
        evidenceStatus == "signed_checkpoint_bound" &&
        parentRecordClaimValid &&
        !parentRecordRevoked &&
        checkpointRegistered &&
        checkpointCalibrated &&
        checkpointSha256.isSha256() &&
        checkpointSha256 == runtimeCheckpointSha256 &&
        sourceLocator in setOf("explicit_content_id", "signed_sidecar", "trusted_gb45438_metadata") &&
        evidenceSignature.isSignedEd25519()

fun ProtectResult.toPresentation(): ProvenancePresentation {
    val formal = hasPublishableProtectionClaim()
    return ProvenancePresentation(
        publishable = formal,
        headline = if (formal) "来源保护记录已通过声明门禁" else "保护记录已生成，声明门禁未通过",
        detail = if (formal) {
            "已登记内容标识、checkpoint 与 Ed25519 事件签名；请保存受保护图片和 content_id。"
        } else {
            "操作结果仅为 operational 记录，不得作为已签名来源结论。"
        },
        rows = listOf(
            "content_id" to contentId.ifBlank { "—" },
            "应用侧主体引用" to creatorRef.ifBlank { "—" },
            "创作者持钥验证" to creatorIdentityVerified.toString(),
            "自然人实名验证" to "false（协议不声明）",
            "owner scope" to (ownerScope ?: "—"),
            "模型" to model.ifBlank { "—" },
            "claim_valid" to claimValid.toString(),
            "evidence_status" to (evidenceStatus ?: "—"),
            "checkpoint" to checkpointSha256.shortHash(),
            "已注册 / 已校准" to "$checkpointRegistered / $checkpointCalibrated",
            "事件签名" to evidenceSignature.label(),
            "签名公钥指纹" to evidenceSignature.publicKeyFingerprintSha256.shortHash(),
            "来源凭证签名可信" to sourceCredential.signatureTrusted.toString(),
            "来源凭证 SHA-256" to sourceCredential.sha256.shortHash(),
            "原图持久化" to privacy.originalPersisted.toString(),
        ),
    )
}

fun VerifyResult.toPresentation(): ProvenancePresentation {
    val formal = hasPublishableVerificationClaim()
    val decoded = verified
    return ProvenancePresentation(
        publishable = formal,
        headline = when {
            formal -> "预登记来源凭证核验通过"
            decoded -> "水印匹配，但声明门禁未通过"
            else -> "未匹配指定的预登记来源凭证"
        },
        detail = if (formal) {
            "恢复消息匹配指定 content_id，且 checkpoint、阈值与签名门禁同时通过。"
        } else {
            "结果不能解释为图片真假、未编辑状态、自然人身份或法律权属结论。"
        },
        rows = listOf(
            "content_id" to contentId.ifBlank { "—" },
            "应用侧主体引用" to creatorRef.ifBlank { "—" },
            "模型" to model.ifBlank { "—" },
            "registered blind verification" to (resultProvenance == "registered_blind_verification").toString(),
            "消息恢复匹配" to verified.toString(),
            "bit accuracy" to bitAccuracy.ratioText(),
            "verification threshold" to verificationThreshold.ratioText(),
            "原保护文件精确匹配" to exactProtectedFileMatch.toString(),
            "claim_valid" to claimValid.toString(),
            "evidence_status" to (evidenceStatus ?: "—"),
            "父记录声明有效" to parentRecordClaimValid.toString(),
            "父记录已撤销" to parentRecordRevoked.toString(),
            "定位方式" to (sourceLocator ?: "—"),
            "创作者密钥指纹" to creatorKeyFingerprintSha256.shortHash(),
            "checkpoint" to checkpointSha256.shortHash(),
            "运行 checkpoint 一致" to (checkpointSha256 != null && checkpointSha256 == runtimeCheckpointSha256).toString(),
            "已注册 / 已校准" to "$checkpointRegistered / $checkpointCalibrated",
            "事件签名" to evidenceSignature.label(),
            "签名公钥指纹" to evidenceSignature.publicKeyFingerprintSha256.shortHash(),
        ),
    )
}

fun RevocationResult.toPresentation(): ProvenancePresentation {
    val valid = schemaVersion == "provenance-revocation.v1" &&
        revoked && !claimValid && evidenceSignature.isSignedEd25519()
    return ProvenancePresentation(
        publishable = valid,
        headline = if (valid) "登记记录已完成签名撤销" else "撤销响应未通过客户端门禁",
        detail = if (valid) {
            "后续核验必须显示 parent_record_revoked=true 且 claim_valid=false。"
        } else {
            "客户端不会把不完整响应展示为已撤销。"
        },
        rows = listOf(
            "content_id" to contentId.ifBlank { "—" },
            "revocation_id" to revocationId.ifBlank { "—" },
            "撤销原因" to reasonCode.ifBlank { "—" },
            "revoked" to revoked.toString(),
            "claim_valid" to claimValid.toString(),
            "创作者密钥指纹" to creatorKeyFingerprintSha256.shortHash(),
            "撤销事件签名" to evidenceSignature.label(),
            "更新后来源凭证" to sourceCredentialSha256.shortHash(),
        ),
    )
}

private fun PayloadSignature.isSignedEd25519(): Boolean =
    signed && status == "signed" && algorithm == "ed25519" &&
        !signatureBase64.isNullOrBlank() && publicKeyFingerprintSha256.isSha256()

private fun PayloadSignature.label(): String = when {
    isSignedEd25519() -> "Ed25519 已附带 · 服务端声明门禁验签"
    signed -> "已附带，但签名字段不完整"
    else -> status ?: "未签名"
}

private fun String?.isSha256(): Boolean =
    this != null && length == 64 && all { it in '0'..'9' || it in 'a'..'f' }

private fun String?.shortHash(): String = when {
    isNullOrBlank() -> "—"
    length <= 18 -> this
    else -> take(12) + "…" + takeLast(6)
}

private fun Double?.ratioText(): String =
    this?.let { String.format(Locale.US, "%.4f", it) } ?: "—"
