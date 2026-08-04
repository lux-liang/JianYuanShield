package com.vpsg.jianyuanshield.core

import org.junit.Assert.assertEquals
import org.junit.Test

class PresentationFormatTest {
    @Test
    fun unavailableComplianceCountIsNotRenderedAsZero() {
        assertEquals("—", formatNullableCount(null))
        assertEquals("0", formatNullableCount(0))
        assertEquals("7", formatNullableCount(7))
    }

    @Test
    fun artifactUrlJoinsCanonicalApiPathExactlyOnce() {
        assertEquals(
            "https://shield.example/base/api/artifacts/task/result.png",
            absoluteArtifactUrl(
                "https://shield.example/base/",
                "/api/artifacts/task/result.png",
            ),
        )
    }

    @Test
    fun absoluteAndBaseLessArtifactUrlsRemainStable() {
        assertEquals(
            "https://cdn.example/result.png",
            absoluteArtifactUrl("https://shield.example", "https://cdn.example/result.png"),
        )
        assertEquals(
            "/api/artifacts/task/result.png",
            absoluteArtifactUrl("", "/api/artifacts/task/result.png"),
        )
    }
}
