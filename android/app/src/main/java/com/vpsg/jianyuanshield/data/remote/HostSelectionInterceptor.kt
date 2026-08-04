package com.vpsg.jianyuanshield.data.remote

import com.vpsg.jianyuanshield.BuildConfig
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
        target = validatedBackendUrl(url, BuildConfig.DEBUG)
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

/**
 * Release builds accept HTTPS only. Debug additionally accepts the Android
 * emulator host 10.0.2.2 over HTTP; credentials, query and fragments are
 * rejected because the value is a service origin, not an arbitrary URL.
 */
fun validatedBackendUrl(raw: String, debugBuild: Boolean): HttpUrl {
    val parsed = raw.trim().toHttpUrlOrNull()
        ?: throw IllegalArgumentException("服务节点地址格式无效")
    val debugHttp = debugBuild && parsed.scheme == "http" && parsed.host == "10.0.2.2"
    if (parsed.scheme != "https" && !debugHttp) {
        throw IllegalArgumentException("正式连接必须使用 HTTPS")
    }
    if (parsed.username.isNotEmpty() || parsed.password.isNotEmpty()) {
        throw IllegalArgumentException("服务节点地址不得包含账号或密码")
    }
    if (parsed.query != null || parsed.fragment != null) {
        throw IllegalArgumentException("服务节点地址不得包含查询参数或片段")
    }
    return parsed
}
