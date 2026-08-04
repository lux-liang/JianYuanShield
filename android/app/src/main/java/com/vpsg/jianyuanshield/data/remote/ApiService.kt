package com.vpsg.jianyuanshield.data.remote

import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.EvidenceAudit
import com.vpsg.jianyuanshield.data.remote.dto.HealthResponse
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.data.remote.dto.ModuleInfo
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.Signature
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.CreatorChallenge
import com.vpsg.jianyuanshield.data.remote.dto.RevocationIntent
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.Field
import retrofit2.http.FormUrlEncoded
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path

/**
 * Retrofit binding for the JianYuanShield FastAPI backend.
 * Paths are relative; the absolute host is injected by [HostSelectionInterceptor].
 */
interface ApiService {

    @GET("api/health")
    suspend fun health(): HealthResponse

    @GET("api/models/status")
    suspend fun modelsStatus(): ModelsStatusResponse

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
    @POST("api/provenance/protect")
    suspend fun protectContent(
        @Part file: MultipartBody.Part,
        @Part("creator_ref") creatorRef: RequestBody,
        @Part("model") model: RequestBody,
        @Part("challenge_id") challengeId: RequestBody,
        @Part("creator_signature_base64") creatorSignatureBase64: RequestBody,
    ): ProtectResult

    @FormUrlEncoded
    @POST("api/creator/challenges")
    suspend fun creatorChallenge(
        @Field("creator_public_key_pem") creatorPublicKeyPem: String,
        @Field("creator_ref") creatorRef: String,
        @Field("model") model: String,
        @Field("image_sha256") imageSha256: String,
    ): CreatorChallenge

    @Multipart
    @POST("api/provenance/verify")
    suspend fun verifyContent(
        @Part file: MultipartBody.Part,
        @Part("content_id") contentId: RequestBody?,
        @Part sourceCredential: MultipartBody.Part?,
    ): VerifyResult

    @FormUrlEncoded
    @POST("api/provenance/records/{content_id}/revocation-intents")
    suspend fun revocationIntent(
        @Path("content_id") contentId: String,
        @Field("reason_code") reasonCode: String,
    ): RevocationIntent

    @FormUrlEncoded
    @POST("api/provenance/records/{content_id}/revoke")
    suspend fun revokeContent(
        @Path("content_id") contentId: String,
        @Field("intent_id") intentId: String,
        @Field("creator_signature_base64") creatorSignatureBase64: String,
    ): RevocationResult

    @Multipart
    @POST("api/compliance/batch")
    suspend fun complianceBatch(
        @Part files: List<MultipartBody.Part>,
        @Part("model") model: RequestBody,
    ): ComplianceResult

    @GET("api/evidence/audit")
    suspend fun evidenceAudit(): EvidenceAudit

    /** 平台证据包 Ed25519 密码学校验状态；不等于现实身份或可信时间证明。 */
    @GET("api/evidence/signature")
    suspend fun evidenceSignature(): Signature

    @GET("api/benchmark/sepmark")
    suspend fun benchmarkSepmark(): SingleBenchmark

    @GET("api/benchmark/lidmark")
    suspend fun benchmarkLidmark(): SingleBenchmark

    @GET("api/benchmark/waveguard")
    suspend fun benchmarkWaveguard(): SingleBenchmark

    @GET("api/benchmark/kadnet")
    suspend fun benchmarkKadnet(): SingleBenchmark
}
