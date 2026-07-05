package com.vpsg.jianyuanshield.ui.pub

/**
 * 鉴源盾 · 公众版静态数据模型 + 打样用样例数据。
 *
 * 这些只是用来填充 UI 的演示数据(对应 HTML 打样里写死的内容),
 * 真接后端时替换为来自 ViewModel 的状态即可。[VerdictKind] 定义在 [Pub] 同包文件。
 */

/** 一条鉴别记录。 */
data class PubRecord(
    val name: String,
    val meta: String,
    val kind: VerdictKind,
    /** 进度条/百分比展示值,0..100。 */
    val percent: Int,
)

/** 科普文章条目。 */
data class LearnArticle(
    val category: String,
    val title: String,
    val minutes: Int,
    val views: String,
    /** 立体缩略图配色,0..4 -> clay 调色板。 */
    val palette: Int,
)

/** 结论文案与百分比标签。 */
fun VerdictKind.label(): String = when (this) {
    VerdictKind.Real -> "通过核验"
    VerdictKind.Ai -> "水印降级"
    VerdictKind.Tampered -> "未能确认"
}

/** 右下角百分比小字,如 "可信 97%" / "降级 88%" / "未确认 91%"。 */
fun VerdictKind.percentLabel(percent: Int): String = when (this) {
    VerdictKind.Real -> "可信 $percent%"
    VerdictKind.Ai -> "降级 $percent%"
    VerdictKind.Tampered -> "未确认 $percent%"
}

/** 集中存放打样样例数据。 */
object PubSample {

    /** 首页"最近鉴别"(3 条)。 */
    val recent = listOf(
        PubRecord("微信图片_0931.jpg", "今天 09:31 · 来自相册", VerdictKind.Real, 97),
        PubRecord("朋友圈截图.png", "昨天 21:08 · 来自相册", VerdictKind.Ai, 88),
        PubRecord("二手交易_实拍.jpg", "6月13日 · 现场拍摄", VerdictKind.Tampered, 91),
    )

    /** 记录页 · 今天。 */
    val recordsToday = listOf(
        PubRecord("微信图片_0931.jpg", "今天 09:31 · 来自相册", VerdictKind.Real, 97),
        PubRecord("收款转账_截图.png", "今天 08:14 · 来自相册", VerdictKind.Tampered, 93),
    )

    /** 记录页 · 本周。 */
    val recordsWeek = listOf(
        PubRecord("网红风景照_转发.jpg", "周四 19:42 · 来自微信", VerdictKind.Ai, 90),
        PubRecord("合同首页_拍照.jpg", "周三 14:05 · 现场拍摄", VerdictKind.Real, 98),
        PubRecord("明星同框_爆料图.jpg", "周一 22:30 · 来自微信", VerdictKind.Ai, 85),
    )

    /** 记录页 · 更早。 */
    val recordsEarlier = listOf(
        PubRecord("家庭聚会_合影.jpg", "6月8日 · 现场拍摄", VerdictKind.Real, 99),
        PubRecord("二手交易_实拍.jpg", "6月5日 · 现场拍摄", VerdictKind.Tampered, 91),
        PubRecord("孩子毕业照_存档.jpg", "6月2日 · 来自相册", VerdictKind.Real, 96),
    )

    /** 科普文章列表。 */
    val articles = listOf(
        LearnArticle("防骗", "收到\"转账截图\"先别急着信", 3, "8,640 人看过", 3),
        LearnArticle("AI 生成", "AI 画的人,手指和耳朵最容易露馅", 2, "1.5 万人看过", 0),
        LearnArticle("换脸", "明星\"同框照\"是真的吗?看光影就懂", 4, "9,210 人看过", 2),
        LearnArticle("隐藏水印", "图片怎么\"记住\"自己从哪来的?", 3, "6,180 人看过", 1),
        LearnArticle("防骗", "家里老人最容易转发的 5 类假图", 5, "2.3 万人看过", 4),
    )
}
