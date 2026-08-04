package com.vpsg.jianyuanshield.data.remote

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.vpsg.jianyuanshield.BuildConfig
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

/**
 * Builds the singleton [ApiService]. The base URL is a placeholder — actual
 * routing is handled by [HostSelectionInterceptor].
 */
object NetworkModule {

    val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
        isLenient = true
    }

    fun createApi(
        hostInterceptor: HostSelectionInterceptor,
        authInterceptor: ApiAuthInterceptor,
    ): ApiService {
        val logging = HttpLoggingInterceptor().apply {
            redactHeader(ApiAuthInterceptor.API_KEY_HEADER)
            level = if (BuildConfig.DEBUG) {
                HttpLoggingInterceptor.Level.BASIC
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
        }

        val client = OkHttpClient.Builder()
            .addInterceptor(hostInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(logging)
            // API origins must not be allowed to redirect a runtime token to a
            // different host. The configured service must return final URLs.
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .writeTimeout(90, TimeUnit.SECONDS)
            .build()

        val contentType = "application/json".toMediaType()
        return Retrofit.Builder()
            // The interceptor normally replaces this host. Keep the fallback HTTPS
            // and non-routable so a missing/invalid runtime URL fails closed.
            .baseUrl("https://jianyuanshield.invalid/")
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
            .create(ApiService::class.java)
    }
}
