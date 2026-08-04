package com.vpsg.jianyuanshield.data.remote

import okhttp3.Interceptor
import okhttp3.Response

/**
 * Injects a user/deployment supplied short-lived API token at request time.
 * There is deliberately no compiled-in fallback. A caller-supplied header is
 * removed first so only the current runtime setting can authorize a request.
 */
class ApiAuthInterceptor : Interceptor {
    @Volatile
    private var token: String? = null

    fun setToken(value: String?) {
        token = validatedApiToken(value)
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder().removeHeader(API_KEY_HEADER)
        token?.let { builder.header(API_KEY_HEADER, it) }
        return chain.proceed(builder.build())
    }

    companion object {
        const val API_KEY_HEADER = "X-API-Key"
    }
}

fun validatedApiToken(raw: String?): String? {
    val clean = raw?.trim().orEmpty()
    if (clean.isEmpty()) return null
    require(clean.length <= 512 && clean.all { !it.isWhitespace() && !it.isISOControl() }) {
        "API Token 格式无效"
    }
    return clean
}
