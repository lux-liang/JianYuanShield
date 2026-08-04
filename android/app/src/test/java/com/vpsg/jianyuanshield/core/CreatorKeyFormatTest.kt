package com.vpsg.jianyuanshield.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class CreatorKeyFormatTest {
    @Test
    fun rawEd25519KeyIsWrappedAsRfc8410SubjectPublicKeyInfo() {
        val raw = ByteArray(32) { it.toByte() }
        val der = ed25519SubjectPublicKeyInfo(raw)
        val expectedPrefix = byteArrayOf(
            0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
        )
        assertEquals(44, der.size)
        assertArrayEquals(expectedPrefix, der.copyOfRange(0, 12))
        assertArrayEquals(raw, der.copyOfRange(12, 44))
    }

    @Test
    fun malformedRawKeyFailsClosed() {
        assertThrows(IllegalArgumentException::class.java) {
            ed25519SubjectPublicKeyInfo(ByteArray(31))
        }
    }
}
