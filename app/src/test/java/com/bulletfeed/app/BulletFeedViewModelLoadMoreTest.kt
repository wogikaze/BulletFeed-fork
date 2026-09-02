package com.bulletfeed.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
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

@OptIn(ExperimentalCoroutinesApi::class)
class BulletFeedViewModelLoadMoreTest {
    @Test
    fun loadMoreFailureRetainsExistingFeedAndCursorForRetry() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val repository = FailingLoadMoreRepository(IOException("network down"))
                val viewModel = readyViewModel(repository)
                val before = viewModel.uiState.value
                val beforeFeedItemIds = before.events.map { it.feedItemId }
                val beforeDeliveries = before.feedDeliveryIds

                viewModel.loadMoreFeed()
                advanceUntilIdle()

                val after = viewModel.uiState.value
                assertEquals(beforeFeedItemIds, after.events.map { it.feedItemId })
                assertEquals(beforeDeliveries, after.feedDeliveryIds)
                assertEquals("cursor-1", after.feedNextCursor)
                assertFalse(after.isFeedLoadingMore)
                assertTrue(after.feedLoadMoreError?.contains("通信") == true)
                assertEquals("cursor-1", repository.lastCursor)
                assertEquals(1, repository.loadMoreRequests)
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun loadMoreUnauthorizedClearsProtectedFeedAndRequiresRecovery() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val repository = FailingLoadMoreRepository(httpError(401))
                val viewModel = readyViewModel(repository)

                viewModel.loadMoreFeed()
                advanceUntilIdle()

                val after = viewModel.uiState.value
                assertTrue(after.events.isEmpty())
                assertTrue(after.feedDeliveryIds.isEmpty())
                assertNull(after.feedNextCursor)
                assertTrue(after.sessionExpired)
                assertFalse(after.isOffline)
                assertEquals(1, repository.loadMoreRequests)
            } finally {
                Dispatchers.resetMain()
            }
        }

    private suspend fun TestScope.readyViewModel(
        repository: FailingLoadMoreRepository,
    ): BulletFeedViewModel {
        val viewModel = BulletFeedViewModel(repository)
        viewModel.completeOnboarding(
            profile = UserProfile("Androidエンジニア", setOf("モバイル"), "東京"),
            topics = listOf("Kotlin", "Android", "GitHub", "React", "Python"),
            connectGithub = false,
        )
        advanceUntilIdle()
        assertEquals(OnboardingState.READY, viewModel.uiState.value.onboardingState)
        assertTrue(viewModel.uiState.value.events.isNotEmpty())
        assertEquals("cursor-1", viewModel.uiState.value.feedNextCursor)
        return viewModel
    }
}

private class FailingLoadMoreRepository(
    private val failure: Throwable,
    private val inner: MockBulletFeedRepository = MockBulletFeedRepository(),
) : BulletFeedRepository by inner {
    var lastCursor: String? = null
    var loadMoreRequests = 0

    override suspend fun getFilteredFeedPage(
        relation: Relation?,
        status: FeedItemStatus?,
        cursor: String?,
        limit: Int,
    ): FeedPage {
        if (cursor != null) {
            loadMoreRequests += 1
            lastCursor = cursor
            throw failure
        }
        return inner.getFilteredFeedPage(
            relation = relation,
            status = status,
            cursor = null,
            limit = limit,
        ).copy(nextCursor = "cursor-1")
    }
}

private fun httpError(code: Int): HttpException =
    HttpException(
        Response.error<Any>(
            code,
            "".toResponseBody("application/json".toMediaType()),
        ),
    )
