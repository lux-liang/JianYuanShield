package com.vpsg.jianyuanshield.ui.pub.provenance

import android.app.Application
import android.net.Uri
import android.util.Base64
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.app
import com.vpsg.jianyuanshield.core.CreatorKeyIdentity
import com.vpsg.jianyuanshield.core.CreatorKeyManager
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ProtectedSession(
    val result: ProtectResult,
    val protectedUri: Uri,
    val protectedBytes: ByteArray,
    val sourceCredentialBytes: ByteArray,
)

class ProvenanceViewModel(
    app: Application,
    private val repository: ShieldRepository,
    private val creatorKey: CreatorKeyManager,
) : AndroidViewModel(app) {
    private val _models = MutableStateFlow<UiState<ModelsStatusResponse>>(UiState.Loading)
    val models: StateFlow<UiState<ModelsStatusResponse>> = _models.asStateFlow()

    private val _selectedModel = MutableStateFlow<String?>(null)
    val selectedModel: StateFlow<String?> = _selectedModel.asStateFlow()

    private val _protect = MutableStateFlow<UiState<ProtectedSession>>(UiState.Idle)
    val protect: StateFlow<UiState<ProtectedSession>> = _protect.asStateFlow()

    private val _verify = MutableStateFlow<UiState<VerifyResult>>(UiState.Idle)
    val verify: StateFlow<UiState<VerifyResult>> = _verify.asStateFlow()

    private val _exportMessage = MutableStateFlow<String?>(null)
    val exportMessage: StateFlow<String?> = _exportMessage.asStateFlow()

    private val _creatorIdentity = MutableStateFlow<UiState<CreatorKeyIdentity>>(UiState.Loading)
    val creatorIdentity: StateFlow<UiState<CreatorKeyIdentity>> = _creatorIdentity.asStateFlow()

    private val _revocation = MutableStateFlow<UiState<RevocationResult>>(UiState.Idle)
    val revocation: StateFlow<UiState<RevocationResult>> = _revocation.asStateFlow()

    init {
        refreshModels()
        viewModelScope.launch(Dispatchers.IO) {
            _creatorIdentity.value = runCatching { creatorKey.identity() }
                .fold({ UiState.Success(it) }, { UiState.Error(it.message ?: "创作者签名密钥不可用") })
        }
    }

    fun refreshModels() {
        viewModelScope.launch {
            _models.value = UiState.Loading
            try {
                val status = repository.modelsStatus()
                _models.value = UiState.Success(status)
                _selectedModel.value = status.safePreferredModel()
            } catch (ce: CancellationException) {
                throw ce
            } catch (error: Throwable) {
                _selectedModel.value = null
                _models.value = UiState.Error(error.toUserMessage())
            }
        }
    }

    fun selectModel(model: String) {
        val status = (_models.value as? UiState.Success)?.data ?: return
        _selectedModel.value = model.takeIf { status.readyModels.containsKey(it) }
    }

    fun protect(uri: Uri, creatorRef: String) {
        if (_protect.value is UiState.Loading) return
        val model = _selectedModel.value
        val status = (_models.value as? UiState.Success)?.data
        if (model == null || status?.readyModels?.containsKey(model) != true) {
            _protect.value = UiState.Error("没有通过 provenance_ready 门禁的模型")
            return
        }
        val cleanCreator = creatorRef.trim()
        if (!isValidCreatorRef(cleanCreator)) {
            _protect.value = UiState.Error("应用侧主体引用须为 1–128 个可打印字符")
            return
        }
        viewModelScope.launch {
            _protect.value = UiState.Loading
            _verify.value = UiState.Idle
            _exportMessage.value = null
            try {
                // Recheck live readiness immediately before the state-changing call.
                val live = repository.modelsStatus()
                if (live.readyModels.containsKey(model).not()) {
                    _models.value = UiState.Success(live)
                    _selectedModel.value = live.safePreferredModel()
                    error("模型当前未通过 provenance_ready 门禁")
                }
                val result = repository.protectContent(uri, cleanCreator, model, creatorKey)
                _protect.value = UiState.Success(cacheProtectedImage(result))
            } catch (ce: CancellationException) {
                throw ce
            } catch (error: Throwable) {
                _protect.value = UiState.Error(error.toUserMessage())
            }
        }
    }

    fun verify(uri: Uri, contentId: String) {
        if (_verify.value is UiState.Loading) return
        val cleanId = contentId.trim().lowercase()
        if (!isValidContentId(cleanId)) {
            _verify.value = UiState.Error("content_id 必须是 32 位小写十六进制标识")
            return
        }
        runVerify(uri, cleanId, null)
    }

    private fun runVerify(uri: Uri, contentId: String?, credential: ByteArray?) {
        viewModelScope.launch {
            _verify.value = UiState.Loading
            try {
                _verify.value = UiState.Success(repository.verifyContent(uri, contentId, credential))
            } catch (ce: CancellationException) {
                throw ce
            } catch (error: Throwable) {
                _verify.value = UiState.Error(error.toUserMessage())
            }
        }
    }

    fun verifyGeneratedProtection() {
        val session = (_protect.value as? UiState.Success)?.data ?: return
        runVerify(session.protectedUri, null, session.sourceCredentialBytes)
    }

    fun verifyWithSourceCredential(image: Uri, credentialUri: Uri) {
        if (_verify.value is UiState.Loading) return
        viewModelScope.launch {
            _verify.value = UiState.Loading
            try {
                val credential = withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openInputStream(credentialUri)?.use {
                        it.readBytes()
                    } ?: error("无法读取来源凭证")
                }
                require(credential.size in 1..(256 * 1024)) { "来源凭证超过 256 KiB 或为空" }
                _verify.value = UiState.Success(repository.verifyContent(image, null, credential))
            } catch (ce: CancellationException) {
                throw ce
            } catch (error: Throwable) {
                _verify.value = UiState.Error(error.toUserMessage())
            }
        }
    }

    /** Export through the system document picker; no broad storage permission. */
    fun exportProtected(target: Uri) {
        val session = (_protect.value as? UiState.Success)?.data ?: return
        viewModelScope.launch(Dispatchers.IO) {
            _exportMessage.value = runCatching {
                getApplication<Application>().contentResolver.openOutputStream(target)?.use {
                    it.write(session.protectedBytes)
                } ?: error("无法写入目标文件")
                "受保护 PNG 已导出；请与 content_id 一并保存"
            }.getOrElse { it.message ?: "导出失败" }
        }
    }

    fun exportSourceCredential(target: Uri) {
        val session = (_protect.value as? UiState.Success)?.data ?: return
        viewModelScope.launch(Dispatchers.IO) {
            _exportMessage.value = runCatching {
                getApplication<Application>().contentResolver.openOutputStream(target)?.use {
                    it.write(session.sourceCredentialBytes)
                } ?: error("无法写入目标文件")
                "签名来源凭证已导出；可与受保护 PNG 一并离线传递"
            }.getOrElse { it.message ?: "导出失败" }
        }
    }

    fun revoke(contentId: String, reasonCode: String) {
        if (_revocation.value is UiState.Loading) return
        val cleanId = contentId.trim().lowercase()
        if (!isValidContentId(cleanId) || reasonCode !in REVOCATION_REASONS) {
            _revocation.value = UiState.Error("content_id 或撤销原因无效")
            return
        }
        viewModelScope.launch {
            _revocation.value = UiState.Loading
            try {
                _revocation.value = UiState.Success(
                    repository.revokeContent(cleanId, reasonCode, creatorKey),
                )
            } catch (ce: CancellationException) {
                throw ce
            } catch (error: Throwable) {
                _revocation.value = UiState.Error(error.toUserMessage())
            }
        }
    }

    fun resetProtection() {
        _protect.value = UiState.Idle
        _verify.value = UiState.Idle
        _revocation.value = UiState.Idle
        _exportMessage.value = null
    }

    private suspend fun cacheProtectedImage(result: ProtectResult): ProtectedSession = withContext(Dispatchers.IO) {
        require(isValidContentId(result.contentId)) { "服务端返回了无效 content_id" }
        val encoded = result.protectedImage.pngBase64
            ?: error("服务端未返回受保护图片")
        val bytes = runCatching { Base64.decode(encoded, Base64.DEFAULT) }
            .getOrElse { error("受保护图片编码无效") }
        require(bytes.size >= 8 && bytes.copyOfRange(0, 8).contentEquals(PNG_SIGNATURE)) {
            "受保护图片不是有效 PNG"
        }
        require(result.creatorIdentityVerified) { "创作者持钥身份门禁未通过" }
        val credentialEncoded = result.sourceCredential.jsonBase64
            ?: error("服务端未返回签名来源凭证")
        val credential = runCatching { Base64.decode(credentialEncoded, Base64.DEFAULT) }
            .getOrElse { error("来源凭证编码无效") }
        require(
            result.sourceCredential.signatureTrusted &&
                credential.isNotEmpty() && credential.first() == '{'.code.toByte() &&
                sha256(credential) == result.sourceCredential.sha256,
        ) { "来源凭证未通过签名状态与 SHA-256 门禁" }
        val dir = File(getApplication<Application>().cacheDir, "provenance").apply { mkdirs() }
        val file = File(dir, "protected_${result.contentId}.png")
        file.outputStream().use { it.write(bytes) }
        val uri = FileProvider.getUriForFile(
            getApplication(),
            "${getApplication<Application>().packageName}.fileprovider",
            file,
        )
        ProtectedSession(result, uri, bytes, credential)
    }

    companion object {
        private val PNG_SIGNATURE = byteArrayOf(
            0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
        )

        val Factory = viewModelFactory {
            initializer {
                val container = app().container
                ProvenanceViewModel(app(), container.repository, container.creatorKeyManager)
            }
        }
    }
}

private fun sha256(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 0xff) }

val REVOCATION_REASONS = setOf(
    "creator_request",
    "key_compromise",
    "mislabeling",
    "policy_violation",
)

fun isValidContentId(value: String): Boolean =
    value.length == 32 && value.all { it in '0'..'9' || it in 'a'..'f' }

fun isValidCreatorRef(value: String): Boolean =
    value.length in 1..128 && value.all { !it.isISOControl() }
