package com.bulletfeed.app

class MockAppState {
    val catalog: Map<String, FeedEvent> = DemoData.events.associateBy { it.id }
    var feedItems: MutableList<FeedItem> = DemoData.events.map { it.toFeedItem() }.toMutableList()
    var profile: UserProfile =
        UserProfile(
            role = "Androidエンジニア",
            interests = setOf("モバイル", "AI", "クラウド"),
            region = "東京",
        )
    var topics: MutableList<UserTopic> =
        listOf("Kotlin", "Cloudflare Workers", "OpenAI API", "Flutter", "Android")
            .mapIndexed { index, name ->
                UserTopic(
                    id = "topic_$index",
                    name = name,
                    type = TopicType.TECHNOLOGY,
                    priority = TopicPriority.NORMAL,
                    order = index,
                )
            }.toMutableList()
    var onboardingCompleted: Boolean = false
    var github: GithubConnection = GithubConnection(connected = false)
    var repositories: MutableList<GithubRepositoryChoice> =
        mutableListOf(
            GithubRepositoryChoice("repo_123", "niyu/example-worker", "https://github.com/niyu/example-worker", false),
            GithubRepositoryChoice("repo_web", "niyu/bulletfeed-web", "https://github.com/niyu/bulletfeed-web", false),
            GithubRepositoryChoice("repo_app", "niyu/BulletFeed", "https://github.com/niyu/BulletFeed", false),
        )
    var alerts: MutableList<VulnerabilityAlert> = SecurityDemoData.alerts.toMutableList()
    var notifications: MutableList<AppNotification> = NotificationDemoData.notifications.toMutableList()
    val exposures: MutableList<FeedExposure> = mutableListOf()
    var activeFeedSessionId: String? = null
    var feedSessionStarts: Int = 0
    var knowledgeBootstrap: KnowledgeBootstrapSummary =
        KnowledgeBootstrapSummary(
            version = "knowledge-bootstrap-v1",
            explicitKnownFactCount = 0,
            inferredFactCount = 0,
        )
    val topicCatalog: List<UserTopic> =
        listOf(
            "Kotlin",
            "Android",
            "Jetpack Compose",
            "Cloudflare Workers",
            "OpenAI API",
            "Flutter",
            "GitHub",
        ).mapIndexed { index, name ->
            UserTopic("catalog_$index", name, TopicType.TECHNOLOGY, TopicPriority.NORMAL, index)
        }

    var sourceRecommendations: MutableList<SourceRecommendation> =
        mutableListOf(
            SourceRecommendation(
                id = "rec_react_rss",
                endpointId = "ep_react_rss",
                canonicalUrl = "https://react.dev/rss.xml",
                family = "rss_atom",
                discoveryMethod = "feed",
                discoveryProvenance = "curated_seed",
                verificationStatus = "verified",
                authorityStatus = "official",
                authorityConfidence = 0.92f,
                evidenceEligible = false,
                discoveryOnly = false,
                reason = "React の公式フィード",
                explanation = "追跡中のテーマ React に直接対応する公式RSSです。",
                matchedConcepts = listOf("react"),
                matchOrigin = "explicit",
                matchKind = "direct",
                score = 0.88f,
                recommendationStatus = SourceRecommendationStatus.PENDING,
                actionability = SourceActionability.SUBSCRIBE,
                publisher = SourcePublisher("react", "React"),
            ),
            SourceRecommendation(
                id = "rec_hn_discovery",
                endpointId = "ep_hn",
                canonicalUrl = "https://news.ycombinator.com/",
                family = "hacker_news_discovery",
                discoveryMethod = "external_index",
                discoveryProvenance = "external_index",
                verificationStatus = "unverified",
                authorityStatus = "aggregator",
                authorityConfidence = 0.2f,
                evidenceEligible = false,
                discoveryOnly = true,
                reason = "議論の発見用インデックス",
                explanation = "話題の発見には使えますが、事実の根拠にはしません。",
                matchedConcepts = listOf("react"),
                matchOrigin = "inferred",
                matchKind = "neighbor",
                score = 0.31f,
                recommendationStatus = SourceRecommendationStatus.PENDING,
                actionability = SourceActionability.DISCOVERY_ONLY,
            ),
        )

    val sourceSubscriptions: MutableList<SourceSubscription> = mutableListOf()
    val topicRecommendations: MutableList<TopicRecommendation> =
        mutableListOf(
            TopicRecommendation(
                id = "rec_kotlin",
                name = "Kotlin",
                type = TopicType.TECHNOLOGY,
                score = 0.4f,
                reason = "catalog fallback",
                provenance = "inferred",
                alreadyFollowed = false,
                confidence = "medium",
            ),
            TopicRecommendation(
                id = "rec_android",
                name = "Android",
                type = TopicType.TECHNOLOGY,
                score = 0.38f,
                reason = "catalog fallback",
                provenance = "inferred",
                alreadyFollowed = false,
                confidence = "medium",
            ),
        )

    fun topicNames(): List<String> = topics.map { it.name }
}
