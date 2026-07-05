package com.vpsg.jianyuanshield.ui.screens.compliance

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.container
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class ComplianceViewModel(private val repository: ShieldRepository) : ViewModel() {

    private val _result = MutableStateFlow<UiState<ComplianceResult>>(UiState.Idle)
    val result: StateFlow<UiState<ComplianceResult>> = _result.asStateFlow()

    fun run(uris: List<Uri>, modelId: String) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            _result.value = UiState.Loading
            try {
                _result.value = UiState.Success(repository.complianceBatch(uris, modelId))
            } catch (e: Throwable) {
                _result.value = UiState.Error(e.toUserMessage())
            }
        }
    }

    fun reset() {
        _result.value = UiState.Idle
    }

    companion object {
        val Factory = viewModelFactory {
            initializer { ComplianceViewModel(container().repository) }
        }
    }
}
