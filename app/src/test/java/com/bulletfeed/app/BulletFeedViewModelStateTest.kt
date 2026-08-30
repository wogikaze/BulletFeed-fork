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

    private fun httpError(code: Int): HttpException =
        HttpException(
            Response.error<Any>(
                code,
                "".toResponseBody("text/plain".toMediaType()),
            ),
        )
}
