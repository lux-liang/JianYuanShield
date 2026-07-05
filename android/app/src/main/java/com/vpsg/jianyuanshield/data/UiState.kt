package com.vpsg.jianyuanshield.data

/**
 * Generic screen state for one-shot or refreshable data loads.
 */
sealed interface UiState<out T> {
    /** Nothing requested yet (e.g. user hasn't picked an image). */
    data object Idle : UiState<Nothing>

    /** Request in flight. */
    data object Loading : UiState<Nothing>

    data class Success<T>(val data: T) : UiState<T>

    data class Error(val message: String) : UiState<Nothing>
}

inline fun <T> UiState<T>.onSuccess(block: (T) -> Unit): UiState<T> {
    if (this is UiState.Success) block(data)
    return this
}
