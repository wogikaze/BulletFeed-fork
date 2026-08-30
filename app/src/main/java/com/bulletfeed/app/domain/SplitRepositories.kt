package com.bulletfeed.app

interface FeedRepository {
    suspend fun getFeedItems(): List<FeedItem>

    suspend fun getFeedPage(
        cursor: String? = null,
        limit: Int = 20,
    ): FeedPage = FeedPage(items = getFeedItems(), nextCursor = null)

    suspend fun getFilteredFeedPage(
        relation: Relation? = null,
        status: FeedItemStatus? = null,
        cursor: String? = null,
        limit: Int = 20,
    ): FeedPage = getFeedPage(cursor = cursor, limit = limit)

    suspend fun markFeedItemRead(feedItemId: String)

    suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    )

    suspend fun recordExposures(items: List<FeedExposure>)

    suspend fun startFeedSession(): FeedSessionTelemetry = FeedSessionTelemetry()

    suspend fun endFeedSession(sessionId: String): FeedSessionTelemetry =
        FeedSessionTelemetry(id = sessionId)

    suspend fun getFeedSessionMetrics(): FeedSessionMetrics = FeedSessionMetrics()
}

interface EventRepository {
    suspend fun getEventDetail(
        eventId: String,
        fromFeedItemId: String? = null,
    ): EventDetail

    suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent

    suspend fun updateFollowingDetail(
        eventId: String,
        following: Boolean,
    ): EventDetail {
        setFollowing(eventId, following)
        return getEventDetail(eventId)
    }
}

interface MeRepository {
    suspend fun getMe(): MeBootstrap

    suspend fun deleteAccount() {}

    suspend fun getProfile(): UserProfile

    suspend fun saveProfile(profile: UserProfile): UserProfile

    suspend fun getUserTopics(): List<UserTopic>

    suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic

    suspend fun removeUserTopic(topicId: String)

    suspend fun patchUserTopic(
        topicId: String,
        priority: TopicPriority? = null,
        order: Int? = null,
    ): UserTopic

    suspend fun searchTopics(query: String): List<UserTopic>

    suspend fun getTopicRecommendations(includeFollowed: Boolean = true): TopicRecommendationPage =
        TopicRecommendationPage(
            version = "",
            items = emptyList(),
            policyVersion = "",
            cohort = "",
        )

    suspend fun ignoreTopicRecommendation(topicId: String): TopicRecommendationPage =
        getTopicRecommendations()

    suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot

    suspend fun getSourceRecommendations(includeIgnored: Boolean = false): List<SourceRecommendation> =
        emptyList()

    suspend fun decideSourceRecommendation(
        candidateId: String,
        decision: SourceRecommendationDecision,
    ): SourceRecommendation

    suspend fun getSourceSubscriptions(): List<SourceSubscription> = emptyList()

    suspend fun addSourceSubscription(
        kind: UserSourceKind,
        url: String? = null,
        pageId: String? = null,
    ): SourceSubscription

    suspend fun removeSourceSubscription(subscriptionId: String)

    suspend fun getKnowledgeBootstrap(): KnowledgeBootstrapSummary =
        KnowledgeBootstrapSummary(version = "", explicitKnownFactCount = 0, inferredFactCount = 0)

    suspend fun recordKnowledgeCheckpoint(
        subjectKind: BootstrapSubjectKind,
        subjectId: String,
        catchUp: Boolean,
        asOf: String? = null,
    ): KnowledgeBootstrapResult

    suspend fun recordExplicitKnowledgeClaims(claimIds: List<String>): KnowledgeBootstrapResult

    suspend fun resetKnowledgeBootstrap()
}

interface IntegrationRepository {
    suspend fun getGithubConnectionState(): GithubConnection

    suspend fun startGithubAuthorization(): GithubAuthorization

    suspend fun startGithubAccountRecovery(): GithubAuthorization = startGithubAuthorization()

    suspend fun pollGithubAuthorization(): GithubAuthorizationStatus? = null

    suspend fun listGithubRepositories(query: String = ""): List<GithubRepositoryChoice>

    suspend fun getGithubRepositoryPage(
        query: String = "",
        cursor: String? = null,
        limit: Int = 20,
    ): GithubRepositoryPage = GithubRepositoryPage(items = listGithubRepositories(query), nextCursor = null)

    suspend fun updateGithubRepositories(repositoryIds: List<String>): GithubTopicSyncResult

    suspend fun importFromPublicRepo(fullName: String): GithubTopicSyncResult

    suspend fun disconnectGithub()

    suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert>

    suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert

    suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert

    suspend fun getNotifications(): List<AppNotification>

    suspend fun markNotificationRead(notificationId: String): AppNotification

    suspend fun markAllNotificationsRead(): List<AppNotification>
}
