package com.bulletfeed.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
class SiteFeedDiscoverViewModelTest {
    @Test
    fun discoverKeepsCandidatesDiscoveryOnlyAndDoesNotSubscribe() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val repository = MockBulletFeedRepository()
                val viewModel = BulletFeedViewModel(repository)

                viewModel.discoverSiteFeeds("https://notes.example.com/")
                advanceUntilIdle()

                val state = viewModel.uiState.value
                val discovered = requireNotNull(state.siteFeedDiscoverResult)
                assertTrue(discovered.items.isNotEmpty())
                assertTrue(discovered.items.all { it.discoveryOnly })
                assertTrue(discovered.items.all { !it.evidenceEligible })
                assertTrue(repository.getSourceSubscriptions().isEmpty())
                assertFalse(state.isOffline)
                assertNull(state.siteFeedDiscoverError)
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun blankUrlIsLocalValidationNotOffline() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val viewModel = BulletFeedViewModel(MockBulletFeedRepository())

                viewModel.discoverSiteFeeds("   ")
                advanceUntilIdle()

                val state = viewModel.uiState.value
                assertEquals("URLを入力してください。", state.siteFeedDiscoverError)
                assertNull(state.siteFeedDiscoverResult)
                assertFalse(state.isOffline)
                assertFalse(state.sessionExpired)
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun clientValidationIsNotOffline() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val viewModel =
                    BulletFeedViewModel(
                        MockBulletFeedRepository(
                            discoverSiteFeedsOverride = {
                                throw httpError(422, """{"error":{"message":"url is required"}}""")
                            },
                        ),
                    )

                viewModel.discoverSiteFeeds("https://notes.example.com/")
                advanceUntilIdle()

                val state = viewModel.uiState.value
                assertTrue(state.siteFeedDiscoverError?.contains("URLを入力") == true)
                assertFalse(state.isOffline)
                assertFalse(state.sessionExpired)
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun networkFailureStaysOnDiscoverErrorAndDoesNotClaimOffline() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val viewModel =
                    BulletFeedViewModel(
                        MockBulletFeedRepository(
                            discoverSiteFeedsOverride = { throw IOException("network down") },
                        ),
                    )

                viewModel.discoverSiteFeeds("https://notes.example.com/")
                advanceUntilIdle()

                val state = viewModel.uiState.value
                assertTrue(state.siteFeedDiscoverError?.contains("通信") == true)
                assertFalse(state.isOffline)
                assertFalse(state.sessionExpired)
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun serverFailureIsNotOffline() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val viewModel =
                    BulletFeedViewModel(
                        MockBulletFeedRepository(
                            discoverSiteFeedsOverride = { throw httpError(503) },
                        ),
                    )

                viewModel.discoverSiteFeeds("https://notes.example.com/")
                advanceUntilIdle()

                val state = viewModel.uiState.value
                assertTrue(state.siteFeedDiscoverError?.contains("サーバー") == true)
                assertFalse(state.isOffline)
            } finally {
                Dispatchers.resetMain()
            }
        }
}

private fun httpError(code: Int, body: String = ""): HttpException =
    HttpException(
        Response.error<Any>(
            code,
            body.toResponseBody("application/json".toMediaType()),
        ),
    )
