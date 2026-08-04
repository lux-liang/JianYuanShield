package com.vpsg.jianyuanshield.ui.screens.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.container
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import com.vpsg.jianyuanshield.data.settings.SettingsRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class SettingsViewModel(
    private val repository: ShieldRepository,
    private val settings: SettingsRepository,
) : ViewModel() {

    val baseUrl: StateFlow<String> = settings.baseUrl.stateIn(
        scope = viewModelScope,
        started = SharingStarted.Eagerly,
        initialValue = SettingsRepository.DEFAULT_BASE_URL,
    )

    val defaultBaseUrl: String = SettingsRepository.DEFAULT_BASE_URL

    /** Demo mode flag — the whole app serves local mock data when enabled. */
    val demoMode: StateFlow<Boolean> = settings.demoMode.stateIn(
        scope = viewModelScope,
        started = SharingStarted.Eagerly,
        initialValue = false,
    )

    private val _ping = MutableStateFlow<UiState<HealthResponse>>(UiState.Idle)
    val ping: StateFlow<UiState<HealthResponse>> = _ping.asStateFlow()

    fun setDemoMode(enabled: Boolean) {
        viewModelScope.launch { settings.setDemoMode(enabled) }
    }

    /** Persist the URL and immediately verify connectivity. */
    fun saveAndTest(url: String) {
        viewModelScope.launch {
            _ping.value = UiState.Loading
            try {
                repository.saveBaseUrl(url)
                _ping.value = UiState.Success(repository.health())
            } catch (e: Throwable) {
                _ping.value = UiState.Error(e.toUserMessage())
            }
        }
    }

    fun resetToDefault() {
        viewModelScope.launch {
            settings.setBaseUrl(defaultBaseUrl)
            _ping.value = UiState.Idle
        }
    }

    companion object {
        val Factory = viewModelFactory {
            initializer {
                val c = container()
                SettingsViewModel(c.repository, c.settingsRepository)
            }
        }
    }
}
