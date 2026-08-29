package com.bulletfeed.app

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import retrofit2.HttpException
import java.io.IOException
import java.net.ServerSocket

class RealBackendAcceptanceTest {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Test
    fun `remote repository session feed exposure and knownness against live backend`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)

            repository.initialize()
            val userId = sessionManager.userId
            assertNotNull(userId)
            assertTrue(userId!!.startsWith("usr_"))

            val seeded = seedStatuspage(baseUrl, userId)
            assertTrue(seeded.projectedItemCount >= 2)
            assertEquals(0, claimExposureCount(baseUrl, userId))

            val firstPage = repository.getFeedPage(cursor = null, limit = 1)
            assertEquals(1, firstPage.items.size)
            val first = firstPage.items.single()
            assertTrue(first.deliveryId.isNotBlank())
            assertTrue(first.eventId.isNotBlank())
            assertTrue(first.title.isNotBlank())
            assertTrue(first.delta.id.isNotBlank())
            assertNotNull(firstPage.nextCursor)
            assertEquals(0, claimExposureCount(baseUrl, userId))

            val secondPage = repository.getFeedPage(cursor = firstPage.nextCursor, limit = 1)
            assertEquals(1, secondPage.items.size)
            assertNotEquals(first.id, secondPage.items.single().id)
            assertNotEquals(first.deliveryId, secondPage.items.single().deliveryId)
            assertEquals(0, claimExposureCount(baseUrl, userId))

            repository.recordExposures(
                listOf(
                    FeedExposure(
                        deliveryId = first.deliveryId,
                        displayedAt = "2026-08-22T00:12:00Z",
                    ),
                ),
            )
            assertTrue(claimExposureCount(baseUrl, userId) > 0)

            assertApiFailureIsProductionError(repository)
            assertNetworkFailureIsProductionError()
        }

    private suspend fun assertApiFailureIsProductionError(repository: RemoteBulletFeedRepository) {
        try {
            repository.getEventDetail("evt_missing_acceptance")
            fail("expected production API error type")
        } catch (error: HttpException) {
            assertEquals(404, error.code())
        }
    }

    private suspend fun assertNetworkFailureIsProductionError() {
        val closedPort = ServerSocket(0).use { it.localPort }
        val deadSession = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
        val deadApi = BulletFeedApiFactory.create("http://127.0.0.1:$closedPort/", deadSession)
        val deadRepository = RemoteBulletFeedRepository(deadApi, deadSession)
        try {
            deadRepository.getFeedPage(limit = 1)
            fail("expected production network error type")
        } catch (error: IOException) {
            assertTrue(error::class.simpleName != null)
        } catch (error: HttpException) {
            assertTrue(error.code() >= 400)
        }
    }

    private fun seedStatuspage(
        baseUrl: String,
        userId: String,
    ): AcceptanceSeedResponse {
        val body = json.encodeToString(AcceptanceSeedRequest.serializer(), AcceptanceSeedRequest(userId))
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/__acceptance__/seed-statuspage")
            .post(body.toRequestBody(JSON_MEDIA))
            .build()
        return executeJson(request, AcceptanceSeedResponse.serializer())
    }

    private fun claimExposureCount(
        baseUrl: String,
        userId: String,
    ): Int {
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/__acceptance__/claim-exposures?userId=$userId")
            .get()
            .build()
        return executeJson(request, AcceptanceExposureCount.serializer()).count
    }

    private fun <T> executeJson(
        request: Request,
        deserializer: kotlinx.serialization.DeserializationStrategy<T>,
    ): T {
        OkHttpClient().newCall(request).execute().use { response ->
            val payload = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                fail("harness ${request.url.encodedPath} failed with HTTP ${response.code}")
            }
            return json.decodeFromString(deserializer, payload)
        }
    }

    @Serializable
    private data class AcceptanceSeedRequest(
        val userId: String,
    )

    @Serializable
    private data class AcceptanceSeedResponse(
        val eventIds: List<String>,
        val projectedItemCount: Int,
    )

    @Serializable
    private data class AcceptanceExposureCount(
        val count: Int,
    )

    private companion object {
        const val BASE_URL_PROPERTY = "bulletfeed.acceptance.baseUrl"
        val JSON_MEDIA = "application/json".toMediaType()
    }
}
