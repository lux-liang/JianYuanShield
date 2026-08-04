package com.vpsg.jianyuanshield.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.google.crypto.tink.subtle.Ed25519Sign
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class CreatorKeyIdentity(
    val publicKeyPem: String,
    val fingerprintSha256: String,
)

/**
 * Device-held creator signing key. Tink provides the Ed25519 primitive across
 * API 26+, while Android Keystore protects the AES-GCM wrapping key. The
 * private Ed25519 bytes are never returned to the UI or network layer.
 */
class CreatorKeyManager(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    @Synchronized
    fun identity(): CreatorKeyIdentity {
        val pair = loadOrCreate()
        val der = ed25519SubjectPublicKeyInfo(pair.publicKey)
        return CreatorKeyIdentity(
            publicKeyPem = pemPublicKey(der),
            fingerprintSha256 = sha256Hex(der),
        )
    }

    @Synchronized
    fun sign(message: ByteArray): ByteArray = Ed25519Sign(loadOrCreate().privateKey).sign(message)

    private fun loadOrCreate(): StoredPair {
        val encrypted = prefs.getString(KEY_PRIVATE, null)
        val iv = prefs.getString(KEY_IV, null)
        val public = prefs.getString(KEY_PUBLIC, null)
        if (encrypted != null || iv != null || public != null) {
            require(encrypted != null && iv != null && public != null) {
                "创作者签名密钥存储不完整，请清除应用数据后重新登记"
            }
            val privateBytes = decrypt(
                Base64.decode(encrypted, Base64.NO_WRAP),
                Base64.decode(iv, Base64.NO_WRAP),
            )
            val publicBytes = Base64.decode(public, Base64.NO_WRAP)
            require(privateBytes.size == 32 && publicBytes.size == 32) {
                "创作者签名密钥格式无效"
            }
            return StoredPair(privateBytes, publicBytes)
        }

        val generated = Ed25519Sign.KeyPair.newKeyPair()
        val wrapped = encrypt(generated.privateKey)
        val committed = prefs.edit()
            .putString(KEY_PRIVATE, Base64.encodeToString(wrapped.ciphertext, Base64.NO_WRAP))
            .putString(KEY_IV, Base64.encodeToString(wrapped.iv, Base64.NO_WRAP))
            .putString(KEY_PUBLIC, Base64.encodeToString(generated.publicKey, Base64.NO_WRAP))
            .commit()
        check(committed) { "无法持久化创作者签名密钥" }
        return StoredPair(generated.privateKey, generated.publicKey)
    }

    private fun wrappingKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(MASTER_KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                MASTER_KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encrypt(plain: ByteArray): Wrapped {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey())
        cipher.updateAAD(AAD)
        return Wrapped(cipher.doFinal(plain), cipher.iv)
    }

    private fun decrypt(ciphertext: ByteArray, iv: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, wrappingKey(), GCMParameterSpec(128, iv))
        cipher.updateAAD(AAD)
        return cipher.doFinal(ciphertext)
    }

    private data class StoredPair(val privateKey: ByteArray, val publicKey: ByteArray)
    private data class Wrapped(val ciphertext: ByteArray, val iv: ByteArray)

    companion object {
        private const val PREFS_NAME = "jys_creator_identity_secure"
        private const val KEY_PRIVATE = "encrypted_private"
        private const val KEY_IV = "iv"
        private const val KEY_PUBLIC = "public"
        private const val MASTER_KEY_ALIAS = "jys_creator_identity_wrap_v1"
        private val AAD = "jianyuanshield.creator.ed25519.v1".toByteArray(Charsets.UTF_8)
    }
}

/** RFC 8410 SubjectPublicKeyInfo prefix for a raw 32-byte Ed25519 public key. */
fun ed25519SubjectPublicKeyInfo(rawPublicKey: ByteArray): ByteArray {
    require(rawPublicKey.size == 32) { "Ed25519 public key must be 32 bytes" }
    val prefix = byteArrayOf(
        0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
    )
    return prefix + rawPublicKey
}

private fun pemPublicKey(der: ByteArray): String {
    val body = Base64.encodeToString(der, Base64.NO_WRAP).chunked(64).joinToString("\n")
    return "-----BEGIN PUBLIC KEY-----\n$body\n-----END PUBLIC KEY-----\n"
}

private fun sha256Hex(data: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(data)
        .joinToString("") { "%02x".format(it.toInt() and 0xff) }
