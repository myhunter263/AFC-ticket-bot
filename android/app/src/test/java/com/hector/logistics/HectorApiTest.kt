package com.hector.logistics

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.IOException
import java.net.InetAddress
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class HectorApiTest {
    private fun server(): Pair<MockWebServer, OkHttpClient> {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").build()
        val serverTls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        val server = MockWebServer().apply {
            useHttps(serverTls.sslSocketFactory(), false)
            start(InetAddress.getByAddress("localhost", byteArrayOf(127, 0, 0, 1)), 0)
        }
        return server to OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager).build()
    }

    @Test fun rejectsInsecureOrAmbiguousAddresses() {
        listOf("http://example.com", "https://user:pass@example.com", "https://example.com/api",
            "https://example.com/?token=x", "https://example.com/#token").forEach {
            assertThrows(IllegalArgumentException::class.java) { HectorApi.validatedAddress(it) }
        }
        assertEquals("https://103.56.84.85:8443", HectorApi.validatedAddress(" https://103.56.84.85:8443/ "))
    }

    @Test fun sendsPersonalTokenInHeaderAndVersionInBody() {
        val (server, client) = server()
        server.use {
            server.enqueue(MockResponse().setBody("{\"version\":3}"))
            val api = HectorApi(server.url("/").newBuilder().host("localhost").build().toString(), "test-personal-key", client)
            api.requestBlocking("/api/v1/orders/7/accept", "POST", payload("version" to 2))
            val request = server.takeRequest()
            assertEquals("Bearer test-personal-key", request.getHeader("Authorization"))
            assertEquals("/api/v1/orders/7/accept", request.path)
            assertEquals("{\"version\":2}", request.body.readUtf8())
        }
    }

    @Test fun neverFollowsRedirectWithPersonalToken() {
        val (server, client) = server()
        server.use {
            server.enqueue(MockResponse().setResponseCode(307).addHeader("Location", server.url("/unexpected")))
            server.enqueue(MockResponse().setBody("{}"))
            val api = HectorApi(server.url("/").newBuilder().host("localhost").build().toString(), "test-personal-key", client)
            val error = assertThrows(ApiFailure::class.java) { api.requestBlocking("/api/v1/me") }
            assertEquals(307, error.status)
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun conflictDoesNotRetryAMutation() {
        val (server, client) = server()
        server.use {
            server.enqueue(MockResponse().setResponseCode(409).setBody("{\"detail\":\"Version conflict\"}"))
            val api = HectorApi(server.url("/").newBuilder().host("localhost").build().toString(), "test-personal-key", client)
            val error = assertThrows(ApiFailure::class.java) {
                api.requestBlocking("/api/v1/production/tasks/1", "POST", payload("version" to 1, "action" to "claim"))
            }
            assertEquals(409, error.status)
            assertTrue(error.message!!.contains("Обновите"))
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun doesNotTrustAnUnknownCertificate() {
        val (server, _) = server()
        server.use {
            val api = HectorApi(server.url("/").newBuilder().host("localhost").build().toString(), "test-personal-key")
            assertThrows(IOException::class.java) { api.requestBlocking("/api/v1/me") }
        }
    }

    @Test fun websocketAuthenticatesInFirstFrameAndKeepsTokenOutOfUrl() {
        val (server, client) = server()
        server.use {
            val received = CountDownLatch(1)
            val frame = AtomicReference<String>()
            server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    frame.set(text); received.countDown(); webSocket.close(1000, null)
                }
            }))
            val api = HectorApi(server.url("/").newBuilder().host("localhost").build().toString(), "test-personal-key", client)
            val socket = api.events(42, {}, {})
            try {
                assertTrue(received.await(10, TimeUnit.SECONDS))
                val request = server.takeRequest()
                assertEquals("/api/v1/events", request.path)
                assertNull(request.getHeader("Authorization"))
                assertEquals("test-personal-key", JSONObject(frame.get()).getString("token"))
                assertEquals(42, JSONObject(frame.get()).getInt("after"))
            } finally { socket.cancel() }
        }
    }
}
