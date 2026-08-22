package com.bulletfeed.app

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MockBulletFeedRepositoryTest {
    @Test
    fun importantFeedbackTogglesSavedState() =
        runTest {
            val repository = MockBulletFeedRepository()

            val updated = repository.updateEventFeedback("workers-runtime", Feedback.IMPORTANT)

            assertTrue(updated.markedImportant)
        }

    @Test
    fun vulnerabilityStatusIsPersistedInRepository() =
        runTest {
            val repository = MockBulletFeedRepository()

            repository.updateVulnerabilityStatus("vuln-next-auth", VulnerabilityStatus.IN_PROGRESS)
            val updated = repository.getVulnerabilityAlerts().first { it.id == "vuln-next-auth" }

            assertEquals(VulnerabilityStatus.IN_PROGRESS, updated.status)
        }

    @Test
    fun markAllNotificationsReadUpdatesEveryItem() =
        runTest {
            val repository = MockBulletFeedRepository()

            val updated = repository.markAllNotificationsRead()

            assertTrue(updated.all { it.read })
        }

    @Test
    fun markFeedItemReadUpdatesStatus() =
        runTest {
            val repository = MockBulletFeedRepository()

            val updated = repository.markFeedItemRead("fi_workers-runtime")

            assertTrue(updated.read)
            assertEquals("fi_workers-runtime", updated.feedItemId)
        }

    @Test
    fun onboardingPersistsProfileTopicsAndGithubChoice() =
        runTest {
            val repository = MockBulletFeedRepository()
            val profile = UserProfile("Webエンジニア", setOf("AI", "OSS"), "日本")

            val snapshot =
                repository.completeOnboarding(
                    profile = profile,
                    topics = listOf("Kotlin", "GitHub", "Kotlin"),
                    connectGithub = true,
                )

            assertTrue(snapshot.completed)
            assertEquals(profile, snapshot.profile)
            assertEquals(listOf("Kotlin", "GitHub"), snapshot.topics)
            assertTrue(repository.getGithubConnection())
        }

    @Test
    fun searchResultMetaDoesNotRequireSources() {
        val event = DemoData.events.first().copy(sources = emptyList(), announcedAt = "今日 12:00")

        assertEquals("今日 12:00", searchResultMeta(event))
    }

    @Test
    fun searchResultMetaIncludesPublisherWhenPresent() {
        val event = DemoData.events.first()

        assertEquals("${event.announcedAt}  ·  ${event.sources.first().publisher}", searchResultMeta(event))
    }
}
