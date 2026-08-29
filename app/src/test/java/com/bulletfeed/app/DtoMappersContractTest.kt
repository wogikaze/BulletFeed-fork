package com.bulletfeed.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DtoMappersContractTest {
    @Test
    fun `current state phase preserves source specific backend value`() {
        val mapped = CurrentStateDto(
            phase = "prerelease",
            summary = "Release candidate published",
            since = "2026-08-22T00:00:00Z",
            confidence = "high",
        ).toDomain()

        assertEquals("prerelease", mapped.phase)
    }

    @Test
    fun `all backend source kinds are representable`() {
        val sourceKinds = listOf(
            "statuspage",
            "github_advisory",
            "osv",
            "github_release",
            "github_sbom",
            "rss_atom",
            "json_feed",
            "official_changelog",
            "documentation",
        )

        sourceKinds.forEach { kind ->
            val mapped = EventSourceDto(
                publisher = "publisher",
                kind = kind,
                title = "title",
                url = "https://example.com/source",
                publishedAt = "2026-08-22T00:00:00Z",
                retrievedAt = "2026-08-22T00:01:00Z",
                evidence = "evidence",
            ).toDomain()
            assertEquals(kind, mapped.kind.name.lowercase())
        }
    }

    @Test
    fun `unknown dependency type is retained instead of crashing`() {
        val mapped = SecurityAlertDto(
            id = "alert-1",
            advisoryId = "GHSA-test",
            title = "title",
            summary = "summary",
            severity = "high",
            status = "open",
            repository = SecurityAlertRepositoryDto("1", "owner/repository"),
            packageInfo = SecurityAlertPackageDto(
                name = "package",
                currentVersion = "1.0.0",
                fixedVersion = "1.0.1",
                dependencyType = "workspace",
            ),
            source = "github_advisory",
            detectedAt = "2026-08-22T00:00:00Z",
            evidence = "evidence",
            recommendation = "upgrade",
        ).toDomain()

        assertEquals(DependencyType.UNKNOWN, mapped.dependencyType)
        assertEquals("workspace", mapped.dependencyTypeRaw)
        assertEquals("1.0.1", mapped.fixedVersion)
    }

    @Test
    fun `github repository save result maps added and already tracked topics`() {
        val mapped = GithubRepositoryUpdateResultDto(
            connected = true,
            credentialState = "connected",
            accountLogin = "niyu",
            addedTopics = listOf("Kotlin", "Android"),
            alreadyTrackedTopics = listOf("Redis"),
            inspectedRepositoryCount = 2,
            failedRepositoryCount = 0,
        ).toDomain()

        assertEquals(listOf("Kotlin", "Android"), mapped.addedTopics)
        assertEquals(listOf("Redis"), mapped.alreadyTrackedTopics)
        assertEquals(2, mapped.inspectedRepositoryCount)
        assertTrue(mapped.connection.connected)
        assertEquals(
            "テーマに追加しました: Kotlin、Android\nすでに追跡中: Redis",
            githubTopicSyncMessage(mapped, selectedRepositoryCount = 2),
        )
    }

    @Test
    fun `feed feedback types serialize to api snake case and keep ranking aliases`() {
        val expected = mapOf(
            FeedFeedbackType.IMPORTANT to "important",
            FeedFeedbackType.NOT_RELEVANT to "not_relevant",
            FeedFeedbackType.FOLLOW to "follow",
            FeedFeedbackType.ALREADY_KNEW to "already_knew",
            FeedFeedbackType.LEARNED_NOW to "learned_now",
            FeedFeedbackType.LESS_LIKE_THIS to "less_like_this",
            FeedFeedbackType.UNDO to "undo",
        )
        expected.forEach { (type, wire) ->
            assertEquals(wire, type.name.lowercase())
        }
        assertEquals(FeedFeedbackType.IMPORTANT, Feedback.IMPORTANT.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.NOT_RELEVANT, Feedback.NOT_RELEVANT.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.FOLLOW, Feedback.FOLLOW.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.ALREADY_KNEW, Feedback.ALREADY_KNEW.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.LEARNED_NOW, Feedback.LEARNED_NOW.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.LESS_LIKE_THIS, Feedback.LESS_LIKE_THIS.toFeedFeedbackType())
        assertEquals(FeedFeedbackType.UNDO, Feedback.UNDO.toFeedFeedbackType())
        assertEquals(null, Feedback.READ.toFeedFeedbackType())
    }

    @Test
    fun `pagination merge preserves backend order and removes duplicate feed item ids`() {
        val first = feedEvent("event-a", "feed-a")
        val second = feedEvent("event-b", "feed-b")
        val duplicateSecond = second.copy(title = "new duplicate payload")
        val third = feedEvent("event-c", "feed-c")

        val merged = mergeFeedEvents(listOf(first, second), listOf(duplicateSecond, third))

        assertEquals(listOf("feed-a", "feed-b", "feed-c"), merged.map { it.feedItemId })
        assertTrue(merged[1].title != "new duplicate payload")
    }

    private fun feedEvent(id: String, feedItemId: String) = FeedEvent(
        id = id,
        title = id,
        summary = "summary",
        importance = Importance.MEDIUM,
        importanceReason = "reason",
        relation = Relation.REFERENCE,
        relationReason = "reason",
        announcedAt = "2026-08-22T00:00:00Z",
        sourceCount = 0,
        before = "before",
        after = "after",
        explicitImpact = "impact",
        inferredImpact = null,
        sources = emptyList(),
        timeline = emptyList(),
        feedItemId = feedItemId,
    )
}
