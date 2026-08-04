package com.vpsg.jianyuanshield.data.remote

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class EndpointPolicyTest {
    @Test
    fun releaseAllowsHttpsOnly() {
        assertEquals("https", validatedBackendUrl("https://api.example.com", false).scheme)
        assertThrows(IllegalArgumentException::class.java) {
            validatedBackendUrl("http://api.example.com", false)
        }
    }

    @Test
    fun debugHttpIsRestrictedToEmulatorHost() {
        assertEquals("10.0.2.2", validatedBackendUrl("http://10.0.2.2:8026", true).host)
        assertThrows(IllegalArgumentException::class.java) {
            validatedBackendUrl("http://192.168.1.10:8026", true)
        }
    }

    @Test
    fun endpointRejectsEmbeddedCredentialsAndQuery() {
        assertThrows(IllegalArgumentException::class.java) {
            validatedBackendUrl("https://user:secret@example.com", false)
        }
        assertThrows(IllegalArgumentException::class.java) {
            validatedBackendUrl("https://example.com?token=secret", false)
        }
    }

    @Test
    fun runtimeTokenValidationRejectsHeaderInjectionAndOversizedValues() {
        assertEquals("short-lived-token", validatedApiToken(" short-lived-token "))
        assertEquals(null, validatedApiToken(""))
        assertThrows(IllegalArgumentException::class.java) {
            validatedApiToken("token\nX-Injected: value")
        }
        assertThrows(IllegalArgumentException::class.java) {
            validatedApiToken("x".repeat(513))
        }
    }
}
