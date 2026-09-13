package com.bulletfeed.app

import kotlinx.serialization.json.Json
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
    fun `feed session telemetry maps empty disabled session without crashing`() {
        val mapped = FeedSessionDto(
            version = "session-telemetry-v1",
            id = "",
            startedAt = 0,
            endedAt = null,
        ).toDomain()
        assertEquals("", mapped.id)
        assertEquals("session-telemetry-v1", mapped.version)
    }

    @Test
    fun `topic recommendation page localizes user facing recommendation metadata`() {
        val mapped = TopicRecommendationListDto(
            version = "topic-recommendations-v1",
            items = listOf(
                TopicRecommendationDto(
                    id = "kotlin",
                    name = "Kotlin",
                    type = "technology",
                    score = 0.4f,
                    reason = "catalog fallback",
                    provenance = "inferred",
                    alreadyFollowed = false,
                    confidence = "medium",
                ),
            ),
            abstentions = listOf(TopicRecommendationAbstentionDto("obscure", "low score", 0.01f)),
            policyVersion = "cold-start-v1",
            cohort = "empty_profile",
        ).toDomain()

        assertEquals("empty_profile", mapped.cohort)
        assertEquals("利用状況から推定", mapped.items.single().provenance)
        assertEquals("中", mapped.items.single().confidence)
        assertEquals("まだ興味の情報が少ないため、人気のあるテーマから提案しています。", mapped.items.single().reason)
        assertEquals("obscure", mapped.abstentions.single().name)
        assertTrue(mapped.version.isNotBlank())
    }

    @Test
    fun `source recommendation localizes metadata and hides technical explanation`() {
        val mapped = SourceRecommendationDto(
            id = "cand-1",
            endpointId = "ep-1",
            canonicalUrl = "https://news.ycombinator.com/item?id=1",
            family = "hacker_news_discovery",
            discoveryMethod = "external_index",
            discoveryProvenance = "external_index",
            verificationStatus = "unverified",
            authorityStatus = "aggregator",
            authorityConfidence = 0.2f,
            evidenceEligible = false,
            discoveryOnly = true,
            reason = "discussion index",
            explanation = "discovery only",
            matchedConcepts = listOf("react"),
            matchOrigin = "inferred",
            matchKind = "neighbor",
            score = 0.31f,
            recommendationStatus = "pending",
            publisher = SourcePublisherDto("hn", "Hacker News"),
        ).toDomain()

        assertEquals("cand-1", mapped.id)
        assertTrue(mapped.discoveryOnly)
        assertEquals(false, mapped.evidenceEligible)
        assertEquals(SourceRecommendationStatus.PENDING, mapped.recommendationStatus)
        assertEquals("Hacker News", mapped.publisher?.displayName)
        assertEquals("外部インデックス", mapped.discoveryProvenance)
        assertEquals("情報集約サイト", mapped.authorityStatus)
        assertEquals("興味のある分野に関連する情報源です。", mapped.reason)
        assertEquals("", mapped.explanation)
        assertEquals("approved", SourceRecommendationDecision.APPROVED.name.lowercase())
        assertEquals("ignored", SourceRecommendationDecision.IGNORED.name.lowercase())
    }

    @Test
    fun `site feed discover hides technical English explanation`() {
        val mapped = SiteFeedDiscoverResultDto(
            version = "site-feed-discover-v1",
            siteUrl = "https://notes.example.com/",
            canonicalSiteUrl = "https://notes.example.com/",
            preferredFamily = "rss_atom",
            items = listOf(
                SiteFeedDiscoverItemDto(
                    id = "feed-1",
                    endpointId = "ep-feed-1",
                    canonicalUrl = "https://notes.example.com/feed.xml",
                    family = "rss_atom",
                    discoveryMethod = "html_link",
                    discoveryProvenance = "site_html_link",
                    title = "Notes",
                    preferred = true,
                    evidenceEligible = false,
                    discoveryOnly = true,
                    actionability = "subscribe",
                    verificationStatus = "unverified",
                    authorityStatus = "unknown",
                    explanation = "link rel alternate",
                    siteUrl = "https://notes.example.com/",
                ),
            ),
        ).toDomain()

        assertEquals("site-feed-discover-v1", mapped.version)
        assertEquals("rss_atom", mapped.preferredFamily)
        val item = mapped.items.single()
        assertTrue(item.preferred)
        assertTrue(item.discoveryOnly)
        assertEquals(false, item.evidenceEligible)
        assertEquals(SourceActionability.SUBSCRIBE, item.actionability)
        assertEquals("https://notes.example.com/feed.xml", item.canonicalUrl)
        assertEquals("", item.explanation)
    }

    @Test
    fun `source subscription maps failing status from nested backend payload`() {
        val mapped = SourceSubscriptionDto(
            id = "sub-1",
            kind = "rss_atom",
            canonicalUrl = "https://react.dev/blog/rss.xml",
            pageId = null,
            publisher = SourcePublisherDto("react", "React"),
            status = SourceSubscriptionStatusDto(
                selected = true,
                state = "failing",
                lastSuccessAt = null,
                lastAttemptAt = "2026-08-22T00:00:00Z",
                failureCount = 3,
            ),
        ).toDomain()

        assertEquals(SourceSubscriptionState.FAILING, mapped.state)
        assertEquals(3, mapped.failureCount)
        assertEquals("React", mapped.publisher?.displayName)
        assertEquals("rss_atom", UserSourceKind.RSS_ATOM.name.lowercase())
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
    fun `feed displayReason maps user-facing text and keeps codes from GET feed`() {
        val json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
        val dto = json.decodeFromString<FeedItemDto>(
            """
            {
              "id": "fi_1",
              "eventId": "ev_1",
              "delta": {
                "id": "d1",
                "type": "new_fact",
                "summary": "summary",
                "before": "",
                "after": "after",
                "occurredAt": "2026-09-01T00:00:00Z"
              },
              "title": "title",
              "importance": { "level": "medium", "reason": "impact", "confidence": "high" },
              "relation": {
                "level": "direct",
                "reason": "matched topic",
                "matchedTopics": ["Rust"],
                "matchedRepositories": []
              },
              "status": "unread",
              "following": true,
              "updatedAt": "2026-09-01T00:00:00Z",
              "deliveryId": "dlv_1",
              "displayReason": {
                "policyVersion": "display-reason-v1",
                "rankingPolicyVersion": "ranking-v1",
                "primaryCode": "relation.direct_topic",
                "text": "フォロー中のRustに関連。まだ見ていない可能性が高い。",
                "codes": ["relation.direct_topic", "novelty.possibly_unread"],
                "matchKind": "direct",
                "deltaKind": "new_fact",
                "independentEvidenceCount": 1
              }
            }
            """.trimIndent(),
        )
        val mapped = dto.toDomain()
        val reason = mapped.displayReason
        assertEquals("display-reason-v1", reason?.policyVersion)
        assertEquals("relation.direct_topic", reason?.primaryCode)
        assertEquals("フォロー中のRustに関連。まだ見ていない可能性が高い。", reason?.text)
        assertEquals(listOf("relation.direct_topic", "novelty.possibly_unread"), reason?.codes)
        assertEquals("direct", reason?.matchKind)
        assertEquals("new_fact", reason?.deltaKind)
        assertEquals("フォロー中のRustに関連。まだ見ていない可能性が高い。", reason?.userFacingTextOrNull())
        assertEquals(reason, mapped.toFeedEvent().displayReason)
    }

    @Test
    fun `missing displayReason stays null and empty text is not shown`() {
        val json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
        val withoutReason = json.decodeFromString<FeedItemDto>(
            """
            {
              "id": "fi_2",
              "eventId": "ev_2",
              "delta": {
                "id": "d2",
                "type": "detail",
                "summary": "summary",
                "before": "",
                "after": "after",
                "occurredAt": "2026-09-01T00:00:00Z"
              },
              "title": "title",
              "importance": { "level": "low", "reason": "impact", "confidence": "low" },
              "relation": {
                "level": "reference",
                "reason": "reference",
                "matchedTopics": [],
                "matchedRepositories": []
              },
              "status": "unread",
              "following": false,
              "updatedAt": "2026-09-01T00:00:00Z",
              "deliveryId": "dlv_2"
            }
            """.trimIndent(),
        ).toDomain()
        assertEquals(null, withoutReason.displayReason)
        assertEquals(null, withoutReason.toFeedEvent().displayReason)

        val blank = DisplayReason(
            policyVersion = "display-reason-v1",
            rankingPolicyVersion = "ranking-v1",
            primaryCode = "relation.reference",
            text = "   ",
            codes = listOf("relation.reference"),
            matchKind = "reference",
            deltaKind = "new_fact",
        )
        assertEquals(null, blank.userFacingTextOrNull())
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
