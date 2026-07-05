package com.vpsg.jianyuanshield.ui.screens.evidence

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.container
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class EvidenceViewModel(private val repository: ShieldRepository) : ViewModel() {

    private val _state = MutableStateFlow<UiState<EvidenceAudit>>(UiState.Loading)
    val state: StateFlow<UiState<EvidenceAudit>> = _state.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = UiState.Loading
            try {
                _state.value = UiState.Success(repository.evidenceAudit())
            } catch (e: Throwable) {
                _state.value = UiState.Error(e.toUserMessage())
            }
        }
    }

    /** Pull-to-refresh — keeps existing content visible while reloading. */
    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            try {
                _state.value = UiState.Success(repository.evidenceAudit())
            } catch (e: Throwable) {
                if (_state.value !is UiState.Success) _state.value = UiState.Error(e.toUserMessage())
            } finally {
                _refreshing.value = false
            }
        }
    }

    companion object {
        val Factory = viewModelFactory {
            initializer { EvidenceViewModel(container().repository) }
        }
    }
}
