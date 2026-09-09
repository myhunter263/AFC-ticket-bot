package com.hector.logistics

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiFailure(val status: Int, message: String) : IOException(message)

/** Transport only. Authorization, calculations and state transitions belong to the backend. */
class HectorApi(address: String, private val token: String,
                client: OkHttpClient = OkHttpClient()) {
    val base = validatedAddress(address)
    private val http = client.newBuilder().followRedirects(false).followSslRedirects(false)
        .retryOnConnectionFailure(false).callTimeout(120, TimeUnit.SECONDS).build()

    suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): String =
        withContext(Dispatchers.IO) { requestBlocking(path, method, body) }

    internal fun requestBlocking(path: String, method: String = "GET", body: JSONObject? = null): String {
        require(path.startsWith("/api/v1/") && !path.startsWith("//"))
        val request = Request.Builder().url(base + path).header("Authorization", "Bearer $token")
            .method(method, if (method == "GET") null else (body ?: JSONObject()).toString()
                .toRequestBody("application/json; charset=utf-8".toMediaType())).build()
        return http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching { JSONObject(text).opt("detail") }.getOrNull()
                val message = when (response.code) {
                    401 -> "Ключ недействителен или истёк. Войдите заново."
                    403 -> "У вашей роли нет прав на это действие."
                    409 -> "Данные изменились или действие сейчас недоступно. Обновите карточку. ${detail ?: ""}"
                    else -> detail?.toString() ?: "Сервер вернул ошибку ${response.code}"
                }
                throw ApiFailure(response.code, message.take(1000))
            }
            text
        }
    }

    fun events(after: Long, onEvent: (JSONObject) -> Unit, onClosed: () -> Unit): WebSocket =
        http.newWebSocket(Request.Builder().url(base + "/api/v1/events").build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    webSocket.send(JSONObject().put("token", token).put("after", after).toString())
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { JSONObject(text) }.getOrNull()?.let(onEvent)
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = onClosed()
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = onClosed()
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, null)
                }
            })

    companion object {
        fun validatedAddress(address: String): String {
            val url = address.trim().toHttpUrl()
            require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
                url.encodedPath == "/" && url.query == null && url.fragment == null) {
                "Введите HTTPS-адрес сервера без пути, пароля и параметров."
            }
            return url.toString().trimEnd('/')
        }
    }
}

fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key)
fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
fun JSONObject.rows(key: String): List<JSONObject> = optJSONArray(key)?.objects().orEmpty()
fun payload(vararg pairs: Pair<String, Any>): JSONObject = JSONObject().apply {
    pairs.forEach { (key, value) -> put(key, value) }
}
