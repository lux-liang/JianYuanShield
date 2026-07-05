package com.vpsg.jianyuanshield.data.remote

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Rewrites the scheme/host/port of every outgoing request to the user-configured
 * backend URL. Retrofit is built once with a placeholder base URL; the real host
 * can change at runtime (Settings screen) without rebuilding the OkHttp client.
 */
class HostSelectionInterceptor : Interceptor {

    @Volatile
    private var target: HttpUrl? = null

    fun setBaseUrl(url: String) {
        target = url.trim().toHttpUrlOrNull()
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val base = target
        if (base != null) {
            val newUrl = request.url.newBuilder()
                .scheme(base.scheme)
                .host(base.host)
                .port(base.port)
                .build()
            return chain.proceed(request.newBuilder().url(newUrl).build())
        }
        return chain.proceed(request)
    }
}
