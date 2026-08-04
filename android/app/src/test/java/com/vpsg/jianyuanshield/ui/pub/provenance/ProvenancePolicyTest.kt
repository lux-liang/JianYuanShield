package com.vpsg.jianyuanshield.ui.pub.provenance

import com.vpsg.jianyuanshield.data.remote.dto.PayloadSignature
import com.vpsg.jianyuanshield.data.remote.dto.ProtectResult
import com.vpsg.jianyuanshield.data.remote.dto.VerifyResult
import com.vpsg.jianyuanshield.data.remote.dto.SourceCredentialRef
import com.vpsg.jianyuanshield.data.remote.dto.RevocationResult
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProvenancePolicyTest {
    private val signature = PayloadSignature(
        status = "signed",
        signed = true,
        algorithm = "ed25519",
        signatureBase64 = "test-signature",
        publicKeyFingerprintSha256 = "b".repeat(64),
    )

    @Test
    fun protectionClaimRequiresEveryReleaseGate() {
        val complete = ProtectResult(
            schemaVersion = "provenance-record.v2",
            contentId = "a".repeat(32),
            model = "KAD-Net",
            checkpointSha256 = "c".repeat(64),
            checkpointRegistered = true,
            checkpointCalibrated = true,
            evidenceSignature = signature,
            claimValid = true,
            evidenceStatus = "signed_checkpoint_bound",
            mode = "real_checkpoint",
            resultProvenance = "registered_protection_record",
            creatorIdentityVerified = true,
            sourceCredential = SourceCredentialRef(signatureTrusted = true),
        )
        assertTrue(complete.hasPublishableProtectionClaim())
        assertFalse(complete.copy(schemaVersion = "provenance-record.v1").hasPublishableProtectionClaim())
        assertFalse(complete.copy(creatorIdentityVerified = false).hasPublishableProtectionClaim())
        assertFalse(complete.copy(sourceCredential = SourceCredentialRef()).hasPublishableProtectionClaim())
        assertFalse(complete.copy(checkpointCalibrated = false).hasPublishableProtectionClaim())
        assertFalse(complete.copy(claimValid = false).toPresentation().publishable)
    }

    @Test
    fun verificationClaimRequiresRegisteredBlindVerificationAndMatchingCheckpoint() {
        val complete = VerifyResult(
            schemaVersion = "provenance-verification.v1",
            contentId = "a".repeat(32),
            model = "KAD-Net",
            verified = true,
            checkpointSha256 = "c".repeat(64),
            runtimeCheckpointSha256 = "c".repeat(64),
            checkpointRegistered = true,
            checkpointCalibrated = true,
            parentRecordClaimValid = true,
            evidenceSignature = signature,
            claimValid = true,
            evidenceStatus = "signed_checkpoint_bound",
            mode = "real_checkpoint",
            resultProvenance = "registered_blind_verification",
            sourceLocator = "explicit_content_id",
        )
        assertTrue(complete.hasPublishableVerificationClaim())
        assertFalse(complete.copy(verified = false).hasPublishableVerificationClaim())
        assertFalse(complete.copy(runtimeCheckpointSha256 = "d".repeat(64)).hasPublishableVerificationClaim())
        assertFalse(complete.copy(resultProvenance = "single_request_roundtrip").hasPublishableVerificationClaim())
        assertFalse(complete.copy(parentRecordRevoked = true).hasPublishableVerificationClaim())
        assertFalse(complete.copy(sourceLocator = null).hasPublishableVerificationClaim())
    }

    @Test
    fun revocationPresentationRequiresSignedIrreversibleResponse() {
        val complete = RevocationResult(
            schemaVersion = "provenance-revocation.v1",
            revocationId = "d".repeat(32),
            contentId = "a".repeat(32),
            reasonCode = "creator_request",
            evidenceSignature = signature,
            revoked = true,
            claimValid = false,
        )
        assertTrue(complete.toPresentation().publishable)
        assertFalse(complete.copy(revoked = false).toPresentation().publishable)
        assertFalse(complete.copy(claimValid = true).toPresentation().publishable)
    }

    @Test
    fun publicActionsStayInsideRegisteredProvenanceBoundary() {
        val copy = listOf(
            ProvenanceCopy.SCREEN_TITLE,
            ProvenanceCopy.SCOPE,
            ProvenanceCopy.PROTECT_ACTION,
            ProvenanceCopy.VERIFY_ACTION,
        ).joinToString(" ")
        listOf("验真", "拍照验证", "生成痕迹", "通用检测", "任意图片水印核验").forEach {
            assertFalse(copy.contains(it))
        }
        assertTrue(copy.contains("预登记"))
    }

    @Test
    fun identifiersAndCreatorReferencesValidateFailClosed() {
        assertTrue(isValidContentId("a".repeat(32)))
        assertFalse(isValidContentId("A".repeat(32)))
        assertFalse(isValidContentId("a".repeat(31)))
        assertTrue(isValidCreatorRef("competition-team-01"))
        assertFalse(isValidCreatorRef(""))
        assertFalse(isValidCreatorRef("bad\nref"))
    }
}
