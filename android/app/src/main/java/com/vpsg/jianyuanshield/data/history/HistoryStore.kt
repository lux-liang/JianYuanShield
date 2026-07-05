package com.vpsg.jianyuanshield.data.history

import android.content.Context
import android.graphics.Bitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/** 一条真实的鉴别历史(落盘 JSON,跨启动保留)。 */
@Serializable
data class HistoryEntry(
    val taskId: String,
    val title: String,
    /** 创建时间(epoch 秒)。 */
    val createdAt: Long,
    /** VerdictKind.name: Real / Ai / Tampered。 */
    val verdict: String,
    val percent: Int,
    val headlineLabel: String,
    val mode: String,
    val model: String,
    val thumbPath: String? = null,
)

/**
 * 文件版历史仓库(kotlinx 序列化落盘到 filesDir/history.json)。
 *
 * 刻意不用 Room:本机无法编译,Room 的注解处理器代码生成出错时不可见、难排查;
 * 纯 JSON 文件 100% 是可静态核验的普通 Kotlin。容量小(≤200 条),开销可忽略。
 */
class HistoryStore(context: Context) {

    private val appCtx = context.applicationContext
    private val file = File(appCtx.filesDir, "history.json")
    private val thumbsDir = File(appCtx.filesDir, "thumbs").apply { runCatching { mkdirs() } }
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val mutex = Mutex()

    private val _entries = MutableStateFlow(load())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    private fun load(): List<HistoryEntry> = runCatching {
        if (!file.exists()) emptyList()
        else json.decodeFromString<List<HistoryEntry>>(file.readText())
    }.getOrDefault(emptyList())

    suspend fun add(entry: HistoryEntry, thumb: Bitmap?) = withContext(Dispatchers.IO) {
        mutex.withLock {
            val thumbPath = thumb?.let { saveThumb(entry.taskId, it) }
            val withThumb = entry.copy(thumbPath = thumbPath)
            val updated = (listOf(withThumb) + _entries.value).take(200)
            _entries.value = updated
            runCatching { file.writeText(json.encodeToString(updated)) }
            Unit
        }
    }

    suspend fun clear() = withContext(Dispatchers.IO) {
        mutex.withLock {
            _entries.value = emptyList()
            runCatching { file.delete() }
            Unit
        }
    }

    private fun saveThumb(id: String, bmp: Bitmap): String? = runCatching {
        val safe = id.ifBlank { "t_" + System.currentTimeMillis() }
        val f = File(thumbsDir, "$safe.jpg")
        f.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 80, it) }
        f.absolutePath
    }.getOrNull()
}
