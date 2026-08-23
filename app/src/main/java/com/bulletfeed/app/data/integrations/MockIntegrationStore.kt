package com.bulletfeed.app

class MockIntegrationStore(
    private val state: MockAppState,
) : IntegrationRepository {
    override suspend fun getGithubConnectionState(): GithubConnection = state.github

    override suspend fun startGithubAuthorization(): GithubAuthorization =
        GithubAuthorization(
            authorizationUrl = "https://github.com/login/oauth/authorize",
            flowId = "flow_demo",
            pollToken = "poll_demo",
            expiresInSeconds = 600,
        )

    override suspend fun listGithubRepositories(query: String): List<GithubRepositoryChoice> =
        state.repositories.filter { query.isBlank() || it.fullName.contains(query, ignoreCase = true) }

    override suspend fun updateGithubRepositories(repositoryIds: List<String>): GithubTopicSyncResult {
        state.repositories =
            state.repositories
                .map { it.copy(selected = it.id in repositoryIds) }
                .toMutableList()
        state.github = GithubConnection(connected = true, accountLogin = "niyu")
        val inferred = repositoryIds.flatMap { inferredTopicsFor(it) }.distinct()
        val existing = state.topics.map { it.name.lowercase() }.toSet()
        val added = inferred.filter { it.lowercase() !in existing }
        val alreadyTracked = inferred.filter { it.lowercase() in existing }
        added.forEach { name ->
            state.topics += UserTopic(
                id = "topic_${state.topics.size}",
                name = name,
                type = TopicType.TECHNOLOGY,
                priority = TopicPriority.NORMAL,
                order = state.topics.size,
            )
        }
        return GithubTopicSyncResult(
            connection = state.github,
            addedTopics = added,
            alreadyTrackedTopics = alreadyTracked,
            inspectedRepositoryCount = repositoryIds.size,
        )
    }

    override suspend fun disconnectGithub() {
        state.repositories = state.repositories.map { it.copy(selected = false) }.toMutableList()
        state.github = GithubConnection(connected = false)
    }

    override suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert> = state.alerts.toList()

    override suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert =
        state.alerts.first { it.id == alertId }

    override suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert {
        state.alerts =
            state.alerts
                .map { alert -> if (alert.id == alertId) alert.copy(status = status) else alert }
                .toMutableList()
        return state.alerts.first { it.id == alertId }
    }

    override suspend fun getNotifications(): List<AppNotification> = state.notifications.toList()

    override suspend fun markNotificationRead(notificationId: String): AppNotification {
        state.notifications =
            state.notifications
                .map { item -> if (item.id == notificationId) item.copy(read = true) else item }
                .toMutableList()
        return state.notifications.first { it.id == notificationId }
    }

    override suspend fun markAllNotificationsRead(): List<AppNotification> {
        state.notifications = state.notifications.map { it.copy(read = true) }.toMutableList()
        return state.notifications.toList()
    }

    override suspend fun importFromPublicRepo(fullName: String): GithubTopicSyncResult {
        if (BulletFeedApiClient.token == null) {
            BulletFeedApiClient.createSession()
        }
        return BulletFeedApiClient.api.importRepositoryKeywords(
            GithubRepoImportDto(fullName.trim()),
        ).toSyncResult()
    }

    private fun inferredTopicsFor(repositoryId: String): List<String> =
        when (repositoryId) {
            "repo_123" -> listOf("Cloudflare Workers")
            "repo_web" -> listOf("Kotlin")
            "repo_app" -> listOf("Kotlin", "Android")
            else -> emptyList()
        }

    fun setGithubConnected(connected: Boolean): Boolean {
        state.github = state.github.copy(connected = connected, accountLogin = if (connected) "niyu" else null)
        return state.github.connected
    }
}
