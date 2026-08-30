package com.bulletfeed.app

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
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

            val telemetry = repository.startFeedSession()
            assertTrue(telemetry.id.startsWith("fs_"))

            repository.recordExposures(
                listOf(
                    FeedExposure(
                        deliveryId = first.deliveryId,
                        displayedAt = "2026-08-22T00:12:00Z",
                        dwellMs = 1_500,
                        visibleRatio = 0.8f,
                    ),
                ),
            )
            assertTrue(claimExposureCount(baseUrl, userId) > 0)

            repository.sendFeedFeedback(first.id, FeedFeedbackType.LEARNED_NOW)
            val metrics = repository.getFeedSessionMetrics()
            assertTrue(metrics.sessionCount >= 1)
            assertTrue(metrics.displayedCount >= 1)
            val ended = repository.endFeedSession(telemetry.id)
            assertEquals(telemetry.id, ended.id)
            val again = repository.endFeedSession(telemetry.id)
            assertEquals(telemetry.id, again.id)
            assertEquals(metrics.sessionCount, repository.getFeedSessionMetrics().sessionCount)

            assertApiFailureIsProductionError(repository)
            assertNetworkFailureIsProductionError()
        }

    @Test
    fun `source recommendations list and decision reach subscription path`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)

            repository.initialize()
            repository.addUserTopic("React", TopicType.TECHNOLOGY)

            val listed = repository.getSourceRecommendations()
            assertTrue(listed.isNotEmpty())
            assertTrue(listed.all { !it.evidenceEligible })
            assertTrue(listed.any { it.reason.isNotBlank() })
            assertTrue(listed.any { it.discoveryProvenance.isNotBlank() })
            assertTrue(listed.any { it.family.isNotBlank() })
            assertTrue(listed.any { it.authorityStatus.isNotBlank() })
            assertTrue(listed.filter { it.discoveryOnly }.all { !it.evidenceEligible })

            val rss = listed.first { it.family == "rss_atom" && !it.discoveryOnly }
            val approved = repository.decideSourceRecommendation(rss.id, SourceRecommendationDecision.APPROVED)
            assertEquals(SourceRecommendationStatus.APPROVED, approved.recommendationStatus)
            val subscriptions = repository.getSourceSubscriptions()
            assertTrue(subscriptions.any { it.canonicalUrl == rss.canonicalUrl && it.kind == "rss_atom" })

            val pending = repository.getSourceRecommendations().first { it.recommendationStatus == SourceRecommendationStatus.PENDING }
            val ignored = repository.decideSourceRecommendation(pending.id, SourceRecommendationDecision.IGNORED)
            assertEquals(SourceRecommendationStatus.IGNORED, ignored.recommendationStatus)
            assertTrue(repository.getSourceRecommendations().none { it.id == pending.id })
        }

    @Test
    fun `source subscription crud creates worker job and delete removes it`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            val userId = sessionManager.userId!!

            try {
                repository.addSourceSubscription(
                    kind = UserSourceKind.RSS_ATOM,
                    url = "https://not-allowed.example/feed.xml",
                )
                fail("expected allowlist rejection")
            } catch (error: HttpException) {
                assertEquals(403, error.code())
            }
            assertTrue(repository.getSourceSubscriptions().isEmpty())

            val created = repository.addSourceSubscription(
                kind = UserSourceKind.STATUSPAGE,
                pageId = "accptest131job",
            )
            assertEquals("statuspage", created.kind)
            assertEquals(SourceSubscriptionState.PENDING, created.state)
            assertEquals("accptest131job", created.pageId)
            assertEquals(1, sourceSyncJobCount(baseUrl, userId, created.kind, "accptest131job"))

            val listed = repository.getSourceSubscriptions()
            assertEquals(1, listed.size)
            assertEquals(created.id, listed.single().id)

            repository.removeSourceSubscription(created.id)
            assertTrue(repository.getSourceSubscriptions().isEmpty())
            assertEquals(0, sourceSyncJobCount(baseUrl, userId, created.kind, "accptest131job"))
        }

    @Test
    fun `topic recommendations are distinct from search and change after follow`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()

            val empty = repository.getTopicRecommendations()
            assertEquals("empty_profile", empty.cohort)
            assertTrue(empty.version.isNotBlank())
            assertTrue(empty.items.isNotEmpty())
            assertTrue(empty.items.all { it.provenance.isNotBlank() && it.reason.isNotBlank() })

            val search = repository.searchTopics("cloud")
            assertTrue(search.none { it.name == empty.version })

            repository.addUserTopic("React", TopicType.TECHNOLOGY)
            val selected = repository.getTopicRecommendations()
            assertEquals("topic_selected", selected.cohort)
            val hide = selected.items.first { !it.alreadyFollowed }
            val afterIgnore = repository.ignoreTopicRecommendation(hide.id)
            assertTrue(afterIgnore.items.none { it.id == hide.id })
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

    private fun sourceSyncJobCount(
        baseUrl: String,
        userId: String,
        sourceType: String,
        sourceKey: String,
    ): Int {
        val url = (baseUrl.trimEnd('/') + "/__acceptance__/source-sync-jobs").toHttpUrl()
            .newBuilder()
            .addQueryParameter("userId", userId)
            .addQueryParameter("sourceType", sourceType)
            .addQueryParameter("sourceKey", sourceKey)
            .build()
        val request = Request.Builder().url(url).get().build()
        return executeJson(request, AcceptanceExposureCount.serializer()).count
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
