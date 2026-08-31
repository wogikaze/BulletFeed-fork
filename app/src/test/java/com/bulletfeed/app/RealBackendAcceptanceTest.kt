package com.bulletfeed.app

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
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
    fun `unauthenticated feed is session expiry not offline`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            try {
                repository.getFeedPage(limit = 1)
                fail("expected unauthorized feed")
            } catch (error: HttpException) {
                assertEquals(401, error.code())
                val recovered = readyUiState().reduceRootFailure(error)
                assertTrue(recovered.sessionExpired)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.events.isEmpty())
                assertNull(recovered.errorMessage)
            }
        }

    @Test
    fun `worker-not-ready is not classified as offline`() {
        val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
        assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/health/ready")
            .get()
            .build()
        OkHttpClient().newCall(request).execute().use { response ->
            val payload = response.body?.string().orEmpty()
            when (response.code) {
                200 -> assertTrue("ready body was blank: HTTP 200", payload.isNotBlank())
                503 -> {
                    val recovered = readyUiState().reduceRootFailure(
                        HttpException(
                            Response.error<Any>(
                                503,
                                payload.toResponseBody("application/json".toMediaType()),
                            ),
                        ),
                    )
                    assertFalse("503 must not look like offline: $payload", recovered.isOffline)
                    assertTrue(recovered.hasStaleFeed)
                    assertFalse(recovered.sessionExpired)
                    val message = recovered.errorMessage.orEmpty()
                    assertTrue(
                        "expected worker/database/server message, got $message for $payload",
                        "ワーカー" in message || "データベース" in message || "サーバー" in message,
                    )
                }
                else -> fail("unexpected /health/ready HTTP ${response.code}: $payload")
            }
        }
    }

    @Test
    fun `live feed still works after closed-port offline classification`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            val userId = sessionManager.userId!!
            seedStatuspage(baseUrl, userId)

            val before = repository.getFeedPage(limit = 1)
            assertTrue(before.items.isNotEmpty())
            assertTrue(before.items.first().id.isNotBlank())

            assertNetworkFailureIsProductionError()

            val after = repository.getFeedPage(limit = 1)
            assertTrue(after.items.isNotEmpty())
            assertTrue(after.items.first().id.isNotBlank())
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
                val recovered = readyUiState().reduceRootFailure(error)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.hasStaleFeed)
                assertFalse(recovered.sessionExpired)
                assertTrue(
                    recovered.errorMessage?.contains("許可") == true ||
                        recovered.errorMessage?.contains("アクセス権") == true,
                )
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

            val web = repository.addSourceSubscription(
                kind = UserSourceKind.GENERIC_WEB,
                url = "https://react.dev/learn",
            )
            assertEquals("generic_web", web.kind)
            assertEquals(
                1,
                sourceSyncJobCount(baseUrl, userId, web.kind, "https://react.dev/learn"),
            )
            assertTrue(repository.getSourceSubscriptions().any { it.id == web.id })

            repository.removeSourceSubscription(web.id)
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

    @Test
    fun `duplicate topic is conflict not offline`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            repository.addUserTopic("React", TopicType.TECHNOLOGY)
            try {
                repository.addUserTopic("React", TopicType.TECHNOLOGY)
                fail("expected duplicate topic conflict")
            } catch (error: HttpException) {
                assertEquals(409, error.code())
                val recovered = readyUiState().reduceRootFailure(error)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.hasStaleFeed)
                assertFalse(recovered.sessionExpired)
                assertTrue(recovered.errorMessage?.contains("すでに追跡中") == true)
            }
        }

    @Test
    fun `invalid statuspage id is validation not offline`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            try {
                repository.addSourceSubscription(
                    kind = UserSourceKind.STATUSPAGE,
                    pageId = "not-a-valid-id",
                )
                fail("expected invalid Statuspage ID")
            } catch (error: HttpException) {
                assertEquals(422, error.code())
                val recovered = readyUiState().reduceRootFailure(error)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.hasStaleFeed)
                assertFalse(recovered.sessionExpired)
                assertTrue(recovered.errorMessage?.contains("page ID") == true)
            }
        }

    @Test
    fun `statuspage without page id or url is validation not offline`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            try {
                repository.addSourceSubscription(
                    kind = UserSourceKind.STATUSPAGE,
                    url = null,
                    pageId = null,
                )
                fail("expected Statuspage pageId or url")
            } catch (error: HttpException) {
                assertEquals(422, error.code())
                val recovered = readyUiState().reduceRootFailure(error)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.hasStaleFeed)
                assertFalse(recovered.sessionExpired)
                assertTrue(recovered.errorMessage?.contains("page ID または URL") == true)
            }
        }

    @Test
    fun `rss without url is validation not offline`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            try {
                repository.addSourceSubscription(
                    kind = UserSourceKind.RSS_ATOM,
                    url = null,
                )
                fail("expected url is required")
            } catch (error: HttpException) {
                assertEquals(422, error.code())
                val recovered = readyUiState().reduceRootFailure(error)
                assertFalse(recovered.isOffline)
                assertTrue(recovered.hasStaleFeed)
                assertFalse(recovered.sessionExpired)
                assertTrue(recovered.errorMessage?.contains("URLを入力") == true)
            }
        }

    @Test
    fun `knowledge bootstrap from current state suppresses known feed restatements`() =
        runTest {
            val baseUrl = System.getProperty(BASE_URL_PROPERTY).orEmpty().trim()
            assumeTrue("Set $BASE_URL_PROPERTY to a local FastAPI harness", baseUrl.isNotEmpty())

            val sessionManager = SessionManager(InMemorySecretStore(), InMemorySessionPreferenceStore())
            val api = BulletFeedApiFactory.create(baseUrl, sessionManager)
            val repository = RemoteBulletFeedRepository(api, sessionManager)
            repository.initialize()
            val userId = sessionManager.userId!!

            val seeded = seedStatuspage(baseUrl, userId)
            assertTrue(seeded.eventIds.isNotEmpty())
            val eventId = seeded.eventIds.first()

            val before = repository.getFeedPage(cursor = null, limit = 20)
            assertTrue(before.items.any { it.eventId == eventId })

            val empty = repository.getKnowledgeBootstrap()
            assertEquals(0, empty.explicitKnownFactCount)
            assertEquals(0, empty.inferredFactCount)

            val checkpoint = repository.recordKnowledgeCheckpoint(
                subjectKind = BootstrapSubjectKind.EVENT,
                subjectId = eventId,
                catchUp = false,
            )
            assertEquals(false, checkpoint.catchUp)
            assertTrue(checkpoint.knownFactCount > 0)

            val catchUpOnly = repository.recordKnowledgeCheckpoint(
                subjectKind = BootstrapSubjectKind.TOPIC,
                subjectId = "React",
                catchUp = true,
            )
            assertTrue(catchUpOnly.catchUp)
            assertEquals(0, catchUpOnly.knownFactCount)

            val summary = repository.getKnowledgeBootstrap()
            assertTrue(summary.checkpoints.any { it.subjectKind == BootstrapSubjectKind.EVENT && !it.catchUp })
            assertTrue(summary.checkpoints.any { it.catchUp && it.knownFactCount == 0 })
            assertEquals(0, summary.inferredFactCount)
            assertTrue(summary.evidence.none { it.kind.contains("claim_id", ignoreCase = true) })

            val exposuresBefore = claimExposureCount(baseUrl, userId)
            val knownness = bootstrapKnownness(baseUrl, userId, eventId)
            assertTrue(
                "bootstrap should mark current-state claims known: $knownness",
                knownness.any { it.state == "known" },
            )
            assertTrue(
                "low-confidence inferred bootstrap must not hard-hide: $knownness",
                knownness.none { it.state == "probably_known" && it.action == "hide" },
            )
            assertEquals(
                "GET /feed and bootstrap must not write delivery knownness",
                exposuresBefore,
                claimExposureCount(baseUrl, userId),
            )

            val after = repository.getFeedPage(cursor = null, limit = 20)
            assertTrue(after.items.all { it.eventId.isNotBlank() })
            if (knownness.any { it.state == "known" && it.action == "hide" }) {
                assertTrue(
                    "hard-hidden known restatements must leave the feed: before=${before.items.size} after=${after.items.size}",
                    after.items.size < before.items.size,
                )
            }

            repository.resetKnowledgeBootstrap()
            val reset = repository.getKnowledgeBootstrap()
            assertTrue(reset.checkpoints.isEmpty())
            assertEquals(0, reset.explicitKnownFactCount)
        }

    private suspend fun assertApiFailureIsProductionError(repository: RemoteBulletFeedRepository) {
        try {
            repository.getEventDetail("evt_missing_acceptance")
            fail("expected production API error type")
        } catch (error: HttpException) {
            assertEquals(404, error.code())
            val recovered = readyUiState().reduceRootFailure(error)
            assertFalse(recovered.isOffline)
            assertTrue(recovered.hasStaleFeed)
            assertFalse(recovered.sessionExpired)
            assertTrue(recovered.errorMessage?.contains("削除") == true)
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
            val recovered = readyUiState().reduceRootFailure(error)
            assertTrue(recovered.isOffline)
            assertTrue(recovered.hasStaleFeed)
            assertFalse(recovered.sessionExpired)
        } catch (error: HttpException) {
            assertTrue(error.code() >= 400)
            val recovered = readyUiState().reduceRootFailure(error)
            assertFalse(recovered.isOffline)
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

    private fun bootstrapKnownness(
        baseUrl: String,
        userId: String,
        eventId: String,
    ): List<AcceptanceKnownnessRow> {
        val url = (baseUrl.trimEnd('/') + "/__acceptance__/bootstrap-knownness").toHttpUrl()
            .newBuilder()
            .addQueryParameter("userId", userId)
            .addQueryParameter("eventId", eventId)
            .build()
        val request = Request.Builder().url(url).get().build()
        return executeJson(request, AcceptanceKnownnessResponse.serializer()).items
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

    private fun readyUiState(): BulletFeedUiState =
        BulletFeedUiState(
            events = listOf(
                FeedEvent(
                    id = "event-1",
                    title = "Release",
                    summary = "Summary",
                    importance = Importance.MEDIUM,
                    importanceReason = "reason",
                    relation = Relation.DIRECT,
                    relationReason = "reason",
                    announcedAt = "2026-08-30T00:00:00Z",
                    sourceCount = 1,
                    before = "",
                    after = "new",
                    explicitImpact = "impact",
                    inferredImpact = null,
                    sources = emptyList(),
                    timeline = emptyList(),
                    feedItemId = "feed-1",
                ),
            ),
            feedDeliveryIds = mapOf("feed-1" to "delivery-1"),
            feedNextCursor = "cursor-1",
            onboardingState = OnboardingState.READY,
            isLoading = true,
        )

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

    @Serializable
    private data class AcceptanceKnownnessRow(
        val claimId: String,
        val state: String,
        val action: String,
    )

    @Serializable
    private data class AcceptanceKnownnessResponse(
        val items: List<AcceptanceKnownnessRow>,
    )

    private companion object {
        const val BASE_URL_PROPERTY = "bulletfeed.acceptance.baseUrl"
        val JSON_MEDIA = "application/json".toMediaType()
    }
}
