package com.bulletfeed.app

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

class MockMeStore(
    private val state: MockAppState,
) : MeRepository {
    override suspend fun getMe(): MeBootstrap =
        MeBootstrap(
            onboardingCompleted = state.onboardingCompleted,
            onboardingState = if (state.onboardingCompleted) OnboardingState.READY else OnboardingState.PROFILE,
            profile = state.profile,
            topicCount = state.topics.size,
            githubConnected = state.github.connected,
        )

    override suspend fun getProfile(): UserProfile = state.profile

    override suspend fun saveProfile(profile: UserProfile): UserProfile {
        state.profile = profile
        return state.profile
    }

    override suspend fun getUserTopics(): List<UserTopic> = state.topics.toList()

    override suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic {
        val topic =
            UserTopic(
                id = "topic_${state.topics.size}",
                name = name.trim(),
                type = type,
                priority = TopicPriority.NORMAL,
                order = state.topics.size,
            )
        state.topics += topic
        return topic
    }

    override suspend fun removeUserTopic(topicId: String) {
        state.topics.removeAll { it.id == topicId }
    }

    override suspend fun patchUserTopic(
        topicId: String,
        priority: TopicPriority?,
        order: Int?,
    ): UserTopic {
        val index = state.topics.indexOfFirst { it.id == topicId }
        val current = state.topics[index]
        val updated =
            current.copy(
                priority = priority ?: current.priority,
                order = order ?: current.order,
            )
        state.topics[index] = updated
        return updated
    }

    override suspend fun searchTopics(query: String): List<UserTopic> =
        state.topicCatalog.filter { it.name.contains(query, ignoreCase = true) }

    override suspend fun getTopicRecommendations(includeFollowed: Boolean): TopicRecommendationPage {
        val followed = state.topics.map { it.name.lowercase() }.toSet()
        val items =
            state.topicRecommendations.filter { includeFollowed || it.name.lowercase() !in followed }
        return TopicRecommendationPage(
            version = "topic-recommendations-v1",
            items = items,
            policyVersion = "cold-start-v1",
            cohort = if (state.topics.isEmpty()) "empty_profile" else "topic_selected",
        )
    }

    override suspend fun ignoreTopicRecommendation(topicId: String): TopicRecommendationPage {
        state.topicRecommendations.removeAll { it.id == topicId }
        return getTopicRecommendations()
    }

    override suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot {
        val uniqueTopics = uniqueTopicNames(topics)
        if (!connectGithub && uniqueTopics.size < DemoData.MINIMUM_TOPIC_COUNT) {
            throw mockUnprocessable("at least 5 topics are required unless GitHub import is enabled")
        }
        state.profile = profile
        state.topics =
            uniqueTopics
                .mapIndexed { index, name ->
                    UserTopic("topic_$index", name, TopicType.TECHNOLOGY, TopicPriority.NORMAL, index)
                }.toMutableList()
        state.github = state.github.copy(connected = connectGithub)
        state.onboardingCompleted = true
        return OnboardingSnapshot(
            completed = true,
            state = OnboardingState.READY,
            profile = state.profile,
            topics = state.topicNames(),
        )
    }

    override suspend fun getSourceRecommendations(includeIgnored: Boolean): List<SourceRecommendation> =
        state.sourceRecommendations.filter { includeIgnored || it.recommendationStatus != SourceRecommendationStatus.IGNORED }

    override suspend fun decideSourceRecommendation(
        candidateId: String,
        decision: SourceRecommendationDecision,
    ): SourceRecommendation {
        val index = state.sourceRecommendations.indexOfFirst { it.id == candidateId }
        require(index >= 0) { "unknown recommendation" }
        val current = state.sourceRecommendations[index]
        require(decision != SourceRecommendationDecision.APPROVED || current.canApprove()) {
            "recommendation cannot be approved"
        }
        val status =
            when (decision) {
                SourceRecommendationDecision.APPROVED -> SourceRecommendationStatus.APPROVED
                SourceRecommendationDecision.IGNORED -> SourceRecommendationStatus.IGNORED
            }
        val updated = state.sourceRecommendations[index].copy(recommendationStatus = status)
        state.sourceRecommendations[index] = updated
        return updated
    }

    override suspend fun getSourceSubscriptions(): List<SourceSubscription> = state.sourceSubscriptions.toList()

    override suspend fun addSourceSubscription(
        kind: UserSourceKind,
        url: String?,
        pageId: String?,
    ): SourceSubscription {
        val canonical =
            when (kind) {
                UserSourceKind.STATUSPAGE -> {
                    val id = pageId?.trim().orEmpty().ifBlank { "abcd1234" }
                    "https://$id.statuspage.io/api/v2/summary.json"
                }
                UserSourceKind.RSS_ATOM,
                UserSourceKind.JSON_FEED,
                UserSourceKind.GENERIC_WEB,
                -> url?.trim().orEmpty().ifBlank { "https://example.com/feed.xml" }
            }
        if (canonical == "https://invalid.example/feed") {
            error("invalid source url")
        }
        val existing = state.sourceSubscriptions.firstOrNull { it.canonicalUrl == canonical }
        if (existing != null) return existing
        val created =
            SourceSubscription(
                id = "sub_${state.sourceSubscriptions.size}",
                kind = kind.name.lowercase(),
                canonicalUrl = canonical,
                pageId = pageId?.trim()?.takeIf { it.isNotEmpty() },
                state = SourceSubscriptionState.PENDING,
            )
        state.sourceSubscriptions += created
        return created
    }

    override suspend fun discoverSiteFeeds(url: String): SiteFeedDiscoverResult {
        val site = url.trim().ifBlank { "https://notes.example.com/" }
        val host = site.substringAfter("://").substringBefore("/").lowercase()
        if (host == "plain.example.com") {
            return SiteFeedDiscoverResult(
                version = "site-feed-discover-v1",
                siteUrl = site,
                canonicalSiteUrl = site,
                preferredFamily = "generic_web",
                items =
                    listOf(
                        SiteFeedDiscoverItem(
                            id = "discover_web",
                            endpointId = "ep_discover_web",
                            canonicalUrl = site,
                            family = "generic_web",
                            discoveryMethod = "site_url_fallback",
                            discoveryProvenance = "website_feed",
                            title = "Page watch",
                            preferred = true,
                            evidenceEligible = false,
                            discoveryOnly = true,
                            actionability = SourceActionability.SUBSCRIBE,
                            verificationStatus = "unverified",
                            authorityStatus = "unknown",
                            explanation = "No feed was found; generic web watch only.",
                            siteUrl = site,
                        ),
                    ),
            )
        }
        val feedUrl = site.trimEnd('/') + "/feed.xml"
        return SiteFeedDiscoverResult(
            version = "site-feed-discover-v1",
            siteUrl = site,
            canonicalSiteUrl = site,
            preferredFamily = "rss_atom",
            items =
                listOf(
                    SiteFeedDiscoverItem(
                        id = "discover_rss",
                        endpointId = "ep_discover_rss",
                        canonicalUrl = feedUrl,
                        family = "rss_atom",
                        discoveryMethod = "html_link",
                        discoveryProvenance = "site_html_link",
                        title = "Example feed",
                        preferred = true,
                        evidenceEligible = false,
                        discoveryOnly = true,
                        actionability = SourceActionability.SUBSCRIBE,
                        verificationStatus = "unverified",
                        authorityStatus = "unknown",
                        explanation = "Discovered from the site; not evidence until subscribed.",
                        siteUrl = site,
                    ),
                ),
        )
    }

    override suspend fun removeSourceSubscription(subscriptionId: String) {
        state.sourceSubscriptions.removeAll { it.id == subscriptionId }
    }

    override suspend fun getKnowledgeBootstrap(): KnowledgeBootstrapSummary = state.knowledgeBootstrap

    override suspend fun recordKnowledgeCheckpoint(
        subjectKind: BootstrapSubjectKind,
        subjectId: String,
        catchUp: Boolean,
        asOf: String?,
    ): KnowledgeBootstrapResult {
        val checkpoint =
            KnowledgeBootstrapCheckpoint(
                subjectKind = subjectKind,
                subjectId = subjectId,
                asOf = System.currentTimeMillis() / 1000,
                catchUp = catchUp,
                knownFactCount = if (catchUp) 0 else 1,
            )
        val current = state.knowledgeBootstrap
        state.knowledgeBootstrap =
            current.copy(
                checkpoints = current.checkpoints.filterNot {
                    it.subjectKind == subjectKind && it.subjectId == subjectId
                } + checkpoint,
            )
        return KnowledgeBootstrapResult(
            version = current.version,
            subjectKind = subjectKind,
            subjectId = subjectId,
            asOf = checkpoint.asOf,
            catchUp = catchUp,
            knownFactCount = checkpoint.knownFactCount,
        )
    }

    override suspend fun recordExplicitKnowledgeClaims(claimIds: List<String>): KnowledgeBootstrapResult {
        val current = state.knowledgeBootstrap
        state.knowledgeBootstrap = current.copy(explicitKnownFactCount = current.explicitKnownFactCount + claimIds.size)
        return KnowledgeBootstrapResult(version = current.version, knownFactCount = claimIds.size, sessionId = "kbs_mock")
    }

    override suspend fun resetKnowledgeBootstrap() {
        state.knowledgeBootstrap =
            KnowledgeBootstrapSummary(
                version = "knowledge-bootstrap-v1",
                explicitKnownFactCount = 0,
                inferredFactCount = 0,
            )
    }
}

private fun uniqueTopicNames(topics: List<String>): List<String> {
    val unique = mutableListOf<String>()
    val seen = mutableSetOf<String>()
    for (name in topics) {
        val cleaned = name.trim()
        if (cleaned.isEmpty() || !seen.add(cleaned.lowercase())) continue
        unique += cleaned
    }
    return unique
}

private fun mockUnprocessable(message: String): HttpException {
    val body = """{"error":{"code":"validation_error","message":"$message"}}"""
    return HttpException(
        Response.error<Unit>(
            422,
            body.toResponseBody("application/json".toMediaType()),
        ),
    )
}
