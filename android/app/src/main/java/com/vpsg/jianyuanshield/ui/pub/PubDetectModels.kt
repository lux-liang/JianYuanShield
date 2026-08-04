package com.vpsg.jianyuanshield.ui.pub

import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 鉴源盾 · 公众版结果视图模型。
 *
 * 把后端 [com.vpsg.jianyuanshield.data.remote.dto.InferResult](溯源水印 / 攻击鲁棒性 /
 * 合规判定)映射成结果页 / 报告页 / 凭证页可直接渲染的字段。映射逻辑见 [PubResultMapper]。
 *
 * 设计取舍:后端是"主动取证水印"系统(给图嵌入水印再在攻击后尝试恢复),并不是通用的
 * "AI 生成 / 换脸"分类器。因此这里如实呈现后端真正算出的东西(水印可信度、鲁棒性、图像
 * 质量、合规标识),文案据此措辞,不编造后端没给的结论。
 */

/** 结果分项 / 报告块的语义色。 */
enum class PubTone { Warn, Ok, Mut }

/** 结果页 2×2 分项卡。 */
data class PubResultItem(
    val icon: ImageVector,
    val tone: PubTone,
    val label: String,
    val value: String,
    val sub: String,
)

/** 报告页"每一项是怎么判断的"块。 */
data class PubAnalysisBlock(
    val icon: ImageVector,
    val tone: PubTone,
    val label: String,
    val chip: String,
    /** 进度条占比 0..1。 */
    val barFraction: Float,
    val barNumber: String,
    val whyLabel: String,
    val bullets: List<String>,
)

/** 一次鉴别的完整结果(结果 / 报告 / 凭证三屏共用)。 */
data class PubResultUi(
    val verdict: VerdictKind,
    val heroPalette: HeroPalette,
    /** 头部大数字(可信度 / 水印完整度)。 */
    val headlinePercent: Int,
    val headlineLabel: String,
    val title: String,
    val badge: String,
    val desc: String,
    /** 预览图:优先后端 original 工件,其次本机选中图。可空。 */
    val previewUrl: String?,
    /** 可疑区域 / 差异热力图工件 URL,可空(无则不显示叠层)。 */
    val heatmapUrl: String?,
    /** 预览底部标注文案,可空。 */
    val annotation: String?,
    val items: List<PubResultItem>,
    val analysisBlocks: List<PubAnalysisBlock>,
    val summaryText: String,
    /** 报告"这次鉴别的信息" key→value。 */
    val metaInfo: List<Pair<String, String>>,
    // 凭证字段
    val certName: String,
    val certNumber: String,
    val certTime: String,
    val certItems: String,
    val certBadge: String,
    val certDesc: String,
    /** 证据指纹(文件名→sha256),可空。 */
    val sha256: List<Pair<String, String>>,
    // 原始信息
    val model: String,
    val attack: String,
    /** real_checkpoint / demo_simulation。 */
    val mode: String,
    /** registered_blind_verification 才属于跨请求登记核验。 */
    val resultProvenance: String,
    /** 后端声明门禁；只有 true 才允许发布结论。 */
    val claimValid: Boolean,
    /** 用户显式开启了本地演示模式。网络失败绝不会自动置为 true。 */
    val localDemo: Boolean,
    val taskId: String,
) {
    private val trustState: ResultTrustState
        get() = evaluateResultTrust(
            claimValid = claimValid,
            mode = mode,
            localDemo = localDemo,
            resultProvenance = resultProvenance,
        )

    /** 非真实 checkpoint 输出均视为模拟，采取保守策略。 */
    val isSimulation: Boolean
        get() = trustState.isSimulation

    /** 生成、保存、分享来源核验凭证的唯一客户端门禁。 */
    val canIssueCertificate: Boolean
        get() = trustState.canIssueCertificate

    val evidenceStatusLabel: String
        get() = trustState.statusLabel

    val evidenceStatusDetail: String
        get() = trustState.statusDetail
}

/** 服务器连接探测结果。 */
sealed interface ConnProbe {
    data object Idle : ConnProbe
    data object Checking : ConnProbe
    data class Ok(
        val mode: String,
        val version: String?,
        val provenanceReadyModels: List<String> = emptyList(),
    ) : ConnProbe
    data class Fail(val message: String) : ConnProbe
}
