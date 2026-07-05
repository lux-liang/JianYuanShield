package com.vpsg.jianyuanshield.data.remote

import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelState
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part

/**
 * Retrofit binding for the JianYuanShield FastAPI backend.
 * Paths are relative; the absolute host is injected by [HostSelectionInterceptor].
 */
interface ApiService {

    @GET("api/health")
    suspend fun health(): HealthResponse

    @GET("api/models/status")
    suspend fun modelsStatus(): Map<String, ModelState>

    @GET("api/modules")
    suspend fun modules(): List<ModuleInfo>

    @Multipart
    @POST("api/infer/single")
    suspend fun inferSingle(
        @Part file: MultipartBody.Part,
        @Part("model") model: RequestBody,
        @Part("attack") attack: RequestBody,
        @Part("return_b64") returnB64: RequestBody,
    ): InferResult

    @Multipart
    @POST("api/compliance/batch")
    suspend fun complianceBatch(
        @Part files: List<MultipartBody.Part>,
        @Part("model") model: RequestBody,
    ): ComplianceResult

    @GET("api/evidence/audit")
    suspend fun evidenceAudit(): EvidenceAudit

    /** 平台证据包 Ed25519 签名状态(用于凭证页展示"平台签名已验证")。 */
    @GET("api/evidence/signature")
    suspend fun evidenceSignature(): Signature

    @GET("api/benchmark/sepmark")
    suspend fun benchmarkSepmark(): SingleBenchmark

    @GET("api/benchmark/lidmark-lfw-eval")
    suspend fun benchmarkLidmark(): SingleBenchmark

    @GET("api/benchmark/waveguard")
    suspend fun benchmarkWaveguard(): SingleBenchmark

    @GET("api/benchmark/kadnet")
    suspend fun benchmarkKadnet(): SingleBenchmark
}
