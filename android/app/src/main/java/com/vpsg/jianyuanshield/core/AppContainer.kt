package com.vpsg.jianyuanshield.core

import android.content.Context
import com.vpsg.jianyuanshield.data.history.HistoryStore
import com.vpsg.jianyuanshield.data.remote.HostSelectionInterceptor
import com.vpsg.jianyuanshield.data.remote.ApiAuthInterceptor
import com.vpsg.jianyuanshield.data.remote.NetworkModule
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import com.vpsg.jianyuanshield.data.settings.SettingsRepository

/**
 * Lightweight manual dependency container, held by the Application. Avoids a DI
 * framework while keeping a single shared instance of each dependency.
 */
class AppContainer(context: Context) {

    private val appContext = context.applicationContext

    private val hostInterceptor = HostSelectionInterceptor()
    private val authInterceptor = ApiAuthInterceptor()

    val settingsRepository: SettingsRepository = SettingsRepository(appContext)
    val creatorKeyManager: CreatorKeyManager = CreatorKeyManager(appContext)

    /** 鉴别历史(落盘 JSON)。 */
    val historyStore: HistoryStore = HistoryStore(appContext)

    private val apiService = NetworkModule.createApi(hostInterceptor, authInterceptor)

    val repository: ShieldRepository = ShieldRepository(
        appContext = appContext,
        api = apiService,
        settings = settingsRepository,
        hostInterceptor = hostInterceptor,
        authInterceptor = authInterceptor,
    )

    /** Prime the interceptor synchronously with the default so the first
     *  request always has a valid host even before settings flow emits. */
    init {
        hostInterceptor.setBaseUrl(SettingsRepository.DEFAULT_BASE_URL)
    }
}
