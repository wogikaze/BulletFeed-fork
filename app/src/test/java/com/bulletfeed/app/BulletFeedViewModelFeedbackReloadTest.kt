package com.bulletfeed.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BulletFeedViewModelFeedbackReloadTest {
    @Test
    fun importantFeedbackReloadsTheNextFeedPage() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val repository = RecordingBulletFeedRepository()
                val viewModel = BulletFeedViewModel(repository)
                viewModel.completeOnboarding(
                    profile = UserProfile("Androidエンジニア", setOf("モバイル"), "東京"),
                    topics = listOf("Kotlin", "Android", "GitHub", "React", "Python"),
                    connectGithub = false,
                )
                advanceUntilIdle()

                val loadsAfterReady = repository.filteredFeedLoads
                assertTrue("onboarding READY must load the feed", loadsAfterReady >= 1)
                val event = viewModel.uiState.value.events.first()
                assertTrue(event.feedItemId.isNotBlank())

                viewModel.updateEventFeedback(event.id, Feedback.IMPORTANT)
                advanceUntilIdle()

                assertEquals(
                    listOf(event.feedItemId to FeedFeedbackType.IMPORTANT),
                    repository.feedbacks,
                )
                assertTrue(
                    "feedback must GET /feed again so the next page can apply ranking: " +
                        "loads after ready=$loadsAfterReady after feedback=${repository.filteredFeedLoads}",
                    repository.filteredFeedLoads > loadsAfterReady,
                )
                assertTrue(viewModel.uiState.value.events.any { it.id == event.id })
            } finally {
                Dispatchers.resetMain()
            }
        }

    @Test
    fun resetLearnedRankingReloadsTheNextFeedPage() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val repository = RecordingBulletFeedRepository()
                val viewModel = BulletFeedViewModel(repository)
                viewModel.completeOnboarding(
                    profile = UserProfile("Androidエンジニア", setOf("モバイル"), "東京"),
                    topics = listOf("Kotlin", "Android", "GitHub", "React", "Python"),
                    connectGithub = false,
                )
                advanceUntilIdle()

                val loadsAfterReady = repository.filteredFeedLoads
                assertTrue("onboarding READY must load the feed", loadsAfterReady >= 1)

                viewModel.resetLearnedRanking()
                advanceUntilIdle()

                assertEquals(1, repository.rankingResets)
                assertTrue(
                    "ranking reset must GET /feed again so the next page can drop learned order: " +
                        "loads after ready=$loadsAfterReady after reset=${repository.filteredFeedLoads}",
                    repository.filteredFeedLoads > loadsAfterReady,
                )
            } finally {
                Dispatchers.resetMain()
            }
        }
}

private class RecordingBulletFeedRepository(
    private val inner: MockBulletFeedRepository = MockBulletFeedRepository(),
) : BulletFeedRepository by inner {
    val feedbacks = mutableListOf<Pair<String, FeedFeedbackType>>()
    var rankingResets = 0
    var filteredFeedLoads = 0

    override suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ) {
        feedbacks += feedItemId to type
        inner.sendFeedFeedback(feedItemId, type)
    }

    override suspend fun resetLearnedRanking(): Long {
        rankingResets += 1
        return inner.resetLearnedRanking()
    }

    override suspend fun getFilteredFeedPage(
        relation: Relation?,
        status: FeedItemStatus?,
        cursor: String?,
        limit: Int,
    ): FeedPage {
        filteredFeedLoads += 1
        return inner.getFilteredFeedPage(
            relation = relation,
            status = status,
            cursor = cursor,
            limit = limit,
        )
    }
}
