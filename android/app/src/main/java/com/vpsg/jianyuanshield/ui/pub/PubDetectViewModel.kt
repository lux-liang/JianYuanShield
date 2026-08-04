package com.vpsg.jianyuanshield.ui.pub

import android.app.Application
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.ImageCompressor
import com.vpsg.jianyuanshield.core.app
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.history.HistoryEntry
import com.vpsg.jianyuanshield.data.history.HistoryStore
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import com.vpsg.jianyuanshield.data.settings.SettingsRepository
import com.vpsg.jianyuanshield.domain.DEFAULT_ATTACK
import com.vpsg.jianyuanshield.domain.DEFAULT_MODEL
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 公众版"一次鉴别会话"的共享状态:选图 → 调真实后端 [ShieldRepository.inferSingle] →
 * 映射 [PubResultUi]。本地模拟只允许由用户显式开启 demoMode；网络或服务失败直接进入
 * [UiState.Error]，绝不伪装成成功结果。只有通过声明门禁的真实结果才写入历史。
 */
class PubDetectViewModel(
    app: Application,
    private val repository: ShieldRepository,
    private val settings: SettingsRepository,
    private val history: HistoryStore,
) : AndroidViewModel(app) {

    private val _image = MutableStateFlow<Uri?>(null)
    val image: StateFlow<Uri?> = _image.asStateFlow()

    private val _fileName = MutableStateFlow("未选择图片")
    val fileName: StateFlow<String> = _fileName.asStateFlow()

    private val _fileMeta = MutableStateFlow("")
    val fileMeta: StateFlow<String> = _fileMeta.asStateFlow()

    private val _state = MutableStateFlow<UiState<PubResultUi>>(UiState.Idle)
    val state: StateFlow<UiState<PubResultUi>> = _state.asStateFlow()

    private val _probe = MutableStateFlow<ConnProbe>(ConnProbe.Idle)
    val probe: StateFlow<ConnProbe> = _probe.asStateFlow()

    /** 真实历史(落盘)。 */
    val historyEntries: StateFlow<List<HistoryEntry>> = history.entries

    val baseUrl: StateFlow<String> =
        settings.baseUrl.stateIn(viewModelScope, SharingStarted.Eagerly, SettingsRepository.DEFAULT_BASE_URL)
    val demoMode: StateFlow<Boolean> =
        settings.demoMode.stateIn(viewModelScope, SharingStarted.Eagerly, false)
    val uploadConsent: StateFlow<Boolean> =
        settings.uploadConsent.stateIn(viewModelScope, SharingStarted.Eagerly, false)
    val bigFont: StateFlow<Boolean> =
        settings.bigFont.stateIn(viewModelScope, SharingStarted.Eagerly, false)
    val userName: StateFlow<String> =
        settings.userName.stateIn(viewModelScope, SharingStarted.Eagerly, "鉴源盾用户")
    val avatarPath: StateFlow<String?> =
        settings.avatarPath.stateIn(viewModelScope, SharingStarted.Eagerly, null)
    val apiTokenConfigured: StateFlow<Boolean> =
        settings.apiToken.map { it.isNotBlank() }
            .stateIn(viewModelScope, SharingStarted.Eagerly, false)

    private var model: String = DEFAULT_MODEL.id
    private var attack: String = DEFAULT_ATTACK.id

    fun setImage(uri: Uri) {
        _image.value = uri
        _state.value = UiState.Idle
        _fileName.value = "图片"
        _fileMeta.value = ""
        viewModelScope.launch(Dispatchers.IO) {
            val resolver = getApplication<Application>().contentResolver
            var name = "图片_${System.currentTimeMillis()}.jpg"
            var size = -1L
            runCatching {
                resolver.query(uri, null, null, null, null)?.use { c ->
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (c.moveToFirst()) {
                        if (ni >= 0) c.getString(ni)?.let { name = it }
                        if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
                    }
                }
            }
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            runCatching {
                resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            }
            val mime = runCatching { resolver.getType(uri) }.getOrNull()
            _fileName.value = name
            _fileMeta.value = buildMeta(name, mime, opts.outWidth, opts.outHeight, size)
        }
    }

    fun run() {
        if (_state.value is UiState.Loading) return
        val uri = _image.value ?: run {
            _state.value = UiState.Error("还没有选择图片")
            return
        }
        viewModelScope.launch {
            _state.value = UiState.Loading
            val base = runCatching { repository.baseUrl.first() }.getOrDefault(SettingsRepository.DEFAULT_BASE_URL)
            val name = _fileName.value
            try {
                val res = repository.inferSingle(uri, model, attack)
                val explicitDemo = settings.demoMode.first()
                val ui = res.toPubResultUi(base, name, uri.toString(), explicitDemo)
                _state.value = UiState.Success(ui)
                if (ui.canIssueCertificate) saveHistory(uri, ui, res.createdAt)
            } catch (ce: CancellationException) {
                throw ce
            } catch (e: Throwable) {
                val msg = e.toUserMessageSafe()
                _state.value = UiState.Error(
                    "$msg\n\n为避免把模拟结果误作真实结论，本次未自动进入演示模式。" +
                        "如需预览流程，请先在服务器设置中显式开启演示模式。",
                )
            }
        }
    }

    private suspend fun saveHistory(uri: Uri, ui: PubResultUi, createdAt: Long?) {
        val thumb = ImageCompressor.decodeThumbnail(getApplication(), uri)
        history.add(
            HistoryEntry(
                taskId = ui.taskId,
                title = ui.certName,
                createdAt = createdAt ?: (System.currentTimeMillis() / 1000),
                verdict = ui.verdict.name,
                percent = ui.headlinePercent,
                headlineLabel = ui.headlineLabel,
                mode = ui.mode,
                model = ui.model,
            ),
            thumb,
        )
    }

    fun reset() {
        _state.value = UiState.Idle
    }

    fun reportUrl(taskId: String): String =
        baseUrl.value.trimEnd('/') + "/api/reports/" + taskId

    /** 导航和导出层共用的防御性凭证门禁。 */
    fun canIssueCertificate(): Boolean =
        (_state.value as? UiState.Success)?.data?.canIssueCertificate == true

    fun probeConnection() {
        if (_probe.value is ConnProbe.Checking) return
        viewModelScope.launch {
            _probe.value = ConnProbe.Checking
            _probe.value = testConnection()
        }
    }

    suspend fun testConnection(): ConnProbe = withContext(Dispatchers.IO) {
        try {
            val explicitDemo = settings.demoMode.first()
            val h = repository.health()
            val ready = if (explicitDemo) emptyList() else repository.modelsStatus().readyModels.keys.toList()
            ConnProbe.Ok(
                mode = if (explicitDemo) "local_demo" else h.mode ?: "unknown",
                version = h.version,
                provenanceReadyModels = ready,
            )
        } catch (ce: CancellationException) {
            throw ce
        } catch (e: Throwable) {
            ConnProbe.Fail(e.toUserMessageSafe())
        }
    }

    /** 凭证页用:平台证据签名状态文案(best-effort,失败返回 null)。 */
    suspend fun evidenceSignatureLabel(): String? = withContext(Dispatchers.IO) {
        if (!canIssueCertificate()) return@withContext null
        runCatching {
            val s = repository.evidenceSignature()
            if (s.verified == true || s.signatureValid == true) "平台证据已 Ed25519 签名核验" else null
        }.getOrNull()
    }

    suspend fun saveBaseUrl(url: String) = repository.saveBaseUrl(url)
    suspend fun saveApiToken(token: String) = repository.saveApiToken(token)
    suspend fun setDemoMode(enabled: Boolean) = settings.setDemoMode(enabled)
    suspend fun grantConsent() = settings.setUploadConsent(true)
    suspend fun setBigFont(enabled: Boolean) = settings.setBigFont(enabled)
    suspend fun setUserName(name: String) = settings.setUserName(name)

    /** 选图设头像:解码缩略图 → 存到 filesDir(唯一文件名,便于刷新)→ 记录路径。 */
    suspend fun setAvatar(uri: Uri) = withContext(Dispatchers.IO) {
        val bmp = ImageCompressor.decodeThumbnail(getApplication(), uri, 480) ?: return@withContext
        val f = java.io.File(getApplication<Application>().filesDir, "avatar_${System.currentTimeMillis()}.jpg")
        runCatching {
            f.outputStream().use { bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 88, it) }
            settings.setAvatarPath(f.absolutePath)
        }
        Unit
    }

    private fun Throwable.toUserMessageSafe(): String =
        runCatching { toUserMessage() }.getOrElse { message ?: "网络异常" }

    private fun buildMeta(name: String, mime: String?, w: Int, h: Int, size: Long): String {
        val parts = mutableListOf<String>()
        val fmt = when {
            mime?.contains("png") == true -> "PNG"
            mime?.contains("webp") == true -> "WEBP"
            mime?.contains("jpeg") == true || mime?.contains("jpg") == true -> "JPG"
            name.substringAfterLast('.', "").isNotBlank() -> name.substringAfterLast('.').uppercase()
            else -> "图片"
        }
        parts += fmt
        if (w > 0 && h > 0) parts += "$w × $h"
        if (size > 0) parts += humanSize(size)
        return parts.joinToString("  ·  ")
    }

    private fun humanSize(bytes: Long): String = when {
        bytes >= 1024 * 1024 -> String.format("%.1f MB", bytes / 1024.0 / 1024.0)
        bytes >= 1024 -> String.format("%.0f KB", bytes / 1024.0)
        else -> "$bytes B"
    }

    companion object {
        val Factory = viewModelFactory {
            initializer {
                val container = app().container
                PubDetectViewModel(app(), container.repository, container.settingsRepository, container.historyStore)
            }
        }
    }
}
