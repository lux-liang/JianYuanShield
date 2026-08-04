package com.vpsg.jianyuanshield.data.repository

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.vpsg.jianyuanshield.core.ImageCompressor
import com.vpsg.jianyuanshield.core.CreatorKeyManager
import com.vpsg.jianyuanshield.data.MockData
import com.vpsg.jianyuanshield.data.remote.ApiService
import com.vpsg.jianyuanshield.data.remote.ApiAuthInterceptor
import com.vpsg.jianyuanshield.data.remote.HostSelectionInterceptor
import com.vpsg.jianyuanshield.BuildConfig
import com.vpsg.jianyuanshield.data.remote.validatedBackendUrl
import com.vpsg.jianyuanshield.data.remote.validatedApiToken
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
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
import java.security.MessageDigest
import java.util.Base64

/**
 * Single entry point for all backend interactions. Handles base-URL syncing,
 * reading image bytes from content URIs, and assembling multipart requests.
 */
class ShieldRepository(
    private val appContext: Context,
    private val api: ApiService,
    private val settings: SettingsRepository,
    private val hostInterceptor: HostSelectionInterceptor,
    private val authInterceptor: ApiAuthInterceptor,
) {

    val baseUrl: Flow<String> = settings.baseUrl

    /** Ensure the interceptor points at the currently configured backend. */
    private suspend fun syncHost(): String {
        val url = settings.baseUrl.first()
        hostInterceptor.setBaseUrl(url)
        authInterceptor.setToken(settings.apiToken.first())
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

    suspend fun modelsStatus(): ModelsStatusResponse {
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

    /** Register a new protected asset. Raw bytes are preserved for stable hashes. */
    suspend fun protectContent(
        uri: Uri,
        creatorRef: String,
        model: String,
        creatorKey: CreatorKeyManager,
    ): ProtectResult {
        check(!demo(delayMillis = 0)) { "来源登记不支持演示模式" }
        syncHost()
        val raw = readRawImage(uri)
        val imageSha256 = sha256(raw.bytes)
        val identity = creatorKey.identity()
        val challenge = api.creatorChallenge(
            creatorPublicKeyPem = identity.publicKeyPem,
            creatorRef = creatorRef,
            model = model,
            imageSha256 = imageSha256,
        )
        val signingMessage = challenge.signingMessageBase64?.let {
            runCatching { Base64.getDecoder().decode(it) }.getOrNull()
        }
        check(
            challenge.schemaVersion == "creator-identity-challenge.v1" &&
                isHexId(challenge.challengeId, 32) &&
                challenge.creatorRef == creatorRef &&
                challenge.model == model &&
                challenge.imageSha256 == imageSha256 &&
                challenge.creatorKeyFingerprintSha256 == identity.fingerprintSha256 &&
                (challenge.expiresAt ?: 0L) > System.currentTimeMillis() / 1000L &&
                challenge.serverSignatureTrusted &&
                signingMessage != null,
        ) { "创作者一次性挑战未通过绑定与服务端签名门禁" }
        val creatorSignature = Base64.getEncoder().encodeToString(creatorKey.sign(signingMessage))
        return api.protectContent(
            file = raw.part("file"),
            creatorRef = creatorRef.toFormBody(),
            model = model.toFormBody(),
            challengeId = challenge.challengeId.toFormBody(),
            creatorSignatureBase64 = creatorSignature.toFormBody(),
        )
    }

    /** Decode-only verification against one existing registration record. */
    suspend fun verifyContent(
        uri: Uri,
        contentId: String?,
        sourceCredential: ByteArray? = null,
    ): VerifyResult {
        check(!demo(delayMillis = 0)) { "登记凭证核验不支持演示模式" }
        require(!contentId.isNullOrBlank() || sourceCredential != null) {
            "content_id 或来源凭证至少提供一项"
        }
        syncHost()
        return api.verifyContent(
            file = rawImagePart("file", uri),
            contentId = contentId?.toFormBody(),
            sourceCredential = sourceCredential?.let {
                MultipartBody.Part.createFormData(
                    "source_credential",
                    "source-credential.json",
                    it.toRequestBody("application/json".toMediaTypeOrNull()),
                )
            },
        )
    }

    suspend fun revokeContent(
        contentId: String,
        reasonCode: String,
        creatorKey: CreatorKeyManager,
    ): RevocationResult {
        check(!demo(delayMillis = 0)) { "来源登记撤销不支持演示模式" }
        syncHost()
        val identity = creatorKey.identity()
        val intent = api.revocationIntent(contentId, reasonCode)
        val signingMessage = intent.signingMessageBase64?.let {
            runCatching { Base64.getDecoder().decode(it) }.getOrNull()
        }
        check(
            intent.schemaVersion == "provenance-revocation-intent.v1" &&
                isHexId(intent.intentId, 32) &&
                intent.contentId == contentId &&
                intent.reasonCode == reasonCode &&
                intent.creatorKeyFingerprintSha256 == identity.fingerprintSha256 &&
                (intent.expiresAt ?: 0L) > System.currentTimeMillis() / 1000L &&
                intent.serverSignatureTrusted &&
                signingMessage != null,
        ) { "撤销意图未通过记录、创作者密钥与服务端签名门禁" }
        val signature = Base64.getEncoder().encodeToString(creatorKey.sign(signingMessage))
        val revoked = api.revokeContent(contentId, intent.intentId, signature)
        check(
            revoked.schemaVersion == "provenance-revocation.v1" &&
                revoked.contentId == contentId && revoked.revoked && !revoked.claimValid,
        ) { "服务端未返回有效撤销事件" }
        return revoked
    }

    /** Validate before persisting so release builds cannot retain an HTTP origin. */
    suspend fun saveBaseUrl(url: String) {
        val normalized = validatedBackendUrl(url, BuildConfig.DEBUG).toString()
        settings.setBaseUrl(normalized)
        hostInterceptor.setBaseUrl(normalized)
    }

    suspend fun saveApiToken(token: String) {
        val normalized = validatedApiToken(token)
        settings.setApiToken(normalized.orEmpty())
        authInterceptor.setToken(normalized)
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

    private suspend fun rawImagePart(field: String, uri: Uri): MultipartBody.Part =
        readRawImage(uri).part(field)

    private suspend fun readRawImage(uri: Uri): RawImage = withContext(Dispatchers.IO) {
            val bytes = appContext.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                ?: throw IOException("无法读取所选图片")
            val mime = appContext.contentResolver.getType(uri)
                ?.takeIf { it == "image/jpeg" || it == "image/png" || it == "image/webp" }
                ?: "application/octet-stream"
            val name = displayName(uri)
            RawImage(bytes, name, mime)
        }

    private fun RawImage.part(field: String): MultipartBody.Part = MultipartBody.Part.createFormData(
        field,
        name,
        bytes.toRequestBody(mime.toMediaTypeOrNull()),
    )

    private data class RawImage(val bytes: ByteArray, val name: String, val mime: String)

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }

    private fun isHexId(value: String, length: Int): Boolean =
        value.length == length && value.all { it in '0'..'9' || it in 'a'..'f' }

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
