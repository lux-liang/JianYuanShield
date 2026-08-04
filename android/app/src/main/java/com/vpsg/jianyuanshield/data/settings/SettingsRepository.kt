package com.vpsg.jianyuanshield.data.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.vpsg.jianyuanshield.BuildConfig
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "jys_settings")

/**
 * Persists the user-configured backend base URL, demo mode, upload consent and
 * accessibility (big font) preferences.
 */
class SettingsRepository(private val context: Context) {

    private val keyBaseUrl = stringPreferencesKey("base_url")
    private val keyDemoMode = booleanPreferencesKey("demo_mode")
    private val keyUploadConsent = booleanPreferencesKey("upload_consent")
    private val keyBigFont = booleanPreferencesKey("big_font")
    private val keyUserName = stringPreferencesKey("user_name")
    private val keyAvatarPath = stringPreferencesKey("avatar_path")
    private val keyApiToken = stringPreferencesKey("api_token")

    val baseUrl: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[keyBaseUrl]?.takeIf { it.isNotBlank() } ?: BuildConfig.DEFAULT_API_BASE
    }

    /** Demo mode: serve local mock data so the whole UI works without a backend. */
    val demoMode: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[keyDemoMode] ?: false
    }

    /** 用户是否已同意图片上传到所配置的保护/评估服务器。 */
    val uploadConsent: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[keyUploadConsent] ?: false
    }

    /** 大字模式(适老化):放大全局字号。 */
    val bigFont: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[keyBigFont] ?: false
    }

    /** 用户昵称(可在「我的」编辑)。 */
    val userName: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[keyUserName]?.takeIf { it.isNotBlank() } ?: "鉴源盾用户"
    }

    /** 头像本地文件路径(可空,空则显示默认占位)。 */
    val avatarPath: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[keyAvatarPath]?.takeIf { it.isNotBlank() }
    }

    /** Runtime-injected short-lived token; no token is compiled into the app. */
    val apiToken: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[keyApiToken]?.trim().orEmpty()
    }

    suspend fun setBaseUrl(url: String) {
        context.dataStore.edit { it[keyBaseUrl] = url.trim() }
    }

    suspend fun setDemoMode(enabled: Boolean) {
        context.dataStore.edit { it[keyDemoMode] = enabled }
    }

    suspend fun setUploadConsent(granted: Boolean) {
        context.dataStore.edit { it[keyUploadConsent] = granted }
    }

    suspend fun setBigFont(enabled: Boolean) {
        context.dataStore.edit { it[keyBigFont] = enabled }
    }

    suspend fun setUserName(name: String) {
        context.dataStore.edit { it[keyUserName] = name.trim() }
    }

    suspend fun setAvatarPath(path: String) {
        context.dataStore.edit { it[keyAvatarPath] = path }
    }

    suspend fun setApiToken(token: String) {
        val clean = token.trim()
        context.dataStore.edit { prefs ->
            if (clean.isEmpty()) prefs.remove(keyApiToken) else prefs[keyApiToken] = clean
        }
    }

    companion object {
        val DEFAULT_BASE_URL: String = BuildConfig.DEFAULT_API_BASE
    }
}
