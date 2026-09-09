package com.hector.logistics

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** A device-bound key encrypts the personal API token; no credentials ship in the APK. */
class Credentials(context: Context) {
    private val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
    val address: String get() = prefs.getString("address", "https://103.56.84.85:8443")!!
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("hector-login", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("hector-login", KeyProperties.PURPOSE_ENCRYPT or
                KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun load(): String = runCatching {
        val packed = Base64.decode(prefs.getString("token", ""), Base64.NO_WRAP)
        if (packed.size < 29) return ""
        Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, packed.copyOfRange(0, 12)))
            String(doFinal(packed.copyOfRange(12, packed.size)), Charsets.UTF_8)
        }
    }.getOrDefault("")
    fun save(address: String, token: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encoded = Base64.encodeToString(cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
        prefs.edit().putString("address", address).putString("token", encoded).apply()
    }
    fun clear() { prefs.edit().remove("token").apply() }
}
