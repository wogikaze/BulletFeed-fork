package com.bulletfeed.app

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException

class BulletFeedViewModelStateTest {
    @Test
    fun offlineFailureRetainsFeedAndMarksItStale() {
        val state = readyState()

        val recovered = state.reduceRootFailure(IOException("network down"))

        assertEquals(state.events, recovered.events)
        assertTrue(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertFalse(recovered.sessionExpired)
        assertTrue(recovered.errorMessage?.contains("通信") == true)
    }

    @Test
    fun unauthorizedFailureClearsProtectedFeedAndRequiresRecovery() {
        val state = readyState()

        val recovered = state.reduceRootFailure(SessionRecoveryRequiredException())

        assertTrue(recovered.events.isEmpty())
        assertTrue(recovered.feedDeliveryIds.isEmpty())
        assertNull(recovered.feedNextCursor)
        assertTrue(recovered.sessionExpired)
        assertFalse(recovered.isOffline)
        assertFalse(recovered.hasStaleFeed)
        assertNull(recovered.errorMessage)
    }

    @Test
    fun serverFailureRetainsStaleFeedButDoesNotClaimOffline() {
        val state = readyState()

        val recovered = state.reduceRootFailure(httpError(503))

        assertEquals(state.events, recovered.events)
        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertFalse(recovered.sessionExpired)
        assertTrue(recovered.errorMessage?.contains("サーバー") == true)
    }

    @Test
    fun clientForbiddenRetainsStaleFeedAndDoesNotClaimOffline() {
        val recovered = readyState().reduceRootFailure(httpError(403))

        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertFalse(recovered.sessionExpired)
        assertTrue(recovered.errorMessage?.contains("アクセス権") == true)
    }

    @Test
    fun notFoundRetainsStaleFeed() {
        val recovered = readyState().reduceRootFailure(httpError(404))

        assertTrue(recovered.hasStaleFeed)
        assertTrue(recovered.errorMessage?.contains("削除") == true)
    }

    @Test
    fun rateLimitRetainsStaleFeedAndAsksToRetryLater() {
        val recovered = readyState().reduceRootFailure(httpError(429))

        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertTrue(recovered.errorMessage?.contains("集中") == true)
    }

    @Test
    fun staleWorkerHeartbeatIsNotGenericServerOrOffline() {
        val recovered = readyState().reduceRootFailure(
            httpError(
                503,
                """{"detail":"Source sync worker heartbeat is stale or missing"}""",
            ),
        )

        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertTrue(recovered.errorMessage?.contains("ワーカー") == true)
        assertFalse(recovered.errorMessage?.contains("サーバー") == true)
    }

    @Test
    fun databaseNotReadyKeepsStaleFeed() {
        val recovered = readyState().reduceRootFailure(
            httpError(503, """{"detail":"Database is not ready"}"""),
        )

        assertTrue(recovered.hasStaleFeed)
        assertTrue(recovered.errorMessage?.contains("データベース") == true)
    }

    @Test
    fun conflictRetainsStaleFeedAndAsksToReload() {
        val state = readyState()
        val recovered = state.reduceRootFailure(httpError(409))

        assertEquals(state.events, recovered.events)
        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertFalse(recovered.sessionExpired)
        assertTrue(recovered.errorMessage?.contains("再読み込み") == true)
    }

    @Test
    fun unprocessableRetainsStaleFeedAndDoesNotClaimOffline() {
        val recovered = readyState().reduceRootFailure(httpError(422))

        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertTrue(recovered.errorMessage?.contains("API契約") == true)
    }

    @Test
    fun genericClientErrorRetainsStaleFeedAndAsksToRetry() {
        val recovered = readyState().reduceRootFailure(httpError(400))

        assertFalse(recovered.isOffline)
        assertTrue(recovered.hasStaleFeed)
        assertFalse(recovered.sessionExpired)
        assertTrue(recovered.errorMessage?.contains("再試行") == true)
    }

    @Test
    fun retryClearsOfflineBannerWithoutDroppingStaleEvents() {
        val offline = readyState().reduceRootFailure(IOException("network down"))

        val retrying = offline.beginRefresh()

        assertEquals(offline.events, retrying.events)
        assertFalse(retrying.isOffline)
        assertFalse(retrying.hasStaleFeed)
        assertFalse(retrying.sessionExpired)
        assertNull(retrying.errorMessage)
        assertTrue(retrying.isLoading)
    }

    @Test
    fun firstSoftSubsystemErrorWinsWithoutClaimingOffline() {
        val first = IOException("network down").rememberSoftSubsystemError(null)
        val second = httpError(503).rememberSoftSubsystemError(first)

        assertTrue(first.contains("通信"))
        assertEquals(first, second)
        val state = readyState().copy(isLoading = false, isOffline = false, errorMessage = first)
        assertFalse(state.isOffline)
        assertFalse(state.sessionExpired)
        assertEquals(readyState().events, state.events)
    }

    @Test
    fun unauthorizedIsNotSwallowedAsSoftSubsystemError() {
        try {
            httpError(401).rememberSoftSubsystemError(null)
            throw AssertionError("expected 401 to rethrow")
        } catch (error: HttpException) {
            assertEquals(401, error.code())
        }
    }

    @Test
    fun sessionRecoveryIsNotSwallowedAsSoftSubsystemError() {
        try {
            SessionRecoveryRequiredException().rememberSoftSubsystemError("kept")
            throw AssertionError("expected session recovery to rethrow")
        } catch (_: SessionRecoveryRequiredException) {
        }
    }

    private fun readyState(): BulletFeedUiState =
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

    private fun httpError(code: Int, body: String = ""): HttpException =
        HttpException(
            Response.error<Any>(
                code,
                body.toResponseBody("application/json".toMediaType()),
            ),
        )
}
