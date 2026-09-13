package com.bulletfeed.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class EventSearchViewModelTest {
    @Test
    fun searchIsDebouncedAndUsesServerRepositoryResults() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        try {
            val repository = RecordingSearchRepository()
            val viewModel = EventSearchViewModel(repository)
            advanceUntilIdle()
            assertEquals(listOf(""), repository.queries)

            viewModel.search("Cloudflare")
            advanceTimeBy(299)
            assertEquals(listOf(""), repository.queries)
            advanceTimeBy(1)
            advanceUntilIdle()

            assertEquals(listOf("", "Cloudflare"), repository.queries)
            assertEquals(listOf("workers-runtime"), viewModel.uiState.value.results.map { it.id })
            assertFalse(viewModel.uiState.value.isLoading)
            assertNull(viewModel.uiState.value.errorMessage)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun failedSearchRemainsRetryable() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        try {
            val repository = RecordingSearchRepository(failFirstKotlinSearch = true)
            val viewModel = EventSearchViewModel(repository)
            advanceUntilIdle()

            viewModel.search("Kotlin")
            advanceTimeBy(300)
            advanceUntilIdle()
            assertTrue(viewModel.uiState.value.results.isEmpty())
            assertTrue(viewModel.uiState.value.errorMessage?.contains("通信") == true)

            viewModel.retry()
            advanceTimeBy(300)
            advanceUntilIdle()
            assertEquals(listOf("kotlin-release"), viewModel.uiState.value.results.map { it.id })
            assertNull(viewModel.uiState.value.errorMessage)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun loadMoreMergesWithoutDuplicatesAndStopsOnRepeatedCursor() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        try {
            val repository = PagingSearchRepository()
            val viewModel = EventSearchViewModel(repository)
            advanceUntilIdle()
            assertEquals(listOf("a", "b"), viewModel.uiState.value.results.map { it.id })
            assertEquals("page-2", viewModel.uiState.value.nextCursor)

            viewModel.loadMore()
            advanceUntilIdle()
            assertEquals(listOf("a", "b", "c"), viewModel.uiState.value.results.map { it.id })
            assertNull(viewModel.uiState.value.nextCursor)
            assertTrue(viewModel.uiState.value.errorMessage?.contains("cursor") == true)
        } finally {
            Dispatchers.resetMain()
        }
    }
}

private class RecordingSearchRepository(
    private val failFirstKotlinSearch: Boolean = false,
) : EventSearchRepository {
    val queries = mutableListOf<String>()
    private var kotlinFailures = 0

    override suspend fun searchEvents(
        query: String,
        cursor: String?,
        limit: Int,
    ): EventSearchPage {
        queries += query
        if (failFirstKotlinSearch && query == "Kotlin" && kotlinFailures++ == 0) {
            throw IOException("offline")
        }
        val item =
            when (query) {
                "Cloudflare" -> searchItem("workers-runtime")
                "Kotlin" -> searchItem("kotlin-release")
                else -> searchItem("recent")
            }
        return EventSearchPage(items = listOf(item), nextCursor = null)
    }
}

private class PagingSearchRepository : EventSearchRepository {
    override suspend fun searchEvents(
        query: String,
        cursor: String?,
        limit: Int,
    ): EventSearchPage =
        if (cursor == null) {
            EventSearchPage(
                items = listOf(searchItem("a"), searchItem("b")),
                nextCursor = "page-2",
            )
        } else {
            EventSearchPage(
                items = listOf(searchItem("b"), searchItem("c")),
                nextCursor = "page-2",
            )
        }
}

private fun searchItem(id: String) =
    EventSearchItem(
        id = id,
        title = "Event $id",
        summary = "summary",
        currentPhase = "resolved",
        currentSummary = "resolved",
        updatedAt = "2026-09-12T00:00:00Z",
        following = false,
        sourcePublisher = "Example",
    )
