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

    fun topicNames(): List<String> = topics.map { it.name }
}
