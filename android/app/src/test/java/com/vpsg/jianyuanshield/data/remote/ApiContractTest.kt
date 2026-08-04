package com.vpsg.jianyuanshield.data.remote

import com.vpsg.jianyuanshield.data.remote.dto.ComplianceResult
import com.vpsg.jianyuanshield.data.remote.dto.InferResult
import com.vpsg.jianyuanshield.data.remote.dto.NormalizedBenchmark
import com.vpsg.jianyuanshield.data.remote.dto.ModelsStatusResponse
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.SingleBenchmark
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.CreatorChallenge
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test
import retrofit2.http.GET
import retrofit2.http.POST

class ApiContractTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun lidmarkUsesCanonicalBenchmarkRoute() {
        val method = ApiService::class.java.declaredMethods.single {
            it.name == "benchmarkLidmark"
        }
        val route = requireNotNull(method.getAnnotation(GET::class.java))
        assertEquals("api/benchmark/lidmark", route.value)
    }

    @Test
    fun provenanceLifecycleUsesRegisteredProtectAndVerifyRoutes() {
        val protect = ApiService::class.java.declaredMethods.single { it.name == "protectContent" }
        val verify = ApiService::class.java.declaredMethods.single { it.name == "verifyContent" }
        val challenge = ApiService::class.java.declaredMethods.single { it.name == "creatorChallenge" }
        val revoke = ApiService::class.java.declaredMethods.single { it.name == "revokeContent" }
        assertEquals("api/provenance/protect", requireNotNull(protect.getAnnotation(POST::class.java)).value)
        assertEquals("api/provenance/verify", requireNotNull(verify.getAnnotation(POST::class.java)).value)
        assertEquals("api/creator/challenges", requireNotNull(challenge.getAnnotation(POST::class.java)).value)
        assertEquals(
            "api/provenance/records/{content_id}/revoke",
            requireNotNull(revoke.getAnnotation(POST::class.java)).value,
        )
    }

    @Test
    fun missingClaimGateDecodesAsFalse() {
        val result = json.decodeFromString<InferResult>("{}")
        assertFalse(result.claimValid)
    }

    @Test
    fun modelStatusObjectKeepsMetadataAndSelectsOnlyReadyModel() {
        val payload = json.decodeFromString<ModelsStatusResponse>(
            """{
                "schema_version":"model-provenance-status.v1",
                "preferred_model":"LIDMark",
                "LIDMark":{"available":true,"provenance_ready":false},
                "KAD-Net":{
                    "available":true,"registered":true,"calibrated":true,
                    "trusted":true,"provenance_ready":true,
                    "checkpoint_sha256":"${"a".repeat(64)}"
                }
            }""".trimIndent(),
        )

        assertEquals("model-provenance-status.v1", payload.schemaVersion)
        assertFalse(payload.models.getValue("LIDMark").provenanceReady)
        assertEquals(setOf("KAD-Net"), payload.readyModels.keys)
        assertEquals("KAD-Net", payload.safePreferredModel())
    }

    @Test
    fun missingProvenanceReadinessFailsClosed() {
        val payload = json.decodeFromString<ModelsStatusResponse>(
            """{"preferred_model":"KAD-Net","KAD-Net":{"available":true}}""",
        )
        assertNull(payload.safePreferredModel())
    }

    @Test
    fun provenanceClaimFieldsDefaultToFalse() {
        assertFalse(json.decodeFromString<ProtectResult>("{}").claimValid)
        assertFalse(json.decodeFromString<VerifyResult>("{}").claimValid)
        assertFalse(json.decodeFromString<VerifyResult>("{}").verified)
        assertFalse(json.decodeFromString<CreatorChallenge>("{}").serverSignatureTrusted)
        assertFalse(json.decodeFromString<RevocationResult>("{}").revoked)
    }

    @Test
    fun unavailableComplianceStatisticsRemainNull() {
        val result = json.decodeFromString<ComplianceResult>(
            """{"schema_version":"compliance-batch.v2","assessed":0}""",
        )

        assertEquals(0, result.assessed)
        assertNull(result.compliant)
        assertNull(result.degraded)
        assertNull(result.noWatermark)
        assertNull(result.complianceRate)
    }

    @Test
    fun directNormalizedBenchmarkWinsOverCompatibilityNesting() {
        val direct = NormalizedBenchmark(method = "direct")
        val nested = NormalizedBenchmark(method = "nested")
        val payload = SingleBenchmark(
            normalized = direct,
            fullBenchmark = SingleBenchmark(normalized = nested),
        )

        assertSame(direct, payload.resolved())
    }

    @Test
    fun normalizedBenchmarkFallsBackThroughLegacyNesting() {
        val nested = NormalizedBenchmark(method = "nested")
        val payload = SingleBenchmark(
            fullBenchmark = SingleBenchmark(
                smallBenchmark = SingleBenchmark(normalized = nested),
            ),
        )

        assertSame(nested, payload.resolved())
    }
}
