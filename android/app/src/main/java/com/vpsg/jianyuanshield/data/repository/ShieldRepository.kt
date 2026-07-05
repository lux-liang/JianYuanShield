package com.vpsg.jianyuanshield.data.repository

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.vpsg.jianyuanshield.core.ImageCompressor
import com.vpsg.jianyuanshield.data.MockData
import com.vpsg.jianyuanshield.data.remote.ApiService
import com.vpsg.jianyuanshield.data.remote.HostSelectionInterceptor
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelState
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import com.vpsg.jianyuanshield.data.settings.SettingsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/**
 * Single entry point for all backend interactions. Handles base-URL syncing,
 * reading image bytes from content URIs, and assembling multipart requests.
 */
class ShieldRepository(
    private val appContext: Context,
    private val api: ApiService,
    private val settings: SettingsRepository,
    private val hostInterceptor: HostSelectionInterceptor,
) {

    val baseUrl: Flow<String> = settings.baseUrl

    /** Ensure the interceptor points at the currently configured backend. */
    private suspend fun syncHost(): String {
        val url = settings.baseUrl.first()
        hostInterceptor.setBaseUrl(url)
        return url
    }

    /** Demo mode short-circuit: serve local mock data with a small, honest delay. */
    private suspend fun demo(delayMillis: Long = 450): Boolean {
        val enabled = settings.demoMode.first()
        if (enabled) delay(delayMillis)
        return enabled
    }

    suspend fun health(): HealthResponse {
        if (demo()) return MockData.health
        syncHost()
        return api.health()
    }

    suspend fun modelsStatus(): Map<String, ModelState> {
        if (demo()) return MockData.modelsStatus
        syncHost()
        return api.modelsStatus()
    }

    suspend fun modules(): List<ModuleInfo> {
        if (demo()) return MockData.modules
        syncHost()
        return api.modules()
    }

    suspend fun inferSingle(uri: Uri, model: String, attack: String): InferResult {
        // Longer demo delay so the scan-line animation reads as real work.
        if (demo(delayMillis = 1600)) return MockData.inferResult(uri.toString(), model, attack)
        syncHost()
        val part = imagePart("file", uri)
        return api.inferSingle(
            file = part,
            model = model.toFormBody(),
            attack = attack.toFormBody(),
            // Use artifact URLs (lighter) instead of inline base64.
            returnB64 = "false".toFormBody(),
        )
    }

    suspend fun complianceBatch(uris: List<Uri>, model: String): ComplianceResult {
        if (demo(delayMillis = 1200)) {
            return MockData.complianceResult(uris.map { displayName(it) }, model)
        }
        syncHost()
        val parts = uris.map { imagePart("files", it) }
        return api.complianceBatch(files = parts, model = model.toFormBody())
    }

    suspend fun evidenceAudit(): EvidenceAudit {
        if (demo()) return MockData.evidenceAudit
        syncHost()
        return api.evidenceAudit()
    }

    /** 平台证据包 Ed25519 签名状态(凭证页展示用)。 */
    suspend fun evidenceSignature(): Signature {
        if (demo()) return MockData.evidenceAudit.signature
        syncHost()
        return api.evidenceSignature()
    }

    /** Fetch the four single-model benchmarks concurrently. Failed ones are dropped. */
    suspend fun benchmarks(): List<SingleBenchmark> = coroutineScope {
        if (demo(delayMillis = 700)) return@coroutineScope MockData.benchmarks
        syncHost()
        val calls = listOf(
            async { runCatching { api.benchmarkLidmark() }.getOrNull() },
            async { runCatching { api.benchmarkKadnet() }.getOrNull() },
            async { runCatching { api.benchmarkWaveguard() }.getOrNull() },
            async { runCatching { api.benchmarkSepmark() }.getOrNull() },
        )
        calls.mapNotNull { it.await() }
    }

    // ── multipart helpers ────────────────────────────────────────────────────

    private fun String.toFormBody() = toRequestBody("text/plain".toMediaTypeOrNull())

    private suspend fun imagePart(field: String, uri: Uri): MultipartBody.Part =
        withContext(Dispatchers.IO) {
            // 上传前压缩(降采样 + JPEG);失败回退原始字节。
            val bytes = runCatching { ImageCompressor.compress(appContext, uri) }
                .getOrElse {
                    appContext.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw IOException("无法读取所选图片")
                }
            val raw = displayName(uri)
            val name = if (raw.endsWith(".jpg", ignoreCase = true) || raw.endsWith(".jpeg", ignoreCase = true)) raw else "$raw.jpg"
            val body = bytes.toRequestBody("image/jpeg".toMediaTypeOrNull())
            MultipartBody.Part.createFormData(field, name, body)
        }

    private fun displayName(uri: Uri): String {
        var name: String? = null
        runCatching {
            appContext.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0 && cursor.moveToFirst()) {
                    name = cursor.getString(index)
                }
            }
        }
        return name?.takeIf { it.isNotBlank() } ?: "image_${System.currentTimeMillis()}.jpg"
    }
}
