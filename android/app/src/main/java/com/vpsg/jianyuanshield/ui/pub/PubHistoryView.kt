package com.vpsg.jianyuanshield.ui.pub

import com.vpsg.jianyuanshield.data.history.HistoryEntry
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 历史条目 → 列表视图模型(records / home 复用 RecordRow)。 */

fun verdictKindOf(name: String): VerdictKind =
    runCatching { VerdictKind.valueOf(name) }.getOrDefault(VerdictKind.Real)

private fun modeLabel(mode: String): String =
    if (mode == "real_checkpoint") "真实模型" else "演示模拟"

private fun relativeTime(epochSec: Long, nowSec: Long): String {
    val d = nowSec - epochSec
    return when {
        epochSec <= 0L -> "—"
        d < 60 -> "刚刚"
        d < 3600 -> "${d / 60} 分钟前"
        d < 86400 -> "${d / 3600} 小时前"
        d < 7 * 86400 -> "${d / 86400} 天前"
        else -> SimpleDateFormat("MM-dd", Locale.getDefault()).format(Date(epochSec * 1000))
    }
}

fun HistoryEntry.toPubRecord(nowSec: Long): PubRecord = PubRecord(
    name = title,
    meta = relativeTime(createdAt, nowSec) + " · " + modeLabel(mode),
    kind = verdictKindOf(verdict),
    percent = percent,
)

/** total / passed(Real) / flagged(Ai+Tampered)。 */
fun List<HistoryEntry>.stats(): Triple<Int, Int, Int> {
    val total = size
    val passed = count { verdictKindOf(it.verdict) == VerdictKind.Real }
    val flagged = total - passed
    return Triple(total, passed, flagged)
}

data class HistoryGroups(
    val today: List<PubRecord>,
    val week: List<PubRecord>,
    val earlier: List<PubRecord>,
)

fun List<HistoryEntry>.grouped(nowSec: Long): HistoryGroups {
    val today = mutableListOf<PubRecord>()
    val week = mutableListOf<PubRecord>()
    val earlier = mutableListOf<PubRecord>()
    for (e in this) {
        val d = nowSec - e.createdAt
        val r = e.toPubRecord(nowSec)
        when {
            d < 86400 -> today += r
            d < 7 * 86400 -> week += r
            else -> earlier += r
        }
    }
    return HistoryGroups(today, week, earlier)
}
