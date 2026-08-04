package com.vpsg.jianyuanshield.ui.screens.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.container
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.ModelState
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

data class HomeData(
    val baseUrl: String,
    val health: HealthResponse?,
    val models: Map<String, ModelState>,
    val modules: List<ModuleInfo>,
)

class HomeViewModel(private val repository: ShieldRepository) : ViewModel() {

    private val _state = MutableStateFlow<UiState<HomeData>>(UiState.Loading)
    val state: StateFlow<UiState<HomeData>> = _state.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    init {
        load()
    }

    // Home degrades gracefully: each call is independent and may fail (e.g. backend
    // offline) without blocking the rest of the screen. The calls run in PARALLEL —
    // on an unreachable host the screen waits one connect-timeout, not three.
    private suspend fun fetch(): HomeData = coroutineScope {
        val base = async { runCatching { repository.baseUrl.first() }.getOrDefault("") }
        val health = async { runCatching { repository.health() }.getOrNull() }
        val models = async { runCatching { repository.modelsStatus().models }.getOrElse { emptyMap() } }
        val modules = async { runCatching { repository.modules() }.getOrElse { emptyList() } }
        HomeData(base.await(), health.await(), models.await(), modules.await())
    }

    /** Initial load — shows the full-screen loading state. */
    fun load() {
        viewModelScope.launch {
            _state.value = UiState.Loading
            _state.value = UiState.Success(fetch())
        }
    }

    /** Pull-to-refresh / manual refresh — keeps current content visible while reloading. */
    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            _state.value = UiState.Success(fetch())
            _refreshing.value = false
        }
    }

    companion object {
        val Factory = viewModelFactory {
            initializer { HomeViewModel(container().repository) }
        }
    }
}
