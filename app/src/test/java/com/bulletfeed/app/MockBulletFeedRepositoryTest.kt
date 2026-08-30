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

            repository.updateEventFeedback("workers-runtime", Feedback.IMPORTANT)
            val updated = repository.getFeedEvents().first { it.id == "workers-runtime" }

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

            repository.markFeedItemRead("fi_workers-runtime")
            val updated = repository.getFeedItems().first { it.id == "fi_workers-runtime" }

            assertEquals(FeedItemStatus.READ, updated.status)
            assertEquals("fi_workers-runtime", updated.id)
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
    fun sourceRecommendationApproveAndIgnoreUpdateLocalState() =
        runTest {
            val repository = MockBulletFeedRepository()
            val pending = repository.getSourceRecommendations()
            assertTrue(pending.any { it.discoveryOnly })
            assertTrue(pending.none { it.evidenceEligible })

            val official = pending.first { !it.discoveryOnly }
            val approved = repository.decideSourceRecommendation(official.id, SourceRecommendationDecision.APPROVED)
            assertEquals(SourceRecommendationStatus.APPROVED, approved.recommendationStatus)

            val discovery = pending.first { it.discoveryOnly }
            repository.decideSourceRecommendation(discovery.id, SourceRecommendationDecision.IGNORED)
            val visible = repository.getSourceRecommendations()
            assertTrue(visible.none { it.id == discovery.id })
            assertTrue(visible.any { it.id == official.id && it.recommendationStatus == SourceRecommendationStatus.APPROVED })
        }

    @Test
    fun sourceSubscriptionAddAndRemoveUpdateLocalState() =
        runTest {
            val repository = MockBulletFeedRepository()
            val created = repository.addSourceSubscription(
                UserSourceKind.RSS_ATOM,
                url = "https://react.dev/blog/rss.xml",
            )
            assertEquals(listOf(created.id), repository.getSourceSubscriptions().map { it.id })
            repository.removeSourceSubscription(created.id)
            assertTrue(repository.getSourceSubscriptions().isEmpty())
        }
}
