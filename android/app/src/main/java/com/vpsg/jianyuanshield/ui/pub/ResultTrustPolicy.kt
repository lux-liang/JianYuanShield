package com.vpsg.jianyuanshield.ui.pub

/** Pure client-side rendering gate for backend inference/provenance results. */
data class ResultTrustState(
    val isSimulation: Boolean,
    val canIssueCertificate: Boolean,
    val statusLabel: String,
    val statusDetail: String,
)

/**
 * Fail closed unless the backend returned a real checkpoint result, explicitly
 * opened the claim gate, and identified it as a registered blind verification.
 */
fun evaluateResultTrust(
    claimValid: Boolean,
    mode: String?,
    localDemo: Boolean,
    resultProvenance: String?,
): ResultTrustState {
    val isSimulation = localDemo || mode != "real_checkpoint"
    val canIssueCertificate = claimValid &&
        !isSimulation &&
        resultProvenance == "registered_blind_verification"
    val statusLabel = when {
        canIssueCertificate -> "登记盲检结果 · 已通过声明门禁"
        localDemo -> "本地流程演示 · 不可作为结论"
        isSimulation -> "服务器流程模拟 · 不可作为结论"
        !claimValid -> "未通过声明门禁 · 结果不可发布"
        else -> "非登记盲检结果 · 不可生成凭证"
    }
    val statusDetail = when {
        canIssueCertificate -> "后端 provenance=registered_blind_verification 且 claim_valid=true，可生成来源核验凭证。"
        localDemo -> "你已显式开启演示模式；以下指标仅用于预览主动水印流程，不能生成、保存或分享凭证。"
        isSimulation -> "本次未使用真实 checkpoint；以下内容不得用于来源、合规或科研结论。"
        !claimValid -> "后端 claim_valid=false；可查看技术输出，但不得发布结论或生成凭证。"
        else -> "本次 provenance 不是 registered_blind_verification；单请求嵌入—攻击—解码评估不能生成来源凭证。"
    }
    return ResultTrustState(
        isSimulation = isSimulation,
        canIssueCertificate = canIssueCertificate,
        statusLabel = statusLabel,
        statusDetail = statusDetail,
    )
}
