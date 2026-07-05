package com.vpsg.jianyuanshield.core

import com.vpsg.jianyuanshield.data.remote.NetworkModule
import com.vpsg.jianyuanshield.data.remote.dto.ApiErrorEnvelope
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.decodeFromString
import retrofit2.HttpException
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Maps low-level exceptions to friendly, user-facing Chinese messages.
 * Parses the backend's unified error envelope when present.
 */
fun Throwable.toUserMessage(): String = when (this) {
    // Never convert cancellation into a user-visible error — re-throw so coroutine
    // cancellation stays cooperative (e.g. a superseded or scope-cleared request).
    is CancellationException -> throw this
    is HttpException -> parseHttpError(this)
    is SocketTimeoutException -> "请求超时，服务节点处理较慢或网络不稳定，请重试。"
    is ConnectException -> "无法连接可信服务节点，请在「设置」中检查服务节点地址与连接状态。"
    is UnknownHostException -> "找不到服务节点主机，请确认服务节点地址是否正确。"
    is IOException -> "网络异常：${message ?: "请检查网络连接"}"
    else -> message ?: "未知错误"
}

private fun parseHttpError(e: HttpException): String {
    val raw = runCatching { e.response()?.errorBody()?.string() }.getOrNull()
    val parsed = raw?.let {
        runCatching { NetworkModule.json.decodeFromString<ApiErrorEnvelope>(it) }.getOrNull()
    }
    val msg = parsed?.error?.message
    return if (!msg.isNullOrBlank()) {
        "服务端错误（${e.code()}）：$msg"
    } else {
        "服务端错误（HTTP ${e.code()}）"
    }
}
