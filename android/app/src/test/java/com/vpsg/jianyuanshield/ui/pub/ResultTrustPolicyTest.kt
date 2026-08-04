package com.vpsg.jianyuanshield.ui.pub

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ResultTrustPolicyTest {
    @Test
    fun registeredRealVerificationCanIssueCertificate() {
        val state = evaluateResultTrust(
            claimValid = true,
            mode = "real_checkpoint",
            localDemo = false,
            resultProvenance = "registered_blind_verification",
        )

        assertFalse(state.isSimulation)
        assertTrue(state.canIssueCertificate)
        assertEquals("登记盲检结果 · 已通过声明门禁", state.statusLabel)
    }

    @Test
    fun everyUntrustedCombinationFailsClosed() {
        val cases = listOf(
            evaluateResultTrust(false, "real_checkpoint", false, "registered_blind_verification"),
            evaluateResultTrust(true, "demo_simulation", false, "registered_blind_verification"),
            evaluateResultTrust(true, null, false, "registered_blind_verification"),
            evaluateResultTrust(true, "real_checkpoint", true, "registered_blind_verification"),
            evaluateResultTrust(true, "real_checkpoint", false, "checkpoint_single_sample_evaluation"),
            evaluateResultTrust(true, "real_checkpoint", false, null),
        )

        cases.forEach { state -> assertFalse(state.canIssueCertificate) }
    }

    @Test
    fun displayStateDistinguishesSimulationClaimAndProvenanceFailures() {
        assertEquals(
            "本地流程演示 · 不可作为结论",
            evaluateResultTrust(true, "real_checkpoint", true, "registered_blind_verification").statusLabel,
        )
        assertEquals(
            "服务器流程模拟 · 不可作为结论",
            evaluateResultTrust(true, "demo_simulation", false, "registered_blind_verification").statusLabel,
        )
        assertEquals(
            "未通过声明门禁 · 结果不可发布",
            evaluateResultTrust(false, "real_checkpoint", false, "registered_blind_verification").statusLabel,
        )
        assertEquals(
            "非登记盲检结果 · 不可生成凭证",
            evaluateResultTrust(true, "real_checkpoint", false, "checkpoint_single_sample_evaluation").statusLabel,
        )
    }
}
