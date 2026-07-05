package com.vpsg.jianyuanshield.ui.screens.infer

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.vpsg.jianyuanshield.core.container
import com.vpsg.jianyuanshield.core.toUserMessage
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.repository.ShieldRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

data class InferUi(
    val result: InferResult,
    val baseUrl: String,
)

class InferViewModel(private val repository: ShieldRepository) : ViewModel() {

    private val _result = MutableStateFlow<UiState<InferUi>>(UiState.Idle)
    val result: StateFlow<UiState<InferUi>> = _result.asStateFlow()

    fun run(uri: Uri, modelId: String, attackId: String) {
        viewModelScope.launch {
            _result.value = UiState.Loading
            try {
                val base = repository.baseUrl.first()
                val res = repository.inferSingle(uri, modelId, attackId)
                _result.value = UiState.Success(InferUi(res, base))
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
            initializer { InferViewModel(container().repository) }
        }
    }
}
